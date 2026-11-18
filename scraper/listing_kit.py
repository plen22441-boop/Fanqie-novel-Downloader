"""
Listing kit — ข้อมูลเตรียมลงเรื่องบน MyNovel (ทำหลัง QC)

อ่านแค่ "หน้าเรื่อง" หน้าเดียว (ไม่ไล่ตอน) แล้วสรุป:
  • ชื่อเรื่อง / ผู้แต่ง ภาษาจีน, หมวด, เรื่องย่อต้นฉบับ
  • แฮชแท็กที่ตรงกับเรื่อง เรียงตามความนิยมจริงบน MyNovel (จาก branch mynovel-data)
  • ตัวอย่างชื่อเรื่องไทยที่ติดวิวสูงในแท็กเดียวกัน (ใช้เป็นแนวตั้งชื่อ)
  • (ถ้ามี ANTHROPIC_API_KEY) ชื่อเรื่องไทยที่แนะนำ + คำโปรย + เรื่องย่อ โดย Claude
    ถ้าไม่มี key จะเขียน prompt ไว้ให้คัดลอกไปวางในแชตแทน

ใช้:  python scraper/listing_kit.py <book_url> [--stats store.json] [--out output] [--name ชื่อไฟล์]
ไม่ต้องติดตั้งอะไรเพิ่ม (ใช้ stdlib) ยกเว้นส่วน Claude ที่ต้องมี `pip install anthropic`
"""
import argparse, html as htmlmod, json, math, os, pathlib, re, statistics, subprocess, sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
STATS_URL = ("https://raw.githubusercontent.com/plen22441-boop/"
             "Fanqie-novel-Downloader/mynovel-data/store.json")

# ── 1. fetch the book page (one page only) ───────────────────────────────────

def fetch(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        charset = r.headers.get_content_charset()
    if not charset:
        m = re.search(rb'charset=["\']?([\w-]+)', raw[:4000], re.I)
        charset = m.group(1).decode() if m else "utf-8"
    charset = {"gb2312": "gbk"}.get(charset.lower(), charset)
    try:
        return raw.decode(charset)
    except (LookupError, UnicodeDecodeError):
        return raw.decode("gbk", errors="replace")


def _meta(page: str, *names: str) -> str:
    for n in names:
        for pat in (rf'<meta[^>]+(?:property|name)=["\']{re.escape(n)}["\'][^>]*content=["\']([^"\']*)',
                    rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']{re.escape(n)}["\']'):
            m = re.search(pat, page, re.I)
            if m and m.group(1).strip():
                return htmlmod.unescape(m.group(1)).strip()
    return ""


def _json_str(page: str, key: str) -> str:
    """First "key":"..." string value in embedded JSON, unescaped."""
    m = re.search(rf'"{key}"\s*:\s*("(?:[^"\\]|\\.)*")', page)
    if not m:
        return ""
    try:
        return json.loads(m.group(1)).strip()
    except ValueError:
        return ""


def _text(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>|</p>", "\n", fragment, flags=re.I)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    return re.sub(r"\n\s*\n+", "\n", htmlmod.unescape(fragment)).strip()


def extract_book(page: str, url: str) -> dict:
    info = {"url": url, "title": "", "author": "", "intro": "", "categories": [],
            "status": "", "words": "", "keywords": ""}

    if "fanqienovel.com" in url:                         # 番茄: embedded state JSON
        info["title"] = _json_str(page, "bookName")
        info["intro"] = _json_str(page, "abstract")
        m = re.search(r'"author"\s*:\s*\[\{[^\]]*?"name"\s*:\s*("(?:[^"\\]|\\.)*")', page)
        info["author"] = json.loads(m.group(1)) if m else _json_str(page, "authorName")
        cat = _json_str(page, "categoryV2")
        try:
            info["categories"] = [c["Name"] for c in json.loads(cat)] if cat else []
        except (ValueError, KeyError, TypeError):
            pass
        m = re.search(r'"wordNumber"\s*:\s*(\d+)', page)
        info["words"] = m.group(1) if m else ""
        m = re.search(r'"creationStatus"\s*:\s*(\d)', page)
        if m:
            info["status"] = "完结" if m.group(1) == "0" else "连载中"

    # Generic: most Chinese novel sites publish og:novel:* tags
    info["title"] = info["title"] or _meta(page, "og:novel:book_name", "og:title")
    info["author"] = info["author"] or _meta(page, "og:novel:author", "author")
    info["intro"] = info["intro"] or _meta(page, "og:description")
    if not info["categories"]:
        c = _meta(page, "og:novel:category")
        info["categories"] = [x for x in re.split(r"[,，/、 ]+", c) if x]
    info["status"] = info["status"] or _meta(page, "og:novel:status")
    info["keywords"] = _meta(page, "keywords")

    if not info["intro"]:                                # common intro containers
        for sel in (r'id=["\']intro["\']', r'class=["\'][^"\']*\bintro\b',
                    r'class=["\'][^"\']*\bdesc\b', r'class=["\'][^"\']*\bsummary\b'):
            m = re.search(rf'<(div|p|section)[^>]*{sel}[^>]*>(.*?)</\1>', page, re.S | re.I)
            if m and len(_text(m.group(2))) > 20:
                info["intro"] = _text(m.group(2)); break
    if not info["intro"]:
        info["intro"] = _meta(page, "description")
    if not info["title"]:
        m = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S | re.I) or \
            re.search(r"<title>(.*?)</title>", page, re.S | re.I)
        info["title"] = re.split(r"[_\-|｜—]", _text(m.group(1)))[0].strip() if m else ""
    if not info["author"]:
        m = re.search(r"作\s*者\s*[:：]\s*(?:<[^>]+>\s*)*([^<\s]{1,30})", page)
        info["author"] = m.group(1) if m else ""

    info["intro"] = re.sub(r"\s*(最新章节|免费阅读|全文阅读).{0,40}$", "", info["intro"]).strip()
    return info

# ── 2. Chinese genre words → MyNovel Thai hashtags ───────────────────────────
# Keys are regexes matched in title/intro/category/keywords. A match preceded
# by a negation (不/无/非/没有, e.g. "不系统，不后宫") is ignored.

GENRE_MAP = [
    (r"穿越|魂穿|穿到|穿成", ["ทะลุมิติ", "ข้ามมิติ"]),
    (r"穿书|书中|小说里", ["ทะลุนิยาย"]),
    (r"重生|回到.{0,4}年", ["เกิดใหม่", "ย้อนเวลา"]),
    (r"系统|金手指", ["ระบบ"]),
    (r"修仙|修真|仙侠|飞升|渡劫|灵根|宗门|仙界", ["เทพเซียน", "บำเพ็ญเพียร"]),
    (r"武侠|江湖|内力|武功", ["กำลังภายใน"]),
    (r"玄幻|奇幻|魔法|异世|异界|斗气", ["แฟนตาซี", "ต่างโลก"]),
    (r"末世|末日|丧尸|天灾|灾变", ["วันสิ้นโลก", "เอาชีวิตรอด"]),
    (r"囤货|囤积|物资", ["กักตุนเสบียง"]),
    (r"空间|随身", ["มิติพกพา", "มิติวิเศษ"]),
    (r"七零|70年代|七十年代", ["ยุค70"]),
    (r"八零|80年代|八十年代", ["ยุค80"]),
    (r"六零|60年代|六十年代", ["ยุค60"]),
    (r"年代文|年代", ["ย้อนยุค"]),
    (r"种田|农家|乡村|田园|赶海", ["ชีวิตประจำวัน", "สร้างฐานะ"]),
    (r"女强|大女主|女帝|飒", ["นางเอกเก่ง"]),
    (r"甜宠|宠妻|独宠|宠溺|偏执|追妻", ["พระเอกคลั่งรัก", "โรแมนติก"]),
    (r"言情|爱情|恋爱|婚|先婚", ["โรแมนติก"]),
    (r"复仇|报仇|虐渣", ["แก้แค้น"]),
    (r"打脸|爽文|虐渣", ["ตบหน้าคนชั่ว", "สะใจ"]),
    (r"宫斗|宅斗|夺嫡|权谋", ["ชิงอำนาจ"]),
    (r"古代|王朝|皇帝|太子|王爷|皇后|公主|侯府|将军府", ["จีนโบราณ"]),
    (r"历史|架空", ["ประวัติศาสตร์"]),
    (r"三国", ["สามก๊ก"]),
    (r"都市|现代(?!言情)|豪门", ["ยุคปัจจุบัน"]),
    (r"无敌|最强|逆天|天才", ["พระเอกเทพ", "ไร้เทียมทาน"]),
    (r"后宫", ["ฮาเร็ม"]),
    (r"萌宝|带娃|养娃|奶娃|崽", ["เลี้ยงลูก"]),
    (r"家庭|一家|全家", ["ครอบครัว", "ครอบครัวอบอุ่น"]),
    (r"搞笑|沙雕|轻松|欢乐", ["คอมเมดี้", "อ่านเพลิน"]),
    (r"悬疑|推理|探案", ["สืบสวน", "ลึกลับ"]),
    (r"恐怖|惊悚|灵异|诡异|规则怪谈", ["สยองขวัญ"]),
    (r"游戏|无限流|死亡|求生|逃生", ["เอาชีวิตรอด"]),
    (r"异能|超能力|觉醒|超自然", ["พลังพิเศษ"]),
    (r"战争|抗战|军旅|军人|参军|军营|特种兵", ["สงคราม", "ทหาร"]),
    (r"经商|商业|创业|首富|赚钱|发家", ["ธุรกิจ", "สร้างตัว"]),
    (r"基建|领主|建设|种族|城池", ["สร้างเมือง"]),
    (r"科幻|星际|机甲", ["ไซไฟ"]),
    (r"同人", ["แฟนฟิค"]),
    (r"女配|炮灰|配角|路人", ["ตัวประกอบ"]),
    (r"智斗|谋略|腹黑|智商", ["พระเอกฉลาด"]),
    (r"直播|主播", ["ไลฟ์สด", "ไลฟ์สตรีม"]),
    (r"星际|宇宙|星球", ["อวกาศ"]),
    (r"美食|厨|做饭|吃货", ["ทำอาหาร"]),
    (r"赶海|海鲜|渔", ["หาของทะเล", "ทะเล"]),
    (r"军官|团长|首长|军嫂|军婚|兵哥", ["ทหาร", "แต่งงานทหาร", "ทหารคลั่งรัก"]),
    (r"医生|神医|医术|医女|中医", ["หมอ", "แพทย์หญิง"]),
    (r"真假千金|真千金|假千金", ["คุณหนูตัวจริง"]),
    (r"萌宝|团宠|奶团|小福宝", ["เด็กน่ารัก"]),
    (r"无CP|无cp|无感情线", ["ไม่มีคู่รัก"]),
    (r"先婚后爱|闪婚", ["แต่งก่อนรัก"]),
    (r"乡村|农门|农村|山村|穷山", ["ชนบท", "ชีวิตชนบท"]),
    (r"暴富|发家|致富", ["สร้างความร่ำรวย"]),
    (r"分家|断亲", ["แยกบ้านตัดญาติ", "ตัดขาดครอบครัว"]),
    (r"老太|奶奶|阿婆", ["ย่าสายแสบ"]),
    (r"娱乐圈|明星|影帝|顶流", ["วงการบันเทิง"]),
    (r"总裁|霸总", ["ประธานจอมเผด็จการ"]),
    (r"官场|县长|市长|仕途", ["การเมือง"]),
    (r"双洁|1v1|一对一", ["รักเดียวใจเดียว"]),
    (r"快穿", ["ข้ามภพ", "ทะลุมิติ"]),
    (r"悍女|泼辣", ["นางเอกเก่ง"]),
]
BASE_TAGS = ["นิยายจีน", "นิยายแปล"]
NEG = re.compile(r"(不|无|非|没有|拒绝)$")


def match_tags(info: dict) -> dict[str, list[str]]:
    """Thai tag → Chinese words that triggered it."""
    text = "\n".join([info["title"], info["intro"], " ".join(info["categories"]),
                      info.get("keywords", "")])
    hits: dict[str, list[str]] = defaultdict(list)
    for pat, tags in GENRE_MAP:
        for m in re.finditer(pat, text):
            if NEG.search(text[max(0, m.start() - 2):m.start()]):
                continue
            for t in tags:
                if m.group(0) not in hits[t]:
                    hits[t].append(m.group(0))
    return dict(hits)

# ── 3. MyNovel tag popularity (real data from mynovel-data branch) ───────────

def load_store(path: str | None) -> dict | None:
    if path and pathlib.Path(path).exists():
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    for ref in ("origin/mynovel-data", "mynovel-data"):
        try:
            out = subprocess.run(["git", "show", f"{ref}:store.json"], capture_output=True,
                                 check=True, timeout=30).stdout
            return json.loads(out)
        except Exception:
            pass
    try:
        return json.loads(fetch(STATS_URL, timeout=30))
    except Exception as e:
        print(f"  ! โหลดสถิติ MyNovel ไม่ได้: {e}", file=sys.stderr)
        return None


def norm_tag(t: str) -> str:
    return t.strip().lstrip("#").strip()


def tag_stats(store: dict) -> tuple[dict, list[dict], int]:
    books = [b for b in store.get("books", {}).values()
             if b.get("category") in (None, "novel")]
    count, views = Counter(), defaultdict(list)
    for b in books:
        for t in {norm_tag(x) for x in (b.get("tags") or []) if x}:
            if t.isascii():           # skip English genre slugs, keep Thai hashtags
                continue
            count[t] += 1
            if isinstance(b.get("views"), (int, float)):
                views[t].append(b["views"])
    stats = {}
    for t, c in count.items():
        med = int(statistics.median(views[t])) if views[t] else 0
        stats[t] = {"books": c, "median_views": med,
                    "score": round(math.log(1 + c) * math.log10(1 + med), 2)}
    return stats, books, len(books)


def level(score: float, all_scores: list[float]) -> str:
    if not all_scores:
        return "—"
    s = sorted(all_scores, reverse=True)
    top10, top30 = s[max(0, len(s) // 10 - 1)], s[max(0, len(s) * 3 // 10 - 1)]
    return "🔥 สูง" if score >= top10 else "👍 กลาง" if score >= top30 else "· ต่ำ"


def rank_hashtags(hits: dict, stats: dict) -> list[dict]:
    scores = [v["score"] for v in stats.values()]
    rows = []
    for t in list(hits) + [b for b in BASE_TAGS if b not in hits]:
        st = stats.get(t)
        rows.append({
            "tag": t, "why": hits.get(t, ["(แท็กพื้นฐานนิยายแปลจีน)"]),
            "books": st["books"] if st else 0,
            "median_views": st["median_views"] if st else 0,
            "score": st["score"] if st else 0,
            "level": level(st["score"], scores) if st else "ยังไม่มีข้อมูลบน MyNovel",
        })
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


def title_examples(books: list[dict], tags: list[str], n: int = 10) -> list[dict]:
    want = set(tags) - set(BASE_TAGS)
    scored = []
    for b in books:
        bt = {norm_tag(x) for x in (b.get("tags") or [])}
        overlap = len(want & bt)
        if overlap and isinstance(b.get("views"), (int, float)):
            scored.append((min(overlap, 2), b["views"], b))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [{"title": b.get("title", ""), "views": v,
             "tags": [norm_tag(x) for x in (b.get("tags") or []) if not x.isascii()][:6]}
            for _, v, b in scored[:n]]

# ── 4. Thai title / teaser / synopsis ────────────────────────────────────────

def build_prompt(info: dict, ranked: list[dict], examples: list[dict]) -> str:
    tags = ", ".join(r["tag"] for r in ranked[:12])
    ex = "\n".join(f"- {e['title']} ({e['views']:,} วิว)" for e in examples) or "- (ไม่มีข้อมูล)"
    return f"""คุณเป็นบรรณาธิการนิยายแปลจีนสำหรับเว็บ MyNovel (ผู้อ่านไทย)
ช่วยเตรียมข้อมูลลงเรื่องจากข้อมูลต้นฉบับด้านล่าง

<ต้นฉบับ>
ชื่อเรื่อง (จีน): {info['title']}
ผู้แต่ง (จีน): {info['author']}
หมวด: {', '.join(info['categories']) or '-'}
สถานะ: {info['status'] or '-'}
เรื่องย่อต้นฉบับ:
{info['intro'] or '-'}
</ต้นฉบับ>

แฮชแท็กที่ตรงกับเรื่องและนิยมบน MyNovel: {tags}

ชื่อเรื่องที่ได้วิวสูงบน MyNovel ในแนวเดียวกัน (ใช้ดูสไตล์การตั้งชื่อ ห้ามลอก):
{ex}

ตอบเป็นภาษาไทย ตามหัวข้อนี้เท่านั้น:
## ความหมายชื่อจีน
แปลตรงตัว 1 บรรทัด + อ่านแบบพินอิน
## ชื่อเรื่องไทยที่แนะนำ
5 ชื่อ เรียงจากที่แนะนำที่สุด แต่ละชื่อมีเหตุผลสั้นๆ ครึ่งบรรทัด ให้มีทั้งแบบแปลใกล้ต้นฉบับและแบบขายจุดเด่น (ดึงคีย์เวิร์ดแนว เช่น ทะลุมิติ/ยุค70/ระบบ ถ้าเหมาะ) ความยาวไม่เกินประมาณ 40 ตัวอักษร
## คำโปรย
2–3 ประโยคสั้น ดึงดูด ใช้เป็นบรรทัดแรกของหน้าเรื่อง
## เรื่องย่อ
1–2 ย่อหน้า เล่าตามต้นฉบับ ไม่สปอยล์เกินเรื่องย่อเดิม ตัดข้อความโฆษณา/รางวัลของเว็บจีนออก
## แฮชแท็กที่แนะนำ
เลือก 6–10 แท็กจากรายการด้านบนที่ตรงเนื้อเรื่องจริง (ตัดแท็กที่ขัดกับเรื่องย่อออก) เขียนแบบ #แท็ก คั่นด้วยช่องว่าง
"""


def ask_claude(prompt: str) -> str | None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        print("  ! ยังไม่ได้ติดตั้ง anthropic (pip install anthropic)", file=sys.stderr)
        return None
    client = anthropic.Anthropic()
    try:
        resp = client.beta.messages.create(
            model="claude-opus-5-5",
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIStatusError as e:
        print(f"  ! Claude API error {e.status_code}: {e.message}", file=sys.stderr)
        return None
    except anthropic.APIConnectionError as e:
        print(f"  ! Claude API connection error: {e}", file=sys.stderr)
        return None
    if resp.stop_reason == "refusal":
        print("  ! Claude ปฏิเสธคำขอนี้", file=sys.stderr)
        return None
    return "".join(b.text for b in resp.content if b.type == "text").strip() or None

# ── 5. output ────────────────────────────────────────────────────────────────

def render_md(info, ranked, examples, n_books, ai_text, prompt, fetch_error) -> str:
    L = ["# 📋 ข้อมูลเตรียมลงเรื่อง (Listing kit)", "",
         f"ที่มา: {info['url']}  ", f"สร้างเมื่อ: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", ""]
    if fetch_error:
        L += [f"> ⚠️ เปิดหน้าเรื่องไม่ได้: {fetch_error}", ""]
    words = f"{int(info['words']):,} ตัวอักษร" if str(info.get("words", "")).isdigit() else "-"
    L += ["## ข้อมูลต้นฉบับ", "",
          f"| | |", "|---|---|",
          f"| ชื่อเรื่อง (จีน) | **{info['title'] or '-'}** |",
          f"| ผู้แต่ง (จีน) | {info['author'] or '-'} |",
          f"| หมวด | {', '.join(info['categories']) or '-'} |",
          f"| สถานะ | {info['status'] or '-'} |",
          f"| ความยาว | {words} |", "",
          "**เรื่องย่อต้นฉบับ**", "", "```", info["intro"] or "-", "```", ""]

    if ai_text:
        L += ["## ✍️ ชื่อเรื่อง / คำโปรย / เรื่องย่อ (ร่างโดย Claude — ตรวจก่อนใช้)", "", ai_text, ""]

    L += ["## #️⃣ แฮชแท็ก เรียงตามความนิยมบน MyNovel", "",
          f"คะแนนรวม 2 อย่าง: มีคนใช้แท็กนี้เยอะแค่ไหน × เรื่องที่ใช้แท็กนี้ได้วิวเท่าไร (มัธยฐาน) — จากนิยาย {n_books} เรื่องที่ระบบ mynovel_insights เก็บได้", "",
          "| แท็ก | ระดับ | เรื่องที่ใช้ | วิวมัธยฐาน | เจอคำจีน |", "|---|---|---:|---:|---|"]
    for r in ranked:
        L.append(f"| #{r['tag']} | {r['level']} | {r['books']} | {r['median_views']:,} | {' '.join(r['why'])} |")
    top = [r for r in ranked if r["books"]][:10]
    L += ["", "คัดลอกไปใช้ได้เลย (แท็กที่มีข้อมูล 10 อันดับแรก):", "",
          "```", " ".join("#" + r["tag"] for r in top) or "-", "```", "",
          "> แท็กที่ระบบเดาจากคำจีน ควรตัดแท็กที่ไม่ตรงเนื้อเรื่องออกก่อนใช้", ""]

    L += ["## 🏷️ แนวตั้งชื่อ: ชื่อเรื่องที่วิวสูงในแท็กเดียวกัน", ""]
    if examples:
        L += ["| ชื่อเรื่องบน MyNovel | วิว | แท็ก |", "|---|---:|---|"]
        L += [f"| {e['title']} | {e['views']:,} | {' '.join('#' + t for t in e['tags'])} |" for e in examples]
    else:
        L.append("(ยังไม่มีข้อมูลเรื่องที่แท็กตรงกัน)")
    L.append("")

    if not ai_text:
        L += ["## 🤖 ให้ Claude ช่วยตั้งชื่อ/เขียนคำโปรย", "",
              "ยังไม่ได้ตั้ง `ANTHROPIC_API_KEY` จึงยังไม่มีร่างชื่อเรื่องไทยกับคำโปรย "
              "คัดลอกข้อความด้านล่างไปวางในแชตกับ Claude ได้เลย", "",
              "````", prompt.strip(), "````", ""]
    return "\n".join(L)


def safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", s).strip("_")[:60] or "book"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", nargs="?", default="", help="ลิงก์หน้าเรื่อง (ไม่ใส่ได้ ถ้าใส่ --title เอง)")
    ap.add_argument("--title", help="ชื่อเรื่องจีน (เช่น อ่านจากภาพหน้าจอ) ใช้แทนค่าที่ดึงจากเว็บ")
    ap.add_argument("--author")
    ap.add_argument("--intro", help="เรื่องย่อจีน")
    ap.add_argument("--categories", help="หมวด/แท็กจีน คั่นด้วย , หรือ ช่องว่าง")
    ap.add_argument("--status")
    ap.add_argument("--stats", help="path to mynovel-data store.json")
    ap.add_argument("--out", default="output")
    ap.add_argument("--name", default="")
    ap.add_argument("--html-file", help="use a saved HTML file instead of fetching (for tests)")
    args = ap.parse_args()

    if re.fullmatch(r"\d{5,}", args.url.strip()):      # boluomao1 workflow accepts a bare id
        args.url = f"https://www.boluomao1.com/book/{args.url.strip()}.html"
    fetch_error = ""
    page = ""
    if args.html_file:
        page = pathlib.Path(args.html_file).read_text(encoding="utf-8")
    elif args.url and not args.title:
        try:
            page = fetch(args.url)
        except Exception as e:
            fetch_error = str(e)
    info = extract_book(page, args.url or "(ข้อมูลจากภาพ/ไฟล์ที่ส่งมา)")
    for k in ("title", "author", "intro", "status"):
        if getattr(args, k):
            info[k] = getattr(args, k).strip()
    if args.categories:
        info["categories"] = [x for x in re.split(r"[,，/、\s]+", args.categories) if x]
    print(f"ชื่อเรื่อง: {info['title'] or '-'} | ผู้แต่ง: {info['author'] or '-'}")

    store = load_store(args.stats)
    stats, books, n_books = tag_stats(store) if store else ({}, [], 0)
    hits = match_tags(info)
    ranked = rank_hashtags(hits, stats)
    examples = title_examples(books, [r["tag"] for r in ranked])
    prompt = build_prompt(info, ranked, examples)
    ai_text = ask_claude(prompt) if info["title"] else None

    out = pathlib.Path(args.out); out.mkdir(parents=True, exist_ok=True)
    base = "LISTING_" + safe_name(args.name or info["title"] or "book")
    md = render_md(info, ranked, examples, n_books, ai_text, prompt, fetch_error)
    (out / f"{base}.md").write_text(md, encoding="utf-8")
    (out / f"{base}.json").write_text(json.dumps({
        "source": info, "hashtags": ranked, "title_examples": examples,
        "ai_draft": ai_text, "mynovel_books_in_stats": n_books,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Listing kit: {out / (base + '.md')}")
    print("แฮชแท็ก: " + " ".join("#" + r["tag"] for r in ranked if r["books"])[:300])
    return 0 if info["title"] else 1


if __name__ == "__main__":
    sys.exit(main())
