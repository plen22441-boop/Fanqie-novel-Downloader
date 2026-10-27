#!/usr/bin/env python3
"""
schedule_calculator.py — คำนวณตารางเวลาโพสต์นิยายให้ติด Feed ตลอดวัน

กลยุทธ์: ใช้นิยายเรื่อง A (เหยื่อล่อ) โพสต์ถี่ ๆ เพื่อดึงคนเข้า profile
          คนเห็นนิยายเรื่อง B, C, D บน profile → traffic รอง

ข้อมูล Feed Velocity จากการสำรวจจริง (mynovel.co, 27 ต.ค. 2026, ~08:00 น.):
  - ช่วง 7:58–8:04 น. (off-peak เช้า): มีนิยายใหม่ขึ้น feed ~4-5 เรื่อง ใน 6 นาที
  - Velocity เช้า: ~0.7 เรื่อง/นาที
  - คาดการณ์ช่วง peak 20:00–23:00 น.: 3–5× เร็วกว่า → ~2–3.5 เรื่อง/นาที

Usage:
    python schedule_calculator.py
    python schedule_calculator.py --chapters 150 --interval 5 --start 10:00
    python schedule_calculator.py --multi  # วางแผนหลายเรื่องสลับกัน
    python schedule_calculator.py --real   # แสดงผลอิง feed velocity จริง
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

# ── Feed Velocity จริงจาก mynovel.co (วัดเมื่อ 27 ต.ค. 2026, 08:00 น.) ────────
# จำนวนนิยายใหม่ที่ขึ้น feed ต่อนาที แยกตามช่วงเวลา (ประมาณการ)
FEED_VELOCITY = {
    # hour: posts_per_minute (ประมาณการ)
    0:  0.2,   1: 0.1,   2: 0.1,   3: 0.1,
    4:  0.1,   5: 0.2,   6: 0.3,   7: 0.5,
    8:  0.7,   9: 0.8,  10: 0.8,  11: 1.0,   # ← วัดได้จริงที่ ~0.7/min ที่ 8 AM
    12: 1.5,  13: 1.2,  14: 0.9,  15: 1.0,
    16: 1.2,  17: 1.5,  18: 2.0,  19: 2.5,
    20: 3.0,  21: 3.5,  22: 3.0,  23: 2.5,   # ← peak คาดการณ์ 3–3.5/min
}


def posts_per_min(hour: int) -> float:
    return FEED_VELOCITY.get(hour, 0.5)


def safe_interval_min(hour: int, target_rank: int = 5) -> float:
    """
    คำนวณว่าต้องโพสต์ทุกกี่นาทีเพื่ออยู่ใน top N ของ feed
    target_rank=1 → อยู่อันดับ 1, target_rank=5 → อยู่ใน top 5
    """
    v = posts_per_min(hour)
    if v <= 0:
        return 999
    return target_rank / v


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

    per_novel = defaultdict(int)
    for _, title, _ in slots:
        per_novel[title] += 1
    print("\n  สรุปตอนที่จะโพสต์แต่ละเรื่อง:")
    for title, count in per_novel.items():
        print(f"    • {title}: {count} ตอน")

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


# ── Real feed velocity report ──────────────────────────────────────────────────

def print_real_velocity_report():
    """
    แสดงผลการวิเคราะห์ feed velocity จริงและ interval ที่แนะนำแต่ละช่วงเวลา
    อิงข้อมูลจากสกรีนช็อต mynovel.co (27 ต.ค. 2026 เวลา ~08:00 น.)
    """
    print(f"\n{'='*72}")
    print(f"  🔬 Feed Velocity จริงของ mynovel.co + Interval ที่แนะนำ")
    print(f"{'='*72}")
    print(f"  📸 ข้อมูลจากสกรีนช็อตจริง วันที่ 27 ต.ค. 2026 เวลา 07:58–08:05 น.")
    print(f"     • ใน 6 นาที มีนิยายใหม่ขึ้น top feed ~4–5 เรื่อง")
    print(f"     • Velocity ช่วงเช้า (off-peak): ~0.7 เรื่อง/นาที")
    print(f"     • Velocity ช่วง peak 20–23น. (คาดการณ์): ~3–3.5 เรื่อง/นาที")
    print(f"{'='*72}")
    print()
    print(f"  {'ช่วงเวลา':^12}  {'Velocity':^15}  {'Top1 ทุก':^10}  {'Top3 ทุก':^10}  {'Top10 ทุก':^10}")
    print(f"  {'-'*12}  {'-'*15}  {'-'*10}  {'-'*10}  {'-'*10}")

    SHOW_HOURS = [6, 8, 10, 12, 15, 17, 18, 19, 20, 21, 22, 23]
    for h in SHOW_HOURS:
        v = posts_per_min(h)
        stars = peak_icon(h)
        t1 = safe_interval_min(h, 1)
        t3 = safe_interval_min(h, 3)
        t10 = safe_interval_min(h, 10)
        t1_str = f"{t1:.0f} นาที" if t1 < 60 else f"{t1/60:.1f} ชม."
        t3_str = f"{t3:.0f} นาที" if t3 < 60 else f"{t3/60:.1f} ชม."
        t10_str = f"{t10:.0f} นาที" if t10 < 60 else f"{t10/60:.1f} ชม."
        label = f"{h:02d}:00 {stars}"
        print(f"  {label:<14}  {v:.1f}/นาที       {t1_str:<10}  {t3_str:<10}  {t10_str}")

    print()
    print(f"{'='*72}")
    print(f"  💡 กลยุทธ์ที่แนะนำสำหรับ 'เหยื่อล่อ':")
    print(f"{'='*72}")
    print()
    print(f"  ✅ ช่วงเช้า–กลางวัน (06:00–17:00): โพสต์ทุก 5–7 นาที")
    print(f"     → อยู่ใน top 3–5 ได้สบาย ๆ ด้วยตอนน้อยกว่า")
    print()
    print(f"  ⚡ ช่วง pre-peak (17:00–19:00): โพสต์ทุก 3–4 นาที")
    print(f"     → คนเริ่มมากขึ้น ต้องถี่ขึ้น")
    print()
    print(f"  🔥 ช่วง peak (19:00–23:00): โพสต์ทุก 1–2 นาที")
    print(f"     → Competition สูงมาก ถ้าอยากอยู่ top 3 ต้องถี่มาก")
    print(f"     → แนะนำ: ยอมอยู่ top 5–10 ก็พอ (โพสต์ทุก 3 นาที)")
    print()
    print(f"  📦 จำนวนตอนที่ต้องการ (เหยื่อล่อ 1 วัน เริ่ม 08:00–23:00):")
    print(f"     • โพสต์ทุก 3 นาที: ~300 ตอน")
    print(f"     • โพสต์ทุก 5 นาที: ~180 ตอน")
    print(f"     • โพสต์ทุก 7 นาที: ~130 ตอน")
    print()
    print(f"  🎯 แผนที่ practical ที่สุด (180 ตอน, interval ผสม):")
    print(f"     06:00–17:00 (11 ชม.) → ทุก 7 นาที = ~94 ตอน")
    print(f"     17:00–19:00 (2 ชม.)  → ทุก 4 นาที = ~30 ตอน")
    print(f"     19:00–23:00 (4 ชม.)  → ทุก 3 นาที = ~80 ตอน")
    print(f"     รวม: ~204 ตอน  ครอบทุก peak hour")
    print(f"{'='*72}")


def print_bait_schedule(chapters_bait: int = 200, start: str = "08:00"):
    """สร้างตารางโพสต์ผสม interval สำหรับเหยื่อล่อ"""
    base = datetime.strptime(start, "%H:%M").replace(year=2000, month=1, day=1)

    # กำหนด interval แต่ละช่วง
    intervals = []
    for delta_h in range(18):  # 08:00–02:00 (18 ชั่วโมง)
        h = (base.hour + delta_h) % 24
        v = posts_per_min(h)
        # เลือก interval ให้อยู่ top ~5
        target_interval = max(3, min(9, round(safe_interval_min(h, 5))))
        intervals.append((h, target_interval))

    # สร้าง schedule
    schedule = []
    current = base
    chapter_no = 1
    for h, interval_min in intervals:
        # โพสต์ 1 ชั่วโมง ด้วย interval นี้
        end_hour = current + timedelta(hours=1)
        while current < end_hour and chapter_no <= chapters_bait:
            schedule.append((current, chapter_no, interval_min))
            chapter_no += 1
            current += timedelta(minutes=interval_min)
        if chapter_no > chapters_bait:
            break

    if not schedule:
        return

    print(f"\n{'='*65}")
    print(f"  🎯 ตาราง Bait Novel — ปรับ interval ตาม feed velocity จริง")
    print(f"  จำนวนตอน: {chapters_bait}  |  เริ่ม: {start}")
    print(f"{'='*65}")
    print(f"\n  {'เวลา':^7}  {'Peak':^12}  {'Interval':^10}  {'ตอนที่'}")
    print(f"  {'-'*7}  {'-'*12}  {'-'*10}  {'-'*6}")

    prev_interval = -1
    for s_time, ch_no, iv in schedule:
        if iv != prev_interval:
            stars = peak_icon(s_time.hour)
            print(f"  {fmt_time(s_time)}    {stars:<12}  ทุก {iv} นาที    ตอนที่ {ch_no}")
            prev_interval = iv

    last = schedule[-1]
    print(f"\n  สิ้นสุด: {fmt_time(last[0])}  (ตอนที่ {last[1]})")
    all_dt = [s[0] for s in schedule]
    score = coverage_score(all_dt)
    print(f"  Peak coverage: {score['pct']}%")
    print(f"{'='*65}")


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="คำนวณตารางโพสต์นิยายให้ติด Feed")
    parser.add_argument("--chapters", type=int, default=100)
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument("--start", default="08:00")
    parser.add_argument("--title", default="นิยายเรื่องหลัก")
    parser.add_argument("--multi", action="store_true", help="โหมดหลายเรื่องสลับกัน")
    parser.add_argument("--compare", action="store_true", help="เปรียบเทียบทุก interval 3-9 นาที")
    parser.add_argument("--real", action="store_true",
                        help="แสดงผลอิง feed velocity จริงจาก mynovel.co")
    parser.add_argument("--bait", action="store_true",
                        help="สร้างตารางโพสต์เหยื่อล่อแบบปรับ interval อัตโนมัติ")
    args = parser.parse_args()

    if args.real:
        print_real_velocity_report()
        return

    if args.bait:
        print_bait_schedule(args.chapters, args.start)
        return

    if args.compare:
        print_interval_comparison(args.chapters, args.start)
        return

    if args.multi:
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
