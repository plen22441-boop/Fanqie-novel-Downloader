"""จำลองผลลัพธ์จากช่วงเวลาปล่อยตอน (นาที/ตอน) บนแพลตฟอร์ม My Novel

ใช้แบบอิสระหรือแนบกับ book_profile.json โดยเพิ่ม "release_interval_min": 5

CLI:
    python -m reader_sim.release_timing [--intervals 3 4 5 6 7 8 9] [--chapters 60] [--paid-from 30]
"""

from __future__ import annotations
import random, math
from dataclasses import dataclass, field
from typing import List, Dict

# ---------------------------------------------------------------------------
# นิยามกลุ่มนักอ่านตามพฤติกรรมการอ่าน
# ---------------------------------------------------------------------------

@dataclass
class ReaderArchetype:
    name: str
    label_th: str
    count: int           # จำนวนคนในแผง 100
    # ช่วงเวลาที่อ่านต่อตอนได้สบาย (นาที)
    comfortable_min: float
    comfortable_max: float
    # ความอดทนต่อช่วงปล่อยที่ช้ากว่า comfortable_max (0–1, สูง = อดทนได้นาน)
    patience: float
    # พฤติกรรม binge: อ่านต่อเนื่องนานแค่ไหน (นาที/session)
    session_len_min: float
    # โอกาสซื้อเหรียญเมื่อชอบหนังสือ (0–1)
    coin_chance: float
    # โอกาสให้ดาว 4-5
    high_star_chance: float


ARCHETYPES: List[ReaderArchetype] = [
    ReaderArchetype(
        "binge",   "สายบิ้นจ์ (อ่านทีเดียว)",
        count=25,
        comfortable_min=2, comfortable_max=5,
        patience=0.3,       # ไม่ชอบรอนาน ถ้าช้าเกิน 7 นาทีจะเปิดเรื่องอื่นแทน
        session_len_min=90,   # บิ้นจ์นานกว่า: 1.5 ชม
        coin_chance=0.40,
        high_star_chance=0.70,
    ),
    ReaderArchetype(
        "casual",  "ทั่วไป (อ่านชิลๆ)",
        count=45,
        comfortable_min=4, comfortable_max=8,
        patience=0.6,
        session_len_min=40,   # ปรับเป็น 40 นาที
        coin_chance=0.25,
        high_star_chance=0.60,
    ),
    ReaderArchetype(
        "notif",   "สายรอแจ้งเตือน",
        count=20,
        comfortable_min=6, comfortable_max=12,
        patience=0.8,
        session_len_min=20,
        coin_chance=0.30,
        high_star_chance=0.65,
    ),
    ReaderArchetype(
        "weekend", "อ่านแบตช์ (สะสมแล้วอ่านรวด)",
        count=10,
        comfortable_min=1, comfortable_max=999,
        patience=1.0,
        session_len_min=120,  # สะสม 2 ชม อ่านรวด
        coin_chance=0.35,
        high_star_chance=0.55,
    ),
]

# ---------------------------------------------------------------------------
# ฟังก์ชันหลักจำลอง
# ---------------------------------------------------------------------------

@dataclass
class IntervalResult:
    interval_min: int
    chapters_per_hour: float        # ตอน/ชั่วโมงที่นักอ่านอ่านได้จริงในเซสชัน
    avg_session_chapters: float     # ตอนเฉลี่ยต่อเซสชัน
    engagement_score: float         # 0–10 คะแนนรวม engagement
    daily_return_rate: float        # สัดส่วนที่จะกลับมาอ่านวันถัดไป (0–1)
    coin_rate: float                # สัดส่วนที่ซื้อเหรียญ
    algo_score: float               # คะแนน algorithm-friendliness 0–10
    drop_risk: float                # ความเสี่ยง drop (0–1, สูง = ไม่ดี)
    composite: float                # composite score สำหรับ rank

    def grade(self) -> str:
        if self.composite >= 8.0: return "S"
        if self.composite >= 7.0: return "A"
        if self.composite >= 6.0: return "B"
        if self.composite >= 5.0: return "C"
        return "D"


def simulate_interval(
    interval_min: int,
    total_chapters: int = 60,
    paid_from_chapter: int = 30,
    seed: int = 2024,
) -> IntervalResult:
    rng = random.Random(seed + interval_min * 7)

    session_chapters_list = []
    will_return_list = []
    pays_list = []
    algo_signals = []
    drop_risks = []

    for arch in ARCHETYPES:
        for _ in range(arch.count):
            # --- นักอ่านคนนี้จะอยู่ได้กี่นาทีใน session ---
            session_len = rng.uniform(arch.session_len_min * 0.8,
                                      arch.session_len_min * 1.2)

            # --- ช่วงปล่อยเร็วเกินไปหรือช้าเกินไป ทำให้ engagement ลด ---
            if interval_min < arch.comfortable_min:
                # เร็วกว่า comfort → อ่านได้มากแต่เหนื่อยเร็ว
                comfort_factor = 0.85 + 0.15 * (interval_min / arch.comfortable_min)
            elif interval_min > arch.comfortable_max:
                # ช้ากว่า comfort → รอนาน อาจเปิดเรื่องอื่น
                over = (interval_min - arch.comfortable_max) / arch.comfortable_max
                comfort_factor = max(0.4, arch.patience - over * 0.5)
            else:
                comfort_factor = 1.0

            # --- ตอนที่อ่านได้ต่อเซสชัน ---
            raw_chapters = session_len / interval_min
            readable = min(raw_chapters * comfort_factor, total_chapters)
            readable += rng.gauss(0, 1.5)
            readable = max(1, readable)
            session_chapters_list.append(readable)

            # --- โอกาสกลับมาวันถัดไป ---
            # ถ้าอ่านได้ปริมาณที่ "พอดี" จะอยากกลับมา
            # ถ้าอ่านหมดเลย (ตอนหมด) หรืออ่านน้อยเกิน ก็ drop
            fullness = readable / total_chapters  # 0→1
            # sweet spot: อ่านได้ 20-40% ของ total → อยากกลับมา
            sweet = 1.0 - abs(fullness - 0.30) * 2
            return_prob = max(0.1, min(0.95, sweet * comfort_factor))
            will_return_list.append(rng.random() < return_prob)

            # --- ซื้อเหรียญ ---
            reached_paid = readable >= paid_from_chapter
            pays_list.append(reached_paid and rng.random() < arch.coin_chance)

            # --- algo signal: ยิ่ง session นาน + return สูง ยิ่งดี ---
            algo = (session_len * comfort_factor / 60) * return_prob * 10
            algo_signals.append(min(10, algo))

            # --- drop risk ---
            drop = 1.0 - comfort_factor
            drop_risks.append(drop)

    n = sum(a.count for a in ARCHETYPES)
    avg_ch = sum(session_chapters_list) / n
    cph = 60 / interval_min  # theoretical max chapters/hr
    engagement = min(10.0, avg_ch / 8 * 10)  # normalise ที่ 8 ตอน/เซสชัน
    ret_rate = sum(will_return_list) / n
    coin = sum(pays_list) / n
    algo = sum(algo_signals) / n
    drop = sum(drop_risks) / n

    # composite: engagement 30% + return 30% + algo 25% + coin 15%
    comp = (
        engagement * 0.30 +
        ret_rate * 10 * 0.30 +
        algo * 0.25 +
        coin * 10 * 0.15
    )

    return IntervalResult(
        interval_min=interval_min,
        chapters_per_hour=round(cph, 1),
        avg_session_chapters=round(avg_ch, 1),
        engagement_score=round(engagement, 2),
        daily_return_rate=round(ret_rate, 3),
        coin_rate=round(coin, 3),
        algo_score=round(algo, 2),
        drop_risk=round(drop, 3),
        composite=round(comp, 2),
    )


def compare_intervals(
    intervals: List[int] | None = None,
    total_chapters: int = 60,
    paid_from_chapter: int = 30,
    seed: int = 2024,
) -> List[IntervalResult]:
    if intervals is None:
        intervals = [3, 4, 5, 6, 7, 8, 9]
    results = [
        simulate_interval(i, total_chapters, paid_from_chapter, seed)
        for i in intervals
    ]
    results.sort(key=lambda r: r.composite, reverse=True)
    return results


def print_table(results: List[IntervalResult]) -> None:
    print("\n" + "=" * 75)
    print(f"{'ช่วงเวลา':>8} {'ตอน/ชม':>7} {'เฉลี่ย/เซส':>10} {'Engage':>8} "
          f"{'Return%':>8} {'Coin%':>7} {'Algo':>6} {'Drop%':>7} {'Score':>7} {'เกรด':>5}")
    print("-" * 75)
    best = results[0].composite
    for r in results:
        marker = " ◀ แนะนำ" if r.composite == best else ""
        print(
            f"{r.interval_min:>6} นาที"
            f"  {r.chapters_per_hour:>5.1f}"
            f"  {r.avg_session_chapters:>8.1f}"
            f"  {r.engagement_score:>6.2f}"
            f"  {r.daily_return_rate*100:>6.1f}%"
            f"  {r.coin_rate*100:>5.1f}%"
            f"  {r.algo_score:>4.2f}"
            f"  {r.drop_risk*100:>5.1f}%"
            f"  {r.composite:>5.2f}"
            f"   {r.grade()}"
            f"{marker}"
        )
    print("=" * 75)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse, sys

    parser = argparse.ArgumentParser(description="จำลองช่วงเวลาปล่อยตอนบน My Novel")
    parser.add_argument("--intervals", nargs="+", type=int,
                        default=[3, 4, 5, 6, 7, 8, 9])
    parser.add_argument("--chapters", type=int, default=60,
                        help="จำนวนตอนที่จะปล่อยในช่วงนี้")
    parser.add_argument("--paid-from", type=int, default=30,
                        help="เริ่มตอนใช้เหรียญ")
    parser.add_argument("--seed", type=int, default=2024)
    args = parser.parse_args()

    results = compare_intervals(
        intervals=args.intervals,
        total_chapters=args.chapters,
        paid_from_chapter=args.paid_from,
        seed=args.seed,
    )
    print_table(results)

    best = results[0]
    print(f"\n✦ สรุป: ช่วงเวลาที่แนะนำคือ {best.interval_min} นาที/ตอน")
    print(f"  • นักอ่านอ่านเฉลี่ย {best.avg_session_chapters} ตอน/เซสชัน")
    print(f"  • Return rate {best.daily_return_rate*100:.1f}% | Coin {best.coin_rate*100:.1f}%")
