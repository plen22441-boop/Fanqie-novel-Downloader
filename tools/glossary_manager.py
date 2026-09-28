"""
Glossary Manager — จัดการ glossary สำหรับนิยายจีน→ไทย
ใช้งาน:
  python tools/glossary_manager.py --novel "ชื่อนิยาย" add-char
  python tools/glossary_manager.py --novel "ชื่อนิยาย" add-place
  python tools/glossary_manager.py --novel "ชื่อนิยาย" add-term
  python tools/glossary_manager.py --novel "ชื่อนิยาย" list
  python tools/glossary_manager.py --novel "ชื่อนิยาย" export
"""

import json
import os
import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent / "glossary"

MALE_PRONOUNS = ["เขา", "ท่าน", "หล่อน", "พ่อ", "ลุง", "น้า", "อา", "ปู่", "ตา", "พี่ชาย", "น้องชาย"]
FEMALE_PRONOUNS = ["เธอ", "นาง", "หล่อน", "แม่", "ป้า", "น้า", "อา", "ย่า", "ยาย", "พี่สาว", "น้องสาว"]

# หมายเหตุ: น้า/อา ใช้ได้ทั้งชายและหญิง จึงอยู่ทั้งสองฝั่ง


def get_glossary_dir(novel: str) -> Path:
    d = BASE_DIR / novel
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_json(path: Path) -> dict | list:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[บันทึก] {path}")


def add_character(novel: str):
    d = get_glossary_dir(novel)
    path = d / "characters.json"
    chars = load_json(path)

    print("\n─── เพิ่มตัวละคร ───")
    zh_name = input("ชื่อจีน (ต้นฉบับ): ").strip()
    if not zh_name:
        print("[ยกเลิก] ไม่ได้ใส่ชื่อ")
        return

    th_name = input("ชื่อไทย (ทับศัพท์): ").strip()

    print("เพศ: 1=ชาย  2=หญิง  3=ไม่ระบุ")
    gender_map = {"1": "male", "2": "female", "3": "unknown"}
    gender = gender_map.get(input("เลือก (1/2/3): ").strip(), "unknown")

    if gender == "male":
        pronoun_th = input(f"สรรพนามที่ใช้แทน (default: เขา): ").strip() or "เขา"
    elif gender == "female":
        pronoun_th = input(f"สรรพนามที่ใช้แทน (default: เธอ): ").strip() or "เธอ"
    else:
        pronoun_th = input("สรรพนามที่ใช้แทน: ").strip() or "เขา"

    role = input("บทบาท (เช่น พระเอก/นางเอก/ผู้ร้าย/ตัวประกอบ): ").strip()
    note = input("หมายเหตุ (เว้นว่างได้): ").strip()

    chars[zh_name] = {
        "th": th_name,
        "gender": gender,
        "pronoun": pronoun_th,
        "role": role,
        "note": note,
    }
    save_json(path, chars)
    print(f"[เพิ่มแล้ว] {zh_name} → {th_name} ({gender}, pronoun: {pronoun_th})")


def add_place(novel: str):
    d = get_glossary_dir(novel)
    path = d / "places.json"
    places = load_json(path)

    print("\n─── เพิ่มสถานที่ ───")
    zh = input("ชื่อจีน: ").strip()
    if not zh:
        return
    th = input("ชื่อไทย: ").strip()
    note = input("หมายเหตุ (เว้นว่างได้): ").strip()

    places[zh] = {"th": th, "note": note}
    save_json(path, places)


def add_term(novel: str):
    d = get_glossary_dir(novel)
    path = d / "terms.json"
    terms = load_json(path)

    print("\n─── เพิ่มคำศัพท์เฉพาะ ───")
    zh = input("คำจีน: ").strip()
    if not zh:
        return
    th = input("คำแปลไทย: ").strip()
    category = input("หมวด (เช่น ระดับ/เทคนิค/ไอเทม/องค์กร): ").strip()
    note = input("หมายเหตุ (เว้นว่างได้): ").strip()

    terms[zh] = {"th": th, "category": category, "note": note}
    save_json(path, terms)


def list_glossary(novel: str):
    d = get_glossary_dir(novel)

    for filename, label in [("characters.json", "ตัวละคร"), ("places.json", "สถานที่"), ("terms.json", "คำศัพท์")]:
        path = d / filename
        data = load_json(path)
        if not data:
            continue
        print(f"\n══ {label} ({len(data)} รายการ) ══")
        for zh, info in data.items():
            th = info.get("th", "?")
            extra = ""
            if filename == "characters.json":
                g = info.get("gender", "")
                p = info.get("pronoun", "")
                extra = f"  [{g}] pronoun={p}"
                if info.get("role"):
                    extra += f"  บทบาท={info['role']}"
            elif info.get("category"):
                extra = f"  [{info['category']}]"
            print(f"  {zh} → {th}{extra}")


def export_glossary(novel: str):
    """ส่งออกเป็น Markdown สำหรับอ้างอิงตอนแปล"""
    d = get_glossary_dir(novel)
    out_path = d / "glossary_reference.md"
    lines = [f"# Glossary: {novel}\n"]

    for filename, label in [("characters.json", "ตัวละคร"), ("places.json", "สถานที่"), ("terms.json", "คำศัพท์เฉพาะ")]:
        data = load_json(d / filename)
        if not data:
            continue
        lines.append(f"\n## {label}\n")
        lines.append("| จีน | ไทย | หมายเหตุ |")
        lines.append("|-----|-----|---------|")
        for zh, info in data.items():
            th = info.get("th", "")
            note_parts = []
            if filename == "characters.json":
                g = "ชาย" if info.get("gender") == "male" else ("หญิง" if info.get("gender") == "female" else "")
                p = info.get("pronoun", "")
                r = info.get("role", "")
                if g:
                    note_parts.append(g)
                if p:
                    note_parts.append(f"pronoun: {p}")
                if r:
                    note_parts.append(r)
            note = info.get("note", "")
            if note:
                note_parts.append(note)
            lines.append(f"| {zh} | {th} | {', '.join(note_parts)} |")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[ส่งออก] {out_path}")


def batch_import(novel: str, filepath: str):
    """นำเข้าจาก CSV: zh,th,type,gender,pronoun,role,note"""
    import csv
    d = get_glossary_dir(novel)
    chars, places, terms = load_json(d / "characters.json"), load_json(d / "places.json"), load_json(d / "terms.json")

    with open(filepath, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            zh = row.get("zh", "").strip()
            th = row.get("th", "").strip()
            kind = row.get("type", "").strip().lower()
            if not zh or not th:
                continue
            def s(key, default=""):
                v = row.get(key)
                return v.strip() if v else default

            if kind == "character":
                chars[zh] = {"th": th, "gender": s("gender", "unknown"),
                              "pronoun": s("pronoun", "เขา"),
                              "role": s("role"), "note": s("note")}
            elif kind == "place":
                places[zh] = {"th": th, "note": s("note")}
            else:
                terms[zh] = {"th": th, "category": s("role"), "note": s("note")}

    save_json(d / "characters.json", chars)
    save_json(d / "places.json", places)
    save_json(d / "terms.json", terms)
    print("[นำเข้าเสร็จ]")


def main():
    parser = argparse.ArgumentParser(description="Glossary Manager สำหรับนิยายจีน→ไทย")
    parser.add_argument("--novel", required=True, help="ชื่อนิยาย (ใช้เป็นชื่อโฟลเดอร์)")
    parser.add_argument("command", choices=["add-char", "add-place", "add-term", "list", "export", "import"],
                        help="คำสั่งที่ต้องการ")
    parser.add_argument("--file", help="ไฟล์ CSV สำหรับ import")
    args = parser.parse_args()

    cmd_map = {
        "add-char": lambda: add_character(args.novel),
        "add-place": lambda: add_place(args.novel),
        "add-term": lambda: add_term(args.novel),
        "list": lambda: list_glossary(args.novel),
        "export": lambda: export_glossary(args.novel),
        "import": lambda: batch_import(args.novel, args.file) if args.file else print("[ERROR] ต้องระบุ --file"),
    }
    cmd_map[args.command]()


if __name__ == "__main__":
    main()
