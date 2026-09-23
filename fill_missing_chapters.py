#!/usr/bin/env python3
"""
fill_missing_chapters.py

สคริปต์สำหรับดาวน์โหลดตอนที่หายไปและเสียบเข้าไฟล์นิยาย
รองรับทั้งฟอร์แมต == 第N章 == และ 第N章 (ฟอร์แมตของ downloader นี้)

วิธีใช้:
  python fill_missing_chapters.py <ไฟล์นิยาย.txt> <book_id>

ตัวอย่าง:
  python fill_missing_chapters.py "神豪系统，全职花钱.txt" 7580575371670588440
"""

import re
import sys
import json
import time
import random
import os
import requests

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False


def get_cookie(session):
    """สร้าง cookie สำหรับ Fanqie"""
    cookie_path = os.path.join("data", "cookie.json")
    if os.path.exists(cookie_path):
        try:
            with open(cookie_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, str):
                    return data
        except Exception:
            pass
    novel_web_id = random.randint(10**18, 10**19 - 1)
    return f"novel_web_id={novel_web_id}"


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


def get_headers(cookie):
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Cookie": cookie,
    }


def get_chapter_list(session, book_id, cookie):
    """ดึง chapter list ทั้งหมดจาก Fanqie API"""
    # ลอง API endpoint หลายแบบ
    endpoints = [
        f"https://api5-normal-lf.fqnovel.com/reading/bookapi/detail/v/?book_id={book_id}&aid=1967&app_name=novel_fanqie&version_code=999",
        f"https://api5-normal-lf.fqnovel.com/reading/bookapi/search/{book_id}/v",
        f"https://fanqienovel.com/api/reader/directory/detail?bookId={book_id}",
    ]

    for url in endpoints:
        try:
            resp = session.get(url, headers=get_headers(cookie), timeout=15)
            if resp.status_code != 200:
                continue

            # ลอง parse JSON
            try:
                data = resp.json()
                chapters = _parse_json_chapters(data)
                if chapters:
                    print(f"  ดึงรายการตอนจาก API สำเร็จ ({len(chapters)} ตอน)")
                    return chapters
            except Exception:
                pass

            # ลอง parse HTML (ต้องมี bs4)
            if HAS_BS4:
                soup = BeautifulSoup(resp.text, "html.parser")
                items = soup.select("div.chapter-item")
                if items:
                    chapters = []
                    for idx, item in enumerate(items):
                        a_tag = item.find("a")
                        if a_tag:
                            chapters.append({
                                "id": a_tag["href"].split("/")[-1],
                                "index": idx,
                                "title": a_tag.get_text(strip=True),
                            })
                    if chapters:
                        print(f"  ดึงรายการตอนจาก HTML สำเร็จ ({len(chapters)} ตอน)")
                        return chapters

        except Exception as e:
            print(f"  [ลอง {url[:50]}... ไม่สำเร็จ: {e}]")
            continue

    return []


def _parse_json_chapters(data):
    """แปลง JSON response หลายรูปแบบเป็น chapter list"""
    # รูปแบบ 1: data.data.chapter_list
    if isinstance(data, dict):
        for key in ("data", "result"):
            sub = data.get(key, {})
            if isinstance(sub, dict):
                for ckey in ("chapter_list", "chapterList", "item_ids", "chapters"):
                    clist = sub.get(ckey)
                    if isinstance(clist, list) and clist:
                        return _normalize_chapters(clist)
                # ลองหา list โดยตรงใน sub
                for v in sub.values():
                    if isinstance(v, list) and len(v) > 10:
                        result = _normalize_chapters(v)
                        if result:
                            return result
        # รูปแบบ 2: data โดยตรงเป็น list
        for ckey in ("chapter_list", "chapterList", "chapters"):
            clist = data.get(ckey)
            if isinstance(clist, list) and clist:
                return _normalize_chapters(clist)
    elif isinstance(data, list):
        return _normalize_chapters(data)
    return []


def _normalize_chapters(clist):
    """แปลงให้เป็น list ของ {"id": ..., "index": ...}"""
    result = []
    for idx, item in enumerate(clist):
        if not isinstance(item, dict):
            continue
        chapter_id = (
            item.get("item_id") or item.get("id") or item.get("chapterId")
            or item.get("chapter_id") or item.get("itemId")
        )
        title = (
            item.get("title") or item.get("name") or item.get("chapterName")
            or f"第{idx+1}章"
        )
        if chapter_id:
            result.append({"id": str(chapter_id), "index": idx, "title": title})
    return result


def download_chapter(session, chapter_id, cookie, retries=3):
    """ดาวน์โหลดเนื้อหาของตอนโดยใช้ cengui.cn API"""
    url = f"https://api.cengui.cn/api/tomato/content.php?item_id={chapter_id}"
    for attempt in range(retries):
        try:
            resp = session.get(url, headers=get_headers(cookie), timeout=20)
            data = resp.json()
            if data.get("code") == 200:
                content = data.get("data", {}).get("content", "")
                title = data.get("data", {}).get("title", "")

                # ลบ HTML tags
                content = re.sub(r"<header>.*?</header>", "", content, flags=re.DOTALL)
                content = re.sub(r"<footer>.*?</footer>", "", content, flags=re.DOTALL)
                content = re.sub(r"</?article>", "", content)
                content = re.sub(r'<p idx="\d+">', "\n", content)
                content = re.sub(r"</p>", "\n", content)
                content = re.sub(r"<[^>]+>", "", content)
                content = re.sub(r"\\u003c|\\u003e", "", content)

                if title and content.startswith(title):
                    content = content[len(title):].lstrip()

                content = re.sub(r"\n{2,}", "\n", content).strip()
                content = "\n".join(
                    "    " + line if line.strip() else line
                    for line in content.split("\n")
                )
                return content, title
        except Exception as e:
            if attempt < retries - 1:
                print(f"    [retry {attempt+1}/{retries}: {e}]")
                time.sleep(1.5 * (attempt + 1))
    return None, None


def detect_missing_chapters(file_path):
    """ตรวจหาตอนที่หายไปและตำแหน่งในไฟล์"""
    # รองรับสองฟอร์แมต
    pattern_decorated = re.compile(r"^== 第(\d+)章.*==\s*$")  # == 第N章 ... ==
    pattern_plain = re.compile(r"^第(\d+)章\s")                # 第N章 ...

    chapter_lines = {}  # chapter_num -> line_index (0-based)
    lines = []

    with open(file_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            lines.append(line)
            for pat in (pattern_decorated, pattern_plain):
                m = pat.match(line.strip())
                if m:
                    num = int(m.group(1))
                    chapter_lines[num] = i
                    break

    if not chapter_lines:
        return [], lines, chapter_lines, "unknown"

    present = set(chapter_lines.keys())
    max_ch = max(present)
    missing = sorted(set(range(1, max_ch + 1)) - present)

    # ตรวจฟอร์แมต
    sample_line = lines[next(iter(chapter_lines.values()))].strip()
    fmt = "decorated" if sample_line.startswith("==") else "plain"

    return missing, lines, chapter_lines, fmt


def format_chapter(chapter_num, title, content, fmt):
    """จัดรูปแบบตอนให้ตรงกับไฟล์ต้นฉบับ"""
    # ทำความสะอาด title (เอาเลขตอนออกถ้ามี)
    clean_title = re.sub(r"^第[一二三四五六七八九十百千\d]+章\s*", "", title).strip()
    full_title = f"第{chapter_num:03d}章 {clean_title}" if fmt == "decorated" else f"第{chapter_num}章 {clean_title}"

    if fmt == "decorated":
        header = f"\n== {full_title} ==\n\n"
    else:
        header = f"\n{full_title}\n\n"

    return header + content + "\n\n"


def insert_missing_chapters(lines, chapter_lines, new_chapters_data, fmt):
    """เสียบตอนที่หายไปเข้าในลิสต์ของบรรทัด"""
    for chapter_num in sorted(new_chapters_data.keys()):
        content_block = new_chapters_data[chapter_num]

        # หาตำแหน่งเสียบ: หลังตอนก่อนหน้า
        insert_after_line = None
        for prev_num in range(chapter_num - 1, 0, -1):
            if prev_num in chapter_lines:
                # หาบรรทัดสุดท้ายของตอนก่อนหน้า (ก่อนตอนถัดไปหรือท้ายไฟล์)
                start = chapter_lines[prev_num]
                end = len(lines)
                for next_num in sorted(chapter_lines.keys()):
                    if next_num > prev_num and chapter_lines[next_num] > start:
                        end = chapter_lines[next_num]
                        break
                insert_after_line = end
                break

        if insert_after_line is None:
            print(f"  [เตือน] ไม่พบตำแหน่งเสียบสำหรับตอน {chapter_num}")
            continue

        # เสียบเนื้อหา
        new_lines = content_block.splitlines(keepends=True)
        lines[insert_after_line:insert_after_line] = new_lines

        # อัปเดต chapter_lines สำหรับตอนถัดๆ ไป
        shift = len(new_lines)
        chapter_lines[chapter_num] = insert_after_line
        for k in list(chapter_lines.keys()):
            if chapter_lines[k] >= insert_after_line and k != chapter_num:
                chapter_lines[k] += shift

    return lines


def main():
    if len(sys.argv) < 3:
        print("วิธีใช้: python fill_missing_chapters.py <ไฟล์นิยาย.txt> <fanqie_book_id>")
        print("ตัวอย่าง: python fill_missing_chapters.py novel.txt 7580575371670588440")
        sys.exit(1)

    file_path = sys.argv[1]
    book_id = sys.argv[2]

    if not os.path.exists(file_path):
        print(f"ไม่พบไฟล์: {file_path}")
        sys.exit(1)

    print(f"=== Fill Missing Chapters ===")
    print(f"ไฟล์: {file_path}")
    print(f"Book ID: {book_id}")
    print()

    # 1. ตรวจหาตอนที่หายไป
    print("กำลังตรวจหาตอนที่หายไป...")
    missing, lines, chapter_lines, fmt = detect_missing_chapters(file_path)

    if not missing:
        print("ไม่พบตอนที่หายไป!")
        return

    print(f"พบตอนที่หายไป {len(missing)} ตอน: {missing[0]}-{missing[-1]}")
    print(f"รูปแบบไฟล์: {fmt}")
    print()

    session = requests.Session()
    cookie = get_cookie(session)

    # 2. ดึง chapter list
    print("กำลังดึงรายการตอนจาก Fanqie...")
    chapter_list = get_chapter_list(session, book_id, cookie)

    if not chapter_list:
        print("\nไม่สามารถดึงรายการตอนจาก Fanqie API ได้")
        print("โปรดลองวิธีอื่น:")
        print("  1. ตรวจสอบ book ID ว่าถูกต้อง")
        print("  2. ตรวจสอบการเชื่อมต่ออินเทอร์เน็ต")
        print("  3. ลบไฟล์ data/cookie.json แล้วลองใหม่")
        sys.exit(1)

    print()

    # 3. ดาวน์โหลดตอนที่หายไป
    new_chapters_data = {}
    success = 0
    failed = []

    for ch_num in missing:
        list_index = ch_num - 1  # index ใน chapter_list (0-based)
        if list_index >= len(chapter_list):
            print(f"  ตอน {ch_num}: ไม่พบใน chapter list (index {list_index} เกินขอบเขต)")
            failed.append(ch_num)
            continue

        ch_info = chapter_list[list_index]
        chapter_id = ch_info["id"]
        print(f"  กำลังดาวน์โหลดตอน {ch_num} (ID: {chapter_id})...", end="", flush=True)

        content, api_title = download_chapter(session, chapter_id, cookie)
        if content:
            title = api_title or ch_info.get("title", f"第{ch_num}章")
            formatted = format_chapter(ch_num, title, content, fmt)
            new_chapters_data[ch_num] = formatted
            success += 1
            print(f" สำเร็จ ({title[:30]})")
        else:
            print(f" ล้มเหลว!")
            failed.append(ch_num)

        time.sleep(0.5)  # หน่วงเล็กน้อยเพื่อไม่ให้โดน rate limit

    print()
    print(f"ดาวน์โหลดสำเร็จ: {success}/{len(missing)} ตอน")
    if failed:
        print(f"ล้มเหลว: ตอน {failed}")
    print()

    if not new_chapters_data:
        print("ไม่มีตอนที่ดาวน์โหลดสำเร็จ ยกเลิก")
        sys.exit(1)

    # 4. สำรองไฟล์เดิม
    backup_path = file_path + ".backup"
    print(f"กำลังสำรองไฟล์เดิมเป็น {backup_path}...")
    with open(file_path, "r", encoding="utf-8") as f:
        backup_content = f.read()
    with open(backup_path, "w", encoding="utf-8") as f:
        f.write(backup_content)

    # 5. เสียบตอนที่หายไปเข้าไฟล์
    print("กำลังเสียบตอนที่ดาวน์โหลดเข้าในไฟล์...")
    updated_lines = insert_missing_chapters(lines, chapter_lines, new_chapters_data, fmt)

    with open(file_path, "w", encoding="utf-8") as f:
        f.writelines(updated_lines)

    # 6. ตรวจสอบผล
    print("กำลังตรวจสอบผล...")
    still_missing, _, _, _ = detect_missing_chapters(file_path)
    still_missing_target = [c for c in still_missing if c in missing]

    if not still_missing_target:
        print(f"\nสำเร็จ! เสียบครบทุกตอนแล้ว")
    else:
        print(f"\nยังขาด: {still_missing_target}")

    print(f"ไฟล์บันทึกที่: {file_path}")
    print(f"ไฟล์สำรอง:    {backup_path}")


if __name__ == "__main__":
    main()
