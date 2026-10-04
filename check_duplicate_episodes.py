"""
ตรวจสอบชื่อตอนซ้ำใน mynovel.co
Usage:
    python check_duplicate_episodes.py <dashboard_url>

Example:
    python check_duplicate_episodes.py "https://mynovel.co/dashboard/workings/cnoWzT5Pl7g2swhSsK66GF9B?tab=episode"

- เปิดเบราว์เซอร์ให้ login เอง (ถ้ายังไม่ได้ login)
- ดึงรายชื่อตอนทั้งหมด (รองรับการ scroll หน้าต่อหน้า)
- แสดงรายการชื่อตอนที่ซ้ำกัน
"""

import sys
import re
import json
import time
import argparse
from collections import defaultdict
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout


# ---- selectors ที่ใช้ดึงชื่อตอนใน mynovel.co ----
EPISODE_TITLE_SELECTORS = [
    # ลำดับจาก specific → generic
    "div[class*='episode'] h3",
    "div[class*='episode'] h4",
    "div[class*='chapter'] h3",
    "div[class*='chapter'] h4",
    "[class*='episode-title']",
    "[class*='chapter-title']",
    "[class*='episodeTitle']",
    "[class*='chapterTitle']",
    "table tbody tr td:first-child",
    "ul[class*='episode'] li",
    "li[class*='episode']",
]

LOGIN_TIMEOUT_SEC = 120   # รอ login สูงสุด 2 นาที
SCROLL_PAUSE_MS   = 1200  # หยุดระหว่าง scroll
MAX_SCROLL_ROUNDS = 200   # ป้องกัน loop ไม่สิ้นสุด


def wait_for_login(page, dashboard_url: str):
    """เปิดหน้า dashboard แล้วรอจนกว่าจะ login สำเร็จ"""
    print(f"\n[1/3] เปิดหน้า: {dashboard_url}")
    try:
        page.goto(dashboard_url, wait_until="domcontentloaded", timeout=30_000)
    except PwTimeout:
        page.goto(dashboard_url, wait_until="commit", timeout=30_000)

    # ตรวจว่าถูก redirect ไปหน้า login หรือเปล่า
    for _ in range(LOGIN_TIMEOUT_SEC):
        current = page.url
        if "login" in current or "signin" in current or "auth" in current:
            print(f"      กรุณา login ในเบราว์เซอร์ที่เปิดอยู่ ... (รออีก {LOGIN_TIMEOUT_SEC - _}s)")
            time.sleep(1)
            # หลัง login browser จะ redirect กลับมา
            if "login" not in page.url and "signin" not in page.url:
                page.goto(dashboard_url, wait_until="domcontentloaded", timeout=30_000)
                break
        else:
            break
    else:
        print("[WARN] ไม่แน่ใจว่า login สำเร็จหรือเปล่า — ดำเนินการต่อ...")

    page.wait_for_timeout(2000)
    print(f"      URL ปัจจุบัน: {page.url}")


def scroll_to_bottom(page) -> int:
    """Scroll จนสุดหน้า เพื่อโหลด infinite-scroll แล้วคืนจำนวนรอบที่ scroll"""
    prev_height = -1
    rounds = 0
    for _ in range(MAX_SCROLL_ROUNDS):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(SCROLL_PAUSE_MS)
        height = page.evaluate("document.body.scrollHeight")
        rounds += 1
        if height == prev_height:
            break
        prev_height = height
    return rounds


def click_load_more(page) -> bool:
    """กด 'load more' / 'โหลดเพิ่ม' ถ้ามี — คืน True ถ้ากดได้"""
    btn = page.evaluate("""() => {
        const btns = Array.from(document.querySelectorAll('button, a'));
        const found = btns.find(b =>
            /load.?more|โหลดเพิ่ม|ดูเพิ่ม|see.?more|แสดงทั้งหมด/i.test(b.innerText));
        return found ? found.innerText.trim() : null;
    }""")
    if not btn:
        return False
    try:
        page.get_by_text(re.compile(re.escape(btn), re.I)).first.click()
        page.wait_for_timeout(1500)
        return True
    except Exception:
        return False


def handle_pagination(page, base_url: str) -> list[str]:
    """ถ้าเป็น pagination แบบ next-page ให้วนดึงทุกหน้า คืน list ชื่อตอน"""
    all_titles: list[str] = []
    visited: set[str] = set()
    current_url = base_url

    while current_url and current_url not in visited:
        visited.add(current_url)
        page.goto(current_url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(1500)

        titles = extract_titles_from_page(page)
        all_titles.extend(titles)
        print(f"      [pagination] {current_url} → {len(titles)} ชื่อตอน")

        # หา next page
        next_url = page.evaluate("""() => {
            const a = Array.from(document.querySelectorAll('a'));
            const nxt = a.find(x => /next|ถัดไป|下一页/i.test(x.innerText));
            return nxt ? nxt.href : null;
        }""")
        if next_url and next_url not in visited:
            current_url = next_url
        else:
            break

    return all_titles


def extract_titles_from_page(page) -> list[str]:
    """ดึงชื่อตอนจากหน้าปัจจุบัน"""
    # ลองหา selector ที่เจอ element มากที่สุด
    best_sel = None
    best_count = 0

    for sel in EPISODE_TITLE_SELECTORS:
        try:
            count = page.evaluate(
                f"() => document.querySelectorAll('{sel}').length"
            )
            if count > best_count:
                best_count = count
                best_sel = sel
        except Exception:
            pass

    if best_sel and best_count > 0:
        titles = page.evaluate(f"""() =>
            Array.from(document.querySelectorAll('{best_sel}'))
                 .map(el => el.innerText.trim())
                 .filter(t => t.length > 0)
        """)
        return titles

    # Fallback: ดึง text จากทุก element ที่ดูเหมือน "episode X" / "ตอนที่ X"
    fallback = page.evaluate("""() => {
        const all = Array.from(document.querySelectorAll('*'));
        return all
            .filter(el => {
                const t = el.innerText?.trim() || '';
                return (
                    el.children.length === 0 &&
                    t.length > 0 && t.length < 200 &&
                    /ตอน|ตอนที่|episode|chapter|ep\.|ch\./i.test(t)
                );
            })
            .map(el => el.innerText.trim());
    }""")
    return fallback or []


def get_all_episode_titles(page, dashboard_url: str) -> list[str]:
    """ดึงรายชื่อตอนทั้งหมด — รองรับ infinite scroll + load-more + pagination"""
    print("\n[2/3] ดึงรายชื่อตอน...")

    # ลอง infinite-scroll ก่อน
    scroll_to_bottom(page)

    # กด load-more ซ้ำๆ จนหมด
    for _ in range(50):
        if not click_load_more(page):
            break
        scroll_to_bottom(page)

    titles = extract_titles_from_page(page)

    # ถ้าดึงได้น้อยมาก ลองวิธี pagination
    if len(titles) < 5:
        print("      ไม่พบตอนด้วย scroll — ลองวิธี pagination...")
        titles = handle_pagination(page, dashboard_url)

    return titles


def check_duplicates(titles: list[str]) -> dict[str, list[int]]:
    """คืน dict {ชื่อ: [ตำแหน่ง 1-based, ...]} เฉพาะที่ซ้ำ"""
    index_map: dict[str, list[int]] = defaultdict(list)
    for i, title in enumerate(titles, start=1):
        key = title.strip().lower()
        index_map[key].append(i)

    return {
        title: positions
        for title, positions in index_map.items()
        if len(positions) > 1
    }


def print_report(titles: list[str], duplicates: dict[str, list[int]]):
    print(f"\n[3/3] ผลการตรวจสอบ")
    print(f"      ตอนทั้งหมด : {len(titles)}")
    print(f"      ชื่อซ้ำกัน : {len(duplicates)} กลุ่ม")

    if not duplicates:
        print("\n✅  ไม่พบชื่อตอนซ้ำกัน!")
        return

    print("\n⚠️   รายการชื่อตอนที่ซ้ำ:")
    print("─" * 60)
    for rank, (key, positions) in enumerate(
        sorted(duplicates.items(), key=lambda x: x[1][0]), start=1
    ):
        # หาชื่อต้นฉบับ (case-sensitive) จาก position แรก
        orig_title = titles[positions[0] - 1]
        print(f"  {rank:3d}. \"{orig_title}\"")
        print(f"       ซ้ำ {len(positions)} ครั้ง ที่ตำแหน่ง: {positions}")
    print("─" * 60)

    print(f"\n  รวม {sum(len(p) for p in duplicates.values())} ตอนที่ซ้ำกัน")
    print(f"  (ลองลบออก {sum(len(p)-1 for p in duplicates.values())} ตอนเพื่อไม่มีซ้ำ)")


def save_report(titles: list[str], duplicates: dict[str, list[int]], out_path: str = "duplicate_report.json"):
    data = {
        "total_episodes": len(titles),
        "duplicate_groups": len(duplicates),
        "all_titles": titles,
        "duplicates": [
            {
                "title": titles[positions[0] - 1],
                "occurrences": len(positions),
                "positions": positions,
            }
            for positions in duplicates.values()
            for positions in [positions]  # unpack properly
        ],
    }
    # rebuild properly
    data["duplicates"] = [
        {
            "title": titles[pos[0] - 1],
            "occurrences": len(pos),
            "positions": pos,
        }
        for pos in (
            sorted(duplicates.values(), key=lambda x: x[0])
        )
    ]
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n📄  บันทึกรายงานแล้ว: {out_path}")


def main():
    parser = argparse.ArgumentParser(
        description="ตรวจสอบชื่อตอนซ้ำใน mynovel.co"
    )
    parser.add_argument(
        "url",
        nargs="?",
        default="https://mynovel.co/dashboard/workings/cnoWzT5Pl7g2swhSsK66GF9B?tab=episode",
        help="URL ของ dashboard episode",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="รันแบบ headless (ต้องมี cookie ที่ valid อยู่แล้ว)",
    )
    parser.add_argument(
        "--cookies",
        default=None,
        help="path ไฟล์ cookies.json (export จาก browser extension เช่น EditThisCookie)",
    )
    parser.add_argument(
        "--output",
        default="duplicate_report.json",
        help="ไฟล์ผลลัพธ์ JSON (default: duplicate_report.json)",
    )
    args = parser.parse_args()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=args.headless,
            executable_path="/opt/pw-browsers/chromium",
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            locale="th-TH",
            viewport={"width": 1280, "height": 900},
        )

        # โหลด cookies ถ้ามี
        if args.cookies:
            try:
                with open(args.cookies, encoding="utf-8") as f:
                    cookies = json.load(f)
                context.add_cookies(cookies)
                print(f"[cookies] โหลด {len(cookies)} cookies จาก {args.cookies}")
            except Exception as e:
                print(f"[WARN] โหลด cookies ไม่ได้: {e}")

        page = context.new_page()

        # ---- step 1: เปิดหน้าและรอ login ----
        wait_for_login(page, args.url)

        # ---- step 2: ดึงรายชื่อตอน ----
        titles = get_all_episode_titles(page, args.url)

        if not titles:
            print("\n[ERROR] ดึงชื่อตอนไม่ได้เลย")
            print("  แนะนำ:")
            print("  1. ตรวจสอบว่า login สำเร็จแล้ว")
            print("  2. ลองเพิ่ม --cookies cookies.json")
            print("  3. เปิดหน้าเว็บในเบราว์เซอร์แล้ว inspect element เพื่อหา selector")
            browser.close()
            sys.exit(1)

        print(f"      พบ {len(titles)} ตอน")

        # แสดงตัวอย่าง 5 ชื่อแรก
        sample = titles[:5]
        print(f"      ตัวอย่าง: {sample}")

        # ---- step 3: เช็คซ้ำ ----
        duplicates = check_duplicates(titles)
        print_report(titles, duplicates)

        if args.output:
            save_report(titles, duplicates, args.output)

        browser.close()


if __name__ == "__main__":
    main()
