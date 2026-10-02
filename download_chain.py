"""
Download a whole novel by following the "next chapter" (下一章) link, starting
from any chapter URL. Works on sites such as tongrenxsw.com where the book
index page is hard to parse.

Usage:
    python download_chain.py https://www.tongrenxsw.com/chapter/A0EDDF.html
    python download_chain.py <url> --output downloads --delay 0.5

Progress is saved to <output>/<name>.progress.json after every chapter, so
re-running the same command resumes where it stopped.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from download_novel import extract_text_from_html, get_headers

NEXT_CHAPTER = ("下一章", "下一节", "下一篇", "下章", "下一话")
NEXT_PAGE = ("下一页", "下页")


def fetch(session, url, referer, retries=5):
    for attempt in range(retries):
        try:
            r = session.get(url, headers=get_headers(referer), timeout=25)
            if r.ok:
                r.encoding = r.apparent_encoding or "utf-8"
                return r.text
            if r.status_code == 404:
                return None
            print(f"\n[WARN] HTTP {r.status_code}: {url}")
        except requests.RequestException as e:
            print(f"\n[WARN] {e}")
        time.sleep(2 * (attempt + 1))
    return None


def find_link(soup, url, words):
    """Return absolute URL of the first <a> whose text contains one of words."""
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        if any(w in text for w in words):
            href = a["href"].strip()
            if href.startswith(("javascript", "#")):
                return None
            return urljoin(url, href)
    if words is NEXT_CHAPTER:
        a = soup.select_one("a#next, a#next_url, a.next, a[rel=next]")
        if a and a.get("href") and not a["href"].startswith(("javascript", "#")):
            return urljoin(url, a["href"])
    return None


def guess_next_by_pattern(soup, url, seen):
    """Fallback: pick the first not-yet-seen link shaped like the current URL."""
    path = urlparse(url).path
    shape = re.sub(r"[^/]+$", "", path)           # e.g. /chapter/
    ext = os.path.splitext(path)[1]               # e.g. .html
    for a in soup.find_all("a", href=True):
        full = urljoin(url, a["href"].strip())
        p = urlparse(full)
        if (p.netloc == urlparse(url).netloc and p.path.startswith(shape)
                and p.path.endswith(ext) and p.path != path and full not in seen):
            return full
    return None


def chapter_title(soup):
    for sel in ("h1", ".chapter-title", ".title", "h2"):
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    return soup.title.get_text(strip=True) if soup.title else "?"


def clean(text, title):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    lines = [l for l in lines if l != title]
    return "\n".join(lines)


def get_chapter(session, url, referer, delay):
    """Download one chapter (following real 下一页 links). Returns (title, text)."""
    html = fetch(session, url, referer)
    if html is None:
        return None, ""
    title = chapter_title(BeautifulSoup(html, "html.parser"))
    parts, seen_pages = [], {url}
    while True:
        parts.append(clean(extract_text_from_html(html), title))
        nxt = find_link(BeautifulSoup(html, "html.parser"), url, NEXT_PAGE)
        if not nxt or nxt in seen_pages:
            break
        seen_pages.add(nxt)
        time.sleep(delay)
        html = fetch(session, nxt, url)
        if html is None:
            break
        url = nxt
    return title, "\n".join(parts)


def run_numeric(args, book_id, base):
    """Book index page given: download /book/<id>-N.html for N = 1, 2, 3 ..."""
    from concurrent.futures import ThreadPoolExecutor
    os.makedirs(args.output, exist_ok=True)
    txt_path = os.path.join(args.output, f"book_{book_id}.txt")
    prog_path = os.path.join(args.output, f"book_{book_id}.progress.json")
    n = 1
    if os.path.exists(prog_path):
        n = json.load(open(prog_path))["next_n"]
        print(f"[RESUME] ต่อจากตอนที่ {n}")
    session = requests.Session()
    # A chapter number that surely does not exist: whatever the site returns for
    # it (404, redirect, book page...) is the "not found" fingerprint.
    ref_title, ref_text = get_chapter(session, f"{base}/book/{book_id}-99999.html", base, 0)
    batch, misses, total = 10, 0, 0
    with open(txt_path, "a" if n > 1 else "w", encoding="utf-8") as out:
        while n <= args.max and misses < 3:
            nums = list(range(n, n + batch))
            urls = [f"{base}/book/{book_id}-{i}.html" for i in nums]
            with ThreadPoolExecutor(max_workers=4) as ex:
                res = list(ex.map(lambda u: get_chapter(session, u, base, args.delay), urls))
            for i, (title, text) in zip(nums, res):
                fake = ref_title is not None and (title == ref_title or text == ref_text)
                if fake or len(text.replace(" ", "").replace("\n", "")) < 30:
                    misses += 1
                    if misses >= 3:
                        break
                    continue
                misses = 0
                total += 1
                out.write(f"{title}\n\n{text}\n\n" + "─" * 40 + "\n\n")
                print(f"\r[{i}] {title[:40]:<40}", end="", flush=True)
            out.flush()
            n += batch
            json.dump({"next_n": n}, open(prog_path, "w"))
    print(f"\n✅ จบ: {total} ตอน -> {txt_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="URL of the first chapter to download")
    ap.add_argument("--output", default="downloads")
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between requests")
    ap.add_argument("--max", type=int, default=100000, help="maximum chapters")
    args = ap.parse_args()

    m = re.match(r"(https?://[^/]+)/chapter/([A-Za-z0-9]+)\.html", args.url)
    if m:  # this is the book index page, not a chapter
        return run_numeric(args, m.group(2), m.group(1))

    os.makedirs(args.output, exist_ok=True)
    key = hashlib.md5(args.url.encode()).hexdigest()[:8]
    progress_path = os.path.join(args.output, f"chain_{key}.progress.json")
    txt_path = os.path.join(args.output, f"chain_{key}.txt")

    state = {"next": args.url, "count": 0, "seen": []}
    if os.path.exists(progress_path):
        state = json.load(open(progress_path, encoding="utf-8"))
        print(f"[RESUME] ต่อจากตอนที่ {state['count']} -> {state['next']}")
    seen = set(state["seen"])

    session = requests.Session()
    url, referer = state["next"], args.url
    mode = "a" if state["count"] else "w"

    with open(txt_path, mode, encoding="utf-8") as out:
        while url and state["count"] < args.max:
            if url in seen:
                break
            html = fetch(session, url, referer)
            if html is None:
                print(f"\n[ERROR] โหลดไม่ได้: {url} (รันใหม่เพื่อต่อจากตอนนี้)")
                break

            parts, page_url, page_html = [], url, html
            soup = BeautifulSoup(html, "html.parser")
            title = chapter_title(soup)
            # a chapter may be split into several pages (下一页)
            while True:
                seen.add(page_url)
                parts.append(clean(extract_text_from_html(page_html), title))
                nxt_page = find_link(BeautifulSoup(page_html, "html.parser"), page_url, NEXT_PAGE)
                if not nxt_page or nxt_page in seen:
                    break
                time.sleep(args.delay)
                page_html = fetch(session, nxt_page, page_url)
                if page_html is None:
                    break
                page_url = nxt_page

            out.write(f"{title}\n\n" + "\n".join(parts) + "\n\n" + "─" * 40 + "\n\n")
            out.flush()
            state["count"] += 1

            # next chapter link is read from the last page of this chapter
            last = BeautifulSoup(page_html or html, "html.parser")
            nxt = find_link(last, page_url, NEXT_CHAPTER)
            referer = page_url
            if not nxt:
                nxt = guess_next_by_pattern(last, page_url, seen)
            url = nxt if nxt and nxt not in seen else None
            if url is None:
                print("\n[DEBUG] ไม่พบลิงก์ตอนถัดไป ลิงก์ทั้งหมดในหน้านี้:")
                for a in last.find_all("a", href=True)[-25:]:
                    print(f"   {a.get_text(strip=True)[:30]!r} -> {a['href'][:90]}")
            state.update(next=url, seen=sorted(seen))
            json.dump(state, open(progress_path, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"\r[{state['count']}] {title[:40]:<40}", end="", flush=True)
            time.sleep(args.delay)

    print(f"\n✅ จบ: {state['count']} ตอน -> {txt_path}")


if __name__ == "__main__":
    sys.exit(main())
