"""
boluomao1.com novel downloader — runs on GitHub Actions
Usage: python boluomao1.py <book_url_or_id> [--start N] [--end N] [--delay MS]
"""
import re, sys, time, json, zipfile, argparse, io, pathlib
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    HAS_PW = True
except ImportError:
    HAS_PW = False

try:
    import requests
    from bs4 import BeautifulSoup
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

OUT_DIR = pathlib.Path("output")
OUT_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.boluomao1.com/",
}
BLOCK_RE = re.compile(r"Just a moment|安全验证|人机验证|Verify Yourself|Access Denied", re.I)
HEAD_RE  = re.compile(r"第\s*([0-9]+)\s*[章节回]", re.I)
URL_RE   = re.compile(r"/read/(\d+)/(\d+)\.html", re.I)

# ── helpers ──────────────────────────────────────────────────────────────────

def book_id_from(url_or_id: str) -> str:
    m = re.search(r"(\d{5,})", url_or_id)
    return m.group(1) if m else url_or_id

def clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ",
           re.sub(r" ", " ",
           re.sub(r"\r", "", text or ""))).strip()

def chapter_no(title: str, url: str = "") -> int | None:
    h = HEAD_RE.search(title or "")
    if h:
        return int(h.group(1))
    m = URL_RE.search(url)
    return int(m.group(2)) if m else None

def extract_content(soup: BeautifulSoup):
    """Try multiple selectors to get chapter paragraphs."""
    selectors = [
        ".chapter-content", "#chapter-content",
        ".read-content",    "#read-content",
        ".content",         "#content",
        ".article-content", ".novel-content",
        ".text-content",    ".chapterBody",
    ]
    for sel in selectors:
        box = soup.select_one(sel)
        if not box:
            continue
        paras = [clean(p.get_text()) for p in box.find_all("p")]
        paras = [p for p in paras if p]
        if paras:
            return paras
        text = clean(box.get_text("\n"))
        paras = [l for l in text.split("\n") if l.strip()]
        if paras:
            return paras
    return []

def extract_title(soup: BeautifulSoup) -> str:
    for sel in ["h1.title", ".chapter-title h1", ".chaptertitle", "h1", ".title"]:
        el = soup.select_one(sel)
        if el:
            return clean(el.get_text())
    return ""

def next_page_url(soup: BeautifulSoup, base: str, chapter_num: int, visited: set) -> str | None:
    for a in soup.find_all("a", href=True):
        href = urljoin(base, a["href"])
        if href in visited:
            continue
        m = URL_RE.search(href)
        if m and int(m.group(2)) == chapter_num:
            text = clean(a.get_text())
            if re.search(r"下一页|next", text, re.I) or a.get("class", []):
                return href
    return None

# ── fetchers ─────────────────────────────────────────────────────────────────

def fetch_requests(url: str) -> BeautifulSoup | None:
    if not HAS_REQUESTS:
        return None
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        if BLOCK_RE.search(soup.get_text()):
            return None
        return soup
    except Exception as e:
        print(f"  requests error: {e}", file=sys.stderr)
        return None

_pw_browser = None
_pw_context = None
_pw_instance = None

def pw_start():
    global _pw_browser, _pw_context, _pw_instance
    if _pw_browser:
        return
    _pw_instance = sync_playwright().start()
    _pw_browser  = _pw_instance.chromium.launch(headless=True)
    _pw_context  = _pw_browser.new_context(
        user_agent=HEADERS["User-Agent"],
        locale="zh-CN",
    )

def pw_stop():
    global _pw_browser, _pw_context, _pw_instance
    try:
        if _pw_context: _pw_context.close()
        if _pw_browser: _pw_browser.close()
        if _pw_instance: _pw_instance.stop()
    except Exception:
        pass
    _pw_browser = _pw_context = _pw_instance = None

def fetch_playwright(url: str) -> BeautifulSoup | None:
    if not HAS_PW:
        return None
    try:
        pw_start()
        page = _pw_context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)
        html = page.content()
        page.close()
        soup = BeautifulSoup(html, "html.parser")
        if BLOCK_RE.search(soup.get_text()):
            return None
        return soup
    except Exception as e:
        print(f"  playwright error: {e}", file=sys.stderr)
        return None

def fetch(url: str) -> BeautifulSoup | None:
    soup = fetch_requests(url)
    if soup:
        return soup
    print(f"  requests blocked/failed, trying playwright…", file=sys.stderr)
    return fetch_playwright(url)

# ── catalog ──────────────────────────────────────────────────────────────────

def get_catalog(book_id: str) -> list[dict]:
    book_url = f"https://www.boluomao1.com/book/{book_id}.html"
    print(f"Fetching catalog: {book_url}")
    soup = fetch(book_url)
    if not soup:
        raise RuntimeError(f"Cannot load catalog page: {book_url}")

    selectors = [
        "#chapter-list a", ".chapter-list a", ".chapter_list a",
        "#chapterList a", ".chapterList a", ".list-chapter a",
        ".catalog-list a", "#catalog a", ".volume-list a",
        ".list a", "a[href*='/read/']",
    ]
    found: dict[int, dict] = {}
    links = []
    for sel in selectors:
        links = soup.select(sel)
        if len(links) > 2:
            break

    for a in links:
        href = urljoin(book_url, a.get("href", ""))
        m = URL_RE.search(href)
        if not m:
            continue
        num = int(m.group(2))
        part = 1  # part pages handled during scrape
        if part != 1 and found.get(num):
            continue
        title_text = clean(a.get_text()) or f"第{num}章"
        if num not in found or len(title_text) > len(found[num]["title"]):
            found[num] = {"number": num, "title": title_text, "url": href}

    catalog = sorted(found.values(), key=lambda x: x["number"])
    if not catalog:
        raise RuntimeError("No chapters found in catalog — site structure may have changed")
    return catalog

# ── chapter scraper ───────────────────────────────────────────────────────────

def scrape_chapter(item: dict, delay_ms: int) -> dict:
    out = {
        "number": item["number"], "title": item["title"],
        "url": item["url"], "pages": [], "paragraphs": [],
        "status": "ok", "warnings": [], "error": "",
    }
    current = item["url"]
    visited: set[str] = set()

    try:
        while current and current not in visited:
            visited.add(current)
            soup = fetch(current)
            if not soup:
                raise RuntimeError(f"Blocked or failed: {current}")

            ch_title = extract_title(soup)
            observed = chapter_no(ch_title, current)
            if observed and observed != item["number"]:
                raise RuntimeError(f"Chapter mismatch: expected {item['number']}, got {observed}")

            paras = extract_content(soup)
            if not paras:
                raise RuntimeError("No content found")

            out["title"] = ch_title or out["title"]
            out["pages"].append(current)
            out["paragraphs"].extend(paras)

            pua = re.search(r"[-]", "\n".join(paras))
            if pua:
                out["status"] = "suspicious"
                out["warnings"].append("พบอักขระป้องกันคัดลอก")

            nxt = next_page_url(soup, current, item["number"], visited)
            if nxt:
                time.sleep(max(0.25, delay_ms / 1000))
            current = nxt

        body = "\n\n".join(out["paragraphs"])
        chars = len(re.sub(r"\s", "", body))
        if "�" in body:
            out["status"] = "suspicious"; out["warnings"].append("encoding เสีย")
        if chars < 200:
            out["status"] = "suspicious"; out["warnings"].append(f"สั้นผิดปกติ {chars} ตัวอักษร")
        if len(out["pages"]) > 1:
            out["warnings"].append(f"รวม {len(out['pages'])} หน้า")
    except Exception as e:
        out["status"] = "failed"; out["error"] = str(e)
    return out

# ── QC / export ──────────────────────────────────────────────────────────────

def gaps(items: list[dict]) -> list[int]:
    if not items:
        return []
    have = {x["number"] for x in items}
    return [n for n in range(items[0]["number"], items[-1]["number"] + 1) if n not in have]

def make_report(selected: list[dict], results: list[dict]) -> dict:
    failed     = [x["number"] for x in results if x["status"] == "failed"]
    suspicious = [x["number"] for x in results if x["status"] == "suspicious"]
    attempted  = {x["number"] for x in results}
    not_attempted = [x["number"] for x in selected if x["number"] not in attempted]
    cat_gaps   = gaps(selected)
    return {
        "bookTitle": "",
        "requestedRange": [selected[0]["number"], selected[-1]["number"]] if selected else [],
        "discoveredChapters": len(selected),
        "savedChapters": sum(1 for x in results if x["status"] != "failed"),
        "catalogGaps": cat_gaps,
        "failedChapters": failed,
        "suspiciousChapters": suspicious,
        "notAttempted": not_attempted,
        "complete": not (cat_gaps or failed or suspicious or not_attempted),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "chapters": [
            {**x, "characterCount": len(re.sub(r"\s", "", "\n\n".join(x["paragraphs"])))}
            for x in results
        ],
    }

def report_text(r: dict) -> str:
    def ls(a): return ", ".join(str(x) for x in a) if a else "ไม่มี"
    lines = [
        "รายงานตรวจความครบถ้วน",
        f"ช่วงตอน: {r['requestedRange'][0]}–{r['requestedRange'][1]}",
        f"พบในสารบัญ: {r['discoveredChapters']} ตอน",
        f"บันทึกสำเร็จ: {r['savedChapters']} ตอน",
        f"ช่องว่าง: {ls(r['catalogGaps'])}",
        f"โหลดไม่สำเร็จ: {ls(r['failedChapters'])}",
        f"ต้องตรวจ: {ls(r['suspiciousChapters'])}",
        f"ยังไม่โหลด: {ls(r['notAttempted'])}",
        f"ผลรวม: {'ครบและผ่าน QC' if r['complete'] else 'ยังไม่ผ่าน QC'}",
        "", "รายละเอียด:",
    ]
    for x in r["chapters"]:
        lines.append(
            f"ตอน {x['number']}: {x['status']} | {len(x['pages'])} หน้า | "
            f"{x['characterCount']} ตัวอักษร | {'; '.join(x['warnings']) or x['error'] or 'ปกติ'}"
        )
    return "\n".join(lines) + "\n"

def combined_txt(r: dict) -> str:
    missing = sorted(set(r["catalogGaps"] + r["failedChapters"] + r["notAttempted"]))
    parts = [
        f"ตอนที่ขาด: {', '.join(str(n) for n in missing) if missing else 'ไม่มี'}",
        f"ต้องตรวจ: {', '.join(str(n) for n in r['suspiciousChapters']) if r['suspiciousChapters'] else 'ไม่มี'}",
        "",
    ]
    for x in r["chapters"]:
        if x["status"] != "failed":
            parts.append(f"{x['title']}\n\n{chr(10).join(x['paragraphs'])}\n")
    return "\n".join(parts)

# ── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="book URL or book_id")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end",   type=int, default=0)
    ap.add_argument("--delay", type=int, default=700, help="ms between requests")
    args = ap.parse_args()

    book_id = book_id_from(args.target)
    print(f"Book ID: {book_id}")

    catalog = get_catalog(book_id)
    print(f"Found {len(catalog)} chapters ({catalog[0]['number']}–{catalog[-1]['number']})")

    start = args.start
    end   = args.end if args.end > 0 else catalog[-1]["number"]
    selected = [c for c in catalog if start <= c["number"] <= end]
    print(f"Downloading chapters {start}–{end} ({len(selected)} chapters)")

    results = []
    for i, item in enumerate(selected):
        print(f"  [{i+1}/{len(selected)}] Chapter {item['number']}: {item['title'][:40]}")
        result = scrape_chapter(item, args.delay)
        results.append(result)
        status_icon = {"ok": "✓", "suspicious": "⚠", "failed": "✗"}.get(result["status"], "?")
        detail = result["error"] or "; ".join(result["warnings"]) or "{} page(s)".format(len(result["pages"]))
        print(f"  {status_icon} {result['status']} — {detail}")
        if i < len(selected) - 1:
            time.sleep(max(0.25, args.delay / 1000))

    report = make_report(selected, results)
    base = f"novel_{start}-{end}"

    # Write ZIP
    zip_path = OUT_DIR / f"{base}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        txt = combined_txt(report)
        zf.writestr(f"{base}.txt",       "﻿" + txt)
        zf.writestr("QC_REPORT.txt",     "﻿" + report_text(report))
        zf.writestr("QC_REPORT.json",    json.dumps(report, ensure_ascii=False, indent=2))
        for x in report["chapters"]:
            if x["status"] != "failed":
                fn = f"chapters/{str(x['number']).zfill(4)}_ch{x['number']}.txt"
                body = f"{x['title']}\n\n{chr(10).join(x['paragraphs'])}\n"
                zf.writestr(fn, "﻿" + body)
    print(f"\nSaved: {zip_path}")

    # Summary
    r = report
    print(f"\n{'='*50}")
    print(f"QC: {'PASS ✓' if r['complete'] else 'FAIL ✗'}")
    print(f"Saved {r['savedChapters']}/{r['discoveredChapters']} chapters")
    if r["failedChapters"]:
        print(f"Failed:     {r['failedChapters']}")
    if r["suspiciousChapters"]:
        print(f"Suspicious: {r['suspiciousChapters']}")

    try:
        pw_stop()
    except Exception:
        pass

    sys.exit(0 if r["complete"] else 1)

if __name__ == "__main__":
    main()
