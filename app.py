#!/usr/bin/env python3
"""Novel Downloader — Gradio web app for Hugging Face Spaces"""

import asyncio
import aiohttp
import re
import os
import json
import tempfile
import gradio as gr
from html.parser import HTMLParser


# ── HTML parsing ──────────────────────────────────────────────────────────────

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
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
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
                        return {'ok': False, 'error': 'empty'}
                    elif resp.status in (403, 502):
                        await asyncio.sleep(5 * (retry + 1))
                    else:
                        return {'ok': False, 'error': f'HTTP {resp.status}'}
            except asyncio.TimeoutError:
                await asyncio.sleep(3 * (retry + 1))
            except Exception as e:
                await asyncio.sleep(3 * (retry + 1))
        return {'ok': False, 'error': 'max retries'}
    await asyncio.sleep(delay)


# ── Site-specific downloaders ─────────────────────────────────────────────────

async def download_biquge365(book_id, novel_name, workers, delay, min_chars, log):
    domain = 'm.biquge365.net'
    log(f'🔍 ดึงสารบัญ {domain}/shu/{book_id}/ ...')

    def extract_chapters(html, seen):
        pattern = re.compile(
            rf'<a[^>]*href="(/shu/{book_id}/(\d+)\.html)"[^>]*>(.*?)</a>', re.DOTALL)
        found = []
        for m in pattern.finditer(html):
            url = f'https://{domain}{m.group(1)}'
            title = re.sub(r'<[^>]+>', '', m.group(3)).strip()
            if url not in seen and title:
                seen.add(url)
                found.append((url, title))
        return found

    def find_next(html, page_num):
        for pat in [
            rf'href="([^"]*\?p={page_num+1}[^"]*)"',
            r'<a[^>]*href="([^"]+)"[^>]*>\s*(?:下一页|下一頁)\s*</a>',
            rf'href="(/shu/{book_id}/index_{page_num+1}\.html)"',
        ]:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                h = m.group(1)
                return h if h.startswith('http') else f'https://{domain}{h}'
        return None

    connector = aiohttp.TCPConnector(limit=workers + 2)
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        chapters, seen, toc_url, page_num = [], set(), f'https://{domain}/shu/{book_id}/', 1
        while toc_url:
            try:
                async with session.get(toc_url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                    if r.status != 200:
                        break
                    html = await r.text()
            except Exception as e:
                log(f'❌ ดึงสารบัญหน้า {page_num} ล้มเหลว: {e}')
                break
            new_ch = extract_chapters(html, seen)
            chapters.extend(new_ch)
            log(f'  หน้าสารบัญ {page_num}: พบ {len(new_ch)} ตอน (รวม {len(chapters)})')
            if not new_ch:
                break
            toc_url = find_next(html, page_num)
            page_num += 1
            if toc_url:
                await asyncio.sleep(0.5)
        return await _download_chapters(session, chapters, novel_name, workers, delay, min_chars, log, domain, book_id)


async def download_69shu(book_path, novel_name, workers, delay, min_chars, log):
    domain = 'www.69shu.xyz'
    book_num = book_path.split('/')[-1]
    log(f'🔍 ดึงสารบัญ {domain}/index/{book_path}/ ...')

    def extract_chapters(html, seen):
        pattern = re.compile(
            rf'<a[^>]*href="(/{book_num}/[^"]+\.html[^"]*)"[^>]*>(.*?)</a>', re.DOTALL)
        found = []
        for m in pattern.finditer(html):
            href = m.group(1).rstrip('/')
            url = f'https://{domain}{href}'
            title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if url not in seen and title and len(title) <= 80:
                seen.add(url)
                found.append((url, title))
        return found

    connector = aiohttp.TCPConnector(limit=workers + 2)
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        chapters, seen, page = [], set(), 1
        while True:
            toc_url = f'https://{domain}/index/{book_path}/{page}.html/'
            try:
                async with session.get(toc_url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                    if r.status != 200:
                        break
                    html = await r.text()
            except Exception as e:
                log(f'❌ หน้า {page} ล้มเหลว: {e}')
                break
            new_ch = extract_chapters(html, seen)
            if not new_ch:
                break
            chapters.extend(new_ch)
            log(f'  หน้าสารบัญ {page}: พบ {len(new_ch)} ตอน (รวม {len(chapters)})')
            if not re.search(rf'href="[^"]*/{re.escape(book_path)}/{page+1}\.html/?[^"]*"', html):
                break
            page += 1
            await asyncio.sleep(0.5)
        return await _download_chapters(session, chapters, novel_name, workers, delay, min_chars, log, domain, book_path)


async def download_shubaowb(book_id, novel_name, workers, delay, min_chars, log):
    domain = 'shubaowb.com'
    log(f'🔍 ดึงสารบัญ {domain}/novel/{book_id}.html ...')

    def extract_chapters(html, seen):
        pattern = re.compile(
            rf'<a[^>]*href="([^"]*?/read/{book_id}/[^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
        found = []
        for m in pattern.finditer(html):
            href = m.group(1)
            if not href.startswith('http'):
                href = f'https://{domain}{href}'
            title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if href not in seen:
                seen.add(href)
                found.append((href, title))
        return found

    def find_next(html, page_num):
        for pat in [
            rf'href="(/novel/{book_id}_{page_num+1}\.html)"',
            rf'href="(/novel/{book_id}/{page_num+1}\.html)"',
            r'<a[^>]*href="([^"]+)"[^>]*>\s*(?:下一页|next)\s*</a>',
        ]:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                h = m.group(1)
                return h if h.startswith('http') else f'https://{domain}{h}'
        return None

    connector = aiohttp.TCPConnector(limit=workers + 2)
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        chapters, seen, toc_url, page_num = [], set(), f'https://{domain}/novel/{book_id}.html', 1
        while toc_url:
            try:
                async with session.get(toc_url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                    if r.status != 200:
                        break
                    html = await r.text()
            except Exception as e:
                log(f'❌ หน้า {page_num} ล้มเหลว: {e}')
                break
            new_ch = extract_chapters(html, seen)
            chapters.extend(new_ch)
            log(f'  หน้าสารบัญ {page_num}: พบ {len(new_ch)} ตอน (รวม {len(chapters)})')
            if not new_ch:
                break
            toc_url = find_next(html, page_num)
            page_num += 1
            if toc_url:
                await asyncio.sleep(0.5)
        return await _download_chapters(session, chapters, novel_name, workers, delay, min_chars, log, domain, book_id)


async def download_zhys(book_id, novel_name, workers, delay, min_chars, log):
    domain = 'cn.zhys.tw'
    log(f'🔍 ดึงสารบัญ {domain}/book/{book_id}.html ...')
    connector = aiohttp.TCPConnector(limit=workers + 2)
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        try:
            async with session.get(f'https://{domain}/book/{book_id}.html',
                                   timeout=aiohttp.ClientTimeout(total=20)) as r:
                html = await r.text() if r.status == 200 else ''
        except Exception as e:
            log(f'❌ ดึงสารบัญล้มเหลว: {e}')
            return None, None, f'ดึงสารบัญล้มเหลว: {e}'
        pattern = re.compile(rf'/read/{book_id}/(\d+)\.html')
        chapters_raw, seen = [], set()
        link_re = re.compile(rf'<a[^>]*href="[^"]*?/read/{book_id}/(\d+)\.html"[^>]*>(.*?)</a>', re.DOTALL)
        ch_titles = {}
        for m in link_re.finditer(html):
            cid = m.group(1)
            title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if cid not in seen:
                seen.add(cid)
                chapters_raw.append(cid)
                if title:
                    ch_titles[cid] = title
        log(f'  พบ {len(chapters_raw)} ตอน')
        chapters = [(f'https://{domain}/read/{book_id}/{cid}.html', ch_titles.get(cid, f'Chapter')) for cid in chapters_raw]
        return await _download_chapters(session, chapters, novel_name, workers, delay, min_chars, log, domain, book_id)


# ── Core download engine ──────────────────────────────────────────────────────

async def _download_chapters(session, chapters, novel_name, workers, delay, min_chars, log, domain, book_id):
    if not chapters:
        return None, None, 'ไม่พบตอนในสารบัญ — ลอง URL อื่น'
    log(f'📚 พบ {len(chapters)} ตอน — เริ่มโหลด...')

    semaphore = asyncio.Semaphore(workers)
    raw_results = []
    cnt_ok = cnt_short = cnt_fail = 0
    qc_short, qc_failed = [], []

    async def dl(idx, url, toc_title):
        r = await download_chapter(session, url, semaphore, delay)
        return idx, toc_title, r

    batch_size = 20
    for bs in range(0, len(chapters), batch_size):
        batch = chapters[bs:bs + batch_size]
        batch_res = await asyncio.gather(*[dl(bs + i, u, t) for i, (u, t) in enumerate(batch)])
        for idx, toc_title, r in sorted(batch_res, key=lambda x: x[0]):
            ch_url = chapters[idx][0]
            if r['ok']:
                title = r['title'] or toc_title or f'第{idx+1}章'
                text = r['text']
                is_short = len(text) < min_chars
                raw_results.append((idx, title, text, is_short))
                if is_short:
                    cnt_short += 1
                    qc_short.append({'no': idx+1, 'title': title, 'chars': len(text), 'url': ch_url})
                else:
                    cnt_ok += 1
            else:
                cnt_fail += 1
                label = toc_title or f'第{idx+1}章'
                raw_results.append((idx, label, f'[โหลดล้มเหลว: {r["error"]}]', False))
                qc_failed.append({'no': idx+1, 'title': label, 'error': r['error'], 'url': ch_url})
        done = bs + len(batch)
        log(f'  ดาวน์โหลด {done}/{len(chapters)} — OK:{cnt_ok} สั้น:{cnt_short} ล้มเหลว:{cnt_fail}')
        await asyncio.sleep(0.3)

    raw_results.sort(key=lambda x: x[0])
    sep = '=' * 50
    qc_lines = [
        sep, f'QC REPORT — {novel_name}',
        f'Site: {domain}  |  Book: {book_id}',
        f'ตอนทั้งหมด: {len(chapters)}  OK: {cnt_ok}  สั้น(<{min_chars}): {cnt_short}  ล้มเหลว: {cnt_fail}',
    ]
    if qc_short:
        qc_lines.append('ตอนสั้น:')
        for s in qc_short[:20]:
            qc_lines.append(f'  #{s["no"]} {s["title"]} ({s["chars"]} ตัวอักษร)')
    if qc_failed:
        qc_lines.append('ตอนล้มเหลว:')
        for f in qc_failed[:20]:
            qc_lines.append(f'  #{f["no"]} {f["title"]} — {f["error"]}')
    qc_lines.append(sep)

    body = '\n'.join(f'\n{t}\n\n{txt}' for _, t, txt, _ in raw_results)
    full_text = '﻿' + novel_name + '\n\n' + '\n'.join(qc_lines) + '\n\n' + body

    tmpdir = tempfile.mkdtemp()
    safe = re.sub(r'[\\/:*?"<>|]', '_', novel_name)
    txt_path = os.path.join(tmpdir, f'{safe}.txt')
    qc_path = os.path.join(tmpdir, f'{safe}_QC.json')

    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(full_text)

    qc_data = {
        'book': novel_name, 'site': domain, 'book_id': book_id,
        'total_chapters': len(chapters), 'ok': cnt_ok, 'short': cnt_short, 'failed': cnt_fail,
        'min_chars': min_chars, 'short_chapters': qc_short, 'failed_chapters': qc_failed,
    }
    with open(qc_path, 'w', encoding='utf-8') as f:
        json.dump(qc_data, f, ensure_ascii=False, indent=2)

    summary = (
        f'✅ เสร็จแล้ว!\n'
        f'ตอนทั้งหมด: {len(chapters)}\n'
        f'OK: {cnt_ok}  |  สั้น: {cnt_short}  |  ล้มเหลว: {cnt_fail}'
    )
    log(summary)
    return txt_path, qc_path, summary


# ── Main async runner ─────────────────────────────────────────────────────────

async def run_download(url, novel_name, workers, delay, min_chars, log_fn):
    try:
        site, book_id = parse_novel_url(url)
        log_fn(f'✅ ตรวจพบ: site={site}  book_id={book_id}')
    except ValueError as e:
        return None, None, str(e)

    if not novel_name.strip():
        novel_name = f'{site}_{book_id.replace("/", "_")}'

    if site == 'biquge365':
        return await download_biquge365(book_id, novel_name, workers, delay, min_chars, log_fn)
    elif site == '69shu':
        return await download_69shu(book_id, novel_name, workers, delay, min_chars, log_fn)
    elif site == 'shubaowb':
        return await download_shubaowb(book_id, novel_name, workers, delay, min_chars, log_fn)
    elif site == 'zhys':
        return await download_zhys(book_id, novel_name, workers, delay, min_chars, log_fn)
    else:
        return None, None, f'site "{site}" ยังไม่รองรับใน web app (ใช้ GitHub Actions แทน)'


# ── Gradio UI ─────────────────────────────────────────────────────────────────

def gradio_download(url, novel_name, workers, delay, min_chars):
    logs = []

    def log(msg):
        logs.append(msg)

    txt_path, qc_path, summary = asyncio.run(
        run_download(url, novel_name, int(workers), float(delay), int(min_chars), log)
    )
    log_text = '\n'.join(logs)
    return log_text, txt_path, qc_path


with gr.Blocks(title="Novel Downloader", theme=gr.themes.Soft()) as demo:
    gr.Markdown("""
# 📚 Novel Downloader
วางลิงก์นิยายแล้วกด **Download** — รองรับ biquge365 / 69shu / shubaowb / zhys / 4jiwx / shuixxs
""")

    with gr.Row():
        url_input = gr.Textbox(
            label="🔗 ลิงก์นิยาย",
            placeholder="https://m.biquge365.net/shu/528722/",
            scale=3,
        )
        name_input = gr.Textbox(
            label="ชื่อไฟล์ (ไม่ใส่ก็ได้)",
            placeholder="เว้นว่างให้ระบบตั้งชื่อให้",
            scale=2,
        )

    with gr.Row():
        workers_sl = gr.Slider(1, 10, value=3, step=1, label="Workers (โหลดพร้อมกัน)")
        delay_sl = gr.Slider(0.5, 5, value=2, step=0.5, label="Delay วินาที")
        min_chars_n = gr.Number(value=300, label="QC: ขั้นต่ำตัวอักษร/ตอน", precision=0)

    dl_btn = gr.Button("⬇️ Download", variant="primary", size="lg")

    log_box = gr.Textbox(label="Log", lines=12, interactive=False)

    with gr.Row():
        txt_out = gr.File(label="📄 ไฟล์ TXT (กดโหลด)")
        qc_out = gr.File(label="📊 QC Report JSON")

    dl_btn.click(
        fn=gradio_download,
        inputs=[url_input, name_input, workers_sl, delay_sl, min_chars_n],
        outputs=[log_box, txt_out, qc_out],
    )

    gr.Markdown("""
---
**ตัวอย่าง URL:**
- `https://m.biquge365.net/shu/528722/`
- `https://www.69shu.xyz/index/2/2829/1.html/`
- `https://shubaowb.com/novel/YH2B.html`
""")

if __name__ == "__main__":
    demo.launch()
