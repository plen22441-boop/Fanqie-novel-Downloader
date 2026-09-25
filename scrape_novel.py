#!/usr/bin/env python3
"""
Novel Scraper — ixdzs8.com (and similar sites)
Downloads a complete novel, checks for missing/duplicate/mixed content.

Usage:
  NOVEL_URL=https://ixdzs8.com/read/620538/ python scrape_novel.py
"""

import asyncio
import os
import re
import sys
from pathlib import Path
from playwright.async_api import async_playwright

NOVEL_URL  = os.environ.get("NOVEL_URL", "https://ixdzs8.com/read/620538/")
PARALLEL   = int(os.environ.get("PARALLEL", "20"))
DELAY_S    = float(os.environ.get("DELAY_S", "0.3"))
MIN_CHARS  = int(os.environ.get("MIN_CHARS", "100"))
OUT_TXT    = os.environ.get("OUT_TXT", "novel.txt")
OUT_REPORT = os.environ.get("OUT_REPORT", "report.txt")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

CONTENT_SELECTORS = [
    "#content", "#chaptercontent", ".chapter-content", ".read-content",
    ".novel-content", ".chapter-txt", "#booktxt", "article", ".content",
]


# ── helpers ────────────────────────────────────────────────────────────────

def chapter_num(url: str) -> int:
    m = re.search(r"[p/](\d+)\.html", url)
    return int(m.group(1)) if m else 0


async def wait_past_security(page, max_tries: int = 6) -> None:
    """Spin until security-check page resolves (JS sets cookies & redirects)."""
    for _ in range(max_tries):
        body = await page.inner_text("body")
        if not any(k in body for k in ("安全验证", "Checking your", "验证中", "正在进行")):
            return
        await page.wait_for_timeout(1500)


async def extract_content(page) -> str:
    for sel in CONTENT_SELECTORS:
        el = await page.query_selector(sel)
        if not el:
            continue
        text = await el.inner_text()
        clean = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(clean.replace(" ", "").replace("\n", "")) >= MIN_CHARS:
            return clean
    return ""


# ── chapter list ───────────────────────────────────────────────────────────

async def get_chapters(url: str) -> list[dict]:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=UA, locale="zh-CN",
                                        extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9"})
        page = await ctx.new_page()

        print(f"[*] Loading novel page: {url}")
        await page.goto(url, wait_until="networkidle", timeout=60_000)
        await page.wait_for_timeout(2_000)
        await wait_past_security(page)

        novel_id = re.search(r"/read/(\d+)/", url).group(1)
        anchors = await page.query_selector_all(f'a[href*="/read/{novel_id}/"]')

        seen: set[str] = set()
        chapters: list[dict] = []
        for a in anchors:
            href = await a.get_attribute("href") or ""
            title = (await a.inner_text()).strip()
            if not href:
                continue
            if not href.startswith("http"):
                href = "https://ixdzs8.com" + href
            href = href.split("?")[0].split("#")[0]
            if href == url.rstrip("/") + "/" or href == url:
                continue
            if href not in seen:
                seen.add(href)
                chapters.append({"url": href, "title": title})

        await browser.close()

    chapters.sort(key=lambda c: chapter_num(c["url"]))
    print(f"[*] Found {len(chapters)} chapters")
    return chapters


# ── per-chapter fetch ──────────────────────────────────────────────────────

async def fetch_one(ctx, ch: dict, idx: int, total: int) -> dict:
    page = await ctx.new_page()
    try:
        await page.goto(ch["url"], wait_until="load", timeout=30_000)
        await wait_past_security(page)
        content = await extract_content(page)
        clen = len(content.replace(" ", "").replace("\n", ""))
        status = "✓" if clen >= MIN_CHARS else "⚠"
        print(f"  [{idx+1}/{total}] {status} {ch['title'][:35]} ({clen} chars)")
        return {**ch, "content": content, "chars": clen}
    except Exception as exc:
        print(f"  [{idx+1}/{total}] ✗ {ch['title'][:35]} — {exc}")
        return {**ch, "content": "", "chars": 0}
    finally:
        await page.close()


async def scrape_all(chapters: list[dict]) -> list[dict]:
    results: list[dict | None] = [None] * len(chapters)
    sem = asyncio.Semaphore(PARALLEL)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        contexts = [
            await browser.new_context(user_agent=UA, locale="zh-CN")
            for _ in range(PARALLEL)
        ]

        async def worker(i: int, ch: dict) -> None:
            async with sem:
                result = await fetch_one(contexts[i % PARALLEL], ch, i, len(chapters))
                results[i] = result
                await asyncio.sleep(DELAY_S)

        await asyncio.gather(*[worker(i, ch) for i, ch in enumerate(chapters)])

        for ctx in contexts:
            await ctx.close()
        await browser.close()

    return [r for r in results if r is not None]


# ── quality check ──────────────────────────────────────────────────────────

def check_quality(results: list[dict]) -> list[str]:
    issues: list[str] = []
    seen_sigs: dict[str, str] = {}

    for i, ch in enumerate(results):
        if ch["chars"] < MIN_CHARS:
            issues.append(f"⚠️  [{i+1}] {ch['title']} — เนื้อหาสั้น/ว่าง ({ch['chars']} ตัว)  {ch['url']}")
            continue

        sig = ch["content"].replace(" ", "").replace("\n", "")[:200]
        if sig in seen_sigs:
            issues.append(f"🔁 [{i+1}] {ch['title']} — ซ้ำกับ {seen_sigs[sig]}")
        else:
            seen_sigs[sig] = ch["title"]

    return issues


# ── output ─────────────────────────────────────────────────────────────────

def save_txt(results: list[dict]) -> None:
    sep = "\n\n" + "─" * 50 + "\n\n"
    body = sep.join(f"{r['title']}\n\n{r['content']}" for r in results)
    Path(OUT_TXT).write_text(body, encoding="utf-8")
    print(f"\n[+] Saved {OUT_TXT} ({len(body):,} bytes, {len(results)} chapters)")


def save_report(results: list[dict], issues: list[str]) -> None:
    ok = sum(1 for r in results if r["chars"] >= MIN_CHARS)
    lines = [
        f"Novel URL : {NOVEL_URL}",
        f"Total     : {len(results)} chapters",
        f"OK        : {ok}",
        f"Issues    : {len(issues)}",
        "",
        "─" * 50,
        "",
    ]
    lines += issues if issues else ["🎉 ไม่พบปัญหา (no issues found)"]
    text = "\n".join(lines)
    Path(OUT_REPORT).write_text(text, encoding="utf-8")
    print(f"[+] Report saved to {OUT_REPORT}")
    print(text)


# ── main ───────────────────────────────────────────────────────────────────

async def main() -> None:
    chapters = await get_chapters(NOVEL_URL)
    if not chapters:
        print("No chapters found — check the URL or selectors.")
        sys.exit(1)

    print(f"\n[*] Scraping {len(chapters)} chapters ({PARALLEL} parallel) …\n")
    results = await scrape_all(chapters)

    issues = check_quality(results)
    save_txt(results)
    save_report(results, issues)


if __name__ == "__main__":
    asyncio.run(main())
