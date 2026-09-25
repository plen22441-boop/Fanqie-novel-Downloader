"""
ตรวจสอบความสมบูรณ์ของไฟล์นิยายที่ดาวน์โหลดจาก Fanqie Novel Downloader

การใช้งาน:
    python validate_novel.py <ชื่อไฟล์.txt>
    python validate_novel.py                    (จะถามชื่อไฟล์)
"""

import sys
import os
import re
from collections import Counter


SHORT_THRESHOLD = 200   # ตัวอักษร — ถ้าน้อยกว่านี้ถือว่าสั้นผิดปกติ
HASH_SAMPLE = 2000      # ใช้ N ตัวอักษรแรกในการ hash เพื่อตรวจซ้ำ


def parse_novel(text: str) -> tuple[list[dict], str | None, str | None]:
    """แยกตอนออกจากเนื้อหาไฟล์ คืน (chapters, book_title, book_author)"""
    lines = text.splitlines()
    chapters: list[dict] = []
    cur = None
    header_lines: list[str] = []

    for line in lines:
        t = line.strip()
        m_num = re.match(r'^第(\d+)章\s*(.*)', t)
        m_spc = re.match(r'^(番外|特别篇|if线)[\d\s]*(.*)', t) if not m_num else None

        if m_num or m_spc:
            if cur:
                chapters.append(cur)
            cur = {
                "title": t,
                "num": int(m_num.group(1)) if m_num else None,
                "special": bool(m_spc),
                "content": "",
                "issues": [],
            }
        elif cur is not None:
            cur["content"] += (t + "\n") if t else "\n"
        else:
            header_lines.append(line)

    if cur:
        chapters.append(cur)

    header = "\n".join(header_lines)
    tm = re.search(r'书名[：:]\s*[《]?([^》\n]+)[》]?', header)
    am = re.search(r'作者[：:]\s*([^\n]+)', header)

    return chapters, (tm.group(1).strip() if tm else None), (am.group(1).strip() if am else None)


def analyze(chapters: list[dict]) -> dict:
    """วิเคราะห์ปัญหาในรายการตอน"""
    # หาตอนที่หาย (gap ในลำดับ)
    numbered = sorted([c for c in chapters if c["num"] is not None], key=lambda c: c["num"])
    missing: list[int] = []
    for i in range(len(numbered) - 1):
        for n in range(numbered[i]["num"] + 1, numbered[i + 1]["num"]):
            missing.append(n)

    # ตรวจเนื้อหาสั้น / ว่าง
    for c in chapters:
        length = len(c["content"].strip())
        if length == 0:
            c["issues"].append(("empty", "ว่างเปล่า"))
        elif length < SHORT_THRESHOLD:
            c["issues"].append(("short", f"สั้นเกินไป ({length} ตัวอักษร)"))

    # ตรวจเนื้อหาซ้ำ (FNV-1a hash จาก N ตัวอักษรแรก)
    seen: dict[int, dict] = {}
    for c in chapters:
        tc = c["content"].strip()
        if not tc:
            continue
        h = _fnv1a(tc[:HASH_SAMPLE])
        if h in seen:
            c["issues"].append(("dup", f'ซ้ำกับ "{seen[h]["title"][:25]}…"'))
        else:
            seen[h] = c

    issue_chaps = [c for c in chapters if c["issues"]]
    return {"missing": missing, "issue_chaps": issue_chaps}


def _fnv1a(s: str) -> int:
    h = 0x811C9DC5
    for ch in s:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def print_report(filepath: str, chapters: list[dict], book_title: str | None,
                 book_author: str | None, missing: list[int], issue_chaps: list[dict]) -> None:
    size = os.path.getsize(filepath)
    size_str = f"{size/1024:.1f} KB" if size < 1_048_576 else f"{size/1048576:.2f} MB"

    sep = "─" * 60
    print(f"\n{sep}")
    print("  รายงานการตรวจสอบไฟล์นิยาย")
    print(sep)
    print(f"  ไฟล์   : {os.path.basename(filepath)}  ({size_str})")
    if book_title:
        print(f"  ชื่อเรื่อง: {book_title}")
    if book_author:
        print(f"  ผู้แต่ง  : {book_author}")
    print(sep)

    short_n = sum(1 for c in issue_chaps if any(k == "short" or k == "empty" for k, _ in c["issues"]))
    dup_n   = sum(1 for c in issue_chaps if any(k == "dup" for k, _ in c["issues"]))

    status_total = "✓" if not issue_chaps and not missing else "─"
    status_miss  = "✗" if missing  else "✓"
    status_short = "⚠" if short_n  else "✓"
    status_dup   = "⚠" if dup_n    else "✓"

    print(f"  {status_total}  ตอนทั้งหมด      : {len(chapters)}")
    print(f"  {status_miss}  ตอนที่หายไป     : {len(missing)}")
    print(f"  {status_short}  เนื้อหาสั้น/ว่าง : {short_n}")
    print(f"  {status_dup}  เนื้อหาซ้ำ      : {dup_n}")
    print(sep)

    if missing:
        print("\n  ตอนที่หายไป:")
        chunks = [missing[i:i+10] for i in range(0, len(missing), 10)]
        for chunk in chunks:
            print("    " + "  ".join(f"ตอน {n}" for n in chunk))

    if issue_chaps:
        print("\n  ตอนที่มีปัญหา:")
        for c in issue_chaps:
            issues_str = ", ".join(label for _, label in c["issues"])
            print(f"    [{c['num'] if c['num'] else 'พิเศษ'}] {c['title'][:40]:<40}  — {issues_str}")

    if not missing and not issue_chaps:
        print("\n  ✓ ไฟล์ผ่านการตรวจสอบทั้งหมด — ไม่พบปัญหา")

    print(f"\n{sep}\n")


def main() -> None:
    if len(sys.argv) >= 2:
        filepath = sys.argv[1]
    else:
        filepath = input("ป้อนชื่อไฟล์ .txt: ").strip().strip('"')

    if not os.path.isfile(filepath):
        print(f"ไม่พบไฟล์: {filepath}")
        sys.exit(1)

    print(f"กำลังอ่านไฟล์ {filepath} …")
    with open(filepath, encoding="utf-8", errors="replace") as f:
        text = f.read()

    chapters, book_title, book_author = parse_novel(text)

    if not chapters:
        print("ไม่พบตอนในไฟล์นี้ กรุณาตรวจสอบว่าเป็นไฟล์นิยายที่โหลดจาก Fanqie Novel Downloader")
        sys.exit(1)

    result = analyze(chapters)
    print_report(filepath, chapters, book_title, book_author, **result)


if __name__ == "__main__":
    main()
