#!/usr/bin/env python3
"""
Novel Downloader — runs in GitHub Actions
Downloads Chinese novels from supported sites and saves as .txt
"""

import asyncio
import aiohttp
import re
import sys
import os
import json
import time
from html.parser import HTMLParser


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._skip = {'script', 'style', 'nav', 'header', 'footer', 'aside', 'iframe'}
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
    r'google|adsbygoogle|function\(i,s|var\s+_hmt|百度|本站|书签|收藏|推荐',
    re.IGNORECASE
)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
}


def clean_lines(paragraphs):
    return [p.strip() for p in paragraphs if p.strip() and len(p.strip()) > 1 and not JUNK_RE.search(p)]


def extract_text(html):
    parser = TextExtractor()
    parser.feed(html)
    lines = clean_lines(parser._paragraphs)
    if len(lines) >= 3:
        return lines
    full = ''.join(parser._all_text)
    return clean_lines(full.split('\n'))


def extract_title(html):
    m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)
    if not m:
        m = re.search(r'<h2[^>]*>(.*?)</h2>', html, re.DOTALL | re.IGNORECASE)
    if m:
        return re.sub(r'<[^>]+>', '', m.group(1)).strip()
    return None


async def download_chapter(session, url, semaphore, delay=1.5):
    async with semaphore:
        for retry in range(4):
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        lines = extract_text(html)
                        title = extract_title(html)
                        if lines:
                            return {'ok': True, 'title': title, 'text': '\n\n'.join(lines)}
                        return {'ok': False, 'error': 'empty content'}
                    elif resp.status == 403:
                        wait = 5 * (retry + 1)
                        print(f'  403 on {url}, waiting {wait}s...', flush=True)
                        await asyncio.sleep(wait)
                        continue
                    elif resp.status == 502:
                        wait = 3 * (retry + 1)
                        print(f'  502 on {url}, waiting {wait}s...', flush=True)
                        await asyncio.sleep(wait)
                        continue
                    else:
                        return {'ok': False, 'error': f'HTTP {resp.status}'}
            except asyncio.TimeoutError:
                await asyncio.sleep(3 * (retry + 1))
            except Exception as e:
                await asyncio.sleep(3 * (retry + 1))
        return {'ok': False, 'error': 'max retries'}
    await asyncio.sleep(delay)


SITE_DOMAINS = {
    'shuixxs': 'www.shuixxs.com',
    '4jiwx': 'www.4jiwx.com',
}


async def download_sequential(site, book_id, total_chapters, output_file, novel_name, workers=8, delay=1.5):
    domain = SITE_DOMAINS.get(site, site)
    print(f'=== Downloading from {domain} ===')
    print(f'Book: {book_id}, Chapters: {total_chapters}, Workers: {workers}')

    semaphore = asyncio.Semaphore(workers)
    connector = aiohttp.TCPConnector(limit=workers + 2, force_close=False)

    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        try:
            async with session.get(f'https://{domain}/book/{book_id}.html',
                                   timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    print(f'Site returned {resp.status} — may be blocked')
                else:
                    print('Site accessible!')
        except Exception as e:
            print(f'Cannot reach site: {e}')
            return False

        tasks = []
        for n in range(1, total_chapters + 1):
            url = f'https://{domain}/book/{book_id}-{n}.html'
            tasks.append(download_chapter(session, url, semaphore, delay))

        results = []
        ok = 0
        fail = 0
        batch_size = 20

        for batch_start in range(0, len(tasks), batch_size):
            batch = tasks[batch_start:batch_start + batch_size]
            batch_results = await asyncio.gather(*batch)

            for i, r in enumerate(batch_results):
                ch_num = batch_start + i + 1
                if r['ok']:
                    title = r['title'] or f'第{ch_num}章'
                    results.append(f'\n{title}\n\n{r["text"]}')
                    ok += 1
                else:
                    results.append(f'\n第{ch_num}章\n\n[下载失败: {r["error"]}]')
                    fail += 1

            done = batch_start + len(batch)
            print(f'Progress: {done}/{total_chapters} (OK: {ok}, Failed: {fail})', flush=True)
            await asyncio.sleep(0.5)

    text = '﻿' + novel_name + '\n\n' + '\n'.join(results)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(text)

    print(f'\n=== Done! OK: {ok}, Failed: {fail} ===')
    print(f'Saved to: {output_file}')
    return ok > 0


async def download_zhys(book_id, output_file, novel_name, workers=8, delay=1.5):
    print(f'=== Downloading from cn.zhys.tw ===')
    print(f'Book: {book_id}, Workers: {workers}')

    connector = aiohttp.TCPConnector(limit=workers + 2, force_close=False)

    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        print('Fetching table of contents...', flush=True)
        toc_url = f'https://cn.zhys.tw/book/{book_id}.html'
        try:
            async with session.get(toc_url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    print(f'TOC returned {resp.status}')
                    return False
                html = await resp.text()
        except Exception as e:
            print(f'Cannot fetch TOC: {e}')
            return False

        pattern = re.compile(rf'/read/{book_id}/(\d+)\.html')
        chapters = []
        seen = set()
        for m in pattern.finditer(html):
            ch_id = m.group(1)
            if ch_id not in seen:
                seen.add(ch_id)
                chapters.append(ch_id)

        link_pattern = re.compile(
            rf'<a[^>]*href="[^"]*?/read/{book_id}/(\d+)\.html"[^>]*>(.*?)</a>',
            re.DOTALL
        )
        ch_titles = {}
        for m in link_pattern.finditer(html):
            ch_id = m.group(1)
            title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if title and ch_id not in ch_titles:
                ch_titles[ch_id] = title

        print(f'Found {len(chapters)} chapters in TOC')

        if len(chapters) < 10:
            print('Too few chapters found — site may need JS rendering')
            return False

        def sort_key(ch_id):
            title = ch_titles.get(ch_id, '')
            m = re.search(r'第(\d+)章', title)
            return int(m.group(1)) if m else 0
        chapters.sort(key=sort_key)

        semaphore = asyncio.Semaphore(workers)
        results = []
        ok = 0
        fail = 0

        async def dl(ch_id, idx):
            url = f'https://cn.zhys.tw/read/{book_id}/{ch_id}.html'
            r = await download_chapter(session, url, semaphore, delay)
            return idx, ch_id, r

        batch_size = 20
        for batch_start in range(0, len(chapters), batch_size):
            batch_ids = chapters[batch_start:batch_start + batch_size]
            batch_tasks = [dl(ch_id, batch_start + i) for i, ch_id in enumerate(batch_ids)]
            batch_results = await asyncio.gather(*batch_tasks)

            for idx, ch_id, r in sorted(batch_results, key=lambda x: x[0]):
                title = ch_titles.get(ch_id, f'Chapter {idx + 1}')
                if r['ok']:
                    t = r['title'] or title
                    results.append((idx, f'\n{t}\n\n{r["text"]}'))
                    ok += 1
                else:
                    results.append((idx, f'\n{title}\n\n[下载失败: {r["error"]}]'))
                    fail += 1

            done = batch_start + len(batch_ids)
            print(f'Progress: {done}/{len(chapters)} (OK: {ok}, Failed: {fail})', flush=True)
            await asyncio.sleep(0.5)

    results.sort(key=lambda x: x[0])
    text = '﻿' + novel_name + '\n\n' + '\n'.join(r[1] for r in results)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(text)

    print(f'\n=== Done! OK: {ok}, Failed: {fail} ===')
    print(f'Saved to: {output_file}')
    return ok > 0


async def download_shubaowb(book_id, output_file, novel_name, workers=8, delay=1.5):
    """Download from shubaowb.com — catalog page at /novel/{book_id}.html (multi-page TOC)"""
    domain = 'shubaowb.com'
    print(f'=== Downloading from {domain} ===')
    print(f'Book ID: {book_id}, Workers: {workers}')

    connector = aiohttp.TCPConnector(limit=workers + 2, force_close=False)

    def extract_chapters_from_html(html, seen):
        """Extract chapter (url, title) pairs from one TOC page, skipping duplicates."""
        link_pattern = re.compile(
            rf'<a[^>]*href="([^"]*?/read/{book_id}/[^"]+)"[^>]*>(.*?)</a>',
            re.DOTALL
        )
        found = []
        for m in link_pattern.finditer(html):
            href = m.group(1)
            if not href.startswith('http'):
                href = f'https://{domain}{href}'
            title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if href not in seen:
                seen.add(href)
                found.append((href, title))
        return found

    def find_next_toc_page(html, current_page):
        """Return the URL of the next TOC page, or None if this is the last."""
        # Pattern: /novel/{book_id}_{page}.html  or  /novel/{book_id}/{page}.html
        next_page = current_page + 1
        patterns = [
            rf'href="(/novel/{book_id}_{next_page}\.html)"',
            rf'href="(/novel/{book_id}/{next_page}\.html)"',
            rf'href="(/novel/{book_id}\.html\?page={next_page})"',
            rf'href="([^"]*[?&]page={next_page}[^"]*)"',
        ]
        for pat in patterns:
            m = re.search(pat, html)
            if m:
                href = m.group(1)
                if not href.startswith('http'):
                    href = f'https://{domain}{href}'
                return href
        # Generic "next page" anchor containing next page number
        m = re.search(rf'<a[^>]*href="([^"]+)"[^>]*>\s*(?:下一页|next|{next_page})\s*</a>', html, re.IGNORECASE)
        if m:
            href = m.group(1)
            if not href.startswith('http'):
                href = f'https://{domain}{href}'
            return href
        return None

    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        chapters = []
        seen = set()
        page_num = 1
        toc_url = f'https://{domain}/novel/{book_id}.html'

        while toc_url:
            print(f'Fetching TOC page {page_num}: {toc_url}', flush=True)
            try:
                async with session.get(toc_url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status != 200:
                        print(f'TOC page {page_num} returned {resp.status}')
                        break
                    html = await resp.text()
            except Exception as e:
                print(f'Cannot fetch TOC page {page_num}: {e}')
                break

            new_chapters = extract_chapters_from_html(html, seen)
            chapters.extend(new_chapters)
            print(f'  → {len(new_chapters)} new chapters (total: {len(chapters)})', flush=True)

            if not new_chapters:
                break  # no new chapters found on this page — stop paginating

            next_url = find_next_toc_page(html, page_num)
            toc_url = next_url
            page_num += 1
            if next_url:
                await asyncio.sleep(0.5)

        if not chapters:
            # Fallback: look for any internal chapter-like links on page 1
            toc_url = f'https://{domain}/novel/{book_id}.html'
            try:
                async with session.get(toc_url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    html = await resp.text() if resp.status == 200 else ''
            except Exception:
                html = ''
            fallback = re.compile(r'href="(/[^"]*(?:chapter|read|chap)[^"]*)"')
            for m in fallback.finditer(html):
                href = f'https://{domain}{m.group(1)}'
                if href not in seen:
                    seen.add(href)
                    chapters.append((href, ''))

        print(f'Total chapters found across all TOC pages: {len(chapters)}')

        if len(chapters) < 1:
            print('No chapters found — check the book ID or site structure')
            return False

        semaphore = asyncio.Semaphore(workers)
        results = []
        ok = 0
        fail = 0

        async def dl(idx, url, title):
            r = await download_chapter(session, url, semaphore, delay)
            return idx, title, r

        batch_size = 20
        for batch_start in range(0, len(chapters), batch_size):
            batch = chapters[batch_start:batch_start + batch_size]
            batch_tasks = [dl(batch_start + i, url, title) for i, (url, title) in enumerate(batch)]
            batch_results = await asyncio.gather(*batch_tasks)

            for idx, toc_title, r in sorted(batch_results, key=lambda x: x[0]):
                if r['ok']:
                    t = r['title'] or toc_title or f'第{idx + 1}章'
                    results.append((idx, f'\n{t}\n\n{r["text"]}'))
                    ok += 1
                else:
                    label = toc_title or f'Chapter {idx + 1}'
                    results.append((idx, f'\n{label}\n\n[下载失败: {r["error"]}]'))
                    fail += 1

            done = batch_start + len(batch)
            print(f'Progress: {done}/{len(chapters)} (OK: {ok}, Failed: {fail})', flush=True)
            await asyncio.sleep(0.5)

    results.sort(key=lambda x: x[0])
    text = '﻿' + novel_name + '\n\n' + '\n'.join(r[1] for r in results)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(text)

    print(f'\n=== Done! OK: {ok}, Failed: {fail} ===')
    print(f'Saved to: {output_file}')
    return ok > 0


async def download_69shu(book_path, output_file, novel_name, workers=8, delay=1.5, min_chars=300):
    """
    Download from www.69shu.xyz
    book_path: path segment after /index/, e.g. "2/2829"
    Catalog: https://www.69shu.xyz/index/{book_path}/{page}.html/
    """
    domain = 'www.69shu.xyz'
    book_num = book_path.split('/')[-1]
    print(f'=== Downloading from {domain} ===')
    print(f'Book path: /index/{book_path}/ | Book num: {book_num} | min_chars: {min_chars}')

    connector = aiohttp.TCPConnector(limit=workers + 2, force_close=False)

    def extract_chapters(html, seen):
        pattern = re.compile(
            rf'<a[^>]*href="(/{book_num}/[^"]+\.html[^"]*)"[^>]*>(.*?)</a>',
            re.DOTALL
        )
        found = []
        for m in pattern.finditer(html):
            href = m.group(1).rstrip('/')
            url = f'https://{domain}{href}'
            title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if url not in seen and title and len(title) <= 80:
                seen.add(url)
                found.append((url, title))
        return found

    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        chapters = []
        seen = set()
        page = 1

        while True:
            toc_url = f'https://{domain}/index/{book_path}/{page}.html/'
            print(f'Fetching TOC page {page}: {toc_url}', flush=True)
            try:
                async with session.get(toc_url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status != 200:
                        print(f'TOC page {page} returned {resp.status} — stop')
                        break
                    html = await resp.text()
            except Exception as e:
                print(f'Cannot fetch TOC page {page}: {e}')
                break

            new_ch = extract_chapters(html, seen)
            if not new_ch:
                print(f'No new chapters on page {page} — TOC scan complete')
                break
            chapters.extend(new_ch)
            print(f'  → {len(new_ch)} chapters (total: {len(chapters)})', flush=True)

            # check if next page link exists in HTML
            has_next = re.search(
                rf'href="[^"]*/{re.escape(book_path)}/{page + 1}\.html/?[^"]*"', html
            )
            if not has_next:
                break
            page += 1
            await asyncio.sleep(0.5)

        if not chapters:
            print('No chapters found — check book_path or site structure')
            return False

        print(f'Total: {len(chapters)} chapters — downloading...')

        semaphore = asyncio.Semaphore(workers)
        raw_results = []
        cnt_ok = cnt_short = cnt_fail = 0
        qc_short = []
        qc_failed = []

        async def dl(idx, url, toc_title):
            r = await download_chapter(session, url, semaphore, delay)
            return idx, toc_title, r

        batch_size = 20
        for bs in range(0, len(chapters), batch_size):
            batch = chapters[bs:bs + batch_size]
            batch_res = await asyncio.gather(*[dl(bs + i, url, t) for i, (url, t) in enumerate(batch)])

            for idx, toc_title, r in sorted(batch_res, key=lambda x: x[0]):
                ch_url = chapters[idx][0]
                if r['ok']:
                    title = r['title'] or toc_title or f'第{idx + 1}章'
                    text = r['text']
                    is_short = len(text) < min_chars
                    raw_results.append((idx, title, text, is_short))
                    if is_short:
                        cnt_short += 1
                        qc_short.append({'no': idx + 1, 'title': title, 'chars': len(text), 'url': ch_url})
                    else:
                        cnt_ok += 1
                else:
                    cnt_fail += 1
                    label = toc_title or f'第{idx + 1}章'
                    raw_results.append((idx, label, f'[下载失败: {r["error"]}]', False))
                    qc_failed.append({'no': idx + 1, 'title': label, 'error': r['error'], 'url': ch_url})

            done = bs + len(batch)
            print(f'Progress: {done}/{len(chapters)} — OK:{cnt_ok} Short:{cnt_short} Failed:{cnt_fail}', flush=True)
            await asyncio.sleep(0.5)

    raw_results.sort(key=lambda x: x[0])

    # QC header embedded in TXT
    sep = '=' * 50
    qc_header_lines = [
        sep,
        f'QC REPORT — {novel_name}',
        f'Site: {domain}  |  Book path: /index/{book_path}/',
        f'Chapters: {len(chapters)}  |  OK: {cnt_ok}  |  Short(<{min_chars}): {cnt_short}  |  Failed: {cnt_fail}',
    ]
    if qc_short:
        qc_header_lines.append('Short chapters:')
        for s in qc_short:
            qc_header_lines.append(f'  #{s["no"]} {s["title"]} ({s["chars"]} chars)')
    if qc_failed:
        qc_header_lines.append('Failed chapters:')
        for f in qc_failed:
            qc_header_lines.append(f'  #{f["no"]} {f["title"]} — {f["error"]}')
    qc_header_lines.append(sep)

    body = '\n'.join(f'\n{t}\n\n{text}' for _, t, text, _ in raw_results)
    full_text = '﻿' + novel_name + '\n\n' + '\n'.join(qc_header_lines) + '\n\n' + body

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(full_text)

    # QC JSON report
    qc_data = {
        'tool': 'Fanqie Novel Downloader',
        'book': novel_name,
        'site': domain,
        'book_path': book_path,
        'total_chapters': len(chapters),
        'ok': cnt_ok,
        'short': cnt_short,
        'failed': cnt_fail,
        'min_chars': min_chars,
        'short_chapters': qc_short,
        'failed_chapters': qc_failed,
    }
    qc_file = output_file.replace('.txt', '_QC.json')
    with open(qc_file, 'w', encoding='utf-8') as f:
        json.dump(qc_data, f, ensure_ascii=False, indent=2)

    print(f'\n=== Done! OK:{cnt_ok}  Short:{cnt_short}  Failed:{cnt_fail} ===')
    print(f'TXT : {output_file}')
    print(f'QC  : {qc_file}')
    return (cnt_ok + cnt_short) > 0


async def download_biquge365(book_id, output_file, novel_name, workers=8, delay=1.5, min_chars=300):
    """
    Download from m.biquge365.net
    book_id: numeric id, e.g. "528722"
    TOC: https://m.biquge365.net/shu/{book_id}/
    """
    domain = 'm.biquge365.net'
    print(f'=== Downloading from {domain} ===')
    print(f'Book ID: {book_id}, Workers: {workers}')

    connector = aiohttp.TCPConnector(limit=workers + 2, force_close=False)

    def extract_chapters(html, seen):
        pattern = re.compile(
            rf'<a[^>]*href="(/shu/{book_id}/(\d+)\.html)"[^>]*>(.*?)</a>',
            re.DOTALL
        )
        found = []
        for m in pattern.finditer(html):
            href = m.group(1)
            url = f'https://{domain}{href}'
            title = re.sub(r'<[^>]+>', '', m.group(3)).strip()
            if url not in seen and title:
                seen.add(url)
                found.append((url, title))
        return found

    def find_next_toc_url(html, base_url, page_num):
        # Try ?p=N pattern
        m = re.search(rf'href="([^"]*\?p={page_num + 1}[^"]*)"', html)
        if m:
            href = m.group(1)
            return href if href.startswith('http') else f'https://{domain}{href}'
        # Try 下一页 anchor
        m = re.search(r'<a[^>]*href="([^"]+)"[^>]*>\s*(?:下一页|下一頁)\s*</a>', html, re.IGNORECASE)
        if m:
            href = m.group(1)
            return href if href.startswith('http') else f'https://{domain}{href}'
        # Try _{page}.html or /{page}.html in TOC url
        next_p = page_num + 1
        for pat in [rf'href="(/shu/{book_id}/index_{next_p}\.html)"',
                    rf'href="(/shu/{book_id}/{next_p}\.html)"']:
            m = re.search(pat, html)
            if m:
                return f'https://{domain}{m.group(1)}'
        return None

    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        chapters = []
        seen = set()
        toc_url = f'https://{domain}/shu/{book_id}/'
        page_num = 1

        while toc_url:
            print(f'Fetching TOC page {page_num}: {toc_url}', flush=True)
            try:
                async with session.get(toc_url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status != 200:
                        print(f'TOC page {page_num} returned {resp.status} — stop')
                        break
                    html = await resp.text()
            except Exception as e:
                print(f'Cannot fetch TOC page {page_num}: {e}')
                break

            new_ch = extract_chapters(html, seen)
            chapters.extend(new_ch)
            print(f'  → {len(new_ch)} chapters (total: {len(chapters)})', flush=True)

            if not new_ch:
                break

            next_url = find_next_toc_url(html, toc_url, page_num)
            toc_url = next_url
            page_num += 1
            if next_url:
                await asyncio.sleep(0.5)

        if not chapters:
            print('No chapters found — check book_id or site structure')
            return False

        print(f'Total: {len(chapters)} chapters — downloading...')

        semaphore = asyncio.Semaphore(workers)
        raw_results = []
        cnt_ok = cnt_short = cnt_fail = 0
        qc_short = []
        qc_failed = []

        async def dl(idx, url, toc_title):
            r = await download_chapter(session, url, semaphore, delay)
            return idx, toc_title, r

        batch_size = 20
        for bs in range(0, len(chapters), batch_size):
            batch = chapters[bs:bs + batch_size]
            batch_res = await asyncio.gather(*[dl(bs + i, url, t) for i, (url, t) in enumerate(batch)])

            for idx, toc_title, r in sorted(batch_res, key=lambda x: x[0]):
                ch_url = chapters[idx][0]
                if r['ok']:
                    title = r['title'] or toc_title or f'第{idx + 1}章'
                    text = r['text']
                    is_short = len(text) < min_chars
                    raw_results.append((idx, title, text, is_short))
                    if is_short:
                        cnt_short += 1
                        qc_short.append({'no': idx + 1, 'title': title, 'chars': len(text), 'url': ch_url})
                    else:
                        cnt_ok += 1
                else:
                    cnt_fail += 1
                    label = toc_title or f'第{idx + 1}章'
                    raw_results.append((idx, label, f'[下载失败: {r["error"]}]', False))
                    qc_failed.append({'no': idx + 1, 'title': label, 'error': r['error'], 'url': ch_url})

            done = bs + len(batch)
            print(f'Progress: {done}/{len(chapters)} — OK:{cnt_ok} Short:{cnt_short} Failed:{cnt_fail}', flush=True)
            await asyncio.sleep(0.5)

    raw_results.sort(key=lambda x: x[0])

    sep = '=' * 50
    qc_header_lines = [
        sep,
        f'QC REPORT — {novel_name}',
        f'Site: {domain}  |  Book ID: {book_id}',
        f'Chapters: {len(chapters)}  |  OK: {cnt_ok}  |  Short(<{min_chars}): {cnt_short}  |  Failed: {cnt_fail}',
    ]
    if qc_short:
        qc_header_lines.append('Short chapters:')
        for s in qc_short:
            qc_header_lines.append(f'  #{s["no"]} {s["title"]} ({s["chars"]} chars)')
    if qc_failed:
        qc_header_lines.append('Failed chapters:')
        for f in qc_failed:
            qc_header_lines.append(f'  #{f["no"]} {f["title"]} — {f["error"]}')
    qc_header_lines.append(sep)

    body = '\n'.join(f'\n{t}\n\n{text}' for _, t, text, _ in raw_results)
    full_text = '﻿' + novel_name + '\n\n' + '\n'.join(qc_header_lines) + '\n\n' + body

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(full_text)

    qc_data = {
        'tool': 'Fanqie Novel Downloader',
        'book': novel_name,
        'site': domain,
        'book_id': book_id,
        'total_chapters': len(chapters),
        'ok': cnt_ok,
        'short': cnt_short,
        'failed': cnt_fail,
        'min_chars': min_chars,
        'short_chapters': qc_short,
        'failed_chapters': qc_failed,
    }
    qc_file = output_file.replace('.txt', '_QC.json')
    with open(qc_file, 'w', encoding='utf-8') as f:
        json.dump(qc_data, f, ensure_ascii=False, indent=2)

    print(f'\n=== Done! OK:{cnt_ok}  Short:{cnt_short}  Failed:{cnt_fail} ===')
    print(f'TXT : {output_file}')
    print(f'QC  : {qc_file}')
    return (cnt_ok + cnt_short) > 0


def parse_novel_url(url):
    """Auto-detect site and book_id from a novel URL. Returns (site, book_id) or raises."""
    url = url.strip().rstrip('/')

    # biquge365: https://m.biquge365.net/shu/528722/
    m = re.search(r'biquge365\.[^/]+/shu/(\d+)', url)
    if m:
        return 'biquge365', m.group(1)

    # 69shu: https://www.69shu.xyz/index/2/2829/1.html
    m = re.search(r'69shu\.[^/]+/index/(\d+/\d+)', url)
    if m:
        return '69shu', m.group(1)

    # shubaowb: https://shubaowb.com/novel/YH2B.html
    m = re.search(r'shubaowb\.[^/]+/novel/([^/.\s]+)', url)
    if m:
        return 'shubaowb', m.group(1)

    # zhys: https://cn.zhys.tw/book/12345.html
    m = re.search(r'zhys\.[^/]+/book/([^/.\s]+)', url)
    if m:
        return 'zhys', m.group(1)

    # 4jiwx: https://www.4jiwx.com/book/ABCD.html
    m = re.search(r'4jiwx\.[^/]+/book/([^/.\s]+)', url)
    if m:
        return '4jiwx', m.group(1)

    # shuixxs: https://www.shuixxs.com/book/ABCD.html
    m = re.search(r'shuixxs\.[^/]+/book/([^/.\s]+)', url)
    if m:
        return 'shuixxs', m.group(1)

    raise ValueError(
        f'ไม่รู้จัก URL นี้: {url}\n'
        'รองรับ: biquge365 / 69shu / shubaowb / zhys / 4jiwx / shuixxs'
    )


async def main():
    output_dir = os.environ.get('OUTPUT_DIR', '.')
    workers = int(os.environ.get('WORKERS', '3'))
    delay = float(os.environ.get('DELAY', '2'))
    min_chars = int(os.environ.get('MIN_CHARS', '300'))

    novel_url = os.environ.get('NOVEL_URL', '').strip()
    novel_name = os.environ.get('NOVEL_NAME', '').strip()

    # Legacy mode: SITE + BOOK_ID still work if NOVEL_URL is empty
    site = os.environ.get('SITE', '').strip()
    book_id = os.environ.get('BOOK_ID', '').strip()

    if novel_url:
        try:
            site, book_id = parse_novel_url(novel_url)
            print(f'URL parsed: site={site}  book_id={book_id}')
        except ValueError as e:
            print(e)
            sys.exit(1)
    elif not site or not book_id:
        print('ต้องใส่ NOVEL_URL หรือ SITE+BOOK_ID')
        sys.exit(1)

    if not novel_name:
        novel_name = f'{site}_{book_id.replace("/", "_")}'

    safe_name = re.sub(r'[\\/:*?"<>|]', '_', novel_name)
    output_file = os.path.join(output_dir, f'{safe_name}.txt')

    if site in ('shuixxs', '4jiwx'):
        total = int(os.environ.get('TOTAL_CHAPTERS', '503'))
        success = await download_sequential(site, book_id, total, output_file, novel_name, workers, delay)
    elif site == 'zhys':
        success = await download_zhys(book_id, output_file, novel_name, workers, delay)
    elif site == 'shubaowb':
        success = await download_shubaowb(book_id, output_file, novel_name, workers, delay)
    elif site == '69shu':
        success = await download_69shu(book_id, output_file, novel_name, workers, delay, min_chars)
    elif site == 'biquge365':
        success = await download_biquge365(book_id, output_file, novel_name, workers, delay, min_chars)
    else:
        print(f'ไม่รู้จัก site: {site}')
        sys.exit(1)

    if not success:
        print('Download failed!')
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
