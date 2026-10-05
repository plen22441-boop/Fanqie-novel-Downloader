import json
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
MARKERS = ("Just a moment", "Checking", "正在验证浏览器", "Verify Yourself", "身份验证", "Attention Required")
CAPTCHA = re.compile(r"captcha|verify yourself|身份验证|人机验证|cf-turnstile|geetest|WAF", re.I)
BLOCK_JS = """() => {
  const out = [];
  for (const el of document.querySelectorAll('div,article,section,main,td')) {
    const n = el.innerText ? el.innerText.length : 0;
    if (n < 300) continue;
    let big = false;
    for (const c of el.children) { if (c.innerText && c.innerText.length > n * 0.9) { big = true; break; } }
    if (!big) out.push([el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
      (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\\s+/).join('.') : ''), n]);
  }
  return out.sort((a, b) => b[1] - a[1]).slice(0, 5);
}"""


def wait_pass(page, secs=40):
    for _ in range(secs * 2):
        if not any(m in page.title() for m in MARKERS):
            return True
        time.sleep(0.5)
    return False


def shape(h):
    return re.sub(r"[0-9a-f]{5,}|\d+", "N", h)


def classify(links, base):
    pats = {}
    for t, h in links:
        if not h or h.startswith(("javascript", "#", "mailto")):
            continue
        k = shape(urlparse(urljoin(base, h)).path + ("?" + urlparse(urljoin(base, h)).query if urlparse(urljoin(base, h)).query else ""))
        pats.setdefault(k, []).append((t[:24], h))
    for k, v in sorted(pats.items(), key=lambda x: -len(x[1]))[:14]:
        print(f"   {len(v):4d}  {k}   e.g. {v[0]}  {v[-1]}")
    return pats


def req_view(url):
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}, timeout=25)
        soup = BeautifulSoup(r.text, "html.parser")
        print(f"[requests] HTTP {r.status_code} len={len(r.text)} title={soup.title.string.strip() if soup.title and soup.title.string else None}"
              f" captcha={bool(CAPTCHA.search(r.text[:6000]))} links={len(soup.find_all('a', href=True))}")
    except Exception as e:
        print("[requests] failed", type(e).__name__, e)


def chapter_probe(page, url):
    page.goto(url, wait_until="domcontentloaded")
    ok = wait_pass(page)
    time.sleep(2)
    html = page.content()
    print(f"  CHAPTER {url}\n   passed={ok} title={page.title()!r} html={len(html)} captcha={bool(CAPTCHA.search(html[:6000]))}")
    try:
        print("   biggest text blocks:", page.evaluate(BLOCK_JS))
    except Exception as e:
        print("   block scan failed", e)
    body = page.inner_text("body") if page.query_selector("body") else ""
    for pat in (r"本章字数[:：]?\s*(\d+)", r"字数[:：]?\s*(\d+)", r"[（(]\s*\d+\s*/\s*\d+\s*[)）]", r"第\s*\d+\s*/\s*\d+\s*页"):
        m = re.search(pat, body)
        if m:
            print("   marker", pat, "->", m.group(0))
    nav = page.eval_on_selector_all(
        "a[href]", "els => els.map(e => [e.innerText.trim(), e.getAttribute('href')])"
        ".filter(x => /下一[页頁章]|上一[页頁章]|目录|目錄|next|prev/i.test(x[0]))")
    print("   nav links:", nav[:6])
    ads = re.findall(r".{0,15}(?:http|www\.|\.com|\.net|\.cc).{0,15}", body)
    print("   url-like snippets in body:", len(ads), ads[:3])


def probe(url, p):
    print("=" * 70, "\nURL:", url)
    req_view(url)
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(user_agent=UA, locale="zh-CN")
    page = ctx.new_page()
    xhrs = []

    def on_resp(r):
        try:
            if r.request.resource_type in ("xhr", "fetch") and not re.search(r"google|doubleclick|analytics|baidu|cnzz|51\.la|hm\.", r.url):
                body = ""
                try:
                    body = r.text()[:160].replace("\n", " ")
                except Exception:
                    pass
                xhrs.append((r.request.method, r.status, r.url[:140], body))
        except Exception:
            pass

    page.on("response", on_resp)
    page.goto(url, wait_until="domcontentloaded")
    ok = wait_pass(page)
    time.sleep(4)
    html = page.content()
    print(f"[playwright] passed={ok} title={page.title()!r} html={len(html)} captcha={bool(CAPTCHA.search(html[:6000]))}")
    if len(html) < 4000:
        print("--- raw html ---\n", html[:2500])
    print("--- xhr/fetch ---")
    for x in xhrs[:12]:
        print("  ", x)
    links = page.eval_on_selector_all(
        "a[href]", "els => els.map(e => [e.innerText.trim(), e.getAttribute('href')])")
    print(f"--- links: {len(links)}  (shape groups) ---")
    pats = classify(links, url)
    toc = [(t, h) for t, h in links if re.search(r"目录|目錄|章节|章節|全部|列表|开始阅读|開始閱讀|立即阅读|查看更多|更多章", t)]
    print("--- toc-like links:", toc[:8])
    cands = [urljoin(url, h) for t, h in links if re.search(r"\d", h) and re.search(r"chapter|read|\.html|/\d+", h) and urljoin(url, h) != url]
    first = None
    if re.search(r"/chapter/|/read/|/\d+\.html", url):
        first = url
    elif cands:
        first = cands[0]
    if first:
        chapter_probe(page, first)
    b.close()


def main(urls):
    with sync_playwright() as p:
        for u in urls:
            try:
                probe(u, p)
            except Exception as e:
                print("PROBE ERROR", u, type(e).__name__, e)


if __name__ == "__main__":
    main(sys.argv[1:])
