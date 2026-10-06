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


async def download_shuixxs(book_id, total_chapters, output_file, novel_name, workers=8, delay=1.5):
    print(f'=== Downloading from shuixxs.com ===')
    print(f'Book: {book_id}, Chapters: {total_chapters}, Workers: {workers}')

    semaphore = asyncio.Semaphore(workers)
    connector = aiohttp.TCPConnector(limit=workers + 2, force_close=False)

    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        try:
            async with session.get(f'https://www.shuixxs.com/book/{book_id}.html',
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
            url = f'https://www.shuixxs.com/book/{book_id}-{n}.html'
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


async def main():
    novel_name = os.environ.get('NOVEL_NAME', '萌宝驾到豪门全家宠上天')
    site = os.environ.get('SITE', 'shuixxs')
    output_dir = os.environ.get('OUTPUT_DIR', '.')
    safe_name = re.sub(r'[\\/:*?"<>|]', '_', novel_name)
    output_file = os.path.join(output_dir, f'{safe_name}.txt')

    if site == 'shuixxs':
        book_id = os.environ.get('BOOK_ID', 'YA9K')
        total = int(os.environ.get('TOTAL_CHAPTERS', '503'))
        workers = int(os.environ.get('WORKERS', '8'))
        delay = float(os.environ.get('DELAY', '1.5'))
        success = await download_shuixxs(book_id, total, output_file, novel_name, workers, delay)
    elif site == 'zhys':
        book_id = os.environ.get('BOOK_ID', '7945508')
        workers = int(os.environ.get('WORKERS', '8'))
        delay = float(os.environ.get('DELAY', '1.5'))
        success = await download_zhys(book_id, output_file, novel_name, workers, delay)
    else:
        print(f'Unknown site: {site}')
        sys.exit(1)

    if not success:
        print('Download failed from primary site, trying fallback...')
        if site == 'shuixxs':
            success = await download_zhys('7945508', output_file, novel_name)
        else:
            success = await download_shuixxs('YA9K', 503, output_file, novel_name)

    if not success:
        print('Both sites failed!')
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
