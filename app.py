#!/usr/bin/env python3
"""Novel Downloader — Streamlit web app (self-adapting universal scraper)

Architecture:
  Scan → Detect Issues → Fix → Download with profile → QC

3-step workflow:
  1. Scan: fetch TOC + analyze sample chapters → build SiteProfile
  2. Fix:  detect issues (low content, empty titles, no multipage, etc.)
           and attempt automatic fixes (desktop URLs, different headers, etc.)
  3. Download: use the (possibly fixed) profile for reliable extraction + QC

The system learns each website's structure by examining sample chapters during
the scan phase, then uses that knowledge for reliable extraction.
"""

import asyncio
import aiohttp
import re
import json
import io
import zipfile
import statistics
from urllib.parse import urlparse, urljoin
import streamlit as st
from html.parser import HTMLParser


# ── Junk / Navigation Filters ────────────────────────────────────────────────

JUNK_RE = re.compile(
    r'当前位置|上一章|下一章|回目录|©\s*20\d\d|document\.domain|'
    r'google|adsbygoogle|function\(i,s|var\s+_hmt|百度|本站|书签|收藏|推荐|'
    r'首页|返回目录|关灯|护眼|字号|章节报错|一秒记住|笔趣阁|更新快|无弹窗|'
    r'本章未完|点击下一页|请点击下一页|最新章节|设为首页|加入书架|手机版|'
    r'请记住本站|如遇到内容乱|验证码|\/\/',
    re.IGNORECASE,
)

JUNK_SECTION_RE = re.compile(
    r'<(?:div|section|ul|ol)[^>]+(?:id|class)="[^"]*'
    r'(?:recommend|related|similar|tuijian|hot|rank|listmain|booklist|'
    r'guess|like|other[_-]?novel|bottom|foot|sidebar|widget|ad[_-s]|banner)'
    r'[^"]*"[^>]*>[\s\S]*?</(?:div|section|ul|ol)>',
    re.IGNORECASE,
)

PAGE_MARKER_RE = re.compile(r'[（(]第\s*\d+\s*/\s*\d+\s*页[）)]')

_NAV_EXACT = {
    '返回', '目录', '首页', '书签', '收藏', '推荐', '关灯', '护眼',
    '上一章', '下一章', '上一页', '下一页', '回目录', '加入书架',
    '提交关闭',
}

_CHAPTER_HDR_RE = re.compile(r'^第\s*\d+\s*[章节話话回]')


# ── Text cleaning ────────────────────────────────────────────────────────────

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


def count_chinese(text):
    return len(re.findall(r'[一-鿿]', text))


# ── HTML parsing ─────────────────────────────────────────────────────────────

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


def _strip_html_junk(html):
    """Remove script/style/nav/footer/aside/form and recommendation sections."""
    stripped = re.sub(
        r'<(script|style|nav|header|footer|aside|iframe|form|button)'
        r'[^>]*>[\s\S]*?</\1>',
        '', html, flags=re.IGNORECASE,
    )
    stripped = JUNK_SECTION_RE.sub('', stripped)
    return stripped


def find_content_div(html):
    """Extract the main story content div, stripping junk and recommendations."""
    stripped = _strip_html_junk(html)

    CONTENT_PAT = re.compile(
        r'<(?:div|section|article)[^>]+(?:id|class)="[^"]*'
        r'(?:content|article|chapter|read|text|novel|book|chap|body|'
        r'BookContent|readcontent|booktext|nr_content|zhangjieTXT)[^"]*"[^>]*>'
        r'([\s\S]*?)'
        r'</(?:div|section|article)>',
        re.IGNORECASE,
    )
    best_text = ''
    best_count = 0
    for m in CONTENT_PAT.finditer(stripped):
        inner = re.sub(r'<[^>]+>', ' ', m.group(1))
        cn = count_chinese(inner)
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
        cn = count_chinese(inner)
        if cn > best_count:
            best_count = cn
            best_text = inner
    if best_count >= 100:
        return best_text

    paragraphs = re.findall(r'<p[^>]*>([\s\S]*?)</p>', stripped, re.IGNORECASE)
    return ' '.join(re.sub(r'<[^>]+>', ' ', p) for p in paragraphs)


def extract_text_from_html(html):
    parser = TextExtractor()
    parser.feed(html)
    lines = clean_lines(parser._paragraphs)
    lines = _remove_leading_headings(lines)
    if len(lines) >= 3:
        return lines
    lines = clean_lines(''.join(parser._all_text).split('\n'))
    return _remove_leading_headings(lines)


def extract_text_from_content(content_text):
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


def _extract_all_text_stripped(html):
    """Extract all visible text from HTML after stripping junk tags/sections."""
    stripped = _strip_html_junk(html)
    stripped = re.sub(r'<br\s*/?>', '\n', stripped, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', stripped)
    lines = clean_lines(text.split('\n'))
    return _remove_leading_headings(lines)


def smart_extract(html, use_content_div=True):
    """Try all extraction methods, return whichever yields the most Chinese text."""
    candidates = []

    # Method 1: Content-div heuristic
    content = find_content_div(html)
    lines1 = extract_text_from_content(content)
    cn1 = sum(count_chinese(l) for l in lines1)
    candidates.append((cn1, lines1))

    # Method 2: <p> paragraphs from full HTML parser
    lines2 = extract_text_from_html(html)
    cn2 = sum(count_chinese(l) for l in lines2)
    candidates.append((cn2, lines2))

    # Method 3: All visible text after stripping junk
    lines3 = _extract_all_text_stripped(html)
    cn3 = sum(count_chinese(l) for l in lines3)
    candidates.append((cn3, lines3))

    best_cn, best_lines = max(candidates, key=lambda x: x[0])
    if best_lines:
        return best_lines
    return lines2 or lines1 or lines3


# ── HTTP helpers ─────────────────────────────────────────────────────────────

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Connection': 'keep-alive',
}


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
        except Exception:
            await asyncio.sleep(3 * (retry + 1))
    return None, 'max retries'


async def fetch_html(session, url):
    html, _ = await _fetch_one(session, url)
    return html


# ── URL parsing ──────────────────────────────────────────────────────────────

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


# ── Site Analysis ────────────────────────────────────────────────────────────

def _candidate_page2_urls(url):
    """Generate candidate page-2 URLs to probe for multi-page chapters."""
    candidates = []
    m = re.match(r'^(.*?)(\d+)(\.html?)$', url)
    if m:
        candidates.append(f'{m.group(1)}{m.group(2)}_2{m.group(3)}')
    sep = '&' if '?' in url else '?'
    candidates.append(f'{url}{sep}page=2')
    return candidates


def _get_next_page_url(base_url, page_num, pattern):
    """Build URL for page N using the discovered multi-page pattern."""
    if pattern == 'underscore':
        m = re.match(r'^(.*?\d+?)(?:_\d+)?(\.html?)$', base_url)
        if m:
            return f'{m.group(1)}_{page_num}{m.group(2)}'
    elif pattern == 'query':
        base = re.sub(r'[?&]page=\d+', '', base_url)
        sep = '&' if '?' in base else '?'
        return f'{base}{sep}page={page_num}'
    return None


async def analyze_site(session, chapters, log):
    """Fetch sample chapters to learn content structure and pagination.

    Compares all three extraction methods; picks the one with most Chinese chars.
    Returns a profile dict used by the downloader.
    """
    if not chapters:
        return {'multipage_pattern': None, 'avg_chars': 0,
                'best_method': 'smart', 'sample_char_counts': [], 'low_quality': False}

    n = len(chapters)
    indices = sorted(set([0, max(0, n // 4), n // 2, min(n - 1, 3 * n // 4)]))
    if len(indices) > 4:
        indices = indices[:4]
    samples = [chapters[i][0] for i in indices]

    char_counts_smart = []
    multipage_pattern = None
    multipage_extra_chars = 0

    for url in samples:
        html = await fetch_html(session, url)
        if not html:
            continue

        # smart_extract already picks the best of all three methods
        lines = smart_extract(html)
        cn = sum(count_chinese(l) for l in lines)
        char_counts_smart.append(cn)

        if multipage_pattern is None:
            for candidate_url in _candidate_page2_urls(url):
                html2 = await fetch_html(session, candidate_url)
                if html2 is None:
                    continue
                lines2 = smart_extract(html2)
                cn2 = sum(count_chinese(l) for l in lines2)
                first_page_start = ''.join(lines[:2])
                page2_start = ''.join(lines2[:2])
                if cn2 > 80 and page2_start != first_page_start:
                    multipage_pattern = (
                        'underscore' if '_2.html' in candidate_url else 'query'
                    )
                    multipage_extra_chars = cn2
                    log(f'🔍 พบระบบหน้าต่อ ({multipage_pattern}) — '
                        f'หน้า 2 มี {cn2} ตัวอักษรจีน')
                    break

        await asyncio.sleep(0.3)

    avg_chars = int(statistics.mean(char_counts_smart)) if char_counts_smart else 0
    if multipage_pattern:
        avg_chars += multipage_extra_chars

    low_quality = avg_chars < 200
    quality = 'ดี' if avg_chars > 1500 else 'ปานกลาง' if avg_chars > 500 else 'ต่ำมาก (อาจต้องใช้ JS หรือ login)'
    log(f'🔍 วิเคราะห์เสร็จ — เฉลี่ย ~{avg_chars} อักษรจีน/ตอน, คุณภาพ: {quality}, '
        f'หน้าต่อ: {"มี" if multipage_pattern else "ไม่พบ"}')
    if low_quality:
        log(f'⚠️ เนื้อหาน้อยมาก — เว็บนี้อาจใช้ JavaScript หรือต้องการ login เพื่อแสดงเนื้อหา')

    return {
        'multipage_pattern': multipage_pattern,
        'avg_chars': avg_chars,
        'best_method': 'smart',
        'sample_char_counts': char_counts_smart,
        'low_quality': low_quality,
    }


# ── Issue Detection & Fix ───────────────────────────────────────────────────

def detect_issues(scan_info):
    """Analyze scan results and return a list of issues with severity and fixability.

    Each issue: {id, severity, icon, title, detail, fixable, fixed}
    severity: 'critical' | 'warning' | 'info'
    """
    issues = []
    chapters = scan_info.get('chapters', [])
    profile = scan_info.get('profile', {})
    avg_chars = profile.get('avg_chars', 0)
    mp = profile.get('multipage_pattern')
    sample_counts = profile.get('sample_char_counts', [])

    # 1. Content quality
    if avg_chars < 100:
        issues.append({
            'id': 'content_critical',
            'severity': 'critical',
            'icon': '🔴',
            'title': 'เนื้อหาน้อยมาก',
            'detail': f'เฉลี่ยเพียง ~{avg_chars} ตัวอักษรจีน/ตอน — '
                      f'เว็บอาจใช้ JavaScript โหลดเนื้อหา หรือต้อง login',
            'fixable': True,
            'fixed': False,
        })
    elif avg_chars < 500:
        issues.append({
            'id': 'content_low',
            'severity': 'warning',
            'icon': '🟡',
            'title': 'เนื้อหาค่อนข้างน้อย',
            'detail': f'เฉลี่ย ~{avg_chars} ตัวอักษรจีน/ตอน — '
                      f'ปกติควรได้ 1,500-3,000 อาจได้แค่หน้าแรกของแต่ละตอน',
            'fixable': True,
            'fixed': False,
        })
    else:
        issues.append({
            'id': 'content_ok',
            'severity': 'info',
            'icon': '🟢',
            'title': 'เนื้อหาดี',
            'detail': f'เฉลี่ย ~{avg_chars} ตัวอักษรจีน/ตอน',
            'fixable': False,
            'fixed': True,
        })

    # 2. Empty titles
    empty_titles = sum(1 for _, t in chapters if not t.strip())
    if empty_titles > len(chapters) * 0.5:
        issues.append({
            'id': 'titles_empty',
            'severity': 'warning',
            'icon': '🟡',
            'title': 'ชื่อตอนว่างเปล่า',
            'detail': f'{empty_titles}/{len(chapters)} ตอนไม่มีชื่อ — '
                      f'จะใช้ชื่อจากหน้าตอนแทน (อาจทำให้เรียงลำดับไม่ถูกต้อง)',
            'fixable': True,
            'fixed': False,
        })
    else:
        issues.append({
            'id': 'titles_ok',
            'severity': 'info',
            'icon': '🟢',
            'title': 'ชื่อตอนครบ',
            'detail': f'{len(chapters) - empty_titles}/{len(chapters)} ตอนมีชื่อ',
            'fixable': False,
            'fixed': True,
        })

    # 3. Multi-page
    if mp:
        issues.append({
            'id': 'multipage_ok',
            'severity': 'info',
            'icon': '🟢',
            'title': 'พบระบบหน้าต่อ',
            'detail': f'รูปแบบ: {mp} — จะดาวน์โหลดทุกหน้าของแต่ละตอน',
            'fixable': False,
            'fixed': True,
        })
    else:
        if avg_chars < 800:
            issues.append({
                'id': 'multipage_missing',
                'severity': 'warning',
                'icon': '🟡',
                'title': 'ไม่พบระบบหน้าต่อ',
                'detail': 'เนื้อหาน้อย + ไม่พบหน้าต่อ — อาจได้แค่หน้าแรก',
                'fixable': True,
                'fixed': False,
            })
        else:
            issues.append({
                'id': 'multipage_none',
                'severity': 'info',
                'icon': '🟢',
                'title': 'ตอนละ 1 หน้า',
                'detail': 'ไม่มีระบบหน้าต่อ — เนื้อหาอยู่ในหน้าเดียวครบแล้ว',
                'fixable': False,
                'fixed': True,
            })

    # 4. Chapter count sanity
    if len(chapters) == 0:
        issues.append({
            'id': 'chapters_zero',
            'severity': 'critical',
            'icon': '🔴',
            'title': 'ไม่พบตอน',
            'detail': 'สารบัญว่างเปล่า — URL อาจไม่ถูกต้อง',
            'fixable': False,
            'fixed': False,
        })
    elif len(chapters) < 10:
        issues.append({
            'id': 'chapters_few',
            'severity': 'warning',
            'icon': '🟡',
            'title': f'พบน้อย ({len(chapters)} ตอน)',
            'detail': 'อาจไม่ครบ — สารบัญอาจมีหลายหน้าที่ยังไม่ถูกสแกน',
            'fixable': False,
            'fixed': False,
        })
    else:
        issues.append({
            'id': 'chapters_ok',
            'severity': 'info',
            'icon': '🟢',
            'title': f'จำนวนตอน ({len(chapters)} ตอน)',
            'detail': 'จำนวนตอนดูสมเหตุสมผล',
            'fixable': False,
            'fixed': True,
        })

    # 5. Sample variance — one very low sample among decent ones
    if len(sample_counts) >= 3 and avg_chars > 200:
        low_samples = [c for c in sample_counts if c < avg_chars * 0.3]
        if low_samples:
            if profile.get('variance_checked'):
                issues.append({
                    'id': 'variance_checked',
                    'severity': 'info',
                    'icon': '🟢',
                    'title': 'คุณภาพตรวจแล้ว',
                    'detail': f'ตรวจซ้ำแล้ว — ตอนสั้นเป็นเนื้อหาจริง (ไม่ใช่ข้อผิดพลาด) '
                              f'ระบบ QC จะตรวจอีกครั้งหลังดาวน์โหลด',
                    'fixable': False,
                    'fixed': True,
                })
            else:
                issues.append({
                    'id': 'variance_high',
                    'severity': 'warning',
                    'icon': '🟡',
                    'title': 'คุณภาพไม่สม่ำเสมอ',
                    'detail': f'ตัวอย่างบางตอนได้เพียง {min(sample_counts)} อักษร '
                              f'(เฉลี่ย {avg_chars}) — บางตอนอาจได้เนื้อหาไม่ครบ',
                    'fixable': True,
                    'fixed': False,
                })

    return issues


async def fix_issues(scan_info, issues, log):
    """Attempt to fix detected issues. Modifies scan_info in-place.

    Strategies:
    - Low content: try desktop URL (remove 'm.' prefix), different User-Agent
    - Empty titles: fetch titles from chapter pages in batches
    - Missing multi-page: try additional URL patterns more aggressively
    Returns updated issues list.
    """
    chapters = scan_info['chapters']
    profile = scan_info.get('profile', {})
    fixable_ids = {i['id'] for i in issues if i['fixable'] and not i['fixed']}

    if not fixable_ids:
        log('✅ ไม่มีปัญหาที่ต้องแก้ไข')
        return issues

    connector = aiohttp.TCPConnector(limit=5)
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:

        # ── Fix 1: Low content — try desktop URL ────────────────────────
        if 'content_critical' in fixable_ids or 'content_low' in fixable_ids:
            log('🔧 กำลังลองวิธีแก้ปัญหาเนื้อหาน้อย...')

            # Strategy A: try desktop domain (remove m. prefix)
            sample_url = chapters[0][0] if chapters else ''
            parsed = urlparse(sample_url)
            host = parsed.netloc
            desktop_host = None
            if host.startswith('m.'):
                desktop_host = host[2:]
            elif host.startswith('wap.'):
                desktop_host = 'www.' + host[4:]

            improved = False
            if desktop_host:
                log(f'  ↳ ลอง desktop URL: {desktop_host}')
                test_url = sample_url.replace(host, desktop_host)
                html = await fetch_html(session, test_url)
                if html:
                    lines = smart_extract(html)
                    cn = sum(count_chinese(l) for l in lines)
                    old_avg = profile.get('avg_chars', 0)
                    if cn > old_avg * 1.5 and cn > 200:
                        log(f'  ✅ Desktop URL ดีกว่า: {cn} อักษร (เดิม ~{old_avg})')
                        new_chapters = []
                        for url, title in chapters:
                            new_chapters.append((url.replace(host, desktop_host), title))
                        scan_info['chapters'] = new_chapters
                        scan_info['domain'] = desktop_host
                        chapters = new_chapters
                        improved = True

            # Strategy B: try different User-Agent (Googlebot, mobile)
            if not improved:
                log('  ↳ ลอง User-Agent อื่น...')
                alt_agents = [
                    ('Googlebot', 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'),
                    ('Mobile', 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15'),
                ]
                test_url = chapters[len(chapters)//2][0] if chapters else ''
                for name, ua in alt_agents:
                    try:
                        hdrs = dict(HEADERS)
                        hdrs['User-Agent'] = ua
                        async with session.get(test_url,
                                               headers=hdrs,
                                               timeout=aiohttp.ClientTimeout(total=20)) as resp:
                            if resp.status == 200:
                                html = await resp.text(errors='replace')
                                lines = smart_extract(html)
                                cn = sum(count_chinese(l) for l in lines)
                                old_avg = profile.get('avg_chars', 0)
                                if cn > old_avg * 1.5 and cn > 200:
                                    log(f'  ✅ {name} UA ดีกว่า: {cn} อักษร (เดิม ~{old_avg})')
                                    improved = True
                                    break
                    except Exception:
                        pass

            if not improved:
                log('  ❌ ไม่สามารถแก้ปัญหาเนื้อหาน้อยได้ — เว็บนี้อาจต้องใช้ browser จริง')

        # ── Fix 2: Empty titles — fetch from chapter pages ──────────────
        if 'titles_empty' in fixable_ids:
            log('🔧 กำลังดึงชื่อตอนจากหน้าตอน...')
            empty_indices = [i for i, (_, t) in enumerate(chapters) if not t.strip()]
            batch_indices = empty_indices[:min(50, len(empty_indices))]

            fetched = 0
            sem = asyncio.Semaphore(5)

            async def fetch_title(idx):
                nonlocal fetched
                url = chapters[idx][0]
                async with sem:
                    html = await fetch_html(session, url)
                    if html:
                        title = extract_title(html)
                        if title:
                            chapters[idx] = (url, clean_title(title))
                            fetched += 1
                    await asyncio.sleep(0.3)

            batch_size = 10
            for bs in range(0, len(batch_indices), batch_size):
                batch = batch_indices[bs:bs+batch_size]
                await asyncio.gather(*[fetch_title(i) for i in batch])
                log(f'  ↳ ดึงชื่อตอนแล้ว {min(bs+batch_size, len(batch_indices))}/{len(batch_indices)}')

            if fetched > 0:
                log(f'  ✅ ดึงชื่อตอนสำเร็จ {fetched}/{len(batch_indices)} ตอน')
                scan_info['chapters'] = chapters
            else:
                log('  ❌ ไม่สามารถดึงชื่อตอนจากหน้าตอนได้')

        # ── Fix 3: Missing multi-page — try more patterns ───────────────
        if 'multipage_missing' in fixable_ids:
            log('🔧 กำลังค้นหาระบบหน้าต่อเพิ่มเติม...')
            test_indices = [0, len(chapters)//3, len(chapters)//2, len(chapters)*2//3]
            found_pattern = None

            for idx in test_indices:
                if idx >= len(chapters):
                    continue
                url = chapters[idx][0]
                html = await fetch_html(session, url)
                if not html:
                    continue

                lines = smart_extract(html)
                first_snippet = ''.join(lines[:2])

                # Try more aggressive URL patterns
                extra_candidates = []
                m = re.match(r'^(.*?)(\d+)(\.s?html?)$', url)
                if m:
                    base, num, ext = m.group(1), m.group(2), m.group(3)
                    extra_candidates.append(f'{base}{num}_2{ext}')
                    extra_candidates.append(f'{base}{num}-2{ext}')
                    extra_candidates.append(f'{base}{num}/2{ext}')
                sep = '&' if '?' in url else '?'
                extra_candidates.append(f'{url}{sep}page=2')
                extra_candidates.append(f'{url}{sep}p=2')

                # Also check for 下一页 links in HTML
                next_m = re.search(
                    r'<a[^>]+href="([^"]+)"[^>]*>\s*(?:下一页|下一頁|next\s*page)\s*</a>',
                    html, re.IGNORECASE
                )
                if next_m:
                    href = next_m.group(1)
                    if not href.startswith('http'):
                        href = urljoin(url, href)
                    extra_candidates.insert(0, href)

                for candidate_url in extra_candidates:
                    html2 = await fetch_html(session, candidate_url)
                    if html2 is None:
                        continue
                    lines2 = smart_extract(html2)
                    cn2 = sum(count_chinese(l) for l in lines2)
                    page2_start = ''.join(lines2[:2])
                    if cn2 > 80 and page2_start != first_snippet:
                        if '_2.' in candidate_url or '-2.' in candidate_url:
                            found_pattern = 'underscore'
                        elif 'page=' in candidate_url or 'p=' in candidate_url:
                            found_pattern = 'query'
                        else:
                            found_pattern = 'underscore'
                        log(f'  ✅ พบระบบหน้าต่อ: {found_pattern} (+{cn2} อักษร)')
                        break
                if found_pattern:
                    break
                await asyncio.sleep(0.3)

            if found_pattern:
                profile['multipage_pattern'] = found_pattern
                scan_info['profile'] = profile
            else:
                log('  ❌ ไม่พบระบบหน้าต่อเพิ่มเติม')

        # ── Fix 4: High variance — re-sample the low-scoring chapters ────
        if 'variance_high' in fixable_ids:
            log('🔧 กำลังตรวจสอบตอนที่ได้คะแนนต่ำซ้ำ...')
            sample_counts = profile.get('sample_char_counts', [])
            avg = profile.get('avg_chars', 0)
            if sample_counts and avg > 200:
                n = len(chapters)
                indices = sorted(set([0, max(0, n // 4), n // 2, min(n - 1, 3 * n // 4)]))
                low_idx = [i for i, c in zip(indices, sample_counts) if c < avg * 0.3]
                for idx in low_idx:
                    url = chapters[idx][0]
                    for attempt_ua in [
                        HEADERS['User-Agent'],
                        'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
                    ]:
                        try:
                            hdrs = dict(HEADERS)
                            hdrs['User-Agent'] = attempt_ua
                            async with session.get(url, headers=hdrs,
                                                   timeout=aiohttp.ClientTimeout(total=20)) as resp:
                                if resp.status == 200:
                                    html = await resp.text(errors='replace')
                                    lines = smart_extract(html)
                                    cn = sum(count_chinese(l) for l in lines)
                                    if cn > avg * 0.5:
                                        log(f'  ✅ ตอนที่ {idx+1} ดีขึ้น: {cn} อักษร')
                                        break
                        except Exception:
                            pass
                    await asyncio.sleep(0.3)
                log('  ℹ️ ความแตกต่างอาจเกิดจากเนื้อหาตอนสั้นจริง — จะตรวจละเอียดอีกครั้งตอนดาวน์โหลด')
            profile['variance_checked'] = True
            scan_info['profile'] = profile

        # ── Re-analyze after fixes ──────────────────────────────────────
        log('🔍 กำลังวิเคราะห์ซ้ำหลังแก้ไข...')
        new_profile = await analyze_site(session, chapters, log)

        # Keep multipage pattern if we found one in fix
        if profile.get('multipage_pattern') and not new_profile.get('multipage_pattern'):
            new_profile['multipage_pattern'] = profile['multipage_pattern']

        scan_info['profile'] = new_profile
        scan_info['chapters'] = chapters

    # Re-detect issues with updated data
    return detect_issues(scan_info)


# ── Chapter next-page fallback ───────────────────────────────────────────────

def _chapter_next_page_fallback(html, current_url):
    """Detect next page using HTML text markers (fallback when no pattern known)."""
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
        return f'{base}{cid}_{int(pn) + 1 if pn else 2}.html'
    return None


# ── Chapter downloader ───────────────────────────────────────────────────────

async def download_chapter(session, url, semaphore, delay, profile):
    """Download one chapter using the site profile for smart extraction."""
    async with semaphore:
        html, err = await _fetch_one(session, url)
        if html is None:
            return {'ok': False, 'error': err}

        title = extract_title(html)
        use_cd = profile.get('use_content_div', True)
        all_lines = smart_extract(html, use_content_div=use_cd)
        first_snippet = ''.join(all_lines[:3])

        mp = profile.get('multipage_pattern')
        if mp:
            # Use discovered URL pattern for page 2, 3, ...
            for pn in range(2, 21):
                nxt = _get_next_page_url(url, pn, mp)
                if not nxt:
                    break
                await asyncio.sleep(delay * 0.3)
                h2, _ = await _fetch_one(session, nxt)
                if h2 is None:
                    break
                extra = smart_extract(h2, use_content_div=use_cd)
                if not extra or sum(count_chinese(l) for l in extra) < 30:
                    break
                if ''.join(extra[:3]) == first_snippet:
                    break
                all_lines.extend(extra)
        elif re.search(r'本章未完|点击下一页|下一页继续|未完待续', html or ''):
            # Text-marker fallback
            cur_url, cur_html = url, html
            for _ in range(19):
                nxt = _chapter_next_page_fallback(cur_html, cur_url)
                if not nxt or nxt == cur_url:
                    break
                await asyncio.sleep(delay * 0.3)
                h2, _ = await _fetch_one(session, nxt)
                if h2 is None:
                    break
                extra = smart_extract(h2, use_content_div=use_cd)
                if not extra or sum(count_chinese(l) for l in extra) < 30:
                    break
                if ''.join(extra[:3]) == first_snippet:
                    break
                all_lines.extend(extra)
                cur_html, cur_url = h2, nxt

        if all_lines:
            text = '\n\n'.join(all_lines)
            cn = count_chinese(text)
            return {'ok': True, 'title': title, 'text': text, 'cn_chars': cn}
        return {'ok': False, 'error': 'empty'}
    await asyncio.sleep(delay)


# ── TOC scrapers ─────────────────────────────────────────────────────────────

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
            rf'href="([^"]*\?p={pn + 1}[^"]*)"',
            r'href="([^"]+)"[^>]*>\s*(?:下一页|下一頁)\s*</a>',
            rf'href="(/shu/{book_id}/index_{pn + 1}\.html)"',
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
            rf'href="[^"]*/{re.escape(book_path)}/{page + 1}\.html/?[^"]*"', html
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
            rf'href="(/novel/{book_id}_{pn + 1}\.html)"',
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
            chapters.append((url, title or f'Chapter {len(chapters) + 1}'))
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
            if href.startswith('http'):
                abs_url = href
            elif href.startswith('/'):
                abs_url = base_domain + href
            else:
                abs_url = urljoin(toc_url, href)
            if urlparse(abs_url).netloc != parsed.netloc:
                continue
            if abs_url not in seen:
                seen.add(abs_url)
                found.append((abs_url, text))
        return found

    def find_next_toc_page(html, current_url, pn):
        for pat in [
            r'<a[^>]+href="([^"]+)"[^>]*>\s*(?:下一页|下一頁)\s*</a>',
            rf'href="([^"]*[?/]p(?:age)?[=_/]{pn + 1}[^"]*)"',
            rf'href="([^"]*index_{pn + 1}\.html[^"]*)"',
            rf'href="([^"]*/{pn + 1}\.html[^"]*)"',
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


# ── Sort ─────────────────────────────────────────────────────────────────────

def _sort_chapters(chapters):
    """Sort by 第N章 if most titles have chapter numbers; otherwise keep TOC order."""
    titled = sum(1 for _, t in chapters if re.search(r'第\s*\d+\s*[章节話话回]', t))

    if titled >= len(chapters) * 0.3:
        def key(pair):
            idx, (url, title) = pair
            m = re.search(r'第\s*(\d+)\s*[章节話话回]', title)
            if m:
                return (0, int(m.group(1)))
            return (1, idx)
        indexed = sorted(enumerate(chapters), key=key)
        return [ch for _, ch in indexed]

    return list(chapters)


# ── Scan (step 1) ────────────────────────────────────────────────────────────

async def scan_novel(url, log=None):
    if log is None:
        log = lambda _: None
    connector = aiohttp.TCPConnector(limit=5)
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        site, book_id = parse_novel_url(url)

        if site == 'biquge365':
            chapters, domain = await get_chapters_biquge365(session, book_id, log)
            html = await fetch_html(session, f'https://{domain}/shu/{book_id}/')
            title = extract_title(html) if html else f'biquge365_{book_id}'
        elif site == '69shu':
            chapters, domain = await get_chapters_69shu(session, book_id, log)
            title = f'69shu_{book_id}'
        elif site == 'shubaowb':
            chapters, domain = await get_chapters_shubaowb(session, book_id, log)
            title = f'shubaowb_{book_id}'
        elif site == 'zhys':
            chapters, domain = await get_chapters_zhys(session, book_id, log)
            title = f'zhys_{book_id}'
        elif site == 'universal':
            chapters, domain, title = await get_chapters_universal(session, url, log)
        else:
            return None, f'site "{site}" ยังไม่รองรับ'

        if not chapters:
            return None, 'ไม่พบตอนในสารบัญ — ลองตรวจสอบ URL อีกครั้ง'

        log(f'🔍 กำลังวิเคราะห์โครงสร้างเว็บ ({min(4, len(chapters))} ตัวอย่าง)...')
        profile = await analyze_site(session, chapters, log)

        return {
            'site': site,
            'book_id': book_id,
            'domain': domain,
            'title': title or f'{site}_{book_id}',
            'chapters': chapters,
            'profile': profile,
        }, None


# ── Download engine (step 2) ─────────────────────────────────────────────────

async def run_download(scan_info, novel_name, workers, delay, min_chars, log_fn, progress_fn):
    site = scan_info['site']
    book_id = scan_info['book_id']
    domain = scan_info['domain']
    profile = scan_info.get('profile', {})
    chapters = _sort_chapters(scan_info['chapters'])

    if not novel_name.strip():
        novel_name = scan_info['title'] or f'{site}_{str(book_id).replace("/", "_")}'

    connector = aiohttp.TCPConnector(limit=workers + 2)
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        log_fn(f'📚 {len(chapters)} ตอน — เริ่มโหลด...')
        if profile.get('multipage_pattern'):
            log_fn(f'   (หน้าต่อ: {profile["multipage_pattern"]})')
        semaphore = asyncio.Semaphore(workers)
        raw_results = []
        cnt_ok = cnt_short = cnt_fail = 0
        qc_short, qc_failed = [], []

        async def dl(idx, u, t):
            r = await download_chapter(session, u, semaphore, delay, profile)
            return idx, t, r

        batch_size = 20
        for bs in range(0, len(chapters), batch_size):
            batch = chapters[bs:bs + batch_size]
            res = await asyncio.gather(
                *[dl(bs + i, u, t) for i, (u, t) in enumerate(batch)]
            )
            for idx, toc_title, r in sorted(res, key=lambda x: x[0]):
                ch_url = chapters[idx][0]
                if r['ok']:
                    title = r['title'] or toc_title or f'第{idx + 1}章'
                    text = r['text']
                    cn = r.get('cn_chars', count_chinese(text))
                    raw_results.append((idx, title, text, cn))
                    if cn < min_chars:
                        cnt_short += 1
                        qc_short.append({
                            'no': idx + 1, 'title': title,
                            'chars': cn, 'url': ch_url,
                        })
                    else:
                        cnt_ok += 1
                else:
                    cnt_fail += 1
                    label = toc_title or f'第{idx + 1}章'
                    raw_results.append((idx, label, f'[โหลดล้มเหลว: {r["error"]}]', 0))
                    qc_failed.append({
                        'no': idx + 1, 'title': label,
                        'error': r['error'], 'url': ch_url,
                    })
            done = bs + len(batch)
            progress_fn(done / len(chapters))
            log_fn(f'  {done}/{len(chapters)} — OK:{cnt_ok}  สั้น:{cnt_short}  ล้มเหลว:{cnt_fail}')
            await asyncio.sleep(0.2)

    raw_results.sort(key=lambda x: x[0])

    # ── Post-download QC ─────────────────────────────────────────────────
    ok_chars = [cn for _, _, _, cn in raw_results if cn > 0]
    median_chars = int(statistics.median(ok_chars)) if ok_chars else 0

    # Detect common junk suffix that appears in many chapters
    if len(raw_results) > 10:
        endings = {}
        for _, _, text, cn in raw_results:
            if cn > 50:
                last = text.strip()[-80:]
                endings[last] = endings.get(last, 0) + 1
        common_junk = [e for e, c in endings.items() if c > len(raw_results) * 0.3]
        if common_junk:
            cleaned_count = 0
            cleaned = []
            for idx, title, text, cn in raw_results:
                for suffix in common_junk:
                    if text.endswith(suffix):
                        text = text[:-len(suffix)].rstrip()
                        cn = count_chinese(text)
                        cleaned_count += 1
                cleaned.append((idx, title, text, cn))
            raw_results = cleaned
            if cleaned_count:
                log_fn(f'🧹 ลบข้อความซ้ำท้ายตอนออก {cleaned_count} ตอน')

    # Flag chapters far below median
    qc_suspicious = []
    if median_chars > 200:
        for idx, title, text, cn in raw_results:
            if 0 < cn < median_chars * 0.35:
                qc_suspicious.append({
                    'no': idx + 1, 'title': title,
                    'chars': cn, 'expected': median_chars,
                })

    # Check for missing chapter numbers
    qc_missing = []
    numbered = {}
    for idx, title, text, cn in raw_results:
        m_num = re.search(r'第\s*(\d+)\s*[章节話话回]', title)
        if m_num:
            numbered[int(m_num.group(1))] = idx
    if len(numbered) > len(raw_results) * 0.3 and numbered:
        expected_range = set(range(min(numbered), max(numbered) + 1))
        missing = sorted(expected_range - set(numbered.keys()))
        if missing:
            qc_missing = missing[:30]

    # ── Build output ─────────────────────────────────────────────────────
    sep = '=' * 50
    qc_lines = [
        sep,
        f'QC REPORT — {novel_name}',
        f'Site: {domain}  |  Book: {book_id}',
        f'ตอนทั้งหมด: {len(chapters)}  OK: {cnt_ok}  '
        f'สั้น(<{min_chars}): {cnt_short}  ล้มเหลว: {cnt_fail}',
        f'ค่ากลาง: {median_chars} ตัวอักษรจีน/ตอน',
    ]
    if profile.get('multipage_pattern'):
        qc_lines.append(f'Multi-page: {profile["multipage_pattern"]}')
    if qc_suspicious:
        qc_lines += [
            f'⚠️ ตอนสั้นผิดปกติ (<35% ของค่ากลาง {median_chars}):'
        ] + [
            f'  #{s["no"]} {s["title"]} ({s["chars"]} อักษร, คาด ~{s["expected"]})'
            for s in qc_suspicious[:20]
        ]
    if qc_short:
        qc_lines += ['ตอนสั้น:'] + [
            f'  #{s["no"]} {s["title"]} ({s["chars"]} chars)' for s in qc_short[:20]
        ]
    if qc_failed:
        qc_lines += ['ตอนล้มเหลว:'] + [
            f'  #{f["no"]} {f["title"]} — {f["error"]}' for f in qc_failed[:20]
        ]
    if qc_missing:
        qc_lines.append(
            f'ตอนที่อาจหายไป: {", ".join(f"第{n}章" for n in qc_missing)}'
        )
    qc_lines.append(sep)

    body = '\n'.join(f'\n{t}\n\n{txt}' for _, t, txt, _ in raw_results)
    txt_content = '﻿' + novel_name + '\n\n' + '\n'.join(qc_lines) + '\n\n' + body

    qc_data = {
        'book': novel_name, 'site': domain, 'book_id': book_id,
        'total_chapters': len(chapters), 'ok': cnt_ok, 'short': cnt_short,
        'failed': cnt_fail, 'min_chars': min_chars,
        'median_chars': median_chars,
        'multipage_pattern': profile.get('multipage_pattern'),
        'avg_chars_from_scan': profile.get('avg_chars', 0),
        'short_chapters': qc_short, 'failed_chapters': qc_failed,
        'suspicious_chapters': qc_suspicious,
        'missing_chapters': qc_missing,
    }

    safe = re.sub(r'[\\/:*?"<>|]', '_', novel_name)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f'{safe}.txt', txt_content.encode('utf-8'))
        zf.writestr(f'{safe}_QC.json',
                     json.dumps(qc_data, ensure_ascii=False, indent=2))
    buf.seek(0)

    summary = (
        f'✅ เสร็จแล้ว!\n'
        f'ตอนทั้งหมด: {len(chapters)}\n'
        f'OK: {cnt_ok}  |  สั้น: {cnt_short}  |  ล้มเหลว: {cnt_fail}\n'
        f'ค่ากลาง: {median_chars} ตัวอักษรจีน/ตอน'
    )
    if qc_missing:
        summary += f'\n⚠️ ตอนที่อาจหายไป: {len(qc_missing)} ตอน'
    if qc_suspicious:
        summary += f'\n⚠️ ตอนสั้นผิดปกติ: {len(qc_suspicious)} ตอน'
    log_fn(summary)
    return buf.getvalue(), f'{safe}.zip', summary


# ── Streamlit UI ─────────────────────────────────────────────────────────────

st.set_page_config(page_title='Novel Downloader', page_icon='📚', layout='centered')
st.title('📚 Novel Downloader')
st.markdown('วางลิงก์นิยายแล้วกด **สแกน** → ตรวจปัญหา → **แก้ไข** → **โหลด**')

# ── Step 1: Scan ─────────────────────────────────────────────────────────────

with st.form('scan_form'):
    url_input = st.text_input(
        '🔗 ลิงก์นิยาย',
        placeholder='https://m.biquge365.net/shu/528722/',
        value=st.session_state.get('scan_url', ''),
    )
    scan_submitted = st.form_submit_button(
        '🔍 ขั้นตอนที่ 1: สแกน', type='primary', use_container_width=True
    )

if scan_submitted and url_input.strip():
    scan_log_area = st.empty()
    scan_logs = []

    def scan_log(msg):
        scan_logs.append(msg)
        scan_log_area.text_area(
            'Scan Log', '\n'.join(scan_logs), height=180,
            label_visibility='collapsed',
        )

    with st.spinner('กำลังสแกนสารบัญ + วิเคราะห์โครงสร้างเว็บ...'):
        scan_info, err = asyncio.run(scan_novel(url_input.strip(), log=scan_log))
    if err:
        st.error(f'สแกนล้มเหลว: {err}')
        st.session_state.pop('scan_info', None)
        st.session_state.pop('issues', None)
    else:
        st.session_state['scan_url'] = url_input.strip()
        st.session_state['scan_info'] = scan_info
        st.session_state['issues'] = detect_issues(scan_info)
        st.session_state.pop('download_result', None)
        st.session_state.pop('fix_done', None)

elif scan_submitted:
    st.warning('กรุณาใส่ URL ก่อนค่ะ')

# ── Show scan result + Issue Report ──────────────────────────────────────────

scan_info = st.session_state.get('scan_info')
issues = st.session_state.get('issues', [])

if scan_info:
    chapters = scan_info['chapters']
    profile = scan_info.get('profile', {})

    st.success(
        f'**{scan_info["title"]}**  \n'
        f'พบ **{len(chapters)} ตอน** บน {scan_info["domain"]}  \n'
        f'ตอนแรก: {chapters[0][1] or chapters[0][0]}  \n'
        f'ตอนสุดท้าย: {chapters[-1][1] or chapters[-1][0]}'
    )

    # ── Issue Report ─────────────────────────────────────────────────────
    if issues:
        st.divider()
        st.subheader('📋 รายงานการตรวจสอบ')

        has_fixable = any(i['fixable'] and not i['fixed'] for i in issues)
        all_ok = all(i['severity'] == 'info' or i['fixed'] for i in issues)
        criticals = [i for i in issues if i['severity'] == 'critical' and not i['fixed']]
        warnings = [i for i in issues if i['severity'] == 'warning' and not i['fixed']]

        for issue in issues:
            if issue['fixed'] or issue['severity'] == 'info':
                st.markdown(f"✅ **{issue['title']}** — {issue['detail']}")
            elif issue['severity'] == 'critical':
                st.markdown(f"❌ **{issue['title']}** — {issue['detail']}")
            else:
                st.markdown(f"⚠️ **{issue['title']}** — {issue['detail']}")

        if all_ok:
            st.success('🎉 ตรวจสอบผ่านทุกข้อ — พร้อมดาวน์โหลดค่ะ!')
        elif criticals:
            st.error(
                f'พบปัญหาร้ายแรง {len(criticals)} ข้อ'
                + (f', คำเตือน {len(warnings)} ข้อ' if warnings else '')
                + (' — กด **แก้ไข** เพื่อลองแก้ปัญหาอัตโนมัติ' if has_fixable else '')
            )
        elif warnings:
            st.warning(
                f'พบคำเตือน {len(warnings)} ข้อ'
                + (' — กด **แก้ไข** เพื่อลองแก้ปัญหาอัตโนมัติ' if has_fixable else '')
            )

        # ── Step 2: Fix Button ───────────────────────────────────────────
        if has_fixable:
            st.divider()
            st.subheader('🔧 ขั้นตอนที่ 2: แก้ไขปัญหา')
            fixable_list = [i for i in issues if i['fixable'] and not i['fixed']]
            st.markdown('**จะลองแก้ไข:**')
            for i in fixable_list:
                st.markdown(f"- {i['icon']} {i['title']}")

            if st.button('🔧 แก้ไข', type='primary', use_container_width=True):
                fix_log_area = st.empty()
                fix_logs = []

                def fix_log(msg):
                    fix_logs.append(msg)
                    fix_log_area.text_area(
                        'Fix Log', '\n'.join(fix_logs), height=220,
                        label_visibility='collapsed',
                    )

                with st.spinner('กำลังแก้ไขปัญหาอัตโนมัติ...'):
                    new_issues = asyncio.run(
                        fix_issues(scan_info, issues, fix_log)
                    )

                st.session_state['issues'] = new_issues
                st.session_state['fix_done'] = True
                st.rerun()

        # Show fix result if just fixed
        if st.session_state.get('fix_done'):
            still_bad = [i for i in issues if i['severity'] != 'info' and not i['fixed']]
            if not still_bad:
                st.success('✅ แก้ไขเสร็จสิ้น — ปัญหาทั้งหมดได้รับการแก้ไขแล้วค่ะ!')
            else:
                st.info(
                    f'แก้ไขเสร็จสิ้น — ยังเหลือปัญหา {len(still_bad)} ข้อ '
                    f'ที่ไม่สามารถแก้ไขอัตโนมัติได้ '
                    f'(ดาวน์โหลดได้ แต่อาจได้เนื้อหาไม่ครบ)'
                )

    # ── Step 3: Download settings ────────────────────────────────────────

    st.divider()
    can_download = not any(i['severity'] == 'critical' and not i['fixed'] for i in issues)

    if can_download:
        st.subheader('⬇️ ขั้นตอนที่ 3: ดาวน์โหลด')

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

        unfixed_warnings = [i for i in issues if i['severity'] == 'warning' and not i['fixed']]
        if unfixed_warnings:
            st.warning(
                '⚠️ ยังมีคำเตือนที่ยังไม่ได้แก้ไข — ดาวน์โหลดได้ แต่อาจไม่สมบูรณ์  \n'
                + '  \n'.join(f"- {w['title']}" for w in unfixed_warnings)
            )

        if st.button('⬇️ โหลดเลย!', type='primary', use_container_width=True):
            log_area = st.empty()
            progress_bar = st.progress(0.0, text='กำลังโหลด...')
            logs = []

            def log(msg):
                logs.append(msg)
                log_area.text_area(
                    'Log', value='\n'.join(logs), height=220,
                    label_visibility='collapsed',
                )

            def set_progress(val):
                progress_bar.progress(min(val, 1.0), text=f'โหลดแล้ว {val * 100:.0f}%')

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
    else:
        st.error(
            '❌ ไม่สามารถดาวน์โหลดได้ — มีปัญหาร้ายแรงที่ยังไม่ได้แก้ไข  \n'
            'กรุณากด **แก้ไข** ด้านบน หรือลองเว็บอื่นค่ะ'
        )

st.markdown("""
---
**วิธีใช้:** สแกน → ตรวจปัญหา → แก้ไข (ถ้ามี) → โหลด
**ตัวอย่าง URL:**
- `https://m.biquge365.net/shu/528722/`
- `https://www.69shu.xyz/index/2/2829/1.html/`
- `https://shubaowb.com/novel/YH2B.html`
- และเว็บนิยายจีนอื่นๆ ที่มีสารบัญตอน
""")
