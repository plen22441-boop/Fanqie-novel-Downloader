#!/usr/bin/env python3
"""จำลองนักอ่าน My Novel 100 คน จาก book_profile.json

ตัวอย่าง:
    python simulate_readers.py reader_sim/examples/book_profile.example.json
    python simulate_readers.py profile.json --comments comments.json --out reports/my_book
    python simulate_readers.py --vocab      # ดูรายการมิติ/แนว/พล็อตที่ใช้ได้
"""

import argparse
import json
import os
import sys

from reader_sim import DIMENSIONS, GENRES, TROPES, run
from reader_sim.report import to_html, to_markdown


def main():
    ap = argparse.ArgumentParser(description="จำลองนักอ่าน My Novel 100 คน")
    ap.add_argument("profile", nargs="?", help="ไฟล์ book_profile.json")
    ap.add_argument("--comments", help="JSON {reader_id: ความเห็น} สำหรับใส่ในรายงาน")
    ap.add_argument("--out", help="โฟลเดอร์ผลลัพธ์ (ค่าเริ่มต้น: reports/<ชื่อไฟล์>)")
    ap.add_argument("--seed", type=int, default=2024)
    ap.add_argument("--iterations", type=int, default=300, help="จำนวนรอบ Monte Carlo")
    ap.add_argument("--vocab", action="store_true", help="แสดงมิติ/แนว/พล็อตที่ใช้ได้")
    args = ap.parse_args()

    if args.vocab:
        for name, vocab in (("scores", DIMENSIONS), ("genres", GENRES), ("tropes", TROPES)):
            print(f"[{name}]")
            for k, v in vocab.items():
                print(f"  {k:20s} {v}")
        return
    if not args.profile:
        ap.error("ต้องระบุไฟล์ profile")

    with open(args.profile, encoding="utf-8") as f:
        book = json.load(f)
    comments = {}
    if args.comments:
        with open(args.comments, encoding="utf-8") as f:
            comments = json.load(f)

    try:
        res = run(book, seed=args.seed, iterations=args.iterations)
    except ValueError as exc:
        sys.exit(f"profile ไม่ถูกต้อง: {exc}")

    out = args.out or os.path.join("reports", os.path.splitext(os.path.basename(args.profile))[0])
    os.makedirs(out, exist_ok=True)
    md = to_markdown(res)
    with open(os.path.join(out, "report.md"), "w", encoding="utf-8") as f:
        f.write(md)
    with open(os.path.join(out, "report.html"), "w", encoding="utf-8") as f:
        f.write(to_html(res, comments))
    with open(os.path.join(out, "results.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(md)
    print(f"บันทึกรายงานที่ {out}/ (report.html, report.md, results.json)")


if __name__ == "__main__":
    main()
