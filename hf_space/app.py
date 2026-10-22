#!/usr/bin/env python3
"""Novel Downloader — Streamlit web app (universal, trafilatura-powered)"""

import asyncio
import aiohttp
import re
import json
import io
import zipfile
from urllib.parse import urljoin, urlparse
import trafilatura
import streamlit as st


HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Connection': 'keep-alive',
}


# ── Fetch ─────────────────────────────────────────────────────────────────────

async def fetch_html(session, url, retries=3):
    for attempt in range(retries):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status == 200:
                    return await r.text(errors='replace')
                if r.status in (403, 429, 502, 503):
                    await asyncio.sleep(4 * (attempt + 1))
                else:
                    return None
        except Exception:
            await asyncio.sleep(3 * (attempt + 1))
    return None


# ── Content extraction (trafilatura — no selectors needed) ────────────────────

def extract_content(html):
    text = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=False,
        no_fallback=False,
        favor_recall=True,
    )
    if text and len(text.replace(' ', '').replace('\n', '')) > 80:
        return text.strip()
    return ''


def extract_title(html):
    meta = trafilatura.extract_metadata(html)
    if meta and meta.title:
        title = re.sub(r'[_—\-\s]*(笔趣阁|biquge|小说|章节)\S*', '', meta.title, flags=re.I)
        title = title.strip(' -—_')
        if title and len(title) < 100:
            return title
    m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL | re.I)
    if m:
        return re.sub(r'<[^>]+>', '', m.group(1)).strip()
    return ''


def extract_book_info(html):
    """Extract novel name and author from TOC page."""
    meta = trafilatura.extract_metadata(html)
    name = ''
    author = ''
    if meta:
        if meta.title:
            name = re.sub(r'[_—\-\s]*(笔趣阁|biquge|小说网|章节|目录)\S*', '', meta.title, flags=re.I).strip()
        if meta.author:
            author = meta.author
    # fallback regex for author
    if not author:
        m = re.search(r'作\s*者[：:]\s*([^\s<&]{2,20})', html)
        if m:
            author = m.group(1).strip()
    return name or '未知书名', author or '未知作者'


# ── Universal chapter-link finder ─────────────────────────────────────────────

def find_chapter_links(html, toc_url):
    parsed = urlparse(toc_url)
    base = f'{parsed.scheme}://{parsed.netloc}'
    url_path = parsed.path

    # guess book ID from URL path
    book_id_match = re.search(r'/([A-Za-z0-9]{4,})[/\-_.]', url_path)
    book_id = book_id_match.group(1) if book_id_match else ''

    raw = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.DOTALL | re.I)

    chapters = []
    seen = set()

    for href, title_html in raw:
        href = href.strip()
        if not href or href.startswith('#') or href.startswith('javascript') or href.startswith('mailto'):
            continue
        full_url = href if href.startswith('http') else urljoin(base, href)
        if urlparse(full_url).netloc != parsed.netloc:
            continue
        if full_url == toc_url or full_url == toc_url.rstrip('/'):
            continue

        is_chapter = False
        if book_id and book_id in full_url:
            is_chapter = True
        if re.search(r'(chapter|chap|read|txt|novel|article)[\-/]\d', full_url, re.I):
            is_chapter = True
        if re.search(r'/\d{5,}', full_url):
            is_chapter = True
        if re.search(r'\d{4,}\.html', full_url):
            is_chapter = True

        if is_chapter and full_url not in seen:
            seen.add(full_url)
            title = re.sub(r'<[^>]+>', '', title_html).strip()
            chapters.append((full_url, title or ''))

    def url_num(ch):
        nums = re.findall(r'\d+', ch[0])
        return int(nums[-1]) if nums else 0

    chapters.sort(key=url_num)
    return chapters


async def collect_all_chapters(session, toc_url, log_fn):
    """Follow TOC pagination and collect all chapter links."""
    all_chapters = []
    seen_urls = set()
    visited_toc = set()
    current = toc_url
    page_num = 1

    while current and current not in visited_toc:
        visited_toc.add(current)
        html = await fetch_html(session, current)
        if not html:
            log_fn(f'  ดึงสารบัญหน้า {page_num} ล้มเหลว')
            break

        if page_num == 1:
            name, author = extract_book_info(html)

        new = [(u, t) for u, t in find_chapter_links(html, toc_url) if u not in seen_urls]
        for u, t in new:
            seen_urls.add(u)
        all_chapters.extend(new)
        log_fn(f'สารบัญหน้า {page_num}: +{len(new)} ตอน (รวม {len(all_chapters)})')

        if not new:
            break

        # Find next TOC page
        next_toc = None
        m = re.search(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>\s*(?:下一页|下页|›|»|next)\s*</a>', html, re.I)
        if m:
            href = m.group(1)
            next_toc = href if href.startswith('http') else urljoin(toc_url, href)

        current = next_toc
        page_num += 1
        if current:
            await asyncio.sleep(0.3)

    return all_chapters, name, author


# ── Chapter downloader ────────────────────────────────────────────────────────

async def download_chapter(session, url, title_hint, semaphore, delay):
    async with semaphore:
        html = await fetch_html(session, url)
        if html is None:
            return {'ok': False, 'error': 'fetch failed'}

        title = extract_title(html) or title_hint or ''
        content = extract_content(html)

        # Handle split chapters (本章未完 / 下一页)
        if content and re.search(r'本章未完|点击下一页|下一页继续', html):
            visited = {url}
            cur_html = html
            cur_url = url
            for _ in range(19):
                m = re.search(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>\s*下一页', cur_html, re.I)
                if not m:
                    break
                nxt = m.group(1)
                nxt = nxt if nxt.startswith('http') else urljoin(cur_url, nxt)
                if nxt in visited:
                    break
                visited.add(nxt)
                await asyncio.sleep(delay * 0.4)
                next_html = await fetch_html(session, nxt)
                if not next_html:
                    break
                extra = extract_content(next_html)
                if extra:
                    content += '\n\n' + extra
                cur_html = next_html
                cur_url = nxt

        if content:
            return {'ok': True, 'title': title, 'text': content}
        return {'ok': False, 'error': 'empty content'}

    await asyncio.sleep(delay)


# ── Core engine ───────────────────────────────────────────────────────────────

async def run_download(url, novel_name_input, workers, delay, min_chars, log_fn, progress_fn):
    url = url.strip().rstrip('/')
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None, None, 'URL ไม่ถูกต้อง'

    connector = aiohttp.TCPConnector(limit=workers + 4)
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        log_fn('🔍 ดึงสารบัญ...')
        chapters, auto_name, author = await collect_all_chapters(session, url, log_fn)

        if not chapters:
            return None, None, 'ไม่พบตอนในสารบัญ — ลองวาง URL หน้าสารบัญโดยตรง'

        novel_name = novel_name_input.strip() or auto_name
        log_fn(f'📖 ชื่อ: {novel_name} | ผู้แต่ง: {author}')
        log_fn(f'📚 พบ {len(chapters)} ตอน — เริ่มโหลด...')

        semaphore = asyncio.Semaphore(workers)
        raw_results = []
        cnt_ok = cnt_short = cnt_fail = 0
        qc_short, qc_failed = [], []

        async def dl(idx, u, t):
            r = await download_chapter(session, u, t, semaphore, delay)
            return idx, t, u, r

        batch_size = 20
        for bs in range(0, len(chapters), batch_size):
            batch = chapters[bs:bs + batch_size]
            res = await asyncio.gather(*[dl(bs + i, u, t) for i, (u, t) in enumerate(batch)])
            for idx, toc_title, ch_url, r in sorted(res, key=lambda x: x[0]):
                if r['ok']:
                    title = r['title'] or toc_title or f'第{idx+1}章'
                    text = r['text']
                    raw_results.append((idx, title, text))
                    if len(text) < min_chars:
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
            log_fn(f'  {done}/{len(chapters)} — OK:{cnt_ok}  สั้น:{cnt_short}  ล้มเหลว:{cnt_fail}')
            await asyncio.sleep(0.1)

    raw_results.sort(key=lambda x: x[0])
    sep = '=' * 50
    qc_lines = [
        sep,
        f'QC REPORT — {novel_name}',
        f'URL: {url}',
        f'ตอนทั้งหมด: {len(chapters)}  OK: {cnt_ok}  สั้น(<{min_chars}): {cnt_short}  ล้มเหลว: {cnt_fail}',
    ]
    if qc_short:
        qc_lines += ['ตอนสั้น:'] + [f'  #{s["no"]} {s["title"]} ({s["chars"]} chars)' for s in qc_short[:30]]
    if qc_failed:
        qc_lines += ['ตอนล้มเหลว:'] + [f'  #{f["no"]} {f["title"]} — {f["error"]}' for f in qc_failed[:30]]
    qc_lines.append(sep)

    body = '\n'.join(f'\n{t}\n\n{txt}' for _, t, txt in raw_results)
    txt_content = '﻿' + novel_name + '\n作者：' + author + '\n\n' + '\n'.join(qc_lines) + '\n\n' + body

    qc_data = {
        'book': novel_name, 'author': author, 'url': url,
        'total_chapters': len(chapters), 'ok': cnt_ok,
        'short': cnt_short, 'failed': cnt_fail, 'min_chars': min_chars,
        'short_chapters': qc_short, 'failed_chapters': qc_failed,
    }

    safe = re.sub(r'[\\/:*?"<>|]', '_', novel_name)
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
st.markdown('วางลิงก์หน้าสารบัญนิยาย แล้วกด **Download** — รองรับทุกเว็บอัตโนมัติ')

with st.form('dl_form'):
    url = st.text_input('🔗 ลิงก์สารบัญนิยาย', placeholder='https://www.example.com/book/12345/')
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
💡 **วิธีใช้:** วาง URL หน้าสารบัญของนิยาย (หน้าที่มีรายชื่อตอนทั้งหมด) แล้วกด Download
""")
