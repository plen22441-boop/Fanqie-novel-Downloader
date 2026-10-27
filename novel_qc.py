#!/usr/bin/env python3
"""
novel_qc.py — ระบบ QC จำลองนักอ่าน MyNovel (ไทย)
รับไฟล์ .txt หรือ .epub แล้วประเมินจากมุมมองนักอ่านหญิงไทย

Usage:
    python novel_qc.py <novel_file> [--synopsis "คำโปรย..."] [--api-key sk-...]
    python novel_qc.py novel.txt
    python novel_qc.py novel.epub --synopsis "นิยายแนวย้อนยุค..."
"""

import argparse
import json
import os
import re
import sys
import textwrap
from pathlib import Path


# ── ดึงเนื้อหาจากไฟล์ ─────────────────────────────────────────────────────────

def read_txt(path: Path) -> tuple[str, str]:
    """คืน (title, full_text)"""
    text = path.read_text(encoding="utf-8", errors="replace")
    title = path.stem
    return title, text


def read_epub(path: Path) -> tuple[str, str]:
    """คืน (title, full_text) จาก epub"""
    try:
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup
    except ImportError:
        print("[!] ต้องการ ebooklib และ beautifulsoup4: pip install ebooklib bs4")
        sys.exit(1)

    book = epub.read_epub(str(path))
    title = book.title or path.stem

    chapters = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        text = soup.get_text("\n")
        if len(text.strip()) > 100:
            chapters.append(text.strip())

    return title, "\n\n".join(chapters)


def extract_sample(full_text: str, max_chars: int = 12000) -> str:
    """ดึง 3 บทแรก หรือ max_chars ตัวอักษรแรก"""
    # ลองแบ่งบทด้วย pattern ทั่วไป
    chapter_patterns = [
        r"(?m)^第[一二三四五六七八九十百千\d]+章",
        r"(?m)^Chapter\s+\d+",
        r"(?m)^ตอนที่\s+\d+",
        r"(?m)^\d+\.",
    ]
    for pattern in chapter_patterns:
        splits = re.split(pattern, full_text)
        if len(splits) >= 4:
            # เอา 3 บทแรก (splits[0] = ก่อนบทที่ 1, splits[1..3] = บท 1-3)
            sample = "\n\n".join(splits[:4])
            if len(sample) > max_chars:
                sample = sample[:max_chars]
            return sample.strip()

    # ถ้าแบ่งบทไม่ได้ เอาแค่ max_chars ตัวแรก
    return full_text[:max_chars].strip()


# ── สร้าง prompt ───────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """คุณคือทีม QC นิยายของสำนักพิมพ์ไทยที่เชี่ยวชาญตลาดนิยายออนไลน์ไทย
คุณประเมินนิยายจีนแปลสำหรับแพลตฟอร์ม MyNovel และเว็บนิยายไทยชั้นนำ

**ฐานนักอ่านที่คุณจำลอง:**
- นักอ่านหญิงไทย อายุ 18–35 ปี ที่ชอบนิยายจีนแปล
- อ่านบน MyNovel, นิยาย24h, Readawrite, Fictionlog
- ชอบแนวหลัก: โรแมนซ์ CEO/จอมมาร, ย้อนยุคจีน, แฟนตาซีรัก, ยามาตะ, เจ้าพ่อ×เจ้าสาว
- ต้องการ: ปมดึงดูดภายใน 3 บทแรก, พระเอก/นางเอกน่าติดตาม, tension สม่ำเสมอ
- ไม่ชอบ: บทนำยาวเกินไป, ตัวละครแบน, โครงเรื่องซ้ำมากโดยไม่มีจุดขายใหม่

**เกณฑ์ประเมินตลาด:**
- ความเร็วพล็อต (บท 1 ต้องมี hook)
- ความเป็น "จอมมาร/เจ้าพ่อ" ของพระเอก (ขายได้บนตลาดไทย)
- ความน่าเอาใจช่วยของนางเอก (ไม่ passive เกิน)
- ศักยภาพ fanbase / clip รีวิว / word of mouth
- ความเหมาะสมเนื้อหากับวัฒนธรรมไทย
- ความยาวเหมาะแก่การแปลและเผยแพร่ระยะยาว

ตอบเป็นภาษาไทย ในรูปแบบ JSON ที่กำหนด"""

def build_user_prompt(title: str, synopsis: str, sample: str) -> str:
    return f"""## นิยายที่ส่ง QC

**ชื่อเรื่อง:** {title}

**คำโปรย/synopsis:**
{synopsis or "(ไม่มีคำโปรย — ให้ประเมินจากเนื้อหาตัวอย่างอย่างเดียว)"}

**ตัวอย่างเนื้อหา (บทแรก ๆ):**
```
{sample}
```

---

กรุณาประเมินและตอบกลับใน JSON format นี้ เท่านั้น (ไม่ต้องมีข้อความอื่น):

{{
  "title_th": "ชื่อที่แนะนำสำหรับตลาดไทย",
  "overall_status": "ผ่านการคัดเลือก | ผ่านแบบมีเงื่อนไข | ไม่ผ่าน",
  "female_reader_score": <0.0–10.0>,
  "thai_market_score": <0.0–10.0>,
  "female_reader_analysis": "วิเคราะห์จากมุมนักอ่านหญิง 2–4 ประโยค",
  "market_editorial_analysis": "วิเคราะห์ตลาดและบรรณาธิการ 2–4 ประโยค",
  "risk_factors": ["จุดเสี่ยง 1", "จุดเสี่ยง 2", "จุดเสี่ยง 3"],
  "strengths": ["จุดแข็ง 1", "จุดแข็ง 2"],
  "genre_tags": ["แท็กแนว 1", "แท็กแนว 2"],
  "translation_priority": "สูง | กลาง | ต่ำ",
  "editor_notes": "หมายเหตุเพิ่มเติมสำหรับทีมแปล"
}}"""


# ── เรียก Claude API ───────────────────────────────────────────────────────────

def call_claude(system: str, user: str, api_key: str, model: str = "claude-opus-4-5") -> dict:
    try:
        import anthropic
    except ImportError:
        print("[!] ต้องการ anthropic SDK: pip install anthropic")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    raw = message.content[0].text.strip()

    # ดึง JSON ออกจาก response (กรณีมี markdown code block)
    json_match = re.search(r"\{[\s\S]+\}", raw)
    if json_match:
        return json.loads(json_match.group())
    return json.loads(raw)


# ── แสดงผลรายงาน ──────────────────────────────────────────────────────────────

BAR_WIDTH = 40

def score_bar(score: float, color: bool = True) -> str:
    filled = int(round(score / 10 * BAR_WIDTH))
    bar = "█" * filled + "░" * (BAR_WIDTH - filled)
    return bar


def print_report(result: dict, novel_title: str):
    W = 64
    sep = "─" * W

    print()
    print("╔" + "═" * W + "╗")
    print("║" + " 📚 รายงาน QC นิยาย — MyNovel Simulation ".center(W) + "║")
    print("╚" + "═" * W + "╝")
    print()

    title_display = result.get("title_th") or novel_title
    status = result.get("overall_status", "—")
    status_icon = {"ผ่านการคัดเลือก": "✅", "ผ่านแบบมีเงื่อนไข": "⚠️", "ไม่ผ่าน": "❌"}.get(status, "❓")
    print(f"  ชื่อ : {title_display}")
    print(f"  สถานะ: {status_icon} {status}")
    print(f"  ลำดับความสำคัญแปล: {result.get('translation_priority', '—')}")
    tags = "  ".join(result.get("genre_tags", []))
    if tags:
        print(f"  แนว : {tags}")
    print()
    print(sep)

    # คะแนน
    fr = float(result.get("female_reader_score", 0))
    tm = float(result.get("thai_market_score", 0))
    print(f"\n  ศักยภาพนักอ่านหญิง   {fr:.1f}/10")
    print(f"  {score_bar(fr)}")
    print(f"\n  ศักยภาพตลาดไทย       {tm:.1f}/10")
    print(f"  {score_bar(tm)}")

    print(f"\n{sep}")

    # จุดแข็ง
    strengths = result.get("strengths", [])
    if strengths:
        print("\n  ✨ จุดแข็ง")
        for s in strengths:
            print(f"     • {s}")

    # มุมนักอ่านหญิง
    print("\n  👩 มุมนักอ่านหญิง")
    for line in textwrap.wrap(result.get("female_reader_analysis", ""), width=W - 5):
        print(f"     {line}")

    # มุมตลาด
    print("\n  📊 มุมตลาดและบรรณาธิการ")
    for line in textwrap.wrap(result.get("market_editorial_analysis", ""), width=W - 5):
        print(f"     {line}")

    # จุดเสี่ยง
    risks = result.get("risk_factors", [])
    if risks:
        print("\n  ⚠️  จุดเสี่ยง")
        for r in risks:
            print(f"     • {r}")

    # หมายเหตุ
    notes = result.get("editor_notes", "")
    if notes:
        print("\n  📝 หมายเหตุทีมแปล")
        for line in textwrap.wrap(notes, width=W - 5):
            print(f"     {line}")

    print(f"\n{sep}\n")


def save_json_report(result: dict, novel_path: Path):
    out = novel_path.with_suffix(".qc.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  💾 บันทึก JSON: {out}")


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="QC นิยายจำลองนักอ่าน MyNovel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            ตัวอย่าง:
              python novel_qc.py novel.txt
              python novel_qc.py novel.epub --synopsis "พระเอกเป็นจอมมาร..."
              python novel_qc.py novel.txt --api-key sk-ant-...
              python novel_qc.py novel.txt --save-json
        """),
    )
    parser.add_argument("file", type=Path, help="ไฟล์นิยาย (.txt หรือ .epub)")
    parser.add_argument("--synopsis", default="", help="คำโปรย/synopsis ของนิยาย (ถ้ามี)")
    parser.add_argument("--api-key", default="", help="Anthropic API key (หรือตั้ง env ANTHROPIC_API_KEY)")
    parser.add_argument("--model", default="claude-opus-4-5", help="Claude model (default: claude-opus-4-5)")
    parser.add_argument("--save-json", action="store_true", help="บันทึกผลเป็น .qc.json")
    parser.add_argument("--max-chars", type=int, default=12000, help="จำนวนตัวอักษรตัวอย่าง (default: 12000)")
    args = parser.parse_args()

    # ตรวจไฟล์
    if not args.file.exists():
        print(f"[!] ไม่พบไฟล์: {args.file}")
        sys.exit(1)

    # API key
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[!] ต้องการ Anthropic API key\n"
              "    ตั้ง environment variable: export ANTHROPIC_API_KEY=sk-ant-...\n"
              "    หรือส่งผ่าน --api-key sk-ant-...")
        sys.exit(1)

    # อ่านไฟล์
    suffix = args.file.suffix.lower()
    print(f"[*] กำลังอ่าน {args.file.name} ...")
    if suffix == ".epub":
        title, full_text = read_epub(args.file)
    elif suffix == ".txt":
        title, full_text = read_txt(args.file)
    else:
        print(f"[!] รองรับเฉพาะ .txt และ .epub (ได้รับ: {suffix})")
        sys.exit(1)

    # ดึงตัวอย่าง
    sample = extract_sample(full_text, max_chars=args.max_chars)
    char_count = len(full_text)
    print(f"[*] ความยาวทั้งหมด: {char_count:,} ตัวอักษร | ตัวอย่างที่ส่ง: {len(sample):,} ตัวอักษร")

    # เรียก Claude
    print(f"[*] กำลังวิเคราะห์ด้วย {args.model} ...")
    user_prompt = build_user_prompt(title, args.synopsis, sample)

    result = call_claude(SYSTEM_PROMPT, user_prompt, api_key, args.model)

    # แสดงผล
    print_report(result, title)

    # บันทึก JSON
    if args.save_json:
        save_json_report(result, args.file)


if __name__ == "__main__":
    main()
