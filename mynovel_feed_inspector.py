#!/usr/bin/env python3
"""
mynovel_feed_inspector.py — ดึง feed อัปเดตล่าสุดจาก mynovel.co
รันบนเครื่องตัวเองได้เลย (ไม่ต้องผ่าน cloud)

Usage:
    pip install requests beautifulsoup4
    python mynovel_feed_inspector.py
    python mynovel_feed_inspector.py --url https://mynovel.co/latest
    python mynovel_feed_inspector.py --pages 3  # ดึงหลายหน้า
"""

import argparse
import json
import re
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://mynovel.co"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "th-TH,th;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://mynovel.co/",
}

# URL ที่คาดว่าเป็น feed — อิงจากโครงสร้างที่พบจาก search
# mynovel.co มี section: นิยายอัปเดตล่าสุด, daily top sellers, newly opened
FEED_URL_CANDIDATES = [
    "/",                    # หน้าหลัก (มี feed อัปเดตล่าสุด)
    "/latest",              # อาจเป็น page แยก
    "/update",
    "/novel/update",
    "/novel/latest",
    "/home",
    "/announcements",       # ยืนยันแล้วว่ามีจริง
]


def fetch(url: str, session: requests.Session) -> BeautifulSoup | None:
    try:
        r = session.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  [!] ดึงไม่ได้: {url} → {e}")
        return None


def inspect_homepage(session: requests.Session):
    """ดึงหน้าหลักและวิเคราะห์โครงสร้าง feed"""
    print(f"\n[*] กำลังเข้า {BASE_URL} ...")
    soup = fetch(BASE_URL, session)
    if not soup:
        return None

    # หา links ที่เกี่ยวกับ feed
    print("\n[*] Links ที่น่าสนใจบนหน้าหลัก:")
    feed_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        if any(k in href.lower() for k in ["latest", "update", "recent", "new", "อัปเดต", "ล่าสุด"]):
            full = urljoin(BASE_URL, href)
            feed_links.append({"text": text, "href": full})
            print(f"  → {text!r}: {full}")

    # สแกนหาการ์ดนิยายบนหน้าหลัก
    print("\n[*] วิเคราะห์การ์ดนิยายบนหน้าหลัก:")
    novels = extract_novel_cards(soup)
    for n in novels[:10]:
        print(f"  • {n.get('title', '—')[:40]:40s}  เวลา: {n.get('time', '—')}")

    return {"feed_links": feed_links, "sample_novels": novels}


def extract_novel_cards(soup: BeautifulSoup) -> list[dict]:
    """
    พยายามดึงข้อมูลนิยายจาก DOM
    ลอง heuristic หลายแบบเพราะยังไม่รู้ structure จริง
    """
    novels = []

    # วิธี 1: หา element ที่มีเวลา (time, relative time)
    time_patterns = [
        r"\d+\s*(นาที|ชั่วโมง|วัน|สัปดาห์|เดือน)",
        r"\d{1,2}:\d{2}",
        r"\d{1,2}/\d{1,2}/\d{2,4}",
    ]
    time_re = re.compile("|".join(time_patterns))

    # หา parent element ที่น่าจะเป็น card
    for elem in soup.find_all(["article", "div", "li", "section"]):
        text = elem.get_text(" ", strip=True)
        if time_re.search(text) and len(text) > 10:
            title_elem = elem.find(["h1", "h2", "h3", "h4", "a"])
            title = title_elem.get_text(strip=True) if title_elem else ""
            time_match = time_re.search(text)
            time_str = time_match.group() if time_match else ""
            link_elem = elem.find("a", href=True)
            link = urljoin(BASE_URL, link_elem["href"]) if link_elem else ""

            if title and len(title) > 3:
                novels.append({"title": title, "time": time_str, "link": link})

    # deduplicate
    seen = set()
    unique = []
    for n in novels:
        if n["title"] not in seen:
            seen.add(n["title"])
            unique.append(n)
    return unique[:50]


def analyze_feed_timing(novels: list[dict]):
    """วิเคราะห์ความถี่ของการอัปเดตใน feed"""
    print("\n[*] วิเคราะห์ความถี่ feed:")

    minute_counts = {}
    for n in novels:
        t = n.get("time", "")
        m = re.search(r"(\d+)\s*นาที", t)
        h = re.search(r"(\d+)\s*ชั่วโมง", t)
        if m:
            mins = int(m.group(1))
            bucket = f"{mins} นาทีที่แล้ว"
            minute_counts[bucket] = minute_counts.get(bucket, 0) + 1
        elif h:
            hrs = int(h.group(1))
            bucket = f"{hrs} ชั่วโมงที่แล้ว"
            minute_counts[bucket] = minute_counts.get(bucket, 0) + 1

    if minute_counts:
        print("  การกระจายตัวของเวลาอัปเดต:")
        for k, v in sorted(minute_counts.items()):
            bar = "█" * v
            print(f"    {k:<20} {bar} ({v})")
    else:
        print("  ไม่พบข้อมูลเวลาในรูปแบบที่คาดหวัง")
        print("  (อาจต้องดู HTML source เพื่อหา selector ที่ถูกต้อง)")


def probe_feed_urls(session: requests.Session):
    """ลอง URL ที่อาจเป็น feed"""
    print("\n[*] ทดสอบ URL candidates สำหรับ feed:")
    for path in FEED_URL_CANDIDATES:
        url = urljoin(BASE_URL, path)
        try:
            r = session.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
            novels = extract_novel_cards(BeautifulSoup(r.text, "html.parser"))
            print(f"  {r.status_code} {url}  →  พบการ์ดนิยาย {len(novels)} รายการ")
        except Exception as e:
            print(f"  ERR  {url}  →  {e}")
        time.sleep(0.5)


def measure_feed_velocity(session: requests.Session, feed_url: str, wait_minutes: int = 5):
    """
    วัด "ความเร็ว" ของ feed จริง:
    ดึงรายชื่อนิยายครั้งที่ 1 → รอ → ดึงอีกครั้ง → นับว่ามีกี่เรื่องใหม่ขึ้น
    ใช้หาว่าต้องโพสต์ถี่แค่ไหนจึงอยู่บนหน้าแรก
    """
    print(f"\n[*] วัดความเร็ว feed ({wait_minutes} นาที)")
    soup1 = fetch(feed_url, session)
    if not soup1:
        return

    novels1 = {n["title"] for n in extract_novel_cards(soup1)}
    print(f"  รอบที่ 1: พบ {len(novels1)} รายการ")
    print(f"  รอ {wait_minutes} นาที...")
    time.sleep(wait_minutes * 60)

    soup2 = fetch(feed_url, session)
    if not soup2:
        return
    novels2 = {n["title"] for n in extract_novel_cards(soup2)}
    new_entries = novels2 - novels1

    print(f"  รอบที่ 2: พบ {len(novels2)} รายการ")
    print(f"  เรื่องใหม่ที่ขึ้นมาใน {wait_minutes} นาที: {len(new_entries)} เรื่อง")
    if new_entries:
        print("  รายชื่อ:")
        for t in list(new_entries)[:10]:
            print(f"    • {t[:50]}")

    if len(new_entries) > 0:
        push_off_rate = len(new_entries) / wait_minutes
        safe_interval = 1 / push_off_rate if push_off_rate > 0 else 999
        print(f"\n  📊 Feed velocity: ~{push_off_rate:.1f} เรื่อง/นาที")
        print(f"  ➡️  ต้องโพสต์ทุก ≤ {safe_interval:.1f} นาที จึงอยู่บนหน้าแรก")
        print(f"  (ช่วงนี้ของวัน — ช่วง peak อาจเร็วกว่านี้ 3-5x)")


def main():
    parser = argparse.ArgumentParser(description="ดึงและวิเคราะห์ feed จาก mynovel.co")
    parser.add_argument("--url", default=BASE_URL)
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--save", action="store_true", help="บันทึกผลเป็น JSON")
    parser.add_argument("--velocity", action="store_true",
                        help="วัดความเร็ว feed จริง (รอ 5 นาทีระหว่างดึง)")
    parser.add_argument("--wait", type=int, default=5,
                        help="จำนวนนาทีรอระหว่างการวัด velocity (default: 5)")
    args = parser.parse_args()

    session = requests.Session()

    # probe หน้าหลักก่อน
    result = inspect_homepage(session)

    if result:
        analyze_feed_timing(result.get("sample_novels", []))

    # probe URL candidates
    probe_feed_urls(session)

    # วัด velocity ถ้าขอ
    if args.velocity and result and result.get("feed_links"):
        best_feed = result["feed_links"][0]["href"] if result["feed_links"] else BASE_URL
        measure_feed_velocity(session, best_feed, args.wait)

    if args.save and result:
        out = f"mynovel_feed_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n[*] บันทึกแล้ว: {out}")

    print("\n[*] เสร็จสิ้น")
    print("     หากต้องการวัดความเร็ว feed จริง:")
    print("     python mynovel_feed_inspector.py --velocity --wait 5")


if __name__ == "__main__":
    main()
