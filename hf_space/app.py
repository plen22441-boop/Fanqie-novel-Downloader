#!/usr/bin/env python3
"""Novel Downloader — Streamlit web app (universal, trafilatura-powered)"""

import asyncio
import aiohttp
import re
import json
import io
import os
import zipfile
import textwrap
from urllib.parse import urljoin, urlparse
import trafilatura
import streamlit as st


# ── QC helpers (inline, no extra file dependency) ─────────────────────────────

_QC_SYSTEM = """คุณคือทีม QC นิยายของสำนักพิมพ์ไทยที่เชี่ยวชาญตลาดนิยายออนไลน์ไทย
คุณประเมินนิยายจีนแปลสำหรับแพลตฟอร์ม MyNovel และเว็บนิยายไทยชั้นนำ

**ฐานนักอ่านที่คุณจำลอง:**
- นักอ่านหญิงไทย อายุ 18–35 ปี ที่ชอบนิยายจีนแปล
- อ่านบน MyNovel, นิยาย24h, Readawrite, Fictionlog
- ชอบแนวหลัก: โรแมนซ์ CEO/จอมมาร, ย้อนยุคจีน, แฟนตาซีรัก, เจ้าพ่อ×เจ้าสาว, BL
- ต้องการ: ปมดึงดูดภายใน 3 บทแรก, พระเอก/นางเอกน่าติดตาม, tension สม่ำเสมอ
- ไม่ชอบ: บทนำยาวเกินไป, ตัวละครแบน, โครงเรื่องซ้ำโดยไม่มีจุดขายใหม่

**เกณฑ์ประเมินตลาด:**
- ความเร็วพล็อต (บท 1 ต้องมี hook ดึงดูด)
- ความเป็น "จอมมาร/เจ้าพ่อ/เย็นชา" ของพระเอก (ขายได้บนตลาดไทย)
- ความน่าเอาใจช่วยของนางเอก (ไม่ passive เกิน)
- ศักยภาพ fanbase / clip รีวิว / word of mouth
- ความเหมาะสมเนื้อหากับวัฒนธรรมไทย
- ความยาวเหมาะแก่การแปลและเผยแพร่ระยะยาว

ตอบเป็นภาษาไทย ในรูปแบบ JSON ที่กำหนดเท่านั้น"""

def _qc_user_prompt(title, synopsis, sample):
    return f"""## นิยายที่ส่ง QC

**ชื่อเรื่อง:** {title}

**คำโปรย/synopsis:**
{synopsis or "(ไม่มีคำโปรย — ให้ประเมินจากเนื้อหาตัวอย่างอย่างเดียว)"}

**ตัวอย่างเนื้อหา (บทแรก ๆ):**
```
{sample}
```

กรุณาประเมินและตอบกลับใน JSON format นี้เท่านั้น (ไม่มีข้อความอื่น):

{{
  "title_th": "ชื่อที่แนะนำสำหรับตลาดไทย",
  "overall_status": "ผ่านการคัดเลือก | ผ่านแบบมีเงื่อนไข | ไม่ผ่าน",
  "female_reader_score": <0.0–10.0>,
  "thai_market_score": <0.0–10.0>,
  "female_reader_analysis": "วิเคราะห์จากมุมนักอ่านหญิง 2–4 ประโยค",
  "market_editorial_analysis": "วิเคราะห์ตลาดและบรรณาธิการ 2–4 ประโยค",
  "risk_factors": ["จุดเสี่ยง 1", "จุดเสี่ยง 2", "จุดเสี่ยง 3"],
  "strengths": ["จุดแข็ง 1", "จุดแข็ง 2"],
  "genre_tags": ["แท็กแนว 1", "แท็กแนว 2"],
  "translation_priority": "สูง | กลาง | ต่ำ",
  "editor_notes": "หมายเหตุเพิ่มเติมสำหรับทีมแปล"
}}"""

def _extract_sample(text, max_chars=12000):
    for pattern in [r"(?m)^第[一二三四五六七八九十百千\d]+章", r"(?m)^Chapter\s+\d+",
                    r"(?m)^ตอนที่\s+\d+", r"(?m)^\d+\."]:
        splits = re.split(pattern, text)
        if len(splits) >= 4:
            sample = "\n\n".join(splits[:4])
            return sample[:max_chars].strip()
    return text[:max_chars].strip()

def _call_qc_api(title, synopsis, sample, api_key, model="claude-opus-4-5"):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model,
        max_tokens=2048,
        system=_QC_SYSTEM,
        messages=[{"role": "user", "content": _qc_user_prompt(title, synopsis, sample)}],
    )
    raw = msg.content[0].text.strip()
    m = re.search(r"\{[\s\S]+\}", raw)
    return json.loads(m.group() if m else raw)


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

st.set_page_config(page_title='Novel Downloader & QC', page_icon='📚', layout='centered')
st.title('📚 Novel Downloader & QC')

tab_dl, tab_qc = st.tabs(['⬇️ Download นิยาย', '🔍 QC จำลองนักอ่าน MyNovel'])

# ── Tab 1: Download ────────────────────────────────────────────────────────────
with tab_dl:
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

    st.markdown('---\n💡 **วิธีใช้:** วาง URL หน้าสารบัญของนิยาย แล้วกด Download')


# ── Tab 2: QC จำลองนักอ่าน ────────────────────────────────────────────────────
with tab_qc:
    st.markdown(
        '**จำลองการ QC จากมุมมองนักอ่านหญิงไทย** บน MyNovel  \n'
        'อัปโหลดไฟล์นิยาย (.txt หรือ .epub) เพื่อรับคะแนนและวิเคราะห์ตลาด'
    )

    with st.form('qc_form'):
        uploaded = st.file_uploader('📂 อัปโหลดไฟล์นิยาย', type=['txt', 'epub'])
        synopsis_input = st.text_area(
            '📝 คำโปรย / Synopsis (ไม่บังคับ)',
            placeholder='ใส่คำโปรยหรือเนื้อเรื่องย่อ เพื่อให้การวิเคราะห์แม่นยำขึ้น...',
            height=100,
        )
        api_key_input = st.text_input(
            '🔑 Anthropic API Key',
            type='password',
            placeholder='sk-ant-... (หรือตั้ง env ANTHROPIC_API_KEY)',
            value=os.environ.get('ANTHROPIC_API_KEY', ''),
        )
        qc_model = st.selectbox(
            'Claude Model',
            ['claude-opus-4-5', 'claude-sonnet-4-5', 'claude-haiku-4-5'],
            index=0,
        )
        max_chars = st.slider('ตัวอักษรตัวอย่างที่ส่ง AI (มากขึ้น = แม่นขึ้น แต่ช้ากว่า)', 4000, 20000, 12000, step=2000)
        qc_submitted = st.form_submit_button('🔍 วิเคราะห์', type='primary', use_container_width=True)

    if qc_submitted:
        if not uploaded:
            st.warning('กรุณาอัปโหลดไฟล์นิยายก่อนค่ะ')
        elif not api_key_input.strip():
            st.warning('กรุณาใส่ Anthropic API Key')
        else:
            with st.spinner('กำลังอ่านไฟล์และวิเคราะห์...'):
                try:
                    raw_bytes = uploaded.read()
                    fname = uploaded.name
                    title_guess = re.sub(r'\.(txt|epub)$', '', fname, flags=re.I)

                    if fname.lower().endswith('.epub'):
                        import ebooklib
                        from ebooklib import epub as eblib_epub
                        from bs4 import BeautifulSoup
                        import tempfile, pathlib
                        with tempfile.NamedTemporaryFile(suffix='.epub', delete=False) as tf:
                            tf.write(raw_bytes)
                            tf_path = tf.name
                        book = eblib_epub.read_epub(tf_path)
                        title_guess = book.title or title_guess
                        parts = []
                        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                            soup = BeautifulSoup(item.get_content(), 'html.parser')
                            t = soup.get_text('\n')
                            if len(t.strip()) > 100:
                                parts.append(t.strip())
                        full_text = '\n\n'.join(parts)
                        os.unlink(tf_path)
                    else:
                        full_text = raw_bytes.decode('utf-8', errors='replace')

                    sample = _extract_sample(full_text, max_chars)
                    result = _call_qc_api(title_guess, synopsis_input, sample, api_key_input.strip(), qc_model)

                    # ── แสดงผลรายงาน ─────────────────────────────────────────
                    status = result.get('overall_status', '—')
                    status_color = {'ผ่านการคัดเลือก': 'green', 'ผ่านแบบมีเงื่อนไข': 'orange', 'ไม่ผ่าน': 'red'}.get(status, 'gray')
                    status_icon = {'ผ่านการคัดเลือก': '✅', 'ผ่านแบบมีเงื่อนไข': '⚠️', 'ไม่ผ่าน': '❌'}.get(status, '❓')

                    st.markdown(f'## {result.get("title_th", title_guess)}')
                    st.markdown(f'**สถานะ:** :{status_color}[{status_icon} {status}]')

                    tags = result.get('genre_tags', [])
                    if tags:
                        st.markdown(' '.join(f'`{t}`' for t in tags))

                    st.markdown(f'**ลำดับความสำคัญการแปล:** {result.get("translation_priority", "—")}')
                    st.markdown('---')

                    col1, col2 = st.columns(2)
                    fr = float(result.get('female_reader_score', 0))
                    tm = float(result.get('thai_market_score', 0))
                    with col1:
                        st.metric('ศักยภาพนักอ่านหญิง', f'{fr:.1f} / 10')
                        st.progress(fr / 10)
                    with col2:
                        st.metric('ศักยภาพตลาดไทย', f'{tm:.1f} / 10')
                        st.progress(tm / 10)

                    st.markdown('---')

                    strengths = result.get('strengths', [])
                    if strengths:
                        st.markdown('### ✨ จุดแข็ง')
                        for s in strengths:
                            st.markdown(f'- {s}')

                    st.markdown('### 👩 มุมนักอ่านหญิง')
                    st.markdown(result.get('female_reader_analysis', ''))

                    st.markdown('### 📊 มุมตลาดและบรรณาธิการ')
                    st.markdown(result.get('market_editorial_analysis', ''))

                    risks = result.get('risk_factors', [])
                    if risks:
                        st.markdown('### ⚠️ จุดเสี่ยง')
                        for r in risks:
                            st.markdown(f'- {r}')

                    notes = result.get('editor_notes', '')
                    if notes:
                        st.markdown('### 📝 หมายเหตุทีมแปล')
                        st.markdown(notes)

                    st.markdown('---')
                    st.download_button(
                        '💾 โหลดผล QC (JSON)',
                        data=json.dumps(result, ensure_ascii=False, indent=2).encode('utf-8'),
                        file_name=f'{title_guess}_QC_simulation.json',
                        mime='application/json',
                    )

                except ImportError as e:
                    st.error(f'ขาด dependency: {e}  \nรัน: pip install anthropic ebooklib bs4')
                except Exception as e:
                    st.error(f'เกิดข้อผิดพลาด: {e}')
