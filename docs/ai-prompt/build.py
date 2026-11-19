"""สร้างไฟล์ชุดคำสั่งสำหรับ AI ตัวอื่น โดยเติมสถิติแท็กล่าสุดจาก branch mynovel-data
ใช้:  git fetch --depth 1 origin mynovel-data:refs/remotes/origin/mynovel-data
      python docs/ai-prompt/build.py
"""
import pathlib, sys
from datetime import date
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scraper"))
import listing_kit as k

here = pathlib.Path(__file__).parent
st, _, n = k.tag_stats(k.load_store(None))
sc = [v["score"] for v in st.values()]
rows = sorted(((v["score"], t, v) for t, v in st.items() if v["books"] >= 2), reverse=True)[:70]
tags = ["| แท็ก | ระดับ | จำนวนเรื่องที่ใช้ | วิวมัธยฐาน |", "|---|---|---:|---:|"]
tags += [f"| #{t} | {k.level(s, sc)} | {v['books']} | {v['median_views']:,} |" for s, t, v in rows]
mp = ["| คำจีนที่เจอ (ชื่อเรื่อง/เรื่องย่อ/หมวด) | แท็กไทยที่ควรใช้ |", "|---|---|"]
for pat, tg in k.GENRE_MAP:
    words = pat.replace("(?!言情)", "").replace(".{0,4}", "…").replace("|", " / ")
    mp.append(f"| {words} | {' '.join('#' + t for t in tg)} |")
out = (here / "template.md").read_text(encoding="utf-8")
out = out.replace("{DATE}", date.today().isoformat()).replace("{N}", str(n))
out = out.replace("{TAGS}", "\n".join(tags)).replace("{MAP}", "\n".join(mp))
dst = here / "ชุดคำสั่ง_QC_ลงเรื่อง_MyNovel.md"
dst.write_text(out, encoding="utf-8")
print(f"{dst} ({n} เรื่อง, {len(rows)} แท็ก)")
