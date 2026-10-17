"""จำลองตารางเวลาปล่อยตอนตลอด 24 ชั่วโมง — เพื่อให้ปรากฏใน feed นักอ่านได้ตลอดวัน

เป้าหมาย:
  1. ครอบทุกช่วงเวลาที่นักอ่านไทยเปิดแอป (peak hours)
  2. "หลอกหลอน" feed — ไม่ว่าจะเปิดแอปตอนไหนก็เจอเรา
  3. เพิ่มโอกาสกด profile → อ่านเรื่องอื่นของเรา (cross-title discovery)

CLI:
    python -m reader_sim.schedule_optimizer --chapters-per-day 12
    python -m reader_sim.schedule_optimizer --chapters-per-day 8 --show-heatmap
"""

from __future__ import annotations
import math, random
from dataclasses import dataclass, field
from typing import List, Dict

# ---------------------------------------------------------------------------
# โปรไฟล์กิจกรรมนักอ่านไทยรายชั่วโมง (ค่าสัมพัทธ์ 0–10)
# อ้างอิงจากพฤติกรรมทั่วไปของแพลตฟอร์มนิยายไทย
# ---------------------------------------------------------------------------
#              0  1  2  3  4  5  6  7  8  9  10 11 12 13 14 15 16 17 18 19 20 21 22 23
HOURLY_TRAFFIC = [
    1, 0, 0, 0, 0, 1, 2, 5, 7, 6,  5,  5,  8,  7,  5,  5,  6,  7,  8,  9, 10,  9,  7,  3
]
# peak: 20.00 (10), 19.00 (9), 21.00 (9), 12.00/18.00 (8), 7-9 เช้า (5-7)

PEAK_LABEL = {
    range(6,  9):  "เช้า (ระหว่างเดินทาง)",
    range(11, 14): "เที่ยง (พักกลางวัน)",
    range(17, 20): "เย็น (กลับบ้าน)",
    range(20, 24): "ดึก (ก่อนนอน)",
}

def peak_name(hour: int) -> str:
    for r, label in PEAK_LABEL.items():
        if hour in r:
            return label
    return "นอกช่วง peak"

# ---------------------------------------------------------------------------
# ฟังก์ชันหลัก
# ---------------------------------------------------------------------------

@dataclass
class ReleaseSlot:
    hour: int
    minute: int
    traffic_score: float       # ระดับ traffic ณ เวลานั้น (0–10)
    visibility_minutes: float  # นาทีที่คาดว่าจะอยู่ใน feed ก่อนถูกดันลง
    expected_views: float      # ยอดวิวที่คาดต่อตอน
    profile_visits: float      # โอกาสที่นักอ่านจะกด profile (0–1)
    peak_label: str

    def time_str(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}"


def calc_visibility(traffic: float, chapters_per_day: int) -> float:
    """ประมาณนาทีที่ตอนนี้จะอยู่ใน top feed ก่อนถูกดัน
    ยิ่ง traffic สูงและปล่อยบ่อย ยิ่งอยู่ได้สั้น"""
    base = 120  # 2 ชั่วโมงถ้าไม่มีคู่แข่ง
    competition_penalty = chapters_per_day * 3  # แต่ละตอนที่ปล่อยดันคนอื่นลง
    traffic_boost = traffic * 2
    return max(20, base - competition_penalty + traffic_boost)


def optimize_schedule(
    chapters_per_day: int = 12,
    seed: int = 2024,
) -> List[ReleaseSlot]:
    """
    กระจาย chapters_per_day ตอนให้ครอบ peak hours ตลอดวัน
    โดยให้ priority กับช่วงที่มี traffic สูง แต่ยังมีช่องว่างพอ
    """
    rng = random.Random(seed)

    # สร้าง candidate slots ทุกครึ่งชั่วโมงตลอด 24 ชั่วโมง
    slots_48: List[tuple] = []  # (hour, minute, traffic)
    for h in range(24):
        t = HOURLY_TRAFFIC[h]
        for m in [0, 30]:
            # traffic ครึ่งชั่วโมงที่สอง: blend กับชั่วโมงถัดไป
            if m == 30:
                next_h = (h + 1) % 24
                t_adj = (HOURLY_TRAFFIC[h] + HOURLY_TRAFFIC[next_h]) / 2
            else:
                t_adj = float(t)
            slots_48.append((h, m, t_adj))

    # อัลกอริทึม greedy: เลือก slot ที่ให้ coverage ดีที่สุด
    # หลักการ: ช่วงเวลาที่ห่างจาก slot ที่เลือกไปแล้วมากที่สุด + traffic สูง
    selected: List[tuple] = []

    # กำหนดจุดเริ่มต้นที่ peak สูงสุด (20:00)
    selected.append((20, 0, HOURLY_TRAFFIC[20]))
    remaining = [s for s in slots_48 if s not in selected]

    while len(selected) < chapters_per_day and remaining:
        best = None
        best_score = -1
        for cand in remaining:
            ch, cm, ct = cand
            cand_mins = ch * 60 + cm
            # ระยะห่างจาก slot ที่ใกล้ที่สุดที่เลือกไปแล้ว (วนรอบ 24 ชม)
            min_dist = min(
                min(
                    abs(cand_mins - (sh * 60 + sm)),
                    1440 - abs(cand_mins - (sh * 60 + sm))
                )
                for sh, sm, _ in selected
            )
            # score: ระยะห่าง (อยากกระจาย) + traffic (อยากโดน traffic)
            score = min_dist * 0.6 + ct * 10
            if score > best_score:
                best_score = score
                best = cand
        if best:
            selected.append(best)
            remaining = [s for s in remaining if s != best]

    # จัดเรียงตามเวลา
    selected.sort(key=lambda x: x[0] * 60 + x[1])

    # สร้าง ReleaseSlot objects
    result = []
    for h, m, t in selected:
        vis = calc_visibility(t, chapters_per_day)
        # ยอดวิวสัมพัทธ์: traffic × visibility × random factor
        views = t * (vis / 60) * rng.uniform(0.8, 1.2) * 15
        # profile click: traffic สูง + visibility นาน = มีโอกาสสูง
        profile_p = min(0.95, (t / 10) * 0.4 + (vis / 120) * 0.3 + 0.15)
        result.append(ReleaseSlot(
            hour=h, minute=m,
            traffic_score=round(t, 1),
            visibility_minutes=round(vis),
            expected_views=round(views, 1),
            profile_visits=round(profile_p, 2),
            peak_label=peak_name(h),
        ))
    return result


def print_schedule(slots: List[ReleaseSlot], chapters_per_day: int) -> None:
    total_views = sum(s.expected_views for s in slots)
    avg_gap = 1440 / len(slots)
    covered_hours = len(set(s.hour for s in slots))

    print(f"\n{'='*70}")
    print(f"  ตารางปล่อยตอน {chapters_per_day} ตอน/วัน — กลยุทธ์ Feed Domination")
    print(f"  ครอบ {covered_hours}/24 ชั่วโมง | ช่วงห่างเฉลี่ย {avg_gap:.0f} นาที ({avg_gap/60:.1f} ชม)")
    print(f"{'='*70}")
    print(f"{'เวลา':>7}  {'Traffic':>8}  {'อยู่ใน feed':>11}  {'วิวคาด':>8}  {'กด Profile':>10}  ช่วงไหน")
    print(f"{'-'*70}")

    for s in slots:
        bar = "█" * int(s.traffic_score) + "░" * (10 - int(s.traffic_score))
        print(
            f"  {s.time_str()}   {bar}  "
            f"  {s.visibility_minutes:>4} นาที  "
            f"  {s.expected_views:>5.1f}  "
            f"  {s.profile_visits*100:>5.0f}%     "
            f"  {s.peak_label}"
        )

    print(f"{'='*70}")
    print(f"  ยอดวิวรวมคาด (สัมพัทธ์): {total_views:.0f}  |  "
          f"ช่วง traffic ต่ำสุด: {min(slots, key=lambda s: s.traffic_score).time_str()}")


def print_heatmap(slots: List[ReleaseSlot]) -> None:
    """แสดง heatmap ตลอด 24 ชั่วโมง ว่าเราปล่อยตอนไหน"""
    release_hours = {s.hour for s in slots}
    print("\n  Heatmap การมองเห็น (ทุกชั่วโมง)")
    print("  " + "".join(f"{h:02d}" for h in range(24)))
    print("  " + "".join(
        "🟥" if h in release_hours and HOURLY_TRAFFIC[h] >= 7 else
        "🟧" if h in release_hours and HOURLY_TRAFFIC[h] >= 4 else
        "🟨" if h in release_hours else
        "⬛" if HOURLY_TRAFFIC[h] >= 7 else
        "🟫" if HOURLY_TRAFFIC[h] >= 4 else
        "⬜"
        for h in range(24)
    ))
    print("  🟥 ปล่อยตอน + peak สูง  🟧 ปล่อยตอน + peak กลาง  🟨 ปล่อยตอน + traffic ต่ำ")
    print("  ⬛ peak สูง (ไม่มีตอน)  🟫 peak กลาง              ⬜ traffic ต่ำ")


def print_strategy_note(slots: List[ReleaseSlot], chapters_per_day: int) -> None:
    avg_gap = 1440 / len(slots)
    print(f"""
  📌 สรุปกลยุทธ์
  ─────────────────────────────────────────────────────────────────
  • ปล่อย {chapters_per_day} ตอน/วัน ทุก {avg_gap:.0f} นาที (เฉลี่ย)
  • นักอ่านเปิดแอปตอนไหนก็มีโอกาสเจอเราใน feed ทุก {avg_gap/60:.1f} ชั่วโมง
  • ตอนที่ปล่อยช่วง 19:00–21:00 จะดึง traffic สูงสุด
    → คนที่เจอจะกด profile เพื่ออ่านเรื่องอื่นของเรา ~{max(s.profile_visits for s in slots)*100:.0f}%
  • ตอนที่ปล่อยกลางดึก/เช้าตรู่ช่วยให้ครองหน้าแรกช่วงที่คู่แข่งน้อย
  ─────────────────────────────────────────────────────────────────
  💡 คำแนะนำเพิ่มเติม:
     - ถ้ามีหลายเรื่อง: สลับเรื่องในแต่ละ slot เพื่อ cross-promote
     - ตอนที่ 1 ของเรื่องใหม่: ปล่อยตรง 20:00 เสมอ (traffic peak)
     - สัปดาห์แรก: เพิ่มเป็น {min(chapters_per_day+4, 20)} ตอน/วัน
       เพื่อ "ยึด" feed ก่อนคู่แข่งปรับตัวทัน
""")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="วางแผนตารางปล่อยตอนตลอดวัน")
    parser.add_argument("--chapters-per-day", type=int, default=12,
                        help="จำนวนตอนที่ต้องการปล่อยต่อวัน (default 12)")
    parser.add_argument("--show-heatmap", action="store_true",
                        help="แสดง heatmap การมองเห็น")
    parser.add_argument("--seed", type=int, default=2024)
    args = parser.parse_args()

    slots = optimize_schedule(args.chapters_per_day, args.seed)
    print_schedule(slots, args.chapters_per_day)
    if args.show_heatmap:
        print_heatmap(slots)
    print_strategy_note(slots, args.chapters_per_day)
