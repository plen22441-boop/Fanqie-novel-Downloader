"""แผงนักอ่านจำลอง 100 คน สำหรับเว็บ/แอป My Novel

สัดส่วนกลุ่มนักอ่านด้านล่างเป็น "สมมติฐานตั้งต้น" ไม่ใช่สถิติจริงของแพลตฟอร์ม
เมื่อมีข้อมูลจริง (ยอดวิว, ดาว, ยอดซื้อเหรียญของเรื่องที่ลงไปแล้ว) ให้ปรับ
`count`, `weights`, `hook_threshold` ฯลฯ ของแต่ละกลุ่มเพื่อคาลิเบรตให้ใกล้ความจริง
"""

import random

# มิติที่ใช้ให้คะแนนหนังสือ (0-10) — ผู้ประเมินกรอกใน book_profile.json
DIMENSIONS = {
    "hook": "ความดึงดูดช่วงเปิด (ตอน 1-3)",
    "pacing": "จังหวะการเล่าเรื่อง",
    "prose": "สำนวนภาษา/คุณภาพการแปล",
    "characters": "ความน่าสนใจของตัวละคร",
    "romance": "เคมี/ความฟินของคู่หลัก",
    "world": "การสร้างโลก/ระบบ/ฉาก",
    "plot": "พล็อตและการหักมุม",
    "emotion": "อารมณ์ร่วม",
    "cliffhanger": "การทิ้งท้ายตอนให้อยากกดต่อ",
    "originality": "ความแปลกใหม่",
    "polish": "ความเรียบร้อยหลัง QC (คำผิด/ชื่อเฉพาะสม่ำเสมอ)",
}

GENRES = {
    "romance": "โรแมนซ์",
    "drama": "ดราม่า",
    "sweet": "หวานฟิน",
    "angst": "เศร้า/ทำร้ายจิตใจ",
    "comedy": "ตลก",
    "modern": "ปัจจุบัน",
    "historical": "จีนโบราณ/ย้อนยุค",
    "transmigration": "ทะลุมิติ",
    "rebirth": "เกิดใหม่",
    "revenge": "ล้างแค้น",
    "system": "ระบบ",
    "fantasy": "แฟนตาซี",
    "xianxia": "เซียน/บำเพ็ญเพียร",
    "wuxia": "กำลังภายใน",
    "action": "แอ็กชัน",
    "mystery": "สืบสวน",
    "horror": "สยองขวัญ",
    "bl": "วาย (BL)",
    "gl": "ยูริ (GL)",
    "harem": "ฮาเร็ม",
    "farming": "ทำไร่/ทำอาหาร/ชีวิตชนบท",
    "scifi": "ไซไฟ/วันสิ้นโลก",
}

TROPES = {
    "face_slapping": "ตบหน้าคนชั่ว",
    "op_mc": "ตัวเอกเก่งเกินจริง",
    "cold_ml": "พระเอกเย็นชาแต่คลั่งรัก",
    "dumb_fl": "นางเอกโง่/ถูกหลอกซ้ำๆ",
    "strong_fl": "นางเอกเก่ง ฉลาด",
    "slow_burn": "ค่อยเป็นค่อยไป (slow burn)",
    "contract_marriage": "แต่งงานตามสัญญา",
    "love_triangle": "รักสามเส้า",
    "cheating": "นอกใจ/NTR",
    "non_con": "บังคับขืนใจ",
    "sad_ending": "จบเศร้า",
    "harem": "ฮาเร็ม",
    "villainess": "ทะลุมาเป็นตัวร้าย",
    "cute_kids": "ลูกน้อยน่ารัก",
    "misunderstanding": "เข้าใจผิดยืดเยื้อ",
    "abuse_ml": "พระเอกทำร้ายนางเอก",
    "level_up": "อัปเลเวล/ภารกิจระบบ",
    "found_family": "ครอบครัวที่เลือกเอง",
}

# ---------------------------------------------------------------------------
# นิยามกลุ่มนักอ่าน (รวม count = 100)
# requires: ต้องมีอย่างน้อย 1 แนวในนี้ ไม่งั้นส่วนใหญ่จะไม่กดเข้าอ่านเลย
# weights: น้ำหนักของแต่ละมิติ (ไม่ระบุ = 1)
# hook_threshold: คะแนนช่วงเปิดขั้นต่ำก่อนจะเลิกอ่านใน 3 ตอนแรก
# strictness: ความโหด (หักคะแนนพื้นฐาน)
# spending: สัดส่วน free / occasional / spender
# ---------------------------------------------------------------------------
SEGMENTS = [
    {
        "id": "romance_modern",
        "label": "สาวโรแมนซ์ปัจจุบัน",
        "count": 16,
        "likes": ["romance", "sweet", "modern", "drama", "comedy"],
        "avoids": ["horror", "harem"],
        "loved_tropes": ["cold_ml", "contract_marriage", "strong_fl", "cute_kids"],
        "hated_tropes": ["cheating", "non_con", "abuse_ml", "dumb_fl"],
        "weights": {"romance": 3, "characters": 2.5, "emotion": 2, "world": 0.5},
        "hook_threshold": (5.0, 6.5),
        "strictness": (0.0, 0.8),
        "spending": (0.45, 0.40, 0.15),
        "ages": ["18-24", "25-34", "25-34", "35-44"],
    },
    {
        "id": "romance_ancient",
        "label": "สายจีนโบราณ/ทะลุมิติ",
        "count": 14,
        "likes": ["historical", "transmigration", "rebirth", "romance", "revenge", "farming"],
        "avoids": ["scifi", "harem"],
        "loved_tropes": ["strong_fl", "face_slapping", "villainess", "cold_ml", "cute_kids"],
        "hated_tropes": ["dumb_fl", "cheating", "non_con", "misunderstanding"],
        "weights": {"romance": 2, "characters": 2, "plot": 2, "world": 1.5, "prose": 1.5},
        "hook_threshold": (4.5, 6.0),
        "strictness": (0.0, 0.8),
        "spending": (0.35, 0.45, 0.20),
        "ages": ["18-24", "25-34", "25-34", "35-44"],
    },
    {
        "id": "bl",
        "label": "สาววาย (BL)",
        "count": 14,
        "requires": ["bl"],
        "likes": ["bl", "romance", "historical", "modern", "xianxia", "sweet"],
        "avoids": ["harem"],
        "loved_tropes": ["slow_burn", "cold_ml", "found_family"],
        "hated_tropes": ["cheating", "abuse_ml", "misunderstanding"],
        "weights": {"romance": 3.5, "characters": 2.5, "emotion": 2},
        "hook_threshold": (4.5, 6.0),
        "strictness": (0.0, 1.0),
        "spending": (0.30, 0.45, 0.25),
        "ages": ["15-17", "18-24", "18-24", "25-34"],
    },
    {
        "id": "xianxia",
        "label": "สายเซียน/กำลังภายใน",
        "count": 14,
        "requires": ["xianxia", "wuxia", "fantasy", "system"],
        "likes": ["xianxia", "wuxia", "fantasy", "action", "system"],
        "avoids": ["bl", "gl", "sweet"],
        "loved_tropes": ["level_up", "op_mc", "face_slapping"],
        "hated_tropes": ["dumb_fl", "misunderstanding", "love_triangle"],
        "weights": {"world": 3, "plot": 2, "pacing": 2, "romance": 0.3, "emotion": 0.8},
        "hook_threshold": (4.5, 6.0),
        "strictness": (0.2, 1.0),
        "spending": (0.40, 0.40, 0.20),
        "ages": ["15-17", "18-24", "25-34", "35-44"],
    },
    {
        "id": "system_rebirth",
        "label": "สายระบบ/เกิดใหม่ล้างแค้น",
        "count": 12,
        "requires": ["system", "rebirth", "revenge", "transmigration"],
        "likes": ["system", "rebirth", "revenge", "transmigration", "action", "scifi"],
        "avoids": ["angst"],
        "loved_tropes": ["face_slapping", "level_up", "op_mc", "strong_fl"],
        "hated_tropes": ["dumb_fl", "misunderstanding", "sad_ending"],
        "weights": {"pacing": 3, "hook": 2, "cliffhanger": 2.5, "prose": 0.7},
        "hook_threshold": (5.5, 7.0),
        "strictness": (0.0, 0.6),
        "spending": (0.40, 0.40, 0.20),
        "ages": ["15-17", "18-24", "18-24", "25-34"],
    },
    {
        "id": "translation_purist",
        "label": "นักอ่านนิยายแปลจีนตัวยง",
        "count": 10,
        "likes": ["historical", "xianxia", "wuxia", "romance", "rebirth", "transmigration", "bl"],
        "avoids": [],
        "loved_tropes": ["slow_burn", "strong_fl"],
        "hated_tropes": ["non_con"],
        "weights": {"prose": 3.5, "polish": 3, "characters": 1.5, "plot": 1.5},
        "hook_threshold": (4.0, 5.5),
        "strictness": (0.6, 1.4),
        "spending": (0.20, 0.45, 0.35),
        "ages": ["25-34", "25-34", "35-44", "45+"],
    },
    {
        "id": "casual",
        "label": "ขาจร/อ่านฆ่าเวลา",
        "count": 12,
        "likes": ["romance", "comedy", "sweet", "system", "rebirth", "modern"],
        "avoids": ["angst", "horror"],
        "loved_tropes": ["face_slapping", "cute_kids", "op_mc"],
        "hated_tropes": ["sad_ending", "misunderstanding"],
        "weights": {"hook": 3, "pacing": 2.5, "cliffhanger": 2, "world": 0.5, "prose": 0.6},
        "hook_threshold": (6.0, 7.5),
        "strictness": (0.0, 0.5),
        "spending": (0.70, 0.25, 0.05),
        "ages": ["15-17", "18-24", "25-34", "35-44"],
    },
    {
        "id": "critic",
        "label": "สายรีวิว/จับผิด",
        "count": 4,
        "likes": ["historical", "mystery", "xianxia", "drama", "romance", "fantasy"],
        "avoids": [],
        "loved_tropes": ["slow_burn", "strong_fl", "found_family"],
        "hated_tropes": ["dumb_fl", "op_mc", "misunderstanding", "non_con"],
        "weights": {"originality": 2.5, "plot": 2.5, "prose": 2, "characters": 2},
        "hook_threshold": (4.0, 5.0),
        "strictness": (1.0, 1.8),
        "spending": (0.30, 0.40, 0.30),
        "ages": ["25-34", "35-44"],
    },
    {
        "id": "gl",
        "label": "สายยูริ (GL)",
        "count": 4,
        "requires": ["gl"],
        "likes": ["gl", "romance", "sweet", "fantasy", "modern"],
        "avoids": ["harem"],
        "loved_tropes": ["slow_burn", "strong_fl", "found_family"],
        "hated_tropes": ["cheating", "non_con", "sad_ending"],
        "weights": {"romance": 3.5, "characters": 2.5, "emotion": 2},
        "hook_threshold": (4.5, 6.0),
        "strictness": (0.0, 0.8),
        "spending": (0.35, 0.40, 0.25),
        "ages": ["18-24", "25-34"],
    },
]

_NICKNAMES = [
    "มายด์", "แพรว", "ฝน", "เฟิร์น", "ปุ้ย", "น้ำหวาน", "ใบเตย", "มุก", "แป้ง", "จูน",
    "กิ๊ฟ", "ขิม", "เมย์", "พลอย", "ออม", "แนน", "บีม", "ต้นข้าว", "ปาล์ม", "อิง",
    "ฟ้า", "ส้ม", "นุ่น", "แตงโม", "ไอซ์", "โบว์", "ปลา", "หมิว", "ตาล", "มิ้นท์",
    "เกด", "แอม", "นิว", "เจน", "ก้อย", "ข้าวหอม", "พิม", "ชมพู่", "น้ำฝน", "ดาว",
    "ภูมิ", "ต้น", "บอส", "เจมส์", "กัปตัน", "ตั้ม", "เอิร์ธ", "ไผ่", "ป๊อป", "อาร์ม",
]

SPENDING_LABELS = {
    "free": "อ่านแต่ตอนฟรี",
    "occasional": "ซื้อเหรียญเป็นครั้งคราว",
    "spender": "เปย์หนัก",
}


def validate_segments():
    total = sum(s["count"] for s in SEGMENTS)
    if total != 100:
        raise ValueError(f"segment counts must sum to 100, got {total}")
    for s in SEGMENTS:
        for key in ("likes", "avoids", "requires"):
            unknown = set(s.get(key, [])) - set(GENRES)
            if unknown:
                raise ValueError(f"{s['id']}: unknown genres {unknown}")
        for key in ("loved_tropes", "hated_tropes"):
            unknown = set(s[key]) - set(TROPES)
            if unknown:
                raise ValueError(f"{s['id']}: unknown tropes {unknown}")
        unknown = set(s["weights"]) - set(DIMENSIONS)
        if unknown:
            raise ValueError(f"{s['id']}: unknown dimensions {unknown}")


def build_panel(seed=2024):
    """สร้างนักอ่าน 100 คน (seed เดิม = คนชุดเดิมทุกครั้ง เทียบผลข้ามเรื่องได้)"""
    validate_segments()
    rng = random.Random(seed)
    panel = []
    idx = 0
    for seg in SEGMENTS:
        for _ in range(seg["count"]):
            idx += 1
            weights = {}
            for dim in DIMENSIONS:
                base = seg["weights"].get(dim, 1.0)
                weights[dim] = round(max(0.1, base * rng.uniform(0.75, 1.25)), 2)
            spend = rng.choices(["free", "occasional", "spender"], weights=seg["spending"])[0]
            # แต่ละคนชอบ/เกลียดพล็อตไม่ครบทุกข้อของกลุ่ม
            loved = [t for t in seg["loved_tropes"] if rng.random() < 0.7]
            hated = [t for t in seg["hated_tropes"] if rng.random() < 0.75]
            panel.append({
                "id": f"R{idx:03d}",
                "name": f"{_NICKNAMES[(idx - 1) % len(_NICKNAMES)]}#{idx:03d}",
                "segment": seg["id"],
                "segment_label": seg["label"],
                "age": rng.choice(seg["ages"]),
                "requires": seg.get("requires", []),
                "likes": seg["likes"],
                "avoids": seg["avoids"],
                "loved_tropes": loved,
                "hated_tropes": hated,
                "weights": weights,
                "hook_threshold": round(rng.uniform(*seg["hook_threshold"]), 2),
                "patience": round(rng.uniform(5.5, 7.0), 2),
                "strictness": round(rng.uniform(*seg["strictness"]), 2),
                "spending": spend,
            })
    return panel
