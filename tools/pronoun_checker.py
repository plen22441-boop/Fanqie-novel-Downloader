"""
Pronoun Checker — ตรวจสรรพนาม/ชื่อในไฟล์แปลภาษาไทย
ใช้งาน:
  python tools/pronoun_checker.py --novel "ชื่อนิยาย" --file "chapter_001.txt"
  python tools/pronoun_checker.py --novel "ชื่อนิยาย" --dir "chapters/"
  python tools/pronoun_checker.py --novel "ชื่อนิยาย" --file "ch.txt" --report report.md
"""

import json
import re
import argparse
from pathlib import Path
from dataclasses import dataclass, field

BASE_DIR = Path(__file__).parent.parent / "glossary"

# สรรพนามชาย/หญิงในภาษาไทย
MALE_PRONOUNS = {"เขา", "ท่าน", "พ่อ", "ลุง", "ปู่", "ตา", "พี่ชาย", "น้องชาย", "หนุ่ม", "ชาย"}
FEMALE_PRONOUNS = {"เธอ", "นาง", "หล่อน", "แม่", "ป้า", "ย่า", "ยาย", "พี่สาว", "น้องสาว", "สาว", "หญิง"}
# น้า/อา ใช้ได้ทั้งสองเพศ จึงไม่ใส่ใน strict check

# คำที่บ่งชี้เพศชาย/หญิงอยู่ใกล้กัน (window ±30 ตัวอักษร)
MALE_SIGNALS = MALE_PRONOUNS | {"บุตรชาย", "ลูกชาย", "สามี", "ผัว", "เจ้าชาย", "ราชา", "กษัตริย์"}
FEMALE_SIGNALS = FEMALE_PRONOUNS | {"บุตรสาว", "ลูกสาว", "ภรรยา", "เมีย", "เจ้าหญิง", "ราชินี", "นางสาว"}


@dataclass
class Issue:
    line_no: int
    line_text: str
    issue_type: str
    detail: str
    severity: str = "warn"  # "error" | "warn" | "info"


def load_json(path: Path):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_glossary(novel: str):
    d = BASE_DIR / novel
    chars = load_json(d / "characters.json")
    places = load_json(d / "places.json")
    terms = load_json(d / "terms.json")
    return chars, places, terms


def build_name_index(chars: dict) -> dict:
    """สร้าง index: ชื่อไทย → {gender, pronoun, zh_name}"""
    index = {}
    for zh, info in chars.items():
        th = info.get("th", "")
        if th:
            index[th] = {"gender": info.get("gender", "unknown"),
                         "pronoun": info.get("pronoun", ""),
                         "zh": zh}
    return index


def check_pronoun_near_name(line: str, name: str, expected_gender: str, line_no: int) -> list[Issue]:
    """ตรวจสรรพนามรอบๆ ชื่อในบรรทัดเดียวกัน"""
    issues = []
    if name not in line:
        return issues

    wrong_pronouns = FEMALE_PRONOUNS if expected_gender == "male" else MALE_PRONOUNS if expected_gender == "female" else set()

    for wrong in wrong_pronouns:
        # ตรวจว่ามีสรรพนามผิดเพศอยู่ใกล้ชื่อใน ±50 ตัวอักษร
        pattern = re.compile(re.escape(wrong))
        name_positions = [m.start() for m in re.finditer(re.escape(name), line)]
        wrong_positions = [m.start() for m in pattern.finditer(line)]

        for np in name_positions:
            for wp in wrong_positions:
                if abs(np - wp) <= 50:
                    gender_th = "ชาย" if expected_gender == "male" else "หญิง"
                    issues.append(Issue(
                        line_no=line_no,
                        line_text=line.strip(),
                        issue_type="pronoun_mismatch",
                        detail=f'"{name}" เป็น{gender_th} แต่พบ "{wrong}" อยู่ใกล้กัน',
                        severity="error",
                    ))
                    break

    return issues


def check_glossary_consistency(line: str, chars: dict, places: dict, terms: dict, line_no: int) -> list[Issue]:
    """ตรวจว่าใช้ชื่อแปลตรงกับ glossary ไหม (ตรวจจีน→ไทย)"""
    issues = []

    # ตรวจชื่อจีนที่อาจหลุดมาโดยไม่ได้แปล
    zh_pattern = re.compile(r'[一-鿿]{2,}')
    for m in zh_pattern.finditer(line):
        zh_word = m.group()
        # เช็คว่าอยู่ใน glossary ไหม
        if zh_word in chars:
            issues.append(Issue(
                line_no=line_no,
                line_text=line.strip(),
                issue_type="untranslated_name",
                detail=f'พบชื่อจีน "{zh_word}" ที่ยังไม่ได้แปลเป็น "{chars[zh_word].get("th", "?")}"',
                severity="error",
            ))
        elif zh_word in places:
            issues.append(Issue(
                line_no=line_no,
                line_text=line.strip(),
                issue_type="untranslated_place",
                detail=f'พบชื่อสถานที่จีน "{zh_word}" ที่ยังไม่ได้แปลเป็น "{places[zh_word].get("th", "?")}"',
                severity="error",
            ))
        elif zh_word in terms:
            issues.append(Issue(
                line_no=line_no,
                line_text=line.strip(),
                issue_type="untranslated_term",
                detail=f'พบคำศัพท์จีน "{zh_word}" ที่ยังไม่ได้แปลเป็น "{terms[zh_word].get("th", "?")}"',
                severity="warn",
            ))

    return issues


def check_file(filepath: Path, chars: dict, places: dict, terms: dict) -> list[Issue]:
    name_index = build_name_index(chars)
    all_issues = []

    with open(filepath, encoding="utf-8") as f:
        lines = f.readlines()

    for i, line in enumerate(lines, start=1):
        # 1. เช็คสรรพนามผิดเพศรอบๆ ชื่อ
        for th_name, info in name_index.items():
            issues = check_pronoun_near_name(line, th_name, info["gender"], i)
            all_issues.extend(issues)

        # 2. เช็คชื่อจีนที่ยังไม่ได้แปล
        all_issues.extend(check_glossary_consistency(line, chars, places, terms, i))

    return all_issues


def format_report(filepath: Path, issues: list[Issue]) -> str:
    lines = [f"# ผลการตรวจ: {filepath.name}\n"]
    if not issues:
        lines.append("✅ ไม่พบปัญหา\n")
        return "\n".join(lines)

    errors = [i for i in issues if i.severity == "error"]
    warns = [i for i in issues if i.severity == "warn"]

    lines.append(f"พบ {len(errors)} errors, {len(warns)} warnings\n")

    if errors:
        lines.append("\n## ❌ Errors (ต้องแก้)\n")
        for iss in errors:
            lines.append(f"**บรรทัด {iss.line_no}** [{iss.issue_type}]")
            lines.append(f"  {iss.detail}")
            lines.append(f"  > {iss.line_text[:120]}")
            lines.append("")

    if warns:
        lines.append("\n## ⚠️ Warnings (ควรตรวจสอบ)\n")
        for iss in warns:
            lines.append(f"**บรรทัด {iss.line_no}** [{iss.issue_type}]")
            lines.append(f"  {iss.detail}")
            lines.append(f"  > {iss.line_text[:120]}")
            lines.append("")

    return "\n".join(lines)


def print_summary(filepath: Path, issues: list[Issue]):
    errors = [i for i in issues if i.severity == "error"]
    warns = [i for i in issues if i.severity == "warn"]

    if not issues:
        print(f"  ✅ {filepath.name}: ไม่พบปัญหา")
        return

    print(f"  📄 {filepath.name}: {len(errors)} errors, {len(warns)} warnings")
    for iss in issues[:5]:  # แสดง 5 อันแรก
        icon = "❌" if iss.severity == "error" else "⚠️"
        print(f"    {icon} บรรทัด {iss.line_no}: {iss.detail}")
    if len(issues) > 5:
        print(f"    ... และอีก {len(issues)-5} รายการ (ดูรายงาน --report)")


def main():
    parser = argparse.ArgumentParser(description="ตรวจสรรพนาม/ชื่อในนิยายแปลจีน→ไทย")
    parser.add_argument("--novel", required=True, help="ชื่อนิยาย (ตรงกับโฟลเดอร์ใน glossary/)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", help="ไฟล์ .txt ที่แปลแล้ว")
    group.add_argument("--dir", help="โฟลเดอร์ที่มีหลายไฟล์")
    parser.add_argument("--report", help="บันทึกรายงานเป็นไฟล์ .md")
    parser.add_argument("--errors-only", action="store_true", help="แสดงเฉพาะ errors")
    args = parser.parse_args()

    chars, places, terms = load_glossary(args.novel)
    if not chars and not places and not terms:
        print(f"[WARN] ยังไม่มี glossary สำหรับ '{args.novel}'")
        print(f"  สร้างก่อนด้วย: python tools/glossary_manager.py --novel \"{args.novel}\" add-char")

    files = []
    if args.file:
        files = [Path(args.file)]
    else:
        files = sorted(Path(args.dir).glob("*.txt"))

    all_reports = []
    total_errors = total_warns = 0

    print(f"\nกำลังตรวจ {len(files)} ไฟล์ สำหรับนิยาย: {args.novel}\n")

    for fp in files:
        issues = check_file(fp, chars, places, terms)
        if args.errors_only:
            issues = [i for i in issues if i.severity == "error"]
        print_summary(fp, issues)
        all_reports.append(format_report(fp, issues))
        total_errors += sum(1 for i in issues if i.severity == "error")
        total_warns += sum(1 for i in issues if i.severity == "warn")

    print(f"\n{'─'*40}")
    print(f"รวม: {total_errors} errors, {total_warns} warnings")

    if args.report:
        report_path = Path(args.report)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n\n---\n\n".join(all_reports))
        print(f"[รายงาน] {report_path}")


if __name__ == "__main__":
    main()
