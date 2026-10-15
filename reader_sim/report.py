"""สร้างรายงานผลการจำลอง (Markdown สำหรับแชต + HTML ไฟล์เดียวสำหรับแชร์)"""

import html

from .personas import GENRES, SPENDING_LABELS, TROPES

STATUS_LABELS = {
    "finished": "อ่านจนจบช่วงที่ประเมิน",
    "mid_drop": "เลิกกลางทาง",
    "early_drop": "เลิกใน 3 ตอนแรก",
}


def _stars(n):
    return "★" * n + "☆" * (5 - n)


def _ci(res, key):
    lo_hi = res["ci"].get(key)
    return f"{lo_hi[0]:g}–{lo_hi[1]:g}" if lo_hi else "-"


def to_markdown(res):
    b, o, t = res["book"], res["overall"], res["target"]
    lines = [
        f"# ผลจำลองนักอ่าน My Novel 100 คน: {b.get('title', '(ไม่มีชื่อ')}",
        "",
        f"**เกรด {res['grade']}** — {res['grade_text']}",
        "",
        "| ตัวชี้วัด | ทั้ง 100 คน | กลุ่มเป้าหมาย | ช่วง 90% |",
        "|---|---|---|---|",
        f"| ผ่าน (อ่านต่อ + ≥3 ดาว) | {o['pass_pct']}% | {t['pass_pct'] if t else '-'}% | {_ci(res, 'pass_pct')}% |",
        f"| ชอบ (≥4 ดาว) | {o['like_pct']}% | {t['like_pct'] if t else '-'}% | {_ci(res, 'like_pct')}% |",
        f"| ดาวเฉลี่ย | {o['avg_stars']} | {t['avg_stars'] if t else '-'} | {_ci(res, 'avg_stars')} |",
        f"| เพิ่มเข้าชั้น | {o['shelf_pct']}% | {t['shelf_pct'] if t else '-'}% | |",
    ]
    if o["paid_pct"] is not None:
        lines.append(f"| ซื้อเหรียญหลังตอนฟรี | {o['paid_pct']}% | {t['paid_pct'] if t else '-'}% | {_ci(res, 'paid_pct')}% |")
    lines += [
        f"| เลิกใน 3 ตอนแรก / กลางทาง / อ่านจบ | {o['early_drop_pct']}% / {o['mid_drop_pct']}% / {o['finish_pct']}% | | |",
        "",
        "**การกระจายดาว:** " + "  ".join(f"{i}★ {o['star_dist'][i]} คน" for i in range(5, 0, -1)),
        "",
        "## แยกตามกลุ่มนักอ่าน",
        "",
        "| กลุ่ม | คน | ผ่าน | ชอบ | ดาวเฉลี่ย |",
        "|---|---|---|---|---|",
    ]
    for s in sorted(res["segments"], key=lambda s: -s["avg_stars"]):
        lines.append(f"| {s['label']} | {s['n']} | {s['pass_pct']}% | {s['like_pct']}% | {s['avg_stars']} |")
    lines += ["", "## เหตุผลที่เลิกอ่าน"]
    lines += [f"- {k} ({v} คน)" for k, v in res["drop_reasons"]] or ["- ไม่มี"]
    lines += ["", "## จุดที่คนชอบ"]
    lines += [f"- {k} ({v} คน)" for k, v in res["praises"]] or ["- ไม่มี"]
    lines += ["", "## ข้อแนะนำ"]
    lines += [f"- {r}" for r in res["recommendations"]]
    return "\n".join(lines) + "\n"


CSS = """
:root{--bg:#faf7f2;--card:#fff;--ink:#2a2420;--muted:#7a6f66;--line:#e8e1d8;--accent:#c2410c;
--good:#15803d;--mid:#ca8a04;--bad:#b91c1c;--bar:#fdba74}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#1a1714;--card:#24201c;--ink:#f1ebe4;
--muted:#a89c90;--line:#3a332d;--accent:#fb923c;--good:#4ade80;--mid:#facc15;--bad:#f87171;--bar:#9a3412}}
:root[data-theme="dark"]{--bg:#1a1714;--card:#24201c;--ink:#f1ebe4;--muted:#a89c90;--line:#3a332d;--accent:#fb923c;
--good:#4ade80;--mid:#facc15;--bad:#f87171;--bar:#9a3412}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font-family:"Sarabun","Noto Sans Thai",system-ui,sans-serif;line-height:1.6}
main{max-width:1040px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.6rem;margin:0 0 4px}h2{font-size:1.15rem;margin:32px 0 12px}
.sub{color:var(--muted);margin:0 0 20px}
.grade{display:flex;gap:16px;align-items:center;background:var(--card);border:1px solid var(--line);
border-radius:14px;padding:16px 20px;margin-bottom:16px}
.grade b{font-size:2.6rem;color:var(--accent);line-height:1}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.kpi .v{font-size:1.7rem;font-weight:700}.kpi .l{color:var(--muted);font-size:.85rem}
.kpi .c{color:var(--muted);font-size:.78rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;overflow-x:auto}
.bars .row{display:grid;grid-template-columns:150px 1fr 56px;gap:10px;align-items:center;margin:6px 0;font-size:.92rem}
.bars .track{background:var(--line);border-radius:6px;height:14px;overflow:hidden}
.bars .fill{background:var(--bar);height:100%}
table{border-collapse:collapse;width:100%;font-size:.88rem}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600}
.st{color:var(--accent);white-space:nowrap}.good{color:var(--good)}.bad{color:var(--bad)}.mid{color:var(--mid)}
.retention{display:flex;align-items:flex-end;gap:2px;height:120px}
.retention div{flex:1;background:var(--bar);border-radius:3px 3px 0 0;min-width:3px}
.axis{display:flex;justify-content:space-between;color:var(--muted);font-size:.78rem}
ul{margin:0;padding-left:20px}.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}
.tags span{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:1px 10px;margin:2px;font-size:.82rem}
blockquote{margin:6px 0;padding:6px 12px;border-left:3px solid var(--accent);background:var(--bg);border-radius:4px}
.note{color:var(--muted);font-size:.8rem;margin-top:32px}
h1,.sub,.grade{overflow-wrap:anywhere}.grade>div,.kpis>div,.two>div{min-width:0}
@media (max-width:560px){.bars .row{grid-template-columns:96px 1fr 48px}.grade b{font-size:2rem}}
"""


def _kpi(value, label, ci=""):
    c = f'<div class="c">ช่วง 90%: {html.escape(ci)}</div>' if ci else ""
    return f'<div class="kpi"><div class="v">{value}</div><div class="l">{label}</div>{c}</div>'


def _bars(rows):
    top = max([v for _, v, _ in rows] + [1])
    out = ['<div class="bars">']
    for label, value, text in rows:
        out.append(f'<div class="row"><span>{html.escape(label)}</span><div class="track">'
                   f'<div class="fill" style="width:{100 * value / top:.1f}%"></div></div><span>{text}</span></div>')
    out.append("</div>")
    return "".join(out)


def to_html(res, comments=None):
    comments = comments or {}
    b, o, t = res["book"], res["overall"], res["target"]
    e = html.escape
    title = b.get("title", "ไม่มีชื่อเรื่อง")
    parts = [
        "<!doctype html><html lang='th'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>ผลจำลองนักอ่าน: {e(title)}</title>",
        "<link rel='stylesheet' href='https://fonts.googleapis.com/css2?family=Sarabun:wght@400;600;700&display=swap'>",
        f"<style>{CSS}</style></head><body><main>",
        f"<h1>{e(title)}</h1>",
        f"<p class='sub'>จำลองนักอ่าน My Novel 100 คน · ประเมินจาก {b['chapters_read']} ตอนแรก"
        f"{' จากทั้งหมด ' + str(b['chapters_total']) + ' ตอน' if b['chapters_total'] > b['chapters_read'] else ''}"
        f"{' · ตอนฟรี ' + str(b['free_chapters']) + ' ตอน' if b['free_chapters'] else ''}</p>",
        f"<div class='grade'><b>{res['grade']}</b><div><div>{e(res['grade_text'])}</div>"
        f"<div class='tags'>{''.join('<span>' + e(GENRES[g]) + '</span>' for g in b['genres'])}"
        f"{''.join('<span>' + e(TROPES[x]) + '</span>' for x in b['tropes'])}</div></div></div>",
        "<div class='kpis'>",
        _kpi(f"{o['pass_pct']:g}%", "ผ่าน (อ่านต่อ + ≥3 ดาว)", _ci(res, "pass_pct") + "%"),
        _kpi(f"{o['like_pct']:g}%", "ชอบ (≥4 ดาว)", _ci(res, "like_pct") + "%"),
        _kpi(f"{o['avg_stars']:.2f}★", "ดาวเฉลี่ย", _ci(res, "avg_stars")),
        _kpi(f"{o['shelf_pct']:g}%", "เพิ่มเข้าชั้นหนังสือ"),
    ]
    if o["paid_pct"] is not None:
        parts.append(_kpi(f"{o['paid_pct']:g}%", "ซื้อเหรียญหลังตอนฟรี", _ci(res, "paid_pct") + "%"))
    if t:
        parts.append(_kpi(f"{t['like_pct']:g}%", f"ชอบ เฉพาะกลุ่มเป้าหมาย ({t['n']} คน)"))
    parts.append("</div>")

    parts.append("<h2>การกระจายดาว</h2><div class='card'>")
    parts.append(_bars([(_stars(i), o["star_dist"][i], f"{o['star_dist'][i]} คน") for i in range(5, 0, -1)]))
    parts.append("</div>")

    ret = res["retention"]
    parts.append("<h2>คนที่ยังอ่านอยู่ในแต่ละตอน</h2><div class='card'><div class='retention'>")
    parts += [f"<div title='ตอน {i + 1}: {v} คน' style='height:{v}%'></div>" for i, v in enumerate(ret)]
    parts.append(f"</div><div class='axis'><span>ตอน 1 ({ret[0]} คน)</span>"
                 f"<span>ตอน {len(ret)} ({ret[-1]} คน)</span></div></div>")

    parts.append("<h2>แยกตามกลุ่มนักอ่าน</h2><div class='card'><table><tr><th>กลุ่ม</th><th>คน</th>"
                 "<th>ผ่าน</th><th>ชอบ</th><th>ดาวเฉลี่ย</th><th>เลิกเร็ว</th></tr>")
    for s in sorted(res["segments"], key=lambda s: -s["avg_stars"]):
        cls = "good" if s["avg_stars"] >= 3.8 else "bad" if s["avg_stars"] < 2.8 else "mid"
        parts.append(f"<tr><td>{e(s['label'])}</td><td>{s['n']}</td><td>{s['pass_pct']:g}%</td>"
                     f"<td>{s['like_pct']:g}%</td><td class='{cls}'>{s['avg_stars']:.2f}</td>"
                     f"<td>{s['early_drop_pct']:g}%</td></tr>")
    parts.append("</table></div>")

    def tally_list(items):
        if not items:
            return "<p>ไม่มี</p>"
        return "<ul>" + "".join(f"<li>{e(k)} <span class='sub'>({v} คน)</span></li>" for k, v in items) + "</ul>"

    parts.append("<div class='two'><div><h2>เหตุผลที่เลิกอ่าน</h2><div class='card'>"
                 + tally_list(res["drop_reasons"]) + "</div></div>"
                 "<div><h2>จุดที่คนชอบ</h2><div class='card'>" + tally_list(res["praises"]) + "</div></div></div>")

    parts.append("<h2>ข้อแนะนำก่อนลงเว็บ</h2><div class='card'><ul>")
    parts += [f"<li>{e(r)}</li>" for r in res["recommendations"] + b.get("editor_recommendations", [])]
    parts.append("</ul></div>")

    if comments:
        parts.append("<h2>เสียงจากนักอ่าน</h2><div class='card'>")
        by_id = {r["id"]: r for r in res["readers"]}
        for rid, text in comments.items():
            r = by_id.get(rid)
            if r:
                parts.append(f"<div><b>{e(r['name'])}</b> <span class='sub'>({e(r['segment_label'])})</span> "
                             f"<span class='st'>{_stars(r['stars'])}</span><blockquote>{e(text)}</blockquote></div>")
        parts.append("</div>")

    parts.append("<h2>รายคน (100 คน)</h2><div class='card'><table><tr><th>นักอ่าน</th><th>กลุ่ม</th>"
                 "<th>อายุ</th><th>การจ่าย</th><th>ดาว</th><th>สถานะ</th><th>เหตุผล</th></tr>")
    for r in res["readers"]:
        status = STATUS_LABELS[r["status"]]
        if r["status"] != "finished":
            status += f" (ตอน {r['reached']})"
        why = r["drop_reason"] or ", ".join(r["praises"][:2]) or ", ".join(r["complaints"][:1]) or "-"
        paid = " · ซื้อเหรียญ" if r["paid"] else ""
        parts.append(f"<tr><td>{e(r['name'])}</td><td>{e(r['segment_label'])}</td><td>{r['age']}</td>"
                     f"<td>{SPENDING_LABELS[r['spending']]}</td><td class='st'>{_stars(r['stars'])}</td>"
                     f"<td>{status}{paid}</td><td>{e(why)}</td></tr>")
    parts.append("</table></div>")
    parts.append(f"<p class='note'>ตัวเลขเป็นการจำลองจากคะแนนรายมิติที่ผู้ประเมินให้ + โปรไฟล์นักอ่านสมมติ "
                 f"ไม่ใช่ผลสำรวจจริง · ช่วง 90% มาจากการสุ่มซ้ำ {res['iterations']} รอบ</p>")
    parts.append("</main></body></html>")
    return "".join(parts)
