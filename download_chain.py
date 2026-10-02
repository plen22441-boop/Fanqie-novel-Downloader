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
from urllib.parse import urljoin

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="URL of the first chapter to download")
    ap.add_argument("--output", default="downloads")
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between requests")
    ap.add_argument("--max", type=int, default=100000, help="maximum chapters")
    args = ap.parse_args()

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
            url = nxt if nxt and nxt not in seen else None
            state.update(next=url, seen=sorted(seen))
            json.dump(state, open(progress_path, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"\r[{state['count']}] {title[:40]:<40}", end="", flush=True)
            time.sleep(args.delay)

    print(f"\n✅ จบ: {state['count']} ตอน -> {txt_path}")


if __name__ == "__main__":
    sys.exit(main())
