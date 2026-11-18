"""
QC ไฟล์นิยาย (.txt) ที่โหลดมาจากแหล่งอื่น

ตรวจ: ตอนขาด / ตอนซ้ำ / ลำดับสลับ / ตอนสั้นผิดปกติ / ตัวอักษรเสีย (encoding, อักขระกันก๊อป)
      / ข้อความโฆษณาหรือลายน้ำของเว็บที่ติดมา / ตอนที่เนื้อหาซ้ำกันทั้งตอน

ใช้:  python scraper/qc_txt.py <ไฟล์.txt> [--min-chars 300] [--json report.json]
"""
import argparse, hashlib, json, re, statistics, sys
from collections import Counter

CN_NUM = {c: i for i, c in enumerate("零一二三四五六七八九")} | {"两": 2, "〇": 0}
CN_UNIT = {"十": 10, "百": 100, "千": 1000, "万": 10000}

HEAD_RE = re.compile(
    r"^\s*(?:正文\s*)?(?:第\s*([0-9０-９]+|[零〇一二两三四五六七八九十百千万]+)\s*[章节回话]"
    r"|Chapter\s*(\d+)|ตอนที่\s*(\d+))(.*)$", re.I)
AD_RE = re.compile(
    r"(www\.|https?://|\.com|\.net|\.org|笔趣阁|biquge|69shu|顶点小说|手机阅读|最新章节|"
    r"请记住本书|本书首发|首发网址|一秒记住|天才一秒|加入书签|投推荐票|求月票|求打赏|"
    r"章节错误|点此举报|免费阅读|小说网|阅读网|PS[:：]|ps[:：]|本章完|未完待续|请收藏)", re.I)
BAD_RE = re.compile(r"[�-]")       # replacement char + private-use (anti-copy fonts)


def cn2int(s: str) -> int | None:
    s = s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if s.isdigit():
        return int(s)
    total, section, num = 0, 0, 0
    for ch in s:
        if ch in CN_NUM:
            num = CN_NUM[ch]
        elif ch in CN_UNIT:
            unit = CN_UNIT[ch]
            if unit == 10000:
                total += (section + num) * unit; section = 0
            else:
                section += (num or 1) * unit
            num = 0
        else:
            return None
    return total + section + num


def read_text(path: str) -> str:
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "gb18030", "big5", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def split_chapters(text: str) -> tuple[str, list[dict]]:
    lines = text.splitlines()
    chapters, header, cur = [], [], None
    for i, line in enumerate(lines, 1):
        m = HEAD_RE.match(line) if len(line) < 80 else None
        num = None
        if m:
            num = cn2int(m.group(1)) if m.group(1) else int(m.group(2) or m.group(3))
        if num is not None:
            cur = {"no": num, "title": line.strip(), "line": i, "body": []}
            chapters.append(cur)
        elif cur:
            cur["body"].append(line)
        else:
            header.append(line)
    return "\n".join(header), chapters


def qc(path: str, min_chars: int = 300) -> dict:
    text = read_text(path)
    header, chs = split_chapters(text)
    nums = [c["no"] for c in chs]
    for c in chs:
        body = "\n".join(c["body"])
        c["chars"] = len(re.sub(r"\s", "", body))
        c["bad_chars"] = len(BAD_RE.findall(body))
        c["ads"] = sorted({l.strip()[:60] for l in c["body"] if AD_RE.search(l)})[:5]
        c["hash"] = hashlib.md5(re.sub(r"\s", "", body).encode()).hexdigest() if c["chars"] > 50 else ""

    cnt = Counter(nums)
    missing = sorted(set(range(min(nums), max(nums) + 1)) - set(nums)) if nums else []
    out_of_order = [chs[i]["no"] for i in range(1, len(chs)) if chs[i]["no"] < chs[i - 1]["no"]]
    hashes = Counter(c["hash"] for c in chs if c["hash"])
    med = statistics.median([c["chars"] for c in chs]) if chs else 0
    short = [c for c in chs if c["chars"] < min_chars or (med and c["chars"] < med * 0.3)]

    r = {
        "file": path,
        "header_preview": header.strip()[:300],
        "chapters_found": len(chs),
        "first": nums[0] if nums else None, "last": nums[-1] if nums else None,
        "total_chars": sum(c["chars"] for c in chs),
        "median_chars": int(med),
        "missing": missing,
        "duplicates": sorted(n for n, k in cnt.items() if k > 1),
        "out_of_order": out_of_order,
        "short": [{"no": c["no"], "title": c["title"], "chars": c["chars"]} for c in short],
        "same_content": [[c["no"] for c in chs if c["hash"] == h] for h, k in hashes.items() if k > 1],
        "bad_chars": [{"no": c["no"], "count": c["bad_chars"]} for c in chs if c["bad_chars"]],
        "ads": [{"no": c["no"], "lines": c["ads"]} for c in chs if c["ads"]],
    }
    problems = r["missing"] or r["duplicates"] or r["out_of_order"] or r["short"] or \
        r["same_content"] or r["bad_chars"]
    r["verdict"] = "FAIL" if (not chs or problems) else ("PASS (มีโฆษณาต้องลบ)" if r["ads"] else "PASS")
    return r


def fmt(nums: list, limit: int = 40) -> str:
    if not nums:
        return "ไม่มี ✓"
    s = ", ".join(map(str, nums[:limit]))
    return s + (f" …(+{len(nums) - limit})" if len(nums) > limit else "")


def report_text(r: dict) -> str:
    L = [f"QC: {r['file']}",
         f"ผล: {r['verdict']}",
         f"พบ {r['chapters_found']} ตอน (ตอนที่ {r['first']}–{r['last']}), "
         f"รวม {r['total_chars']:,} ตัวอักษร, มัธยฐาน {r['median_chars']:,}/ตอน",
         f"ตอนขาด: {fmt(r['missing'])}",
         f"ตอนซ้ำ: {fmt(r['duplicates'])}",
         f"ลำดับสลับ: {fmt(r['out_of_order'])}",
         f"เนื้อหาซ้ำทั้งตอน: {fmt([' = '.join(map(str, g)) for g in r['same_content']])}",
         f"ตัวอักษรเสีย: {fmt([f'{b['no']}({b['count']})' for b in r['bad_chars']])}",
         f"ตอนสั้นผิดปกติ: {fmt([f'{s['no']}({s['chars']})' for s in r['short']])}",
         f"มีโฆษณา/ลายน้ำ: {fmt([a['no'] for a in r['ads']])}"]
    for a in r["ads"][:5]:
        L.append(f"   ตอน {a['no']}: {a['lines'][0]}")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--min-chars", type=int, default=300)
    ap.add_argument("--json")
    a = ap.parse_args()
    r = qc(a.file, a.min_chars)
    print(report_text(r))
    if a.json:
        json.dump(r, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return 0 if r["verdict"].startswith("PASS") else 1


if __name__ == "__main__":
    sys.exit(main())
