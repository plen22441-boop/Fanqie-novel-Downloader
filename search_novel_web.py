#!/usr/bin/env python3
"""
Chinese Novel Search Server / CLI
เซิร์ฟเวอร์ค้นหานิยายจีน — ค้นหาจากหลายเว็บไซต์พร้อมกัน ส่งลิงก์ตรงกลับมา

Usage:
  CLI:    python search_novel_web.py "斗破苍穹"
  Server: python search_novel_web.py --server [--port 8080]
          Then open http://localhost:8080
"""

import argparse
import http.server
import json
import os
import random
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from bs4 import BeautifulSoup

TIMEOUT = 12
MAX_RESULTS_PER_SITE = 8

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
    "Gecko/20100101 Firefox/128.0",
]


def _headers(referer=None):
    h = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }
    if referer:
        h["Referer"] = referer
    return h


def _get(url, params=None, encoding=None, referer=None):
    resp = requests.get(
        url, params=params, headers=_headers(referer),
        timeout=TIMEOUT, allow_redirects=True,
    )
    if encoding:
        resp.encoding = encoding
    elif resp.apparent_encoding:
        resp.encoding = resp.apparent_encoding
    return resp


def _soup(resp):
    return BeautifulSoup(resp.text, "lxml")


# ---------------------------------------------------------------------------
# Site-specific search implementations
# ---------------------------------------------------------------------------

def search_69shuba(query):
    """69书吧 — popular aggregator, no VPN needed."""
    try:
        url = "https://www.69shuba.cx/modules/article/search.php"
        encoded = query.encode("gbk", errors="ignore")
        params = {"searchkey": encoded, "searchtype": "articlename"}
        resp = requests.get(
            url, params=params, headers=_headers("https://www.69shuba.cx/"),
            timeout=TIMEOUT, allow_redirects=True,
        )
        resp.encoding = "gbk"
        soup = _soup(resp)
        results = []

        if "/book/" in resp.url:
            title_el = soup.select_one("h1") or soup.select_one(".bread a:last-child")
            title = title_el.get_text(strip=True) if title_el else query
            author_el = soup.select_one(".booknav2 p a") or soup.select_one(".bookinfo a")
            author = author_el.get_text(strip=True) if author_el else ""
            desc_el = soup.select_one(".navtxt p") or soup.select_one("#bookintro")
            desc = desc_el.get_text(strip=True)[:200] if desc_el else ""
            results.append({
                "title": title, "author": author, "url": resp.url,
                "description": desc, "source": "69书吧",
                "source_domain": "69shuba.cx", "free": True, "vpn": False,
            })
            return results

        rows = soup.select(".newbox ul li") or soup.select(".novelslist2 li") or soup.select("table tr")
        for row in rows[:MAX_RESULTS_PER_SITE]:
            a = row.select_one("a[href*='/book/']") or row.select_one("a")
            if not a or not a.get("href"):
                continue
            href = a["href"]
            if not href.startswith("http"):
                href = urllib.parse.urljoin("https://www.69shuba.cx/", href)
            title = a.get_text(strip=True)
            if not title:
                continue
            author_el = row.select_one("a:nth-of-type(2)") or row.select_one(".s4 a")
            author = author_el.get_text(strip=True) if author_el else ""
            results.append({
                "title": title, "author": author, "url": href,
                "description": "", "source": "69书吧",
                "source_domain": "69shuba.cx", "free": True, "vpn": False,
            })
        return results
    except Exception as e:
        return [{"error": str(e), "source": "69书吧"}]


def search_biquge(query):
    """笔趣阁 mirror — no VPN needed."""
    sites = [
        ("https://www.biqu-ge.com", "笔趣阁", "biqu-ge.com"),
        ("https://www.xbiquge.so", "新笔趣阁", "xbiquge.so"),
    ]
    results = []
    for base, name, domain in sites:
        try:
            search_url = f"{base}/search.php"
            resp = _get(search_url, params={"keyword": query}, referer=base)
            soup = _soup(resp)

            if "/book/" in resp.url or "/novel/" in resp.url:
                title_el = soup.select_one("h1") or soup.select_one("#info h1")
                title = title_el.get_text(strip=True) if title_el else query
                author_el = soup.select_one("#info p") or soup.select_one(".book_info a")
                author = ""
                if author_el:
                    t = author_el.get_text(strip=True)
                    m = re.search(r"[：:]\s*(.+)", t)
                    author = m.group(1) if m else t
                results.append({
                    "title": title, "author": author, "url": resp.url,
                    "description": "", "source": name,
                    "source_domain": domain, "free": True, "vpn": False,
                })
                continue

            rows = (soup.select(".result-list .result-item") or
                    soup.select(".novelslist2 li") or
                    soup.select("#hotcontent .item") or
                    soup.select("table tr"))
            for row in rows[:MAX_RESULTS_PER_SITE]:
                a = row.select_one("a[href*='/book/']") or row.select_one("a[href*='/novel/']") or row.select_one("a")
                if not a or not a.get("href"):
                    continue
                href = a["href"]
                if not href.startswith("http"):
                    href = urllib.parse.urljoin(base, href)
                title = a.get_text(strip=True)
                if not title or len(title) < 2:
                    continue
                results.append({
                    "title": title, "author": "", "url": href,
                    "description": "", "source": name,
                    "source_domain": domain, "free": True, "vpn": False,
                })
        except Exception:
            continue
    return results


def search_piaotia(query):
    """飘天文学 — no VPN needed."""
    try:
        url = "https://www.piaotia.com/modules/article/search.php"
        encoded = query.encode("gbk", errors="ignore")
        resp = requests.get(
            url, params={"searchkey": encoded, "searchtype": "articlename"},
            headers=_headers("https://www.piaotia.com/"),
            timeout=TIMEOUT, allow_redirects=True,
        )
        resp.encoding = "gbk"
        soup = _soup(resp)
        results = []

        if "/bookinfo/" in resp.url or "/html/" in resp.url:
            title_el = soup.select_one("h1")
            title = title_el.get_text(strip=True) if title_el else query
            results.append({
                "title": title, "author": "", "url": resp.url,
                "description": "", "source": "飘天文学",
                "source_domain": "piaotia.com", "free": True, "vpn": False,
            })
            return results

        rows = soup.select("table tr") or soup.select(".novelslist2 li")
        for row in rows[:MAX_RESULTS_PER_SITE]:
            a = row.select_one("a[href*='/bookinfo/']") or row.select_one("a[href*='/html/']") or row.select_one("a")
            if not a or not a.get("href"):
                continue
            href = a["href"]
            if not href.startswith("http"):
                href = urllib.parse.urljoin("https://www.piaotia.com/", href)
            title = a.get_text(strip=True)
            if not title or len(title) < 2:
                continue
            results.append({
                "title": title, "author": "", "url": href,
                "description": "", "source": "飘天文学",
                "source_domain": "piaotia.com", "free": True, "vpn": False,
            })
        return results
    except Exception as e:
        return [{"error": str(e), "source": "飘天文学"}]


def search_uukanshu(query):
    """UU看书 — no VPN needed."""
    try:
        url = "https://www.uukanshu.cc/search.html"
        resp = _get(url, params={"keyword": query}, referer="https://www.uukanshu.cc/")
        soup = _soup(resp)
        results = []

        rows = (soup.select(".search-result-list li") or
                soup.select(".result-list li") or
                soup.select(".novelslist2 li") or
                soup.select("table tr"))
        for row in rows[:MAX_RESULTS_PER_SITE]:
            a = row.select_one("a[href*='/book/']") or row.select_one("a[href*='/b/']") or row.select_one("a")
            if not a or not a.get("href"):
                continue
            href = a["href"]
            if not href.startswith("http"):
                href = urllib.parse.urljoin("https://www.uukanshu.cc/", href)
            title = a.get_text(strip=True)
            if not title or len(title) < 2:
                continue
            results.append({
                "title": title, "author": "", "url": href,
                "description": "", "source": "UU看书",
                "source_domain": "uukanshu.cc", "free": True, "vpn": False,
            })
        return results
    except Exception as e:
        return [{"error": str(e), "source": "UU看书"}]


def search_fanqie(query):
    """番茄小说 — official free platform (VPN to China needed)."""
    try:
        url = "https://fanqienovel.com/api/author/search/search_book/v1"
        params = {"filter": "127,127,127,127", "page_count": "0",
                  "page_index": "0", "query_type": "0",
                  "query_word": query}
        resp = requests.get(url, params=params, headers={
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json",
        }, timeout=TIMEOUT)
        data = resp.json()
        results = []
        books = data.get("data", {}).get("search_book_data_list") or []
        for book in books[:MAX_RESULTS_PER_SITE]:
            bid = book.get("book_id", "")
            results.append({
                "title": book.get("book_name", ""),
                "author": book.get("author", ""),
                "url": f"https://fanqienovel.com/page/{bid}",
                "description": book.get("abstract", "")[:200],
                "source": "番茄小说",
                "source_domain": "fanqienovel.com",
                "free": True, "vpn": True,
                "status": "完结" if book.get("creation_status") == 1 else "连载",
                "word_count": book.get("word_number", 0),
            })
        return results
    except Exception as e:
        return [{"error": str(e), "source": "番茄小说"}]


def search_webnovel(query):
    """WebNovel — Qidian International, English translations."""
    try:
        url = "https://www.webnovel.com/go/pcm/search/result"
        params = {"searchKey": query, "type": "1", "pageIndex": "1"}
        resp = requests.get(url, params=params, headers={
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json",
        }, timeout=TIMEOUT)
        data = resp.json()
        results = []
        books = data.get("data", {}).get("bookInfo", {}).get("bookItems") or []
        for book in books[:MAX_RESULTS_PER_SITE]:
            bid = book.get("bookId", "")
            slug = book.get("bookName", "").replace(" ", "-").lower()
            results.append({
                "title": book.get("bookName", ""),
                "author": book.get("authorName", ""),
                "url": f"https://www.webnovel.com/book/{bid}",
                "description": book.get("description", "")[:200],
                "source": "WebNovel",
                "source_domain": "webnovel.com",
                "free": False, "vpn": False,
                "category": book.get("categoryName", ""),
            })
        return results
    except Exception as e:
        return [{"error": str(e), "source": "WebNovel"}]


def search_novelupdates(query):
    """NovelUpdates — English translation database."""
    try:
        url = "https://www.novelupdates.com/"
        resp = _get(url, params={"s": query, "post_type": "seriesplans"})
        soup = _soup(resp)
        results = []
        rows = soup.select(".search_main_box_nu") or soup.select(".search_body_nu .w-blog-entry")
        for row in rows[:MAX_RESULTS_PER_SITE]:
            a = row.select_one("a.search_title") or row.select_one(".search_title a") or row.select_one("a")
            if not a or not a.get("href"):
                continue
            href = a["href"]
            title = a.get_text(strip=True)
            if not title:
                continue
            desc_el = row.select_one(".search_body_nu_desc") or row.select_one("p")
            desc = desc_el.get_text(strip=True)[:200] if desc_el else ""
            results.append({
                "title": title, "author": "", "url": href,
                "description": desc, "source": "NovelUpdates",
                "source_domain": "novelupdates.com", "free": True, "vpn": False,
            })
        return results
    except Exception as e:
        return [{"error": str(e), "source": "NovelUpdates"}]


def search_ddg_site(query, site_domain, source_name):
    """DuckDuckGo site-scoped search as a fallback."""
    try:
        ddg_url = "https://html.duckduckgo.com/html/"
        params = {"q": f'"{query}" site:{site_domain}'}
        resp = requests.post(ddg_url, data=params, headers={
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html",
        }, timeout=TIMEOUT)
        soup = BeautifulSoup(resp.text, "lxml")
        results = []
        for r in soup.select(".result"):
            a = r.select_one(".result__a")
            if not a or not a.get("href"):
                continue
            href = a["href"]
            m = re.search(r"uddg=([^&]+)", href)
            if m:
                href = urllib.parse.unquote(m.group(1))
            title = a.get_text(strip=True)
            snippet_el = r.select_one(".result__snippet")
            snippet = snippet_el.get_text(strip=True)[:200] if snippet_el else ""
            if site_domain not in href:
                continue
            results.append({
                "title": title, "author": "", "url": href,
                "description": snippet, "source": source_name,
                "source_domain": site_domain, "free": True, "vpn": False,
            })
        return results[:MAX_RESULTS_PER_SITE]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

ALL_SEARCHERS = [
    ("69书吧 (ไม่ต้อง VPN)", search_69shuba),
    ("笔趣阁 (ไม่ต้อง VPN)", search_biquge),
    ("飘天文学 (ไม่ต้อง VPN)", search_piaotia),
    ("UU看书 (ไม่ต้อง VPN)", search_uukanshu),
    ("番茄小说 (ต้อง VPN)", search_fanqie),
    ("WebNovel (English)", search_webnovel),
    ("NovelUpdates (English)", search_novelupdates),
]


def search_all(query):
    all_results = []
    errors = []

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {}
        for label, fn in ALL_SEARCHERS:
            futures[pool.submit(fn, query)] = label

        for fut in as_completed(futures):
            label = futures[fut]
            try:
                items = fut.result()
                for item in items:
                    if "error" in item and "url" not in item:
                        errors.append({"source": label, "error": item["error"]})
                    else:
                        all_results.append(item)
            except Exception as e:
                errors.append({"source": label, "error": str(e)})

    if len(all_results) < 3:
        ddg_targets = [
            ("69shuba.cx", "69书吧 (DDG)"),
            ("shuquge.com", "书趣阁 (DDG)"),
            ("quanben.io", "全本小说 (DDG)"),
        ]
        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = {}
            for domain, name in ddg_targets:
                already = any(r.get("source_domain") == domain for r in all_results)
                if not already:
                    futs[pool.submit(search_ddg_site, query, domain, name)] = name
            for fut in as_completed(futs):
                try:
                    all_results.extend(fut.result())
                except Exception:
                    pass

    seen = set()
    unique = []
    for r in all_results:
        key = (r.get("title", "").strip(), r.get("source_domain", ""))
        if key not in seen:
            seen.add(key)
            unique.append(r)

    return {
        "query": query,
        "total": len(unique),
        "results": unique,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# HTTP Server
# ---------------------------------------------------------------------------

class SearchAPIHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=directory or str(Path(__file__).parent), **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/search":
            self._handle_search(parsed)
        elif parsed.path == "/api/ping":
            self._send_json({"status": "ok", "version": "1.0"})
        elif parsed.path == "/":
            self.path = "/novel-search.html"
            super().do_GET()
        else:
            super().do_GET()

    def _handle_search(self, parsed):
        params = urllib.parse.parse_qs(parsed.query)
        q = params.get("q", [""])[0].strip()
        if not q:
            self._send_json({"error": "Missing query parameter 'q'"}, 400)
            return
        data = search_all(q)
        self._send_json(data)

    def _send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)


def start_server(port=8080):
    server = http.server.HTTPServer(("127.0.0.1", port), SearchAPIHandler)
    print(f"Novel Search Server running at http://localhost:{port}")
    print(f"Open http://localhost:{port} in your browser")
    print("Press Ctrl+C to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.server_close()


# ---------------------------------------------------------------------------
# CLI mode
# ---------------------------------------------------------------------------

def cli_search(query):
    print(f"\nSearching for: {query}")
    print("=" * 50)
    data = search_all(query)

    if not data["results"]:
        print("No results found.")
        if data["errors"]:
            print("\nErrors:")
            for e in data["errors"]:
                print(f"  {e['source']}: {e['error']}")
        return

    no_vpn = [r for r in data["results"] if not r.get("vpn")]
    vpn = [r for r in data["results"] if r.get("vpn")]

    if no_vpn:
        print(f"\n--- Free & No VPN ({len(no_vpn)} results) ---\n")
        for i, r in enumerate(no_vpn, 1):
            title = r.get("title", "?")
            author = f" — {r['author']}" if r.get("author") else ""
            src = r.get("source", "")
            url = r.get("url", "")
            tags = []
            if r.get("free"):
                tags.append("FREE")
            if r.get("status"):
                tags.append(r["status"])
            tag_str = f"  [{', '.join(tags)}]" if tags else ""
            print(f"  {i}. {title}{author}")
            print(f"     {src}{tag_str}")
            print(f"     {url}\n")

    if vpn:
        print(f"\n--- Needs VPN ({len(vpn)} results) ---\n")
        for i, r in enumerate(vpn, 1):
            title = r.get("title", "?")
            author = f" — {r['author']}" if r.get("author") else ""
            src = r.get("source", "")
            url = r.get("url", "")
            print(f"  {i}. {title}{author}")
            print(f"     {src}  [VPN]")
            print(f"     {url}\n")

    if data["errors"]:
        print(f"--- {len(data['errors'])} sources had errors ---")
        for e in data["errors"]:
            print(f"  {e['source']}: {e['error']}")

    print(f"\nTotal: {data['total']} results from {len(set(r['source'] for r in data['results']))} sources")


def main():
    parser = argparse.ArgumentParser(description="Chinese Novel Search")
    parser.add_argument("query", nargs="?", help="Novel name to search")
    parser.add_argument("--server", action="store_true", help="Start web server")
    parser.add_argument("--port", type=int, default=8080, help="Server port (default: 8080)")
    args = parser.parse_args()

    if args.server:
        start_server(args.port)
    elif args.query:
        cli_search(args.query)
    else:
        parser.print_help()
        print("\nExamples:")
        print('  python search_novel_web.py "斗破苍穹"')
        print("  python search_novel_web.py --server --port 8080")


if __name__ == "__main__":
    main()
