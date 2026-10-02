"""
Download missing chapters from Fanqienovel and merge into existing file.
Usage: python patch_missing.py <existing_file.txt> <book_id> [--workers 10]
"""

import sys
import re
import os
import time
import random
import argparse
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup

SEPARATOR = "─" * 40

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]


def get_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


def fanqie_chapters(session, book_id):
    url = f"https://api5-normal-lf.fqnovel.com/reading/bookapi/search/{book_id}/v"
    r = session.get(url, headers=get_headers(), timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    chapters = []
    for idx, item in enumerate(soup.select("div.chapter-item")):
        a = item.find("a")
        if not a:
            continue
        raw = a.get_text(strip=True)
        if re.match(r"^(番外|特别篇|if线)\s*", raw):
            title = raw
        else:
            clean = re.sub(r"^第[一二三四五六七八九十百千\d]+章\s*", "", raw).strip()
            title = f"第{idx+1}章 {clean}"
        chapters.append({"index": idx, "id": a["href"].split("/")[-1], "title": title})
    return chapters


def clean_fanqie_content(raw, title=""):
    c = re.sub(r"<header>.*?</header>", "", raw, flags=re.DOTALL)
    c = re.sub(r"<footer>.*?</footer>", "", c, flags=re.DOTALL)
    c = re.sub(r"</?article>", "", c)
    c = re.sub(r'<p idx="\d+">', "\n", c)
    c = re.sub(r"</p>", "\n", c)
    c = re.sub(r"<[^>]+>", "", c)
    if title and c.startswith(title):
        c = c[len(title):].lstrip()
    c = re.sub(r"\n{2,}", "\n", c).strip()
    return "\n".join("    " + ln if ln.strip() else ln for ln in c.split("\n"))


def download_fanqie_chapter(session, chapter, max_retries=5):
    for attempt in range(max_retries):
        try:
            url = f"https://api.cengui.cn/api/tomato/content.php?item_id={chapter['id']}"
            r = session.get(url, headers=get_headers(), timeout=15)
            data = r.json()
            if data.get("code") == 200:
                content = data.get("data", {}).get("content", "")
                api_title = data.get("data", {}).get("title", "")
                return chapter["index"], chapter["title"], clean_fanqie_content(content, api_title)
        except Exception:
            pass
        time.sleep(1.5 * (attempt + 1))
    return chapter["index"], chapter["title"], ""


def parse_existing_file(filepath):
    """Parse existing novel file into header and chapters dict {1-based index -> (title, content)}."""
    with open(filepath, encoding="utf-8") as f:
        text = f.read()

    lines = text.split("\n")
    header_lines = []
    # First two lines are title and author
    for i, line in enumerate(lines):
        header_lines.append(line)
        if i >= 1:
            break
    header = "\n".join(header_lines)

    # Split by separator
    blocks = re.split(r"─{30,}", text)
    chapters = {}
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        # Skip the header block
        bl = block.split("\n")
        first_line = bl[0].strip() if bl else ""
        # Header has book title/author pattern (no chapter number)
        if re.match(r"^作者[：:]", first_line) or not first_line:
            continue
        # Find chapter index from title
        m = re.match(r"^第(\d+)章", first_line)
        if m:
            idx = int(m.group(1))
            content_lines = bl[2:] if len(bl) > 2 else []
            content = "\n".join(content_lines).strip()
            chapters[idx] = (first_line, content)

    return header, chapters


def find_missing(chapters_dict, total):
    """Return sorted list of 1-based chapter indices that are missing or empty."""
    missing = []
    for i in range(1, total + 1):
        if i not in chapters_dict:
            missing.append(i)
        elif not chapters_dict[i][1].strip():
            missing.append(i)
    return missing


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("existing_file", help="Path to existing .txt novel file")
    parser.add_argument("book_id", help="Fanqienovel Book ID (e.g. 7444079991228222526)")
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--output", default=None, help="Output file path (default: overwrites original with _patched suffix)")
    args = parser.parse_args()

    if not os.path.exists(args.existing_file):
        sys.exit(f"[ERROR] File not found: {args.existing_file}")

    print(f"[1/4] อ่านไฟล์เดิม: {args.existing_file}")
    header, existing_chapters = parse_existing_file(args.existing_file)
    print(f"      พบตอนในไฟล์: {len(existing_chapters)}")

    session = requests.Session()
    session.headers.update({"Accept-Language": "zh-CN,zh;q=0.9"})

    print(f"[2/4] ดึงรายชื่อตอนจาก Fanqie API (Book ID: {args.book_id})...")
    all_chapters = fanqie_chapters(session, args.book_id)
    total = len(all_chapters)
    print(f"      ตอนทั้งหมด: {total}")
    if not all_chapters:
        sys.exit("[ERROR] ไม่พบตอนใดๆ จาก API — ตรวจสอบ Book ID")

    # Build a map: 1-based index -> chapter info
    chapter_by_index = {ch["index"] + 1: ch for ch in all_chapters}

    missing_indices = find_missing(existing_chapters, total)
    print(f"      ตอนที่ขาด: {len(missing_indices)} ตอน")
    if missing_indices:
        print(f"      ตอนที่ขาด: {missing_indices}")

    if not missing_indices:
        print("\n✅ ไม่มีตอนที่ขาด — ไฟล์สมบูรณ์แล้ว")
        return

    # Get chapter info for missing ones
    to_download = [chapter_by_index[i] for i in missing_indices if i in chapter_by_index]
    not_in_api = [i for i in missing_indices if i not in chapter_by_index]
    if not_in_api:
        print(f"      ⚠️  ตอนที่ไม่พบใน API: {not_in_api}")

    print(f"\n[3/4] โหลด {len(to_download)} ตอนที่ขาด ({args.workers} workers)...")
    new_chapters = {}
    failed = []

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(download_fanqie_chapter, session, ch): ch for ch in to_download}
        done = 0
        for f in as_completed(futs):
            idx_0, title, content = f.result()
            idx_1 = idx_0 + 1
            new_chapters[idx_1] = (title, content)
            done += 1
            pct = done * 100 // len(to_download)
            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
            print(f"\r      [{bar}] {done}/{len(to_download)} ({pct}%)", end="", flush=True)
            if not content:
                failed.append(title)
    print()

    print(f"[4/4] รวมและบันทึกไฟล์...")
    # Merge: existing + new
    merged = dict(existing_chapters)
    merged.update(new_chapters)

    # Determine output path
    if args.output:
        out_path = args.output
    else:
        base, ext = os.path.splitext(args.existing_file)
        out_path = base + "_patched" + ext

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(header + "\n\n")
        for i in range(1, total + 1):
            if i not in merged:
                continue
            title, content = merged[i]
            f.write(f"{title}\n\n{content}\n\n{SEPARATOR}\n\n")

    still_missing = [i for i in range(1, total + 1) if i not in merged or not merged[i][1].strip()]
    print(f"\n✅ บันทึกแล้ว: {out_path}")
    print(f"   ตอนทั้งหมด: {total} | ในไฟล์: {len(merged)} | โหลดเพิ่ม: {len(new_chapters)}")
    print(f"   โหลดสำเร็จ: {len(new_chapters)-len(failed)} | ล้มเหลว: {len(failed)}")

    if still_missing:
        print(f"\n⚠️  ยังขาดอยู่ ({len(still_missing)} ตอน): {still_missing[:40]}")
    else:
        print("\n🎉 ไฟล์สมบูรณ์ครบทุกตอนแล้ว!")

    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"output_file={out_path}\n")
            f.write(f"patched_chapters={len(new_chapters)}\n")
            f.write(f"failed_chapters={len(failed)}\n")
            f.write(f"still_missing={len(still_missing)}\n")


if __name__ == "__main__":
    main()
