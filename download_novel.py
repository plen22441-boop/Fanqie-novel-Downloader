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
try:
    import cloudscraper
except ImportError:
    cloudscraper = None
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None
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
        "Accept-Encoding": "gzip, deflate",
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
    m = re.search(r"\d{6,}", url) or re.search(r"\d{4,}", url)
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
    endpoints = [
        f"https://api5-normal-lf.fqnovel.com/reading/bookapi/search/{book_id}/v",
        f"https://api5-normal-lf.fqnovel.com/reading/bookapi/detail/v/?book_id={book_id}",
        f"https://api.cenguigui.cn/api/tomato/book.php?book_id={book_id}",
        f"https://fanqienovel.com/page/{book_id}",
    ]
    chapters = []
    for url in endpoints:
        try:
            r = session.get(url, headers=get_headers(), timeout=15)
            print(f"[DEBUG] {url} -> {r.status_code} len={len(r.text)} head={r.text[:300]!r}")
            # Try JSON first
            try:
                data = r.json()
                # flatten any nested chapter list
                raw_list = (
                    data.get("data", {}).get("chapter_list")
                    or data.get("data", {}).get("chapters")
                    or data.get("chapters")
                    or (data.get("data") if isinstance(data.get("data"), list) else None)
                )
                if raw_list:
                    for idx, item in enumerate(raw_list):
                        cid = str(item.get("chapter_id") or item.get("id") or item.get("item_id", ""))
                        raw_title = item.get("chapter_title") or item.get("title") or f"第{idx+1}章"
                        if re.match(r"^(番外|特别篇|if线)\s*", raw_title):
                            title = raw_title
                        else:
                            clean = re.sub(r"^第[一二三四五六七八九十百千\d]+章\s*", "", raw_title).strip()
                            title = f"第{idx+1}章 {clean}" if clean else raw_title
                        if cid:
                            chapters.append({"index": idx, "id": cid, "title": title})
                    if chapters:
                        return chapters
            except Exception:
                pass
            # Try HTML (original format)
            soup = BeautifulSoup(r.text, "html.parser")
            items = soup.select("div.chapter-item")
            if items:
                for idx, item in enumerate(items):
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
                if chapters:
                    return chapters
        except Exception as e:
            print(f"[WARN] fanqie_chapters {url}: {e}")
            continue
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
            url = f"https://api.cenguigui.cn/api/tomato/content.php?item_id={chapter['id']}"
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


# ─── Playwright fallback for Cloudflare ────────────────────────────────────────

def playwright_get_page(url, wait_sec=10):
    """Use a real browser to bypass Cloudflare, return (html, cookies_dict)."""
    if not sync_playwright:
        return None, {}
    print(f"      [INFO] Using Playwright browser to bypass Cloudflare...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=USER_AGENTS[0],
            locale="zh-CN",
        )
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        # Wait for Cloudflare to clear
        for _ in range(wait_sec * 2):
            title = page.title()
            if "Just a moment" not in title and "Checking" not in title:
                break
            time.sleep(0.5)
        time.sleep(2)
        html = page.content()
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        browser.close()
    return html, cookies


def playwright_session_from_cookies(cookies, base_url=""):
    """Build a requests.Session carrying cookies from Playwright."""
    s = requests.Session()
    s.headers.update(get_headers(base_url))
    for name, value in cookies.items():
        s.cookies.set(name, value)
    return s


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


NAV_TXT = {"下一页", "上一页", "下页", "上页", "下一頁", "上一頁", "首页", "尾页", "末页", "目录", "返回目录", "书页", "返回", "首頁", "尾頁"}


def scrape_chapter_list(book_url, html):
    soup = BeautifulSoup(html, "html.parser")
    book_id = extract_book_id(book_url)
    base = f"{urlparse(book_url).scheme}://{urlparse(book_url).netloc}"
    seen, chapters = {}, []

    # ลองดึง link ตอนจาก pattern ต่างๆ
    patterns = [
        f"/book/{book_id}/", f"/read/{book_id}/", f"/txt/{book_id}/",
        f"/{book_id}/", f"chapter", f"chap",
    ]
    for a in soup.find_all("a", href=True):
        href = a["href"]
        full = urljoin(base, href)
        link_txt = a.get_text(strip=True)
        if link_txt in NAV_TXT or re.search(r"/index[_-]?\d*\.html?$", href):
            continue
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


def collect_chapters_all_pages(session, book_url, html, max_pages=300):
    """Merge chapter links from every page of a (possibly paginated) TOC."""
    NEXT_TXT = ("下一页", "下页", "下一頁", "下頁", "next", "Next", ">")
    merged, seen_urls, visited = [], set(), {book_url}
    queue, cur_html, cur_url, pages = [], html, book_url, 0
    while cur_html is not None and pages < max_pages:
        pages += 1
        for ch in scrape_chapter_list(cur_url, cur_html):
            if ch["url"] not in seen_urls:
                seen_urls.add(ch["url"])
                merged.append(ch)
        soup = BeautifulSoup(cur_html, "html.parser")
        base = f"{urlparse(book_url).scheme}://{urlparse(book_url).netloc}"
        for a in soup.find_all("a", href=True):
            txt = a.get_text(strip=True)
            if (txt in NEXT_TXT or "next" in (a.get("rel") or [])) and not a["href"].startswith(("javascript", "#")):
                queue.append(urljoin(cur_url, a["href"]))
        for opt in soup.select("select option[value]"):
            v = opt["value"]
            if v and not v.startswith(("javascript", "#")) and (".htm" in v or "/" in v):
                queue.append(urljoin(cur_url, v))
        cur_html = None
        while queue:
            nxt = queue.pop(0)
            if nxt in visited or urlparse(nxt).netloc != urlparse(book_url).netloc:
                continue
            visited.add(nxt)
            try:
                r = session.get(nxt, headers=get_headers(book_url), timeout=25)
                r.encoding = r.apparent_encoding or "utf-8"
                if r.ok:
                    cur_html, cur_url = r.text, nxt
                    break
            except Exception:
                continue
    print(f"      อ่านสารบัญ {pages} หน้า")
    return merged


def extract_chapter_title(html, fallback=""):
    soup = BeautifulSoup(html, "html.parser")
    for sel in ["h1.chapter-title", "h1.title", ".chapter-title", ".bookname h1", "h1"]:
        el = soup.select_one(sel)
        if el:
            t = el.get_text(strip=True)
            if t and len(t) < 200 and not t.startswith("http"):
                return t
    return fallback


def download_web_chapter(session, chapter, book_url, max_retries=5):
    for attempt in range(max_retries):
        try:
            r = session.get(chapter["url"], headers=get_headers(book_url), timeout=25)
            r.encoding = r.apparent_encoding or "utf-8"
            if r.ok:
                text = extract_text_from_html(r.text, chapter["url"])
                title = chapter["title"]
                if title.startswith("http") or not title:
                    idx = chapter.get("index", 0)
                    title = extract_chapter_title(r.text, f"第{idx+1}章")
                if len(text.replace(" ", "").replace("\n", "")) > 80:
                    return chapter.get("index", 0), title, text
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

    def is_cloudflare(html):
        return "Just a moment" in html or "cf-browser-verification" in html

    def maybe_upgrade_session(html, url=""):
        """Try cloudscraper, then Playwright if Cloudflare challenge detected."""
        nonlocal session
        if not is_cloudflare(html):
            return False, html
        if cloudscraper:
            print("      [INFO] Cloudflare detected, trying cloudscraper...")
            session = cloudscraper.create_scraper()
            session.headers.update({"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
            try:
                r = session.get(url, headers=get_headers(), timeout=15)
                if r.ok and not is_cloudflare(r.text):
                    return True, r.text
            except Exception:
                pass
        if sync_playwright and url:
            pw_html, cookies = playwright_get_page(url)
            if pw_html and not is_cloudflare(pw_html):
                session = playwright_session_from_cookies(cookies, url)
                return True, pw_html
        print("      [WARN] Could not bypass Cloudflare")
        return True, html

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
        upgraded, html = maybe_upgrade_session(html, book_url)
        if upgraded:
            soup = BeautifulSoup(html, "html.parser")
            for sel in ["h1.book-name", "h1.name", ".book-title h1", "h1"]:
                el = soup.select_one(sel)
                if el:
                    n = el.get_text(strip=True)
                    if n and "moment" not in n.lower():
                        name = n
                        break
            for sel in [".author", ".book-author", "[class*='author']"]:
                el = soup.select_one(sel)
                if el:
                    author = el.get_text(strip=True)
                    break
        print(f"      ชื่อ: {name} | ผู้แต่ง: {author}")

        print(f"[2/3] ดึงรายชื่อตอน...")
        chapters = collect_chapters_all_pages(session, book_url, html)
        chapters.sort(key=lambda ch: int(re.findall(r"\d+", ch["url"].replace(extract_book_id(book_url), "", 1))[-1]) if re.findall(r"\d+", ch["url"].replace(extract_book_id(book_url), "", 1)) else 0)
        if not chapters:
            soup_dbg = BeautifulSoup(html, "html.parser")
            hrefs = [a["href"] for a in soup_dbg.find_all("a", href=True)]
            print(f"[DEBUG] html len={len(html)} links={len(hrefs)} sample={hrefs[:40]}")
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
