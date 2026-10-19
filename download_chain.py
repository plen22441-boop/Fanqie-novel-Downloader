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


def fetch(session, url, referer, retries=5, notfound=None):
    for attempt in range(retries):
        try:
            r = session.get(url, headers=get_headers(referer), timeout=25)
            if r.ok:
                r.encoding = r.apparent_encoding or "utf-8"
                return r.text
            if r.status_code == 404:
                return notfound
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


NF = "__404__"


def get_chapter(session, url, referer, delay):
    """Download one chapter (following real 下一页 links).

    Returns (status, title, text); status is "ok", "nf" (404) or "err" (network).
    """
    html = fetch(session, url, referer, notfound=NF)
    if html == NF:
        return "nf", None, ""
    if html is None:
        return "err", None, ""
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
            return "err", title, ""
        url = nxt
    return "ok", title, "\n".join(parts)


def run_numeric(args, book_id, base):
    """Book index page given: download /book/<id>-N.html for N = 1, 2, 3 ...

    Every downloaded chapter is cached in a .jsonl file, so re-running the same
    command only fetches what is still missing.
    """
    from concurrent.futures import ThreadPoolExecutor
    os.makedirs(args.output, exist_ok=True)
    txt_path = os.path.join(args.output, f"book_{book_id}.txt")
    cache_path = os.path.join(args.output, f"book_{book_id}.cache.jsonl")

    chapters = {}
    if os.path.exists(cache_path):
        for line in open(cache_path, encoding="utf-8"):
            d = json.loads(line)
            chapters[d["n"]] = (d["title"], d["text"])
        print(f"[RESUME] มีในแคชแล้ว {len(chapters)} ตอน")

    session = requests.Session()
    # A chapter number that surely does not exist: whatever the site returns for
    # it (404, redirect, book page...) is the "not found" fingerprint.
    _, ref_title, ref_text = get_chapter(session, f"{base}/book/{book_id}-99999.html", base, 0)

    def url_of(i):
        return f"{base}/book/{book_id}-{i}.html"

    def is_end(status, title, text):
        fake = ref_title is not None and (title == ref_title or text == ref_text)
        return status == "nf" or fake or (
            status == "ok" and len(text.replace(" ", "").replace("\n", "")) < 30)

    cache = open(cache_path, "a", encoding="utf-8")

    def run_batch(nums, workers, delay):
        """Download nums; returns (failed_numbers, number_of_end_pages)."""
        todo = [i for i in nums if i not in chapters]
        failed, ends = [], 0
        if todo:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                res = list(ex.map(lambda i: get_chapter(session, url_of(i), base, delay), todo))
            for i, (status, title, text) in zip(todo, res):
                if status == "err":
                    failed.append(i)
                elif is_end(status, title, text):
                    ends += 1
                else:
                    chapters[i] = (title, text)
                    cache.write(json.dumps({"n": i, "title": title, "text": text},
                                           ensure_ascii=False) + "\n")
                    print(f"\r[{i}] {title[:40]:<40}", end="", flush=True)
            cache.flush()
        return failed, ends

    n, failed_all, batch = 1, [], 10
    while n <= args.max:
        nums = list(range(n, n + batch))
        failed, _ = run_batch(nums, 3, args.delay)
        failed_all += failed
        n += batch
        # stop once a whole batch is past the last chapter
        if not any(i in chapters for i in nums) and not failed:
            break

    # retry network failures slowly, a few rounds
    for rnd in range(1, 6):
        failed_all = [i for i in failed_all if i not in chapters]
        if not failed_all:
            break
        print(f"\n[RETRY {rnd}] ตอนที่ยังขาด {len(failed_all)} ตอน รอ {5 * rnd} วินาที...")
        time.sleep(5 * rnd)
        failed_all, _ = run_batch(failed_all, 1, max(args.delay, 2))
    cache.close()

    nums = sorted(chapters)
    with open(txt_path, "w", encoding="utf-8") as out:
        for i in nums:
            title, text = chapters[i]
            out.write(f"{title}\n\n{text}\n\n" + "─" * 40 + "\n\n")
    missing = [i for i in range(1, (nums[-1] if nums else 0) + 1) if i not in chapters]
    print(f"\n✅ จบ: {len(nums)} ตอน -> {txt_path}")
    if missing:
        print(f"⚠️ ยังขาด {len(missing)} ตอน: {missing[:50]}  (รันคำสั่งเดิมอีกครั้งเพื่อโหลดตอนที่ขาด)")


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
