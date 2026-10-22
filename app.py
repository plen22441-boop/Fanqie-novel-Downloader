#!/usr/bin/env python3
"""Novel Downloader — Streamlit web app (universal)"""

import asyncio
import aiohttp
import re
import json
import io
import zipfile
from urllib.parse import urlparse, urljoin
import streamlit as st
from html.parser import HTMLParser


# ── Text cleaning ─────────────────────────────────────────────────────────────

JUNK_RE = re.compile(
    r'当前位置|上一章|下一章|回目录|©\s*20\d\d|document\.domain|'
    r'google|adsbygoogle|function\(i,s|var\s+_hmt|百度|本站|书签|收藏|推荐|'
    r'首页|返回目录|关灯|护眼|字号|章节报错|一秒记住|笔趣阁|更新快|无弹窗|'
    r'本章未完|点击下一页|请点击下一页|最新章节|设为首页|加入书架|手机版|'
    r'请记住本站|如遇到内容乱|\/\/',
    re.IGNORECASE,
)

PAGE_MARKER_RE = re.compile(r'[（(]第\s*\d+\s*/\s*\d+\s*页[）)]')

_NAV_EXACT = {
    '返回', '目录', '首页', '书签', '收藏', '推荐', '关灯', '护眼',
    '上一章', '下一章', '上一页', '下一页', '回目录', '加入书架',
    '提交关闭', '提交', '关闭', '确定', '取消', '登录', '注册',
}

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
        p = PAGE_MARKER_RE.sub('', p).strip()
        if not p:
            continue
        result.append(p)
    return result


def _remove_leading_headings(lines):
    i = 0
    while i < min(6, len(lines)) and _CHAPTER_HDR_RE.match(lines[i]):
        i += 1
    return lines[i:]


def clean_title(title):
    if not title:
        return title
    title = re.sub(r'[_—\-\s]*笔趣阁\S*', '', title)
    title = PAGE_MARKER_RE.sub('', title)
    return title.strip()


# ── HTML parsing ──────────────────────────────────────────────────────────────

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._skip = {'script', 'style', 'nav', 'header', 'footer', 'aside',
                      'iframe', 'h1', 'h2', 'form', 'button'}
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


def find_content_div(html):
    """Extract the main story content from a chapter page."""
    stripped = re.sub(
        r'<(script|style|nav|header|footer|aside|iframe|form)[^>]*>[\s\S]*?</\1>',
        '', html, flags=re.IGNORECASE,
    )

    CONTENT_PAT = re.compile(
        r'<(?:div|section|article)[^>]+(?:id|class)="[^"]*'
        r'(?:content|article|chapter|read|text|novel|book|chap|body)[^"]*"[^>]*>'
        r'([\s\S]*?)'
        r'</(?:div|section|article)>',
        re.IGNORECASE,
    )
    best_text = ''
    best_count = 0
    for m in CONTENT_PAT.finditer(stripped):
        inner = re.sub(r'<[^>]+>', ' ', m.group(1))
        cn = len(re.findall(r'[一-鿿]', inner))
        if cn > best_count:
            best_count = cn
            best_text = inner
    if best_count >= 100:
        return best_text

    for m in re.finditer(
        r'<(?:div|section)[^>]*>([\s\S]{200,15000}?)</(?:div|section)>',
        stripped, re.IGNORECASE,
    ):
        inner = re.sub(r'<[^>]+>', ' ', m.group(1))
        cn = len(re.findall(r'[一-鿿]', inner))
        if cn > best_count:
            best_count = cn
            best_text = inner
    if best_count >= 100:
        return best_text

    paragraphs = re.findall(r'<p[^>]*>([\s\S]*?)</p>', stripped, re.IGNORECASE)
    return ' '.join(re.sub(r'<[^>]+>', ' ', p) for p in paragraphs)


def extract_text_from_html(html):
    """Parse HTML, prefer <p> paragraphs, fall back to all text."""
    parser = TextExtractor()
    parser.feed(html)
    lines = clean_lines(parser._paragraphs)
    lines = _remove_leading_headings(lines)
    if len(lines) >= 3:
        return lines
    lines = clean_lines(''.join(parser._all_text).split('\n'))
    return _remove_leading_headings(lines)


def extract_text_from_content(content_text):
    """Parse pre-stripped content text (from find_content_div)."""
    raw_lines = re.split(r'[\n\r]+|<br\s*/?>|(?<=。)(?=\s)', content_text)
    lines = clean_lines(raw_lines)
    return _remove_leading_headings(lines)


def extract_title(html):
    for pat in [
        r'<h1[^>]*>(.*?)</h1>',
        r'<title[^>]*>(.*?)</title>',
        r'<h2[^>]*>(.*?)</h2>',
    ]:
        m = re.search(pat, html, re.DOTALL | re.IGNORECASE)
        if m:
            raw = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            t = clean_title(raw)
            if t:
                return t
    return None


HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Connection': 'keep-alive',
}


# ── HTTP helpers ──────────────────────────────────────────────────────────────

async def _fetch_one(session, url):
    for retry in range(4):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=25)) as resp:
                if resp.status == 200:
                    return await resp.text(errors='replace'), None
                if resp.status in (403, 429, 502, 503):
                    await asyncio.sleep(5 * (retry + 1))
                else:
                    return None, f'HTTP {resp.status}'
        except asyncio.TimeoutError:
            await asyncio.sleep(3 * (retry + 1))
        except Exception as e:
            await asyncio.sleep(3 * (retry + 1))
    return None, 'max retries'


async def fetch_html(session, url):
    html, _ = await _fetch_one(session, url)
    return html


# ── URL parsing ───────────────────────────────────────────────────────────────

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
    return 'universal', url


# ── Chapter next-page helper ──────────────────────────────────────────────────

def _chapter_next_page(html, current_url):
    if not re.search(r'本章未完|点击下一页|下一页继续|未完待续', html):
        return None
    for pat in [
        r'<a[^>]+href="([^"]*\d+_\d+\.html[^"]*)"[^>]*>\s*下一页\s*</a>',
        r'href="([^"]*\d+_\d+\.html)"[^>]*>[^<]*下一页',
    ]:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            href = m.group(1)
            if href.startswith('http'):
                return href
            dm = re.match(r'(https?://[^/]+)', current_url)
            if dm:
                return dm.group(1) + (href if href.startswith('/') else '/' + href)
    m = re.match(r'(.*?/\d+/)(\d+)(?:_(\d+))?\.html', current_url)
    if m:
        base, cid, pn = m.group(1), m.group(2), m.group(3)
        return f'{base}{cid}_{int(pn)+1 if pn else 2}.html'
    return None


# ── Chapter downloader ────────────────────────────────────────────────────────

async def download_chapter(session, url, semaphore, delay=1.5,
                           multipage=False, use_content_div=False):
    async with semaphore:
        html, err = await _fetch_one(session, url)
        if html is None:
            return {'ok': False, 'error': err}

        title = extract_title(html)

        if use_content_div:
            content = find_content_div(html)
            all_lines = extract_text_from_content(content)
            if len(all_lines) < 3:
                all_lines = extract_text_from_html(html)
        else:
            all_lines = extract_text_from_html(html)

        if multipage or use_content_div:
            cur_url = url
            for _ in range(19):
                nxt = _chapter_next_page(html, cur_url)
                if not nxt or nxt == cur_url:
                    break
                await asyncio.sleep(delay * 0.4)
                html, err = await _fetch_one(session, nxt)
                if html is None:
                    break
                if use_content_div:
                    content = find_content_div(html)
                    extra = extract_text_from_content(content)
                    if len(extra) < 3:
                        extra = extract_text_from_html(html)
                else:
                    extra = extract_text_from_html(html)
                all_lines.extend(extra)
                cur_url = nxt

        if all_lines:
            return {'ok': True, 'title': title, 'text': '\n\n'.join(all_lines)}
        return {'ok': False, 'error': 'empty'}
    await asyncio.sleep(delay)


# ── TOC scrapers ──────────────────────────────────────────────────────────────

async def get_chapters_biquge365(session, book_id, log):
    domain = 'm.biquge365.net'

    def extract(html, seen):
        found = []
        for m in re.finditer(rf'href="(/shu/{book_id}/(\d+)\.html)"', html):
            url = f'https://{domain}{m.group(1)}'
            if url not in seen:
                seen.add(url)
                found.append((url, ''))
        for m in re.finditer(
            rf'href="(https?://[^"]*biquge365[^"]+/shu/{book_id}/(\d+)\.html)"', html
        ):
            url = m.group(1)
            if url not in seen:
                seen.add(url)
                found.append((url, ''))
        for m in re.finditer(r'href="(\d{5,}\.html)"', html):
            url = f'https://{domain}/shu/{book_id}/{m.group(1)}'
            if url not in seen:
                seen.add(url)
                found.append((url, ''))
        if not found:
            for m in re.finditer(
                rf'<a[^>]*href="([^"]*{book_id}[^"]*\d+\.html[^"]*)"[^>]*>(.*?)</a>',
                html, re.DOTALL,
            ):
                href = m.group(1)
                url = href if href.startswith('http') else f'https://{domain}{href}'
                title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
                if url not in seen and title and len(title) <= 80:
                    seen.add(url)
                    found.append((url, title))
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
        for pat in [
            rf'href="([^"]*\?p={pn+1}[^"]*)"',
            r'href="([^"]+)"[^>]*>\s*(?:下一页|下一頁)\s*</a>',
            rf'href="(/shu/{book_id}/index_{pn+1}\.html)"',
        ]:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                h = m.group(1)
                return h if h.startswith('http') else f'https://{domain}{h}'
        return None

    chapters, seen, toc_url, pn = [], set(), f'https://{domain}/shu/{book_id}/', 1
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
            await asyncio.sleep(0.5)
    return chapters, domain


async def get_chapters_69shu(session, book_path, log):
    domain = 'www.69shu.xyz'
    book_num = book_path.split('/')[-1]

    def extract(html, seen):
        found = []
        for m in re.compile(
            rf'<a[^>]*href="(/{book_num}/[^"]+\.html[^"]*)"[^>]*>(.*?)</a>', re.DOTALL
        ).finditer(html):
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
        if not re.search(
            rf'href="[^"]*/{re.escape(book_path)}/{page+1}\.html/?[^"]*"', html
        ):
            break
        page += 1
        await asyncio.sleep(0.3)
    return chapters, domain


async def get_chapters_shubaowb(session, book_id, log):
    domain = 'shubaowb.com'

    def extract(html, seen):
        found = []
        for m in re.compile(
            rf'<a[^>]*href="([^"]*?/read/{book_id}/[^"]+)"[^>]*>(.*?)</a>', re.DOTALL
        ).finditer(html):
            href = m.group(1)
            if not href.startswith('http'):
                href = f'https://{domain}{href}'
            title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if href not in seen:
                seen.add(href)
                found.append((href, title))
        return found

    def next_page(html, pn):
        for pat in [
            rf'href="(/novel/{book_id}_{pn+1}\.html)"',
            r'href="([^"]+)"[^>]*>\s*(?:下一页|next)\s*</a>',
        ]:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                h = m.group(1)
                return h if h.startswith('http') else f'https://{domain}{h}'
        return None

    chapters, seen, toc_url, pn = (
        [], set(), f'https://{domain}/novel/{book_id}.html', 1
    )
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
    for m in re.compile(
        rf'<a[^>]*href="[^"]*?/read/{book_id}/(\d+)\.html"[^>]*>(.*?)</a>', re.DOTALL
    ).finditer(html):
        cid = m.group(1)
        title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        url = f'https://{domain}/read/{book_id}/{cid}.html'
        if url not in seen:
            seen.add(url)
            chapters.append((url, title or f'Chapter {len(chapters)+1}'))
    log(f'พบ {len(chapters)} ตอน')
    return chapters, domain


async def get_chapters_universal(session, toc_url, log):
    """Universal TOC scraper: works on any Chinese novel site."""
    parsed = urlparse(toc_url)
    base_domain = f'{parsed.scheme}://{parsed.netloc}'

    SKIP_HREF = re.compile(
        r'login|register|user|comment|search|tag|page=|javascript:|#|'
        r'\.css|\.js|\.jpg|\.png|\.gif',
        re.IGNORECASE,
    )

    def extract_chapters(html, seen):
        found = []
        for m in re.finditer(
            r'<a[^>]+href="([^"]{4,})"[^>]*>([\s\S]*?)</a>', html, re.IGNORECASE
        ):
            href = m.group(1).strip()
            text = re.sub(r'<[^>]+>', '', m.group(2)).strip()

            if SKIP_HREF.search(href):
                continue
            if not re.search(r'\d{3,}', href):
                continue
            if not text or len(text) > 80:
                continue
            if re.match(r'^[\s\W]+$', text):
                continue

            # Make absolute
            if href.startswith('http'):
                abs_url = href
            elif href.startswith('/'):
                abs_url = base_domain + href
            else:
                abs_url = urljoin(toc_url, href)

            # Must be same domain
            if urlparse(abs_url).netloc != parsed.netloc:
                continue

            if abs_url not in seen:
                seen.add(abs_url)
                found.append((abs_url, text))
        return found

    def find_next_toc_page(html, current_url, pn):
        for pat in [
            r'<a[^>]+href="([^"]+)"[^>]*>\s*(?:下一页|下一頁)\s*</a>',
            rf'href="([^"]*[?/]p(?:age)?[=_/]{pn+1}[^"]*)"',
            rf'href="([^"]*index_{pn+1}\.html[^"]*)"',
            rf'href="([^"]*/{pn+1}\.html[^"]*)"',
        ]:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                href = m.group(1)
                if href.startswith('http'):
                    if urlparse(href).netloc == parsed.netloc:
                        return href
                else:
                    candidate = urljoin(current_url, href)
                    if candidate != current_url:
                        return candidate
        return None

    chapters, seen = [], set()
    current_url = toc_url
    pn = 1

    # Fetch book title from first TOC page
    first_html = await fetch_html(session, toc_url)
    if not first_html:
        return [], parsed.netloc, None

    book_title = extract_title(first_html)
    new = extract_chapters(first_html, seen)
    chapters.extend(new)
    log(f'สารบัญหน้า {pn}: +{len(new)} ตอน (รวม {len(chapters)})')

    for pn in range(2, 31):
        nxt = find_next_toc_page(first_html, current_url, pn - 1)
        if not nxt:
            break
        html = await fetch_html(session, nxt)
        if not html:
            break
        new = extract_chapters(html, seen)
        if not new:
            break
        chapters.extend(new)
        log(f'สารบัญหน้า {pn}: +{len(new)} ตอน (รวม {len(chapters)})')
        current_url = nxt
        first_html = html
        await asyncio.sleep(0.5)

    return chapters, parsed.netloc, book_title


# ── Scan (step 1) ─────────────────────────────────────────────────────────────

async def scan_novel(url):
    connector = aiohttp.TCPConnector(limit=5)
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        site, book_id = parse_novel_url(url)

        if site == 'biquge365':
            chapters, domain = await get_chapters_biquge365(session, book_id, lambda _: None)
            html = await fetch_html(session, f'https://{domain}/shu/{book_id}/')
            title = extract_title(html) if html else f'biquge365_{book_id}'
        elif site == '69shu':
            chapters, domain = await get_chapters_69shu(session, book_id, lambda _: None)
            title = f'69shu_{book_id}'
        elif site == 'shubaowb':
            chapters, domain = await get_chapters_shubaowb(session, book_id, lambda _: None)
            title = f'shubaowb_{book_id}'
        elif site == 'zhys':
            chapters, domain = await get_chapters_zhys(session, book_id, lambda _: None)
            title = f'zhys_{book_id}'
        elif site == 'universal':
            chapters, domain, title = await get_chapters_universal(session, url, lambda _: None)
        else:
            return None, f'site "{site}" ยังไม่รองรับ'

        if not chapters:
            return None, 'ไม่พบตอนในสารบัญ — ลองตรวจสอบ URL อีกครั้ง'

        return {
            'site': site,
            'book_id': book_id,
            'domain': domain,
            'title': title or f'{site}_{book_id}',
            'chapters': chapters,
        }, None


# ── Download engine (step 2) ──────────────────────────────────────────────────

def _sort_chapters(chapters):
    """Sort chapters by the numeric chapter ID in the URL (ascending = correct order)."""
    def url_key(item):
        nums = re.findall(r'\d+', item[0].rstrip('/').split('/')[-1].split('.')[0])
        return int(nums[0]) if nums else 0
    return sorted(chapters, key=url_key)


async def run_download(scan_info, novel_name, workers, delay, min_chars, log_fn, progress_fn):
    site = scan_info['site']
    book_id = scan_info['book_id']
    domain = scan_info['domain']
    chapters = _sort_chapters(scan_info['chapters'])

    if not novel_name.strip():
        novel_name = scan_info['title'] or f'{site}_{str(book_id).replace("/","_")}'

    use_multipage = (site == 'biquge365')
    use_content_div = (site == 'universal')

    connector = aiohttp.TCPConnector(limit=workers + 2)
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        log_fn(f'📚 {len(chapters)} ตอน — เริ่มโหลด...')
        semaphore = asyncio.Semaphore(workers)
        raw_results = []
        cnt_ok = cnt_short = cnt_fail = 0
        qc_short, qc_failed = [], []

        async def dl(idx, u, t):
            r = await download_chapter(
                session, u, semaphore, delay,
                multipage=use_multipage,
                use_content_div=use_content_div,
            )
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
                        qc_short.append({
                            'no': idx + 1, 'title': title,
                            'chars': len(text), 'url': ch_url,
                        })
                    else:
                        cnt_ok += 1
                else:
                    cnt_fail += 1
                    label = toc_title or f'第{idx+1}章'
                    raw_results.append((idx, label, f'[โหลดล้มเหลว: {r["error"]}]'))
                    qc_failed.append({
                        'no': idx + 1, 'title': label,
                        'error': r['error'], 'url': ch_url,
                    })
            done = bs + len(batch)
            progress_fn(done / len(chapters))
            log_fn(f'  {done}/{len(chapters)} — OK:{cnt_ok}  สั้น:{cnt_short}  ล้มเหลว:{cnt_fail}')
            await asyncio.sleep(0.2)

    raw_results.sort(key=lambda x: x[0])
    sep = '=' * 50
    qc_lines = [
        sep,
        f'QC REPORT — {novel_name}',
        f'Site: {domain}  |  Book: {book_id}',
        f'ตอนทั้งหมด: {len(chapters)}  OK: {cnt_ok}  สั้น(<{min_chars}): {cnt_short}  ล้มเหลว: {cnt_fail}',
    ]
    if qc_short:
        qc_lines += ['ตอนสั้น:'] + [
            f'  #{s["no"]} {s["title"]} ({s["chars"]} chars)' for s in qc_short[:20]
        ]
    if qc_failed:
        qc_lines += ['ตอนล้มเหลว:'] + [
            f'  #{f["no"]} {f["title"]} — {f["error"]}' for f in qc_failed[:20]
        ]
    qc_lines.append(sep)

    body = '\n'.join(f'\n{t}\n\n{txt}' for _, t, txt in raw_results)
    txt_content = '﻿' + novel_name + '\n\n' + '\n'.join(qc_lines) + '\n\n' + body

    qc_data = {
        'book': novel_name, 'site': domain, 'book_id': book_id,
        'total_chapters': len(chapters), 'ok': cnt_ok, 'short': cnt_short,
        'failed': cnt_fail, 'min_chars': min_chars,
        'short_chapters': qc_short, 'failed_chapters': qc_failed,
    }

    safe = re.sub(r'[\\/:*?"<>|]', '_', novel_name)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f'{safe}.txt', txt_content.encode('utf-8'))
        zf.writestr(f'{safe}_QC.json', json.dumps(qc_data, ensure_ascii=False, indent=2))
    buf.seek(0)

    summary = (
        f'✅ เสร็จแล้ว!\n'
        f'ตอนทั้งหมด: {len(chapters)}\n'
        f'OK: {cnt_ok}  |  สั้น: {cnt_short}  |  ล้มเหลว: {cnt_fail}'
    )
    log_fn(summary)
    return buf.getvalue(), f'{safe}.zip', summary


# ── Streamlit UI ──────────────────────────────────────────────────────────────

st.set_page_config(page_title='Novel Downloader', page_icon='📚', layout='centered')
st.title('📚 Novel Downloader')
st.markdown('วางลิงก์นิยายแล้วกด **สแกน** — รองรับทุกเว็บนิยายจีน')

# ── Step 1: Scan ──────────────────────────────────────────────────────────────

with st.form('scan_form'):
    url_input = st.text_input(
        '🔗 ลิงก์นิยาย',
        placeholder='https://m.biquge365.net/shu/528722/',
        value=st.session_state.get('scan_url', ''),
    )
    scan_submitted = st.form_submit_button('🔍 สแกน', type='primary', use_container_width=True)

if scan_submitted and url_input.strip():
    with st.spinner('กำลังสแกนสารบัญ...'):
        scan_info, err = asyncio.run(scan_novel(url_input.strip()))
    if err:
        st.error(f'สแกนล้มเหลว: {err}')
        st.session_state.pop('scan_info', None)
    else:
        st.session_state['scan_url'] = url_input.strip()
        st.session_state['scan_info'] = scan_info
        st.session_state.pop('download_result', None)

elif scan_submitted:
    st.warning('กรุณาใส่ URL ก่อนค่ะ')

# ── Show scan result ──────────────────────────────────────────────────────────

scan_info = st.session_state.get('scan_info')

if scan_info:
    chapters = scan_info['chapters']
    st.success(
        f'**{scan_info["title"]}**  \n'
        f'พบ **{len(chapters)} ตอน** บน {scan_info["domain"]}  \n'
        f'ตอนแรก: {chapters[0][1] or chapters[0][0]}  \n'
        f'ตอนสุดท้าย: {chapters[-1][1] or chapters[-1][0]}'
    )

    # ── Step 2: Download settings ─────────────────────────────────────────────

    st.divider()
    st.subheader('⚙️ ตั้งค่าการโหลด')

    novel_name = st.text_input(
        'ชื่อไฟล์',
        value=scan_info['title'],
        placeholder='ชื่อไฟล์ที่บันทึก',
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        workers = st.slider('Workers', 1, 8, 3)
    with c2:
        delay = st.slider('Delay (วิ)', 0.5, 5.0, 2.0, step=0.5)
    with c3:
        min_chars = st.number_input(
            'QC ขั้นต่ำตัวอักษร', min_value=50, max_value=2000, value=300, step=50
        )

    if st.button('⬇️ โหลด', type='primary', use_container_width=True):
        log_area = st.empty()
        progress_bar = st.progress(0.0, text='กำลังโหลด...')
        logs = []

        def log(msg):
            logs.append(msg)
            log_area.text_area(
                'Log', value='\n'.join(logs), height=220, label_visibility='collapsed'
            )

        def set_progress(val):
            progress_bar.progress(min(val, 1.0), text=f'โหลดแล้ว {val*100:.0f}%')

        try:
            zip_bytes, zip_name, summary = asyncio.run(
                run_download(
                    scan_info, novel_name, workers, float(delay),
                    int(min_chars), log, set_progress,
                )
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

st.markdown("""
---
**ตัวอย่าง URL ที่รองรับ:**
- `https://m.biquge365.net/shu/528722/`
- `https://www.69shu.xyz/index/2/2829/1.html/`
- `https://shubaowb.com/novel/YH2B.html`
- และเว็บนิยายจีนอื่นๆ ที่มีสารบัญตอน
""")
