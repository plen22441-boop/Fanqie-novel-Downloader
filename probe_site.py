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
MARKERS = ("请稍候", "Just a moment", "Checking", "正在验证浏览器", "Verify Yourself", "身份验证", "Attention Required")
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


def chapters_mode(url):
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(user_agent=UA, locale="zh-CN")
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        print("detail passed:", wait_pass(page), page.title())
        time.sleep(3)
        raw = page.eval_on_selector_all(
            "a[href*='/site/chapter?id=']", "els => els.map(e => [e.innerText.trim(), e.href])")
        seen, links = set(), []
        for t, h in raw:
            if h not in seen:
                seen.add(h)
                links.append((t, h))
        ids = [int(re.search(r"id=(\d+)", h).group(1)) for _, h in links]
        print("chapter links:", len(links), "first3:", links[:3], "last3:", links[-3:])
        print("ids ascending:", ids == sorted(ids), "descending:", ids == sorted(ids, reverse=True))
        body = page.inner_text("body")
        print("total-count hints:", re.findall(r".{0,8}共\s*\d+\s*章.{0,6}|.{0,8}\d+\s*章节.{0,6}", body)[:4])
        try:
            print("toc container of first link:", page.evaluate(
                "() => { let e = document.querySelector(\"a[href*='/site/chapter?id=']\"); let o=[]; "
                "for (let i=0;i<4&&e;i++){ e=e.parentElement; if(e) o.push(e.tagName.toLowerCase()+(e.id?'#'+e.id:'')+(e.className?'.'+String(e.className).trim().split(/\\s+/).join('.'):'')); } return o; }"))
        except Exception as e:
            print("container scan failed", e)
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        print("cookie names:", list(cookies))
        picks = [0, 1, len(links) // 2, len(links) - 1]
        print("--- strategy A: requests + cookies ---")
        for i in picks:
            try:
                r = requests.get(links[i][1], headers={"User-Agent": UA, "Referer": url, "Accept-Language": "zh-CN,zh;q=0.9"},
                                 cookies=cookies, timeout=25)
                tt = BeautifulSoup(r.text, "html.parser").title
                print(f"  #{i} HTTP {r.status_code} len={len(r.text)} title={tt.string.strip() if tt and tt.string else None}")
            except Exception as e:
                print("  #", i, "failed", type(e).__name__)
        print("--- strategy B: playwright per chapter ---")
        xh = []

        def on_resp(r):
            try:
                if r.request.resource_type in ("xhr", "fetch") and "spudnovel" in r.url and "cdn-cgi" not in r.url:
                    xh.append((r.status, r.url[:110], r.text()[:80].replace("\n", " ")))
            except Exception:
                pass

        page.on("response", on_resp)
        for i in picks:
            del xh[:]
            t0 = time.time()
            page.goto(links[i][1], wait_until="domcontentloaded")
            ok = wait_pass(page, 40)
            for _ in range(20):
                if len(page.inner_text("body")) > 600:
                    break
                time.sleep(0.5)
            txt = page.inner_text("body")
            blocks = page.evaluate(BLOCK_JS)
            m = re.search(r"字数[:：]?\s*(\d+)", txt)
            pg = re.findall(r"[（(]\s*\d+\s*/\s*\d+\s*[)）]|第\s*\d+\s*/\s*\d+\s*页", txt)
            nav = page.eval_on_selector_all(
                "a[href]", "els => els.map(e => [e.innerText.trim(), e.getAttribute('href')])"
                ".filter(x => /下一[页頁章]|上一[页頁章]|目录|next/i.test(x[0]))")
            print(f"  #{i} {links[i][0][:20]!r} passed={ok} {time.time()-t0:.1f}s title={page.title()!r} bodylen={len(txt)} declared={m.group(1) if m else None} pages={pg[:2]}")
            print("     blocks:", blocks[:3], "nav:", nav[:4])
            print("     head:", repr(txt[:50]), "tail:", repr(txt[-60:]))
            print("     ad-words:", re.findall(r".{0,10}(?:土豆|spudnovel|http|www\.).{0,12}", txt)[:3], "xhr:", xh[:2])
        b.close()


def main(urls):
    if urls and urls[0] == "chapters":
        return chapters_mode(urls[1])
    with sync_playwright() as p:
        for u in urls:
            try:
                probe(u, p)
            except Exception as e:
                print("PROBE ERROR", u, type(e).__name__, e)


if __name__ == "__main__":
    main(sys.argv[1:])
