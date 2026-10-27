#!/usr/bin/env python3
"""
schedule_calculator.py — คำนวณตารางเวลาโพสต์นิยายให้ติด Feed ตลอดวัน

กลยุทธ์: ใช้นิยายเรื่อง A (เหยื่อล่อ) โพสต์ถี่ ๆ เพื่อดึงคนเข้า profile
          คนเห็นนิยายเรื่อง B, C, D บน profile → traffic รอง

Usage:
    python schedule_calculator.py
    python schedule_calculator.py --chapters 150 --interval 5 --start 10:00
    python schedule_calculator.py --multi  # วางแผนหลายเรื่องสลับกัน
"""

import argparse
from datetime import datetime, timedelta
from collections import defaultdict


# ── Peak hours ของนักอ่านไทย (ข้อมูลจาก Dek-D / Joylada research) ─────────────
PEAK_HOURS = {
    6:  1,   7:  2,   8:  2,
    9:  1,  10:  1,  11:  2,
    12: 3,  13:  2,  14:  1,
    15: 2,  16:  2,  17:  3,
    18: 3,  19:  4,  20:  5,
    21: 5,  22:  4,  23:  3,
}
MAX_PEAK = 5


def peak_icon(hour):
    level = PEAK_HOURS.get(hour, 0)
    return "⭐" * level if level else "  "


def fmt_time(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def coverage_score(schedules: list[datetime]) -> dict:
    """คำนวณ % ที่ครอบ peak hours"""
    covered_peak = 0
    total_peak = sum(v for v in PEAK_HOURS.values())
    hour_hits = defaultdict(int)
    for s in schedules:
        hour_hits[s.hour] += 1
    for h, peak in PEAK_HOURS.items():
        if hour_hits.get(h, 0) > 0:
            covered_peak += peak
    return {
        "covered_peak_weight": covered_peak,
        "total_peak_weight": total_peak,
        "pct": round(covered_peak / total_peak * 100, 1),
        "hour_hits": dict(hour_hits),
    }


# ── Single novel schedule ──────────────────────────────────────────────────────

def calc_single(chapters: int, interval_min: int, start: str, title: str = "นิยาย A") -> list[datetime]:
    base = datetime.strptime(start, "%H:%M").replace(year=2000, month=1, day=1)
    schedule = [base + timedelta(minutes=i * interval_min) for i in range(chapters)]
    return schedule


def print_single_report(title: str, chapters: int, interval: int, start: str):
    schedule = calc_single(chapters, interval, start, title)
    end = schedule[-1]
    duration_h = (end - schedule[0]).seconds / 3600
    score = coverage_score(schedule)

    print(f"\n{'='*60}")
    print(f"  📚 {title}")
    print(f"  จำนวนตอน: {chapters}  |  Interval: {interval} นาที")
    print(f"  เริ่ม: {fmt_time(schedule[0])}  →  จบ: {fmt_time(end)}")
    print(f"  ครอบเวลาได้: {duration_h:.1f} ชั่วโมง")
    print(f"  Peak coverage: {score['pct']}%")
    print(f"{'='*60}")

    print(f"\n  {'เวลา':^7}  {'Peak':^12}  {'ตอนที่'}")
    print(f"  {'-'*7}  {'-'*12}  {'-'*6}")
    prev_hour = -1
    shown = 0
    for i, s in enumerate(schedule, 1):
        if s.hour != prev_hour:
            stars = peak_icon(s.hour)
            label = PEAK_HOURS.get(s.hour, 0)
            print(f"  {fmt_time(s)}    {stars:<12}  ตอนที่ {i}")
            prev_hour = s.hour
            shown += 1
        if shown > 20:
            remaining = chapters - i
            print(f"  ... (ยังมีอีก {remaining} ตอน จนถึง {fmt_time(end)})")
            break


# ── Multi-novel rotation schedule ─────────────────────────────────────────────

def calc_multi_rotation(novels: list[dict], start: str, end_str: str) -> list[tuple]:
    """
    สลับโพสต์หลายเรื่อง เพื่อให้แต่ละเรื่องขึ้น feed ทีละรอบ
    novels = [{"title": "A", "chapters": 100, "interval": 3}, ...]
    """
    base = datetime.strptime(start, "%H:%M").replace(year=2000, month=1, day=1)
    end_dt = datetime.strptime(end_str, "%H:%M").replace(year=2000, month=1, day=1)
    if end_dt <= base:
        end_dt += timedelta(days=1)

    slots = []  # (datetime, novel_title, chapter_no)
    novel_counters = [0] * len(novels)
    current = base

    while current <= end_dt:
        for i, novel in enumerate(novels):
            if novel_counters[i] < novel["chapters"]:
                slots.append((current, novel["title"], novel_counters[i] + 1))
                novel_counters[i] += 1
                current += timedelta(minutes=novel.get("interval", 5))
            # ถ้าตอนหมดแล้ว ข้ามไปเรื่องถัดไป

        # ถ้าทุกเรื่องตอนหมดแล้ว หยุด
        if all(novel_counters[i] >= novels[i]["chapters"] for i in range(len(novels))):
            break

    return slots


def print_multi_report(novels: list[dict], start: str, end_str: str = "23:30"):
    slots = calc_multi_rotation(novels, start, end_str)
    if not slots:
        print("  ไม่มีตอนให้โพสต์")
        return

    print(f"\n{'='*65}")
    print(f"  📅 ตารางสลับโพสต์หลายเรื่อง  {start} – {end_str}")
    print(f"  รวมทั้งหมด: {len(slots)} ตอน")
    print(f"{'='*65}")

    # สรุปแต่ละเรื่อง
    per_novel = defaultdict(int)
    for _, title, _ in slots:
        per_novel[title] += 1
    print("\n  สรุปตอนที่จะโพสต์แต่ละเรื่อง:")
    for title, count in per_novel.items():
        print(f"    • {title}: {count} ตอน")

    # timeline ย่อ (แสดงทุก 30 นาที)
    print(f"\n  {'เวลา':^7}  {'Peak':^12}  {'เรื่อง + ตอน'}")
    print(f"  {'-'*7}  {'-'*12}  {'-'*25}")
    prev_half = -1
    for s_time, title, ch_no in slots:
        half = s_time.hour * 2 + (1 if s_time.minute >= 30 else 0)
        if half != prev_half:
            stars = peak_icon(s_time.hour)
            print(f"  {fmt_time(s_time)}    {stars:<12}  {title} ตอน {ch_no}")
            prev_half = half

    last_time = slots[-1][0]
    print(f"\n  สิ้นสุด: {fmt_time(last_time)}")
    all_schedules = [s[0] for s in slots]
    score = coverage_score(all_schedules)
    print(f"  Peak coverage: {score['pct']}%")


# ── Interval comparison ────────────────────────────────────────────────────────

def print_interval_comparison(chapters: int, start: str = "08:00"):
    print(f"\n{'='*65}")
    print(f"  📊 เปรียบเทียบ Interval  |  {chapters} ตอน  |  เริ่ม {start}")
    print(f"{'='*65}")
    print(f"  {'Interval':^10}  {'ครอบ (ชม.)':^12}  {'จบเวลา':^8}  {'Peak%':^8}")
    print(f"  {'-'*10}  {'-'*12}  {'-'*8}  {'-'*8}")

    for interval in [3, 4, 5, 6, 7, 8, 9]:
        schedule = calc_single(chapters, interval, start)
        end = schedule[-1]
        duration_h = (end - schedule[0]).seconds / 3600
        score = coverage_score(schedule)
        end_str = fmt_time(end)
        bar = "█" * int(score["pct"] / 10)
        print(f"  {interval} นาที      {duration_h:^12.1f}  {end_str:^8}  {score['pct']:>5.0f}%  {bar}")


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="คำนวณตารางโพสต์นิยายให้ติด Feed")
    parser.add_argument("--chapters", type=int, default=100)
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument("--start", default="08:00")
    parser.add_argument("--title", default="นิยายเรื่องหลัก")
    parser.add_argument("--multi", action="store_true", help="โหมดหลายเรื่องสลับกัน")
    parser.add_argument("--compare", action="store_true", help="เปรียบเทียบทุก interval 3-9 นาที")
    args = parser.parse_args()

    if args.compare:
        print_interval_comparison(args.chapters, args.start)
        return

    if args.multi:
        # ตัวอย่าง: สลับ 3 เรื่อง
        novels = [
            {"title": "เหยื่อล่อ (โพสต์ถี่)", "chapters": args.chapters, "interval": 3},
            {"title": "นิยาย B (โปรไฟล์)", "chapters": max(1, args.chapters // 3), "interval": 3},
            {"title": "นิยาย C (โปรไฟล์)", "chapters": max(1, args.chapters // 3), "interval": 3},
        ]
        print_multi_report(novels, args.start)
    else:
        print_interval_comparison(args.chapters, args.start)
        print_single_report(args.title, args.chapters, args.interval, args.start)


if __name__ == "__main__":
    main()
