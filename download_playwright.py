"""
Playwright-based novel downloader — works on ANY Chinese novel site including JS-heavy ones.
Usage: python download_playwright.py <url> [--workers 5] [--output dir]
"""

import sys
import re
import os
import time
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

SEPARATOR = "─" * 40

CONTENT_SELECTORS = [
    "#chaptercontent", "#BookText", "#content", "#booktxt", "#htmlContent",
    ".chapter-content", ".read-content", ".novel-content", ".chapter-txt",
    ".readcontent", ".duanzhang", ".box_con #content", "article .content",
    "#nr1", "#nr2", ".neirong", ".zuopin_content", "#novelcontent",
    "#chapterBody", ".chaptercontent", "#reader-content", ".text-content",
    ".content", "#articleContent", ".article-content",
]


def clean_text(t):
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def extract_content_from_page(page):
    for sel in CONTENT_SELECTORS:
        try:
            el = page.query_selector(sel)
            if el:
                t = el.inner_text()
                if len(t.replace(" ", "").replace("\n", "")) > 80:
                    return clean_text(t)
        except Exception:
            pass

    # Fallback: find div with most <p> children
    try:
        result = page.evaluate("""() => {
            const divs = document.querySelectorAll('div');
            let best = null, bestLen = 0;
            divs.forEach(d => {
                const ps = d.querySelectorAll('p');
                const txt = Array.from(ps).map(p => p.innerText.trim()).filter(t => t.length > 15).join('\\n');
                if (txt.length > bestLen) { bestLen = txt.length; best = txt; }
            });
            return best || '';
        }""")
        if result and len(result.replace(" ", "")) > 80:
            return clean_text(result)
    except Exception:
        pass

    return ""


def get_chapter_title(page, idx):
    for sel in ["h1", "h2", ".chapter-title", ".chTitle", ".readerTitle", ".title"]:
        try:
            el = page.query_selector(sel)
            if el:
                t = el.inner_text().strip()
                if t and len(t) < 100:
                    return t
        except Exception:
            pass
    return f"第{idx}章"


def find_chapter_links(page, book_url):
    """Auto-detect chapter links from the current page."""
    parsed = urlparse(book_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    # Extract all links
    links = page.evaluate("""() =>
        Array.from(document.querySelectorAll('a[href]')).map(a => ({
            href: a.href,
            text: a.innerText.trim()
        }))
    """)

    # Try to find the book ID from URL
    url_path = parsed.path
    # Extract alphanumeric ID from URL
    book_id_match = re.search(r"/([A-Za-z0-9]{4,})[/\-.]", url_path)
    book_id = book_id_match.group(1) if book_id_match else ""

    # Filter chapter-like links
    seen = {}
    chapters = []

    for link in links:
        href = link["href"]
        text = link["text"]
        if not href or href == book_url:
            continue
        if not href.startswith("http"):
            href = urljoin(base, href)
        if urlparse(href).netloc != parsed.netloc:
            continue

        # Score: more likely to be chapter if book_id in URL, text looks like chapter
        is_chapter = False
        if book_id and book_id in href:
            is_chapter = True
        if re.search(r"(chapter|chap|read|txt|novel)[\-/]\d", href, re.I):
            is_chapter = True
        if re.search(r"/\d{6,}", href):
            is_chapter = True

        if is_chapter and href not in seen:
            seen[href] = True
            chapters.append({"url": href, "title": text or href})

    # Sort by trailing number in URL
    def url_num(ch):
        nums = re.findall(r"\d+", ch["url"])
        return int(nums[-1]) if nums else 0

    chapters.sort(key=url_num)
    return chapters


def find_next_page_url(page):
    """Check if this chapter has a next-page link (split chapters)."""
    try:
        result = page.evaluate("""() => {
            const links = Array.from(document.querySelectorAll('a'));
            const nxt = links.find(a => /下一页|下页|next.?page/i.test(a.innerText));
            return nxt ? nxt.href : null;
        }""")
        return result
    except Exception:
        return None


def download_chapter_pw(browser_context, chapter, idx, max_retries=3):
    for attempt in range(max_retries):
        page = None
        try:
            page = browser_context.new_page()
            page.goto(chapter["url"], wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(800)

            title = get_chapter_title(page, idx)
            content = extract_content_from_page(page)

            # Handle paginated chapters
            visited = {chapter["url"]}
            while True:
                nxt = find_next_page_url(page)
                if not nxt or nxt in visited:
                    break
                # Make sure next page is NOT the next chapter
                current_nums = re.findall(r"\d+", chapter["url"])
                next_nums = re.findall(r"\d+", nxt)
                if current_nums and next_nums and next_nums[-1] != current_nums[-1]:
                    # Different last number = different chapter, stop
                    # Unless it's a sub-page (has one extra number segment)
                    if len(next_nums) <= len(current_nums):
                        break
                visited.add(nxt)
                page.goto(nxt, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(500)
                extra = extract_content_from_page(page)
                if extra:
                    content += "\n" + extra

            page.close()
            return idx, title, content

        except Exception as e:
            if page:
                try:
                    page.close()
                except Exception:
                    pass
            time.sleep(1.5 * (attempt + 1))

    return idx, chapter.get("title", f"第{idx}章"), ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="URL นิยาย")
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--output", default="downloads")
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            locale="zh-CN",
        )

        # Step 1: Get book info and chapter list
        print(f"[1/3] เปิดหน้าหนังสือ...")
        page = context.new_page()
        page.goto(args.url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)

        # Book title
        name = "未知书名"
        for sel in ["h1.book-name", "h1.name", ".book-title h1", "h1", "title"]:
            try:
                el = page.query_selector(sel)
                if el:
                    t = el.inner_text().strip()
                    if t and len(t) < 80:
                        name = t
                        break
            except Exception:
                pass

        # Author
        author = "未知作者"
        for sel in [".author", ".book-author", "[class*='author']"]:
            try:
                el = page.query_selector(sel)
                if el:
                    author = el.inner_text().strip()
                    break
            except Exception:
                pass

        print(f"      ชื่อ: {name} | ผู้แต่ง: {author}")

        # Step 2: Find chapter links
        print(f"[2/3] ค้นหารายชื่อตอน...")
        chapters = find_chapter_links(page, args.url)

        # If no chapters found on this page, check if there's a TOC link
        if len(chapters) < 5:
            toc_link = page.evaluate("""() => {
                const a = Array.from(document.querySelectorAll('a'));
                const toc = a.find(x => /目录|章节列表|全部章节|chapter.?list/i.test(x.innerText));
                return toc ? toc.href : null;
            }""")
            if toc_link:
                print(f"      ไปที่หน้า TOC: {toc_link}")
                page.goto(toc_link, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(2000)
                chapters = find_chapter_links(page, args.url)

        # Check for paginated TOC
        if chapters:
            all_chapters = list(chapters)
            toc_page = 2
            while True:
                next_toc = page.evaluate("""() => {
                    const a = Array.from(document.querySelectorAll('a'));
                    const nxt = a.find(x => /下一页|下页/.test(x.innerText));
                    return nxt ? nxt.href : null;
                }""")
                if not next_toc:
                    break
                print(f"      TOC หน้า {toc_page}...")
                page.goto(next_toc, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(1000)
                more = find_chapter_links(page, args.url)
                new_chapters = [c for c in more if c["url"] not in {x["url"] for x in all_chapters}]
                if not new_chapters:
                    break
                all_chapters.extend(new_chapters)
                toc_page += 1

            chapters = all_chapters

        page.close()

        for i, ch in enumerate(chapters):
            ch["index"] = i

        print(f"      พบ {len(chapters)} ตอน")
        if not chapters:
            print("[ERROR] ไม่พบตอนใดๆ")
            browser.close()
            sys.exit(1)

        # Step 3: Download chapters in parallel
        # Pre-create context pool in main thread (Playwright sync API is not thread-safe)
        print(f"[3/3] โหลดเนื้อหา ({args.workers} workers)...")
        import queue as _queue
        ctx_pool = _queue.Queue()
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        for _ in range(args.workers):
            ctx_pool.put(browser.new_context(user_agent=ua, locale="zh-CN"))

        results = [None] * len(chapters)
        failed = []

        def dl(ch):
            ctx = ctx_pool.get()
            try:
                res = download_chapter_pw(ctx, ch, ch["index"])
            finally:
                ctx_pool.put(ctx)
            return res

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(dl, ch): ch for ch in chapters}
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

        # Close all contexts then browser
        while not ctx_pool.empty():
            try:
                ctx_pool.get_nowait().close()
            except Exception:
                pass
        browser.close()

    # Save
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", name)
    url_slug = re.sub(r"[^\w]", "_", urlparse(args.url).path.strip("/"))[-40:]
    out_path = os.path.join(args.output, f"{safe_name}_{url_slug}.txt")

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
        print(f"\n⚠️  ตอนที่โหลดไม่ได้ ({len(failed)}):")
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
