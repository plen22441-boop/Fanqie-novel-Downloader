"""
Universal novel downloader with parallel chapter fetching.
Supports fanqienovel.com (via API) and other Chinese novel sites (via scraping).
Usage: python download_novel.py <url_or_book_id> [--workers 20] [--output dir]
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
from urllib.parse import urljoin, urlparse


SEPARATOR = "─" * 40
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
]

CONTENT_SELECTORS = [
    "#chaptercontent", "#BookText", "#content", "#booktxt", "#htmlContent",
    ".chapter-content", ".read-content", ".novel-content", ".chapter-txt",
    ".readcontent", ".duanzhang", ".box_con #content", "article .content",
    "#nr1", "#nr2", ".neirong", ".zuopin_content", "#novelcontent",
    "#chapterBody", ".chaptercontent", "#reader-content", ".text-content",
]


def get_headers(referer=None, extra=None):
    h = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    if referer:
        h["Referer"] = referer
    if extra:
        h.update(extra)
    return h


def is_fanqie(url: str) -> bool:
    return "fanqienovel.com" in url or "fqnovel.com" in url


def extract_book_id(url: str) -> str:
    m = re.search(r"\d{6,}", url)
    if not m:
        sys.exit(f"[ERROR] ไม่พบ book ID ใน: {url}")
    return m.group(0)


# ─── Fanqie API path ───────────────────────────────────────────────────────────

def fanqie_book_info(session, book_id):
    url = f"https://fanqienovel.com/page/{book_id}"
    try:
        r = session.get(url, headers=get_headers(), timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        name = (soup.find("h1") or type("_", (), {"text": "未知书名"})()).text.strip()
        author_el = soup.find("div", class_="author-name")
        author = "未知作者"
        if author_el:
            sp = author_el.find("span", class_="author-name-text")
            author = sp.text.strip() if sp else author
        return name, author
    except Exception as e:
        print(f"[WARN] fanqie_book_info: {e}")
        return book_id, "未知作者"


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


# ─── Generic web scraping path ─────────────────────────────────────────────────

def extract_text_from_html(html, base_url=""):
    tmp = BeautifulSoup(html, "html.parser")
    for tag in tmp.select("script,style,ins,iframe,.adsbygoogle,nav,header,footer,.ad,.ads"):
        tag.decompose()

    # Try each selector
    for sel in CONTENT_SELECTORS:
        el = tmp.select_one(sel)
        if el:
            # Remove ads/navigation inside content block
            for sub in el.select("script,style,.ad,.ads,a[href*='novel'],a[href*='book']"):
                sub.decompose()
            t = (el.get_text("\n") or "").strip()
            if len(t.replace(" ", "").replace("\n", "")) > 80:
                return re.sub(r"\n{3,}", "\n\n", t).strip()

    # biquge fallback: look for dense <p> tags
    paragraphs = tmp.find_all("p")
    if paragraphs:
        long_ps = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20]
        if len(long_ps) >= 3:
            return "\n".join(long_ps)

    # last resort: body text
    body = tmp.find("body")
    if body:
        t = (body.get_text("\n") or "").strip()
        return re.sub(r"\n{3,}", "\n\n", t).strip()
    return ""


def scrape_book_info(session, book_url):
    try:
        r = session.get(book_url, headers=get_headers(), timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        # ลอง selector ชื่อหนังสือหลายแบบ
        for sel in ["h1.book-name", "h1.name", ".book-title h1", "h1"]:
            el = soup.select_one(sel)
            if el:
                name = el.get_text(strip=True)
                if name:
                    break
        else:
            name = soup.title.string.strip() if soup.title else "未知书名"
        # ลอง selector ผู้แต่ง
        author = "未知作者"
        for sel in [".author", ".book-author", "[class*='author']"]:
            el = soup.select_one(sel)
            if el:
                author = el.get_text(strip=True)
                break
        return name, author, r.text
    except Exception as e:
        print(f"[WARN] scrape_book_info: {e}")
        return "未知书名", "未知作者", ""


def scrape_chapter_list(book_url, html):
    soup = BeautifulSoup(html, "html.parser")
    book_id = extract_book_id(book_url)
    base = f"{urlparse(book_url).scheme}://{urlparse(book_url).netloc}"
    seen, chapters = {}, []

    # ลองดึง link ตอนจาก pattern ต่างๆ
    patterns = [
        f"/book/{book_id}/", f"/read/{book_id}/",
        f"/{book_id}/", f"chapter", f"chap",
    ]
    for a in soup.find_all("a", href=True):
        href = a["href"]
        full = urljoin(base, href)
        if any(p in href for p in patterns) and full != book_url:
            if full not in seen:
                seen[full] = True
                title = a.get_text(strip=True) or full
                chapters.append({"url": full, "title": title})

    # sort by number in URL
    def url_num(ch):
        nums = re.findall(r"\d+", ch["url"].replace(book_id, ""))
        return int(nums[-1]) if nums else 0

    chapters.sort(key=url_num)
    return chapters


def download_web_chapter(session, chapter, book_url, max_retries=5):
    for attempt in range(max_retries):
        try:
            r = session.get(chapter["url"], headers=get_headers(book_url), timeout=25)
            r.encoding = r.apparent_encoding or "utf-8"
            if r.ok:
                text = extract_text_from_html(r.text, chapter["url"])
                if len(text.replace(" ", "").replace("\n", "")) > 80:
                    return chapter.get("index", 0), chapter["title"], text
        except Exception:
            pass
        time.sleep(1.5 * (attempt + 1))
    return chapter.get("index", 0), chapter["title"], ""


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("target", help="URL หรือ Book ID")
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--output", default="downloads")
    parser.add_argument("--retries", type=int, default=5)
    args = parser.parse_args()

    target = args.target.strip()
    os.makedirs(args.output, exist_ok=True)
    session = requests.Session()
    session.headers.update({"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})

    # ─ Detect mode
    if is_fanqie(target) or (target.isdigit() and len(target) >= 10):
        # Fanqie novel
        book_id = extract_book_id(target)
        print(f"[MODE] Fanqie API | ID: {book_id}")
        print(f"[1/3] ดึงข้อมูลหนังสือ...")
        name, author = fanqie_book_info(session, book_id)
        print(f"      ชื่อ: {name} | ผู้แต่ง: {author}")

        print(f"[2/3] ดึงรายชื่อตอน...")
        chapters = fanqie_chapters(session, book_id)
        print(f"      พบ {len(chapters)} ตอน")
        if not chapters:
            sys.exit("[ERROR] ไม่พบตอนใดๆ — ลองใส่ URL เต็มของเว็บแทน Book ID")

        print(f"[3/3] โหลดเนื้อหา ({args.workers} workers)...")
        results = [None] * len(chapters)
        failed = []
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(download_fanqie_chapter, session, ch, args.retries): ch for ch in chapters}
            done = 0
            for f in as_completed(futs):
                idx, title, content = f.result()
                results[idx] = (title, content)
                done += 1
                pct = done * 100 // len(chapters)
                bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                print(f"\r      [{bar}] {done}/{len(chapters)} ({pct}%)", end="", flush=True)
                if not content:
                    failed.append(title)
        print()

    else:
        # Generic web scraping
        book_url = target if target.startswith("http") else f"https://{target}"
        domain = urlparse(book_url).netloc
        print(f"[MODE] Web scraping | {domain}")

        print(f"[1/3] ดึงข้อมูลหนังสือ...")
        name, author, html = scrape_book_info(session, book_url)
        print(f"      ชื่อ: {name} | ผู้แต่ง: {author}")

        print(f"[2/3] ดึงรายชื่อตอน...")
        chapters = scrape_chapter_list(book_url, html)
        for i, ch in enumerate(chapters):
            ch["index"] = i
        print(f"      พบ {len(chapters)} ตอน")
        if not chapters:
            sys.exit("[ERROR] ไม่พบตอนใดๆ — เว็บอาจต้อง login หรือใช้ JavaScript")

        print(f"[3/3] โหลดเนื้อหา ({args.workers} workers)...")
        results = [None] * len(chapters)
        failed = []
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(download_web_chapter, session, ch, book_url, args.retries): ch for ch in chapters}
            done = 0
            for f in as_completed(futs):
                idx, title, content = f.result()
                results[idx] = (title, content)
                done += 1
                pct = done * 100 // len(chapters)
                bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                print(f"\r      [{bar}] {done}/{len(chapters)} ({pct}%)", end="", flush=True)
                if not content:
                    failed.append(title)
        print()

    # ─ Save
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", name)
    book_id_safe = re.sub(r"[^\w]", "_", extract_book_id(target))
    out_path = os.path.join(args.output, f"{safe_name}_{book_id_safe}.txt")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"{name}\n作者：{author}\n\n")
        for item in results:
            if item is None:
                continue
            title, content = item
            f.write(f"{title}\n\n{content}\n\n{SEPARATOR}\n\n")

    total_chars = sum(len(c) for _, c in results if c and _ is not None)
    print(f"\n✅ บันทึกแล้ว: {out_path}")
    print(f"   ตอนทั้งหมด: {len(results)} | สำเร็จ: {len(results)-len(failed)} | ล้มเหลว: {len(failed)}")
    print(f"   ขนาดรวม: {total_chars:,} ตัวอักษร")

    if failed:
        print(f"\n⚠️  ตอนที่โหลดไม่ได้ ({len(failed)} ตอน):")
        for t in failed[:20]:
            print(f"   - {t}")

    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"novel_name={name}\n")
            f.write(f"total_chapters={len(results)}\n")
            f.write(f"failed_chapters={len(failed)}\n")
            f.write(f"output_file={out_path}\n")


if __name__ == "__main__":
    main()
