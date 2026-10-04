import re
import sys
import time
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def wait_cf(page):
    for _ in range(30):
        if "Just a moment" not in page.title():
            return
        time.sleep(0.5)


def main(url):
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(user_agent=UA, locale="zh-CN")
        page = ctx.new_page()
        reqs = []
        page.on("request", lambda r: reqs.append((r.method, r.resource_type, r.url)))
        page.goto(url, wait_until="domcontentloaded")
        wait_cf(page)
        time.sleep(4)
        html = page.content()
        print("TITLE:", page.title())
        print("HTML LEN:", len(html))
        print("--- XHR/fetch requests ---")
        for m, t, u in reqs:
            if t in ("xhr", "fetch") or (m != "GET"):
                print(m, t, u)
        links = page.eval_on_selector_all(
            "a[href]", "els => els.map(e => [e.innerText.trim(), e.getAttribute('href')])")
        print("--- links:", len(links))
        for t, h in links[:25]:
            print(repr(t[:40]), h)
        print("--- link hrefs shape sample (distinct patterns) ---")
        pats = {}
        for t, h in links:
            k = re.sub(r"\d+", "N", h)
            pats.setdefault(k, []).append(t[:20])
        for k, v in sorted(pats.items(), key=lambda x: -len(x[1]))[:15]:
            print(len(v), k, v[:2])
        print("--- elements mentioning 目录/章节 ---")
        for m in re.finditer(r'<(a|button|div|span)[^>]*>[^<]{0,20}(目录|章节|目錄|全部)[^<]{0,20}<', html):
            print(m.group(0)[:200])
        cands = [urljoin(url, h) for t, h in links
                 if re.search(r"/read/\d+/(p\d+|\d+)\.html", h)]
        print("--- chapter-like links:", len(cands), cands[:3])
        if cands:
            page.goto(cands[0], wait_until="domcontentloaded")
            wait_cf(page)
            time.sleep(2)
            ch = page.content()
            print("CHAPTER URL:", cands[0], "HTML LEN:", len(ch), "TITLE:", page.title())
            for sel in ["article", "#content", ".content", "section", "main", ".page-content"]:
                try:
                    txt = page.eval_on_selector(sel, "e => e.innerText")
                    print("SEL", sel, "textlen", len(txt))
                except Exception:
                    pass
        b.close()


if __name__ == "__main__":
    main(sys.argv[1])
