"""โมเดลจำลองปฏิกิริยานักอ่านต่อหนังสือ 1 เรื่อง

อินพุตคือ book_profile (คะแนนรายมิติที่ผู้ประเมินให้หลังอ่านจริง + แนว + พล็อต)
แต่ละนักอ่านจะคำนวณ: อ่านถึงตอนไหน, ให้กี่ดาว, ผ่าน/ชอบ/จ่ายเหรียญหรือไม่ และเหตุผล
"""

import random
import statistics

from .personas import DIMENSIONS, GENRES, TROPES, build_panel

PAY_PROBABILITY = {
    "free": {3: 0.02, 4: 0.08, 5: 0.15},
    "occasional": {3: 0.15, 4: 0.45, 5: 0.70},
    "spender": {3: 0.35, 4: 0.75, 5: 0.95},
}


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def normalize_book(book):
    """รับได้ทั้ง {"hook": 7} และ {"hook": {"score": 7, "evidence": "..."}}"""
    scores = {}
    for dim, val in book.get("scores", {}).items():
        if dim not in DIMENSIONS:
            raise ValueError(f"unknown dimension '{dim}' (ใช้ได้: {', '.join(DIMENSIONS)})")
        if isinstance(val, dict):
            val = val.get("score")
        if val is not None:
            scores[dim] = float(val)
    missing = {"hook", "pacing", "prose"} - set(scores)
    if missing:
        raise ValueError(f"book profile ต้องมีคะแนนอย่างน้อย: {', '.join(sorted(missing))}")
    for key, vocab in (("genres", GENRES), ("tropes", TROPES)):
        unknown = set(book.get(key, [])) - set(vocab)
        if unknown:
            raise ValueError(f"unknown {key}: {unknown} (ใช้ได้: {', '.join(vocab)})")
    chapters_read = int(book.get("chapters_read", 20))
    return {
        **book,
        "scores": scores,
        "genres": list(book.get("genres", [])),
        "tropes": list(book.get("tropes", [])),
        "chapters_read": chapters_read,
        "chapters_total": int(book.get("chapters_total", chapters_read)),
        "free_chapters": int(book.get("free_chapters", 0)),
    }


def simulate_reader(p, book, rng):
    s = book["scores"]
    wsum = sum(p["weights"][d] for d in s)
    base = sum(p["weights"][d] * v for d, v in s.items()) / wsum

    overlap = [g for g in book["genres"] if g in p["likes"]]
    avoid_hits = [g for g in book["genres"] if g in p["avoids"]]
    off_genre = bool(p["requires"]) and not any(g in p["requires"] for g in book["genres"])
    fit = len(overlap) / max(1, min(len(book["genres"]), 3))
    genre_adj = (fit - 0.5) * 1.6 - min(3.0, 2.0 * len(avoid_hits)) - (2.0 if off_genre else 0)

    loved = [t for t in book["tropes"] if t in p["loved_tropes"]]
    hated = [t for t in book["tropes"] if t in p["hated_tropes"]]
    trope_adj = min(1.0, 0.4 * len(loved)) - min(3.0, 1.2 * len(hated))

    raw = _clamp(base + genre_adj + trope_adj - p["strictness"] + rng.gauss(0, 0.5), 0, 10)
    # raw 9 → 5 ดาว, 7.5 → 4, 6 → 3, 4.5 → 2
    stars = int(_clamp(round(1 + (raw - 3) * 4 / 6), 1, 5))

    # จุดเด่น/จุดด้อยตามสายตาคนนี้ (มิติที่น้ำหนักสูงและคะแนนห่างจากค่ากลาง)
    contrib = sorted(((p["weights"][d] * (v - 6.0), d) for d, v in s.items()))
    complaints = [f"จุดอ่อน: {DIMENSIONS[d]}" for c, d in contrib if c < -1.0][:2]
    praises = [DIMENSIONS[d] for c, d in reversed(contrib) if c > 1.5][:2]
    complaints = [f"เจอพล็อตที่ไม่ชอบ: {TROPES[t]}" for t in hated] + complaints
    praises = [f"ชอบพล็อต: {TROPES[t]}" for t in loved] + praises

    total = book["chapters_read"]
    hook_eff = s["hook"] + genre_adj * 0.8 + trope_adj * 0.3 + rng.gauss(0, 0.7)
    status = "finished"
    reached = total
    drop_reason = None
    if off_genre and rng.random() < 0.85:
        status, reached = "early_drop", 1
        drop_reason = "ไม่ใช่แนว (ไม่มี " + "/".join(GENRES[g] for g in p["requires"][:2]) + ")"
    elif avoid_hits and fit == 0 and s["hook"] < 8.5:
        status, reached = "early_drop", 1
        drop_reason = f"ไม่ใช่แนว ({', '.join(GENRES[g] for g in avoid_hits)})"
    elif hook_eff < p["hook_threshold"]:
        status, reached = "early_drop", rng.randint(1, min(3, total))
        drop_reason = "ไม่ใช่แนว" if fit == 0 else "เปิดเรื่องไม่ดึงพอ"
    else:
        cliff = s.get("cliffhanger", s["pacing"])
        sustain = 0.4 * s["pacing"] + 0.3 * cliff + 0.3 * raw + rng.gauss(0, 0.6)
        if sustain < p["patience"] and total > 3:
            status, reached = "mid_drop", rng.randint(4, total)
            drop_reason = complaints[0] if complaints else "เนื้อเรื่องเริ่มยืด"

    if status == "early_drop":
        stars = min(stars, 2)
    elif status == "mid_drop":
        stars = min(stars, 3)

    passed = status != "early_drop" and stars >= 3
    paid = False
    paywall = book["free_chapters"] and book["free_chapters"] < book["chapters_total"]
    if paywall and status == "finished" and stars >= 3:
        paid = rng.random() < PAY_PROBABILITY[p["spending"]][stars]

    return {
        "id": p["id"],
        "name": p["name"],
        "segment": p["segment"],
        "segment_label": p["segment_label"],
        "age": p["age"],
        "spending": p["spending"],
        "target": bool(overlap) and not avoid_hits and not off_genre,
        "stars": stars,
        "raw": round(raw, 2),
        "status": status,
        "reached": reached,
        "passed": passed,
        "liked": stars >= 4,
        "shelved": status == "finished" and stars >= 4,
        "paid": paid,
        "drop_reason": drop_reason,
        "complaints": complaints[:3],
        "praises": praises[:3],
    }


def _summary(results, paywall):
    n = len(results)
    if n == 0:
        return None
    pct = lambda k: round(100 * sum(1 for r in results if r[k]) / n, 1)
    dist = {i: sum(1 for r in results if r["stars"] == i) for i in range(1, 6)}
    return {
        "n": n,
        "pass_pct": pct("passed"),
        "like_pct": pct("liked"),
        "shelf_pct": pct("shelved"),
        "paid_pct": pct("paid") if paywall else None,
        "avg_stars": round(statistics.mean(r["stars"] for r in results), 2),
        "early_drop_pct": round(100 * sum(r["status"] == "early_drop" for r in results) / n, 1),
        "mid_drop_pct": round(100 * sum(r["status"] == "mid_drop" for r in results) / n, 1),
        "finish_pct": round(100 * sum(r["status"] == "finished" for r in results) / n, 1),
        "star_dist": dist,
    }


def _grade(t):
    if t is None:
        return "D"
    if t["like_pct"] >= 70 and t["avg_stars"] >= 4.2:
        return "S"
    if t["like_pct"] >= 55:
        return "A"
    if t["like_pct"] >= 40:
        return "B"
    if t["like_pct"] >= 25:
        return "C"
    return "D"


GRADE_TEXT = {
    "S": "ตัวท็อป มีโอกาสติดอันดับ ลงได้ทันที",
    "A": "ดีมาก กลุ่มเป้าหมายชอบชัดเจน ลงได้",
    "B": "พอใช้ มีฐานคนอ่าน แต่ควรเกลาจุดอ่อนก่อนลง",
    "C": "เสี่ยง คนส่วนใหญ่ไม่ไปต่อ ควรแก้ก่อนลง",
    "D": "ไม่แนะนำให้ลงในสภาพนี้",
}


def _recommendations(book, overall, target):
    s = book["scores"]
    recs = []
    if overall["early_drop_pct"] >= 30 and s["hook"] < 7:
        recs.append("คนหลุดใน 3 ตอนแรกเยอะ — เกลาตอน 1-3 ให้เข้าเรื่องเร็วขึ้น/ใส่ปมตั้งแต่หน้าแรก หรือพิจารณาเขียนบทนำ/คำโปรยใหม่")
    if overall["mid_drop_pct"] >= 20:
        recs.append("คนเลิกกลางทางเยอะ — ตัดช่วงยืด และให้ทุกตอนจบด้วยคำถามหรือเหตุการณ์ค้างคา")
    if s.get("prose", 10) < 6.5 or s.get("polish", 10) < 6.5:
        recs.append("สำนวน/ความเรียบร้อยยังดึงคะแนนลง โดยเฉพาะสายนิยายแปลตัวยงและสายรีวิว — ขัดเกลาอีกรอบก่อนลง")
    if s.get("cliffhanger", 10) < 6 and book["free_chapters"]:
        recs.append(f"ตอนที่ {book['free_chapters']} (ตอนฟรีตอนสุดท้าย) ควรจบแบบค้างคาที่สุด เพื่อดันยอดซื้อเหรียญ")
    if target and target["like_pct"] - overall["like_pct"] >= 20:
        recs.append("เรื่องนี้เฉพาะกลุ่ม — โปรโมตตรงแท็ก/หมวดของกลุ่มเป้าหมาย ไม่ต้องหวังผู้อ่านทั่วไป")
    if not recs:
        recs.append("ไม่มีจุดอ่อนเด่นชัดจากการจำลอง — โฟกัสที่ปก คำโปรย และแท็กให้ตรงกลุ่ม")
    return recs


def _tally(items, top=6):
    counts = {}
    for it in items:
        counts[it] = counts.get(it, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])[:top]


def run(book, seed=2024, iterations=300, panel_seed=2024):
    book = normalize_book(book)
    panel = build_panel(panel_seed)
    paywall = bool(book["free_chapters"]) and book["free_chapters"] < book["chapters_total"]

    rng = random.Random(seed)
    results = [simulate_reader(p, book, rng) for p in panel]
    overall = _summary(results, paywall)
    target = _summary([r for r in results if r["target"]], paywall)

    segments = []
    seen = []
    for r in results:
        if r["segment"] not in seen:
            seen.append(r["segment"])
    for seg in seen:
        rs = [r for r in results if r["segment"] == seg]
        segments.append({"id": seg, "label": rs[0]["segment_label"], **_summary(rs, paywall)})

    # Monte Carlo: นักอ่านชุดเดิม แต่สุ่มอารมณ์วันนั้นใหม่ เพื่อดูช่วงความไม่แน่นอน
    mc = {"pass_pct": [], "like_pct": [], "avg_stars": [], "paid_pct": []}
    mc_rng = random.Random(seed + 1)
    for _ in range(iterations):
        sm = _summary([simulate_reader(p, book, mc_rng) for p in panel], paywall)
        for k in mc:
            if sm[k] is not None:
                mc[k].append(sm[k])
    ci = {}
    for k, vals in mc.items():
        if vals:
            vals.sort()
            ci[k] = (vals[int(0.05 * len(vals))], vals[int(0.95 * len(vals)) - 1])

    # กราฟคนที่ยังอ่านอยู่ ณ แต่ละตอน
    retention = []
    for ch in range(1, book["chapters_read"] + 1):
        retention.append(sum(1 for r in results if r["reached"] >= ch))

    grade = _grade(target or overall)
    return {
        "book": book,
        "overall": overall,
        "target": target,
        "segments": segments,
        "ci": ci,
        "iterations": iterations,
        "retention": retention,
        "drop_reasons": _tally([r["drop_reason"] for r in results if r["drop_reason"]]),
        "complaints": _tally([c for r in results for c in r["complaints"]]),
        "praises": _tally([c for r in results if r["passed"] for c in r["praises"]]),
        "grade": grade,
        "grade_text": GRADE_TEXT[grade],
        "recommendations": _recommendations(book, overall, target),
        "readers": results,
    }
