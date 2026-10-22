#!/usr/bin/env python3
"""Novel Downloader — Streamlit web app"""

import asyncio
import aiohttp
import re
import json
import io
import zipfile
import streamlit as st
from html.parser import HTMLParser


# ── HTML parsing ──────────────────────────────────────────────────────────────

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        # h1/h2 excluded from body text — extracted separately by extract_title()
        self._skip = {'script', 'style', 'nav', 'header', 'footer', 'aside', 'iframe', 'h1', 'h2'}
        self._in_skip = 0
        self._in_p = False
        self._paragraphs = []
        self._current = []
        self._all_text = []

    def handle_starttag(self, tag, attrs):
        if tag in self._skip:
            self._in_skip += 1
        if tag == 'p' and not self._in_skip:
            self._in_p = True
            self._current = []
        if tag == 'br' and not self._in_skip:
            self._all_text.append('\n')

    def handle_endtag(self, tag):
        if tag in self._skip:
            self._in_skip = max(0, self._in_skip - 1)
        if tag == 'p' and self._in_p:
            self._in_p = False
            text = ''.join(self._current).strip()
            if text:
                self._paragraphs.append(text)

    def handle_data(self, data):
        if self._in_skip:
            return
        if self._in_p:
            self._current.append(data)
        self._all_text.append(data)


JUNK_RE = re.compile(
    r'当前位置|上一章|下一章|回目录|©\s*20\d\d|document\.domain|'
    r'google|adsbygoogle|function\(i,s|var\s+_hmt|百度|本站|书签|收藏|推荐|'
    r'首页|返回目录|关灯|护眼|字号|章节报错|一秒记住|笔趣阁|更新快|无弹窗|'
    r'本章未完|点击下一页|请点击下一页|最新章节|设为首页|加入书架|手机版|'
    r'请记住本站|如遇到内容乱|\/\/',
    re.IGNORECASE
)

PAGE_MARKER_RE = re.compile(r'[（(]第\s*\d+\s*/\s*\d+\s*页[）)]')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Connection': 'keep-alive',
}


_NAV_EXACT = {'返回', '目录', '首页', '书签', '收藏', '推荐', '关灯', '护眼',
              '上一章', '下一章', '上一页', '下一页', '回目录', '加入书架'}

# Lines that look like a chapter heading (repeated at top of content from site UI elements)
_CHAPTER_HDR_RE = re.compile(r'^第\s*\d+\s*[章节話话回]')


def clean_lines(paragraphs):
    result = []
    for p in paragraphs:
        p = p.strip()
        if not p or len(p) <= 1:
            continue
        if p in _NAV_EXACT:
            continue
        if JUNK_RE.search(p):
            continue
        # Strip page markers inline
        p = PAGE_MARKER_RE.sub('', p).strip()
        if not p:
            continue
        result.append(p)
    return result


def clean_title(title):
    if not title:
        return title
    title = re.sub(r'[_—\-\s]*笔趣阁\S*', '', title)
    title = PAGE_MARKER_RE.sub('', title)
    return title.strip()


def _remove_leading_headings(lines):
    """Remove chapter-heading-like lines at the very start (duplicate UI headings)."""
    i = 0
    while i < min(6, len(lines)) and _CHAPTER_HDR_RE.match(lines[i]):
        i += 1
    return lines[i:]


def extract_text(html):
    parser = TextExtractor()
    parser.feed(html)
    lines = clean_lines(parser._paragraphs)
    lines = _remove_leading_headings(lines)
    if len(lines) >= 3:
        return lines
    lines = clean_lines(''.join(parser._all_text).split('\n'))
    return _remove_leading_headings(lines)


def extract_title(html):
    m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)
    if not m:
        m = re.search(r'<h2[^>]*>(.*?)</h2>', html, re.DOTALL | re.IGNORECASE)
    if m:
        raw = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        return clean_title(raw)
    return None


def _chapter_next_page(html, current_url):
    """Return URL of next chapter-page, or None if this is the last page."""
    # Only look for next page if there's an incomplete-chapter marker
    if not re.search(r'本章未完|点击下一页|下一页继续|未完待续', html):
        return None
    # Try to find explicit 下一页 link
    for pat in [
        r'<a[^>]+href="([^"]*\d+_\d+\.html[^"]*)"[^>]*>\s*下一页\s*</a>',
        r'href="([^"]*\d+_\d+\.html)"[^>]*>[^<]*下一页',
        r'下一页[^<]*<a[^>]+href="([^"]+)"',
    ]:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            href = m.group(1)
            if href.startswith('http'):
                return href
            dm = re.match(r'(https?://[^/]+)', current_url)
            if dm:
                return dm.group(1) + (href if href.startswith('/') else '/' + href)
    # Construct next page URL from current URL pattern
    m = re.match(r'(.*?/\d+/)(\d+)(?:_(\d+))?\.html', current_url)
    if m:
        base, cid, pn = m.group(1), m.group(2), m.group(3)
        return f'{base}{cid}_{int(pn)+1 if pn else 2}.html'
    return None


# ── URL detection ─────────────────────────────────────────────────────────────

def parse_novel_url(url):
    url = url.strip().rstrip('/')
    m = re.search(r'biquge365\.[^/]+/shu/(\d+)', url)
    if m:
        return 'biquge365', m.group(1)
    m = re.search(r'69shu\.[^/]+/index/(\d+/\d+)', url)
    if m:
        return '69shu', m.group(1)
    m = re.search(r'shubaowb\.[^/]+/novel/([^/.\s]+)', url)
    if m:
        return 'shubaowb', m.group(1)
    m = re.search(r'zhys\.[^/]+/book/([^/.\s]+)', url)
    if m:
        return 'zhys', m.group(1)
    m = re.search(r'4jiwx\.[^/]+/book/([^/.\s]+)', url)
    if m:
        return '4jiwx', m.group(1)
    m = re.search(r'shuixxs\.[^/]+/book/([^/.\s]+)', url)
    if m:
        return 'shuixxs', m.group(1)
    raise ValueError(
        f'ไม่รู้จัก URL: {url}\n'
        'รองรับ: biquge365 / 69shu / shubaowb / zhys / 4jiwx / shuixxs'
    )


# ── Chapter downloader ────────────────────────────────────────────────────────

async def _fetch_one(session, url):
    """Fetch a URL, return (html, error_str) — retries on transient errors."""
    for retry in range(4):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 200:
                    return await resp.text(), None
                if resp.status in (403, 502):
                    await asyncio.sleep(5 * (retry + 1))
                else:
                    return None, f'HTTP {resp.status}'
        except asyncio.TimeoutError:
            await asyncio.sleep(3 * (retry + 1))
        except Exception as e:
            await asyncio.sleep(3 * (retry + 1))
    return None, 'max retries'


async def download_chapter(session, url, semaphore, delay=1.5, multipage=False):
    async with semaphore:
        html, err = await _fetch_one(session, url)
        if html is None:
            return {'ok': False, 'error': err}

        title = extract_title(html)
        all_lines = extract_text(html)

        if multipage:
            cur_url = url
            for _ in range(19):  # max 20 pages total
                nxt = _chapter_next_page(html, cur_url)
                if not nxt or nxt == cur_url:
                    break
                await asyncio.sleep(delay * 0.4)
                html, err = await _fetch_one(session, nxt)
                if html is None:
                    break
                all_lines.extend(extract_text(html))
                cur_url = nxt

        if all_lines:
            return {'ok': True, 'title': title, 'text': '\n\n'.join(all_lines)}
        return {'ok': False, 'error': 'empty'}
    await asyncio.sleep(delay)


# ── TOC helpers ───────────────────────────────────────────────────────────────

async def fetch_html(session, url):
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
        if r.status == 200:
            return await r.text()
        return None


async def get_chapters_biquge365(session, book_id, log):
    domain = 'm.biquge365.net'

    def extract(html, seen):
        found = []

        # Pattern 1: /shu/{book_id}/DIGITS.html  (relative)
        for m in re.finditer(rf'href="(/shu/{book_id}/(\d+)\.html)"', html):
            url = f'https://{domain}{m.group(1)}'
            if url not in seen:
                seen.add(url)
                found.append((url, ''))

        # Pattern 2: full URL https://...biquge365.net/shu/{book_id}/DIGITS.html
        for m in re.finditer(rf'href="(https?://[^"]*biquge365[^"]+/shu/{book_id}/(\d+)\.html)"', html):
            url = m.group(1)
            if url not in seen:
                seen.add(url)
                found.append((url, ''))

        # Pattern 3: just DIGITS.html (relative to current TOC page)
        for m in re.finditer(r'href="(\d{5,}\.html)"', html):
            url = f'https://{domain}/shu/{book_id}/{m.group(1)}'
            if url not in seen:
                seen.add(url)
                found.append((url, ''))

        # Fill titles from nearby text
        if not found:
            # Fallback: any link with digits that is under this book
            for m in re.finditer(rf'<a[^>]*href="([^"]*{book_id}[^"]*\d+\.html[^"]*)"[^>]*>(.*?)</a>', html, re.DOTALL):
                href = m.group(1)
                url = href if href.startswith('http') else f'https://{domain}{href}'
                title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
                if url not in seen and title and len(title) <= 80:
                    seen.add(url)
                    found.append((url, title))

        # Try to recover titles using <a> tag scan
        if found:
            title_map = {}
            for m in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL):
                t = re.sub(r'<[^>]+>', '', m.group(2)).strip()
                if t and len(t) <= 80:
                    title_map[m.group(1)] = t
            result = []
            for url, title in found:
                path = url.replace(f'https://{domain}', '')
                if not title:
                    title = title_map.get(path) or title_map.get(url) or ''
                result.append((url, title))
            return result
        return found

    def next_page(html, pn):
        for pat in [rf'href="([^"]*\?p={pn+1}[^"]*)"',
                    r'href="([^"]+)"[^>]*>\s*(?:下一页|下一頁)\s*</a>',
                    rf'href="(/shu/{book_id}/index_{pn+1}\.html)"']:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                h = m.group(1)
                return h if h.startswith('http') else f'https://{domain}{h}'
        return None

    chapters, seen, toc_url, pn = [], set(), f'https://{domain}/shu/{book_id}/', 1
    while toc_url:
        html = await fetch_html(session, toc_url)
        if not html:
            log(f'  [debug] ดึงหน้า {toc_url} ล้มเหลว (ไม่ได้ HTML)')
            break
        new = extract(html, seen)
        chapters.extend(new)
        log(f'สารบัญหน้า {pn}: +{len(new)} ตอน (รวม {len(chapters)})')
        if not new:
            break
        toc_url = next_page(html, pn)
        pn += 1
        if toc_url:
            await asyncio.sleep(0.3)
    return chapters, domain


async def get_chapters_69shu(session, book_path, log):
    domain = 'www.69shu.xyz'
    book_num = book_path.split('/')[-1]

    def extract(html, seen):
        found = []
        for m in re.compile(rf'<a[^>]*href="(/{book_num}/[^"]+\.html[^"]*)"[^>]*>(.*?)</a>', re.DOTALL).finditer(html):
            href = m.group(1).rstrip('/')
            url = f'https://{domain}{href}'
            title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if url not in seen and title and len(title) <= 80:
                seen.add(url)
                found.append((url, title))
        return found

    chapters, seen, page = [], set(), 1
    while True:
        html = await fetch_html(session, f'https://{domain}/index/{book_path}/{page}.html/')
        if not html:
            break
        new = extract(html, seen)
        if not new:
            break
        chapters.extend(new)
        log(f'สารบัญหน้า {page}: +{len(new)} ตอน (รวม {len(chapters)})')
        if not re.search(rf'href="[^"]*/{re.escape(book_path)}/{page+1}\.html/?[^"]*"', html):
            break
        page += 1
        await asyncio.sleep(0.3)
    return chapters, domain


async def get_chapters_shubaowb(session, book_id, log):
    domain = 'shubaowb.com'

    def extract(html, seen):
        found = []
        for m in re.compile(rf'<a[^>]*href="([^"]*?/read/{book_id}/[^"]+)"[^>]*>(.*?)</a>', re.DOTALL).finditer(html):
            href = m.group(1)
            if not href.startswith('http'):
                href = f'https://{domain}{href}'
            title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if href not in seen:
                seen.add(href)
                found.append((href, title))
        return found

    def next_page(html, pn):
        for pat in [rf'href="(/novel/{book_id}_{pn+1}\.html)"',
                    r'href="([^"]+)"[^>]*>\s*(?:下一页|next)\s*</a>']:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                h = m.group(1)
                return h if h.startswith('http') else f'https://{domain}{h}'
        return None

    chapters, seen, toc_url, pn = [], set(), f'https://{domain}/novel/{book_id}.html', 1
    while toc_url:
        html = await fetch_html(session, toc_url)
        if not html:
            break
        new = extract(html, seen)
        chapters.extend(new)
        log(f'สารบัญหน้า {pn}: +{len(new)} ตอน (รวม {len(chapters)})')
        if not new:
            break
        toc_url = next_page(html, pn)
        pn += 1
        if toc_url:
            await asyncio.sleep(0.3)
    return chapters, domain


async def get_chapters_zhys(session, book_id, log):
    domain = 'cn.zhys.tw'
    html = await fetch_html(session, f'https://{domain}/book/{book_id}.html')
    if not html:
        return [], domain
    chapters, seen = [], set()
    for m in re.compile(rf'<a[^>]*href="[^"]*?/read/{book_id}/(\d+)\.html"[^>]*>(.*?)</a>', re.DOTALL).finditer(html):
        cid = m.group(1)
        title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        url = f'https://{domain}/read/{book_id}/{cid}.html'
        if url not in seen:
            seen.add(url)
            chapters.append((url, title or f'Chapter {len(chapters)+1}'))
    log(f'พบ {len(chapters)} ตอน')
    return chapters, domain


# ── Core engine ───────────────────────────────────────────────────────────────

async def run_download(url, novel_name, workers, delay, min_chars, log_fn, progress_fn):
    try:
        site, book_id = parse_novel_url(url)
        log_fn(f'✅ ตรวจพบ: site={site}  book_id={book_id}')
    except ValueError as e:
        return None, None, str(e)

    if not novel_name.strip():
        novel_name = f'{site}_{book_id.replace("/","_")}'

    connector = aiohttp.TCPConnector(limit=workers + 2)
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        if site == 'biquge365':
            chapters, domain = await get_chapters_biquge365(session, book_id, log_fn)
        elif site == '69shu':
            chapters, domain = await get_chapters_69shu(session, book_id, log_fn)
        elif site == 'shubaowb':
            chapters, domain = await get_chapters_shubaowb(session, book_id, log_fn)
        elif site == 'zhys':
            chapters, domain = await get_chapters_zhys(session, book_id, log_fn)
        else:
            return None, None, f'site "{site}" ยังไม่รองรับ'

        if not chapters:
            return None, None, 'ไม่พบตอนในสารบัญ'

        log_fn(f'📚 พบ {len(chapters)} ตอน — เริ่มโหลด...')
        semaphore = asyncio.Semaphore(workers)
        raw_results = []
        cnt_ok = cnt_short = cnt_fail = 0
        qc_short, qc_failed = [], []

        use_multipage = (site == 'biquge365')

        async def dl(idx, u, t):
            r = await download_chapter(session, u, semaphore, delay, multipage=use_multipage)
            return idx, t, r

        batch_size = 20
        for bs in range(0, len(chapters), batch_size):
            batch = chapters[bs:bs + batch_size]
            res = await asyncio.gather(*[dl(bs + i, u, t) for i, (u, t) in enumerate(batch)])
            for idx, toc_title, r in sorted(res, key=lambda x: x[0]):
                ch_url = chapters[idx][0]
                if r['ok']:
                    title = r['title'] or toc_title or f'第{idx+1}章'
                    text = r['text']
                    is_short = len(text) < min_chars
                    raw_results.append((idx, title, text))
                    if is_short:
                        cnt_short += 1
                        qc_short.append({'no': idx+1, 'title': title, 'chars': len(text), 'url': ch_url})
                    else:
                        cnt_ok += 1
                else:
                    cnt_fail += 1
                    label = toc_title or f'第{idx+1}章'
                    raw_results.append((idx, label, f'[โหลดล้มเหลว: {r["error"]}]'))
                    qc_failed.append({'no': idx+1, 'title': label, 'error': r['error'], 'url': ch_url})
            done = bs + len(batch)
            progress_fn(done / len(chapters))
            log_fn(f'  {done}/{len(chapters)} — OK:{cnt_ok} สั้น:{cnt_short} ล้มเหลว:{cnt_fail}')
            await asyncio.sleep(0.2)

    raw_results.sort(key=lambda x: x[0])
    sep = '=' * 50
    qc_lines = [sep, f'QC REPORT — {novel_name}',
                f'Site: {domain}  |  Book: {book_id}',
                f'ตอนทั้งหมด: {len(chapters)}  OK: {cnt_ok}  สั้น(<{min_chars}): {cnt_short}  ล้มเหลว: {cnt_fail}']
    if qc_short:
        qc_lines += ['ตอนสั้น:'] + [f'  #{s["no"]} {s["title"]} ({s["chars"]} chars)' for s in qc_short[:20]]
    if qc_failed:
        qc_lines += ['ตอนล้มเหลว:'] + [f'  #{f["no"]} {f["title"]} — {f["error"]}' for f in qc_failed[:20]]
    qc_lines.append(sep)

    body = '\n'.join(f'\n{t}\n\n{txt}' for _, t, txt in raw_results)
    txt_content = '﻿' + novel_name + '\n\n' + '\n'.join(qc_lines) + '\n\n' + body

    qc_data = {'book': novel_name, 'site': domain, 'book_id': book_id,
               'total_chapters': len(chapters), 'ok': cnt_ok, 'short': cnt_short,
               'failed': cnt_fail, 'min_chars': min_chars,
               'short_chapters': qc_short, 'failed_chapters': qc_failed}

    safe = re.sub(r'[\\/:*?"<>|]', '_', novel_name)

    # Pack into zip
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f'{safe}.txt', txt_content.encode('utf-8'))
        zf.writestr(f'{safe}_QC.json', json.dumps(qc_data, ensure_ascii=False, indent=2))
    buf.seek(0)

    summary = (f'✅ เสร็จแล้ว!\n'
               f'ตอนทั้งหมด: {len(chapters)}\n'
               f'OK: {cnt_ok}  |  สั้น: {cnt_short}  |  ล้มเหลว: {cnt_fail}')
    log_fn(summary)
    return buf.getvalue(), f'{safe}.zip', summary


# ── Streamlit UI ──────────────────────────────────────────────────────────────

st.set_page_config(page_title='Novel Downloader', page_icon='📚', layout='centered')

st.title('📚 Novel Downloader')
st.markdown('วางลิงก์นิยายแล้วกด **Download** — รองรับ biquge365 / 69shu / shubaowb / zhys')

with st.form('dl_form'):
    url = st.text_input('🔗 ลิงก์นิยาย', placeholder='https://m.biquge365.net/shu/528722/')
    novel_name = st.text_input('ชื่อไฟล์ (ไม่ใส่ก็ได้)', placeholder='เว้นว่างให้ระบบตั้งชื่อให้')

    c1, c2, c3 = st.columns(3)
    with c1:
        workers = st.slider('Workers', 1, 8, 3)
    with c2:
        delay = st.slider('Delay (วิ)', 0.5, 5.0, 2.0, step=0.5)
    with c3:
        min_chars = st.number_input('QC ขั้นต่ำตัวอักษร', min_value=50, max_value=2000, value=300, step=50)

    submitted = st.form_submit_button('⬇️ Download', type='primary', use_container_width=True)

if submitted and url.strip():
    log_area = st.empty()
    progress_bar = st.progress(0.0, text='กำลังโหลด...')
    logs = []

    def log(msg):
        logs.append(msg)
        log_area.text_area('Log', value='\n'.join(logs), height=220, label_visibility='collapsed')

    def set_progress(val):
        progress_bar.progress(min(val, 1.0), text=f'โหลดแล้ว {val*100:.0f}%')

    try:
        zip_bytes, zip_name, summary = asyncio.run(
            run_download(url, novel_name, workers, float(delay), int(min_chars), log, set_progress)
        )
        progress_bar.progress(1.0, text='เสร็จแล้ว!')
        if zip_bytes:
            st.success(summary)
            st.download_button(
                label='📥 โหลดไฟล์ (.zip มี TXT + QC JSON)',
                data=zip_bytes,
                file_name=zip_name,
                mime='application/zip',
                use_container_width=True,
            )
        else:
            st.error(summary)
    except Exception as e:
        st.error(f'เกิดข้อผิดพลาด: {e}')

elif submitted:
    st.warning('กรุณาใส่ URL ก่อนค่ะ')

st.markdown("""
---
**ตัวอย่าง URL:**
- `https://m.biquge365.net/shu/528722/`
- `https://www.69shu.xyz/index/2/2829/1.html/`
- `https://shubaowb.com/novel/YH2B.html`
""")
