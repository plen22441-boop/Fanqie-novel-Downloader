#!/usr/bin/env python3
"""Scrape a novel from ixdzs8.com and save as .txt"""

import re
import time
import sys
import requests
from bs4 import BeautifulSoup
from pathlib import Path

BOOK_URL = "https://ixdzs8.com/read/609163/"
OUTPUT   = "七零大院_冷面糙汉宠妻成瘾.txt"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://ixdzs8.com/",
}

DELAY = 1.2  # seconds between requests


def get_chapters(book_url: str) -> list[tuple[str, str]]:
    """Return [(title, url), ...] from the book's main page."""
    r = requests.get(book_url, headers=HEADERS, timeout=15)
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")

    # Try common selectors
    links = (
        soup.select(".clist a") or
        soup.select(".chapter-list a") or
        soup.select(".mulu a") or
        soup.select("ul.list a")
    )

    chapters = []
    base = "https://ixdzs8.com"
    for a in links:
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if href and title:
            url = href if href.startswith("http") else base + href
            chapters.append((title, url))

    return chapters


def guess_chapters(book_url: str, max_ch: int = 600) -> list[tuple[str, str]]:
    """Fallback: probe pN.html until 404/empty."""
    base = book_url.rstrip("/")
    chapters = []
    for n in range(1, max_ch + 1):
        url = f"{base}/p{n}.html"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 404:
                print(f"  → stopped at p{n} (404)", flush=True)
                break
            r.encoding = "utf-8"
            soup = BeautifulSoup(r.text, "html.parser")
            title_el = soup.select_one("h1, .chapter-title, .title")
            title = title_el.get_text(strip=True) if title_el else f"第{n}章"
            chapters.append((title, url))
            print(f"  found p{n}: {title}", flush=True)
            time.sleep(DELAY)
        except Exception as e:
            print(f"  error at p{n}: {e}", flush=True)
            break
    return chapters


def scrape_content(url: str) -> str:
    """Return cleaned chapter text from a chapter URL."""
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")

    content_el = (
        soup.select_one("#page") or
        soup.select_one(".read-content") or
        soup.select_one(".content") or
        soup.select_one("article")
    )
    if not content_el:
        return ""

    # Remove known junk tags
    for tag in content_el.select("script, style, .ad, .advert, ins"):
        tag.decompose()

    lines = []
    for el in content_el.find_all(["p", "br"]):
        text = el.get_text(" ", strip=True)
        if text:
            lines.append(text)

    if not lines:
        lines = [ln.strip() for ln in content_el.get_text("\n").splitlines() if ln.strip()]

    # Strip site watermarks
    clean = []
    skip_pat = re.compile(
        r"(ixdzs8|请记住本书首发域名|www\.|m\.ixdzs8|本章未完|点击下一页)", re.I
    )
    for ln in lines:
        if not skip_pat.search(ln):
            clean.append(ln)

    return "\n".join(clean)


def main():
    print(f"Fetching chapter list from {BOOK_URL} …")
    chapters = get_chapters(BOOK_URL)

    if not chapters:
        print("Chapter list not found in HTML (JS-rendered). Probing p1, p2, … instead.")
        chapters = guess_chapters(BOOK_URL)

    if not chapters:
        print("ERROR: could not find any chapters. Exiting.")
        sys.exit(1)

    print(f"Found {len(chapters)} chapters. Downloading …\n")

    out = Path(OUTPUT)
    with out.open("w", encoding="utf-8") as f:
        for i, (title, url) in enumerate(chapters, 1):
            print(f"[{i}/{len(chapters)}] {title}", flush=True)
            content = scrape_content(url)
            f.write(f"\n\n第{i}章　{title}\n\n{content}\n")
            time.sleep(DELAY)

    print(f"\nDone! Saved to: {out.resolve()}")


if __name__ == "__main__":
    main()
