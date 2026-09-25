"""
Standalone novel downloader with parallel chapter fetching.
Usage: python download_novel.py <book_id_or_url> [--workers 20] [--output dir]
"""

import sys
import re
import os
import time
import json
import random
import argparse
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup


SEPARTOR = "─" * 40
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]


def get_headers():
    return {"User-Agent": random.choice(USER_AGENTS)}


def get_book_id(raw: str) -> str:
    m = re.search(r"\d{6,}", raw)
    if not m:
        sys.exit(f"[ERROR] ไม่พบ book ID ใน: {raw}")
    return m.group(0)


def get_book_info(session: requests.Session, book_id: str):
    url = f"https://fanqienovel.com/page/{book_id}"
    try:
        r = session.get(url, headers=get_headers(), timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        name = (soup.find("h1") or type("", (), {"text": "未知书名"})()).text
        author_el = soup.find("div", class_="author-name")
        author = "未知作者"
        if author_el:
            sp = author_el.find("span", class_="author-name-text")
            author = sp.text if sp else author
        return name.strip(), author.strip()
    except Exception as e:
        print(f"[WARN] get_book_info failed: {e}")
        return book_id, "未知作者"


def get_chapters(session: requests.Session, book_id: str) -> list:
    url = f"https://api5-normal-lf.fqnovel.com/reading/bookapi/search/{book_id}/v"
    try:
        r = session.get(url, headers=get_headers(), timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        chapters = []
        for idx, item in enumerate(soup.select("div.chapter-item")):
            a = item.find("a")
            if not a:
                continue
            raw_title = a.get_text(strip=True)
            if re.match(r"^(番外|特别篇|if线)\s*", raw_title):
                title = raw_title
            else:
                clean = re.sub(r"^第[一二三四五六七八九十百千\d]+章\s*", "", raw_title).strip()
                title = f"第{idx+1}章 {clean}"
            chapters.append({
                "index": idx,
                "id": a["href"].split("/")[-1],
                "title": title,
            })
        return chapters
    except Exception as e:
        sys.exit(f"[ERROR] get_chapters failed: {e}")


def clean_content(raw: str, title: str = "") -> str:
    c = re.sub(r"<header>.*?</header>", "", raw, flags=re.DOTALL)
    c = re.sub(r"<footer>.*?</footer>", "", c, flags=re.DOTALL)
    c = re.sub(r"</?article>", "", c)
    c = re.sub(r'<p idx="\d+">', "\n", c)
    c = re.sub(r"</p>", "\n", c)
    c = re.sub(r"<[^>]+>", "", c)
    if title and c.startswith(title):
        c = c[len(title):].lstrip()
    c = re.sub(r"\n{2,}", "\n", c).strip()
    return "\n".join("    " + line if line.strip() else line for line in c.split("\n"))


def download_chapter(session: requests.Session, chapter: dict, max_retries: int = 5) -> tuple:
    chapter_id = chapter["id"]
    for attempt in range(max_retries):
        try:
            url = f"https://api.cengui.cn/api/tomato/content.php?item_id={chapter_id}"
            r = session.get(url, headers=get_headers(), timeout=15)
            data = r.json()
            if data.get("code") == 200:
                content = data.get("data", {}).get("content", "")
                api_title = data.get("data", {}).get("title", "")
                return chapter["index"], chapter["title"], clean_content(content, api_title)
        except Exception:
            pass
        time.sleep(1.5 * (attempt + 1))
    return chapter["index"], chapter["title"], ""


def main():
    parser = argparse.ArgumentParser(description="Fanqie Novel Downloader")
    parser.add_argument("target", help="Book ID or URL")
    parser.add_argument("--workers", type=int, default=20, help="Parallel workers (default: 20)")
    parser.add_argument("--output", default="downloads", help="Output directory")
    parser.add_argument("--retries", type=int, default=5, help="Retries per chapter")
    args = parser.parse_args()

    book_id = get_book_id(args.target)
    os.makedirs(args.output, exist_ok=True)

    session = requests.Session()

    print(f"[1/3] ดึงข้อมูลหนังสือ ID: {book_id}")
    name, author = get_book_info(session, book_id)
    print(f"      ชื่อ: {name} | ผู้แต่ง: {author}")

    print(f"[2/3] ดึงรายชื่อตอน...")
    chapters = get_chapters(session, book_id)
    print(f"      พบ {len(chapters)} ตอน")

    if not chapters:
        sys.exit("[ERROR] ไม่พบตอนใดๆ")

    print(f"[3/3] โหลดเนื้อหา ({args.workers} workers)...")
    results = [None] * len(chapters)
    failed = []

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(download_chapter, session, ch, args.retries): ch
            for ch in chapters
        }
        done_count = 0
        for future in as_completed(futures):
            idx, title, content = future.result()
            results[idx] = (title, content)
            done_count += 1
            pct = done_count * 100 // len(chapters)
            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
            print(f"\r      [{bar}] {done_count}/{len(chapters)} ({pct}%)", end="", flush=True)
            if not content:
                failed.append(title)

    print()

    # บันทึกไฟล์
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", name)
    out_path = os.path.join(args.output, f"{safe_name}_{book_id}.txt")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"{name}\n作者：{author}\n\n")
        for title, content in results:
            if title is None:
                continue
            f.write(f"{title}\n\n{content}\n\n{SEPARTOR}\n\n")

    total_chars = sum(len(c) for _, c in results if c)
    print(f"\n✅ บันทึกแล้ว: {out_path}")
    print(f"   ตอนทั้งหมด: {len(chapters)} | สำเร็จ: {len(chapters)-len(failed)} | ล้มเหลว: {len(failed)}")
    print(f"   ขนาดรวม: {total_chars:,} ตัวอักษร")

    if failed:
        print(f"\n⚠️  ตอนที่โหลดไม่ได้ ({len(failed)} ตอน):")
        for t in failed[:20]:
            print(f"   - {t}")

    # บันทึก summary สำหรับ GitHub Actions
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"novel_name={name}\n")
            f.write(f"total_chapters={len(chapters)}\n")
            f.write(f"failed_chapters={len(failed)}\n")
            f.write(f"output_file={out_path}\n")


if __name__ == "__main__":
    main()
