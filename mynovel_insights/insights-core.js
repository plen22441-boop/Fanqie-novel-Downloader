/*
 * MyNovel Insights — core analysis (no DOM, ใช้ได้ทั้งในเบราว์เซอร์และ Node)
 *
 * โมเดลข้อมูลที่ normalize แล้ว:
 *   event = { ts: Date, kind: 'comment'|'chapter'|'like'|'view'|'other',
 *             bookId?: string, user?: string, precise: boolean }
 *   book  = { id, title, tags: string[], views?: number, rank?: number, list?: string }
 *
 * หมายเหตุสำคัญ: เว็บไม่เปิดเผย "เวลาที่คนอ่าน" ตรง ๆ
 * เราใช้ timestamp ของคอมเมนต์/ไลก์ เป็น "ตัวแทน" ของกิจกรรมผู้อ่าน
 * และ timestamp การลงตอน เป็น "ฝั่งนักเขียน (supply)"
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.InsightsCore = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const TZ_OFFSET_MIN = 7 * 60; // Asia/Bangkok, ไม่มี DST
  const DAYS_TH = ['อา', 'จ', 'อ', 'พ', 'พฤ', 'ศ', 'ส'];

  const TH_MONTHS = {
    'ม.ค.': 0, 'มกราคม': 0, 'ก.พ.': 1, 'กุมภาพันธ์': 1, 'มี.ค.': 2, 'มีนาคม': 2,
    'เม.ย.': 3, 'เมษายน': 3, 'พ.ค.': 4, 'พฤษภาคม': 4, 'มิ.ย.': 5, 'มิถุนายน': 5,
    'ก.ค.': 6, 'กรกฎาคม': 6, 'ส.ค.': 7, 'สิงหาคม': 7, 'ก.ย.': 8, 'กันยายน': 8,
    'ต.ค.': 9, 'ตุลาคม': 9, 'พ.ย.': 10, 'พฤศจิกายน': 10, 'ธ.ค.': 11, 'ธันวาคม': 11,
  };

  // สร้าง Date จากเวลาท้องถิ่นไทย
  function bkkDate(y, mo, d, h, mi) {
    return new Date(Date.UTC(y, mo, d, h || 0, mi || 0) - TZ_OFFSET_MIN * 60000);
  }

  // แปลง Date -> {dow, hour} ตามเวลาไทย
  function bkkParts(date) {
    const t = new Date(date.getTime() + TZ_OFFSET_MIN * 60000);
    return { dow: t.getUTCDay(), hour: t.getUTCHours() };
  }

  function normYear(y) {
    y = +y;
    if (y < 100) y += y >= 40 ? 2500 : 2000; // "69" -> 2569 (พ.ศ.), "26" -> 2026
    if (y > 2400) y -= 543;                  // พ.ศ. -> ค.ศ.
    return y;
  }

  /**
   * แปลงข้อความเวลาเป็น { date, precise }
   * precise=false แปลว่ารู้วันแต่ไม่รู้ชั่วโมงที่แม่นพอ (เช่น "3 วันที่แล้ว")
   * -> ห้ามใช้วิเคราะห์ราย "ชั่วโมง"
   */
  function parseTime(input, now) {
    if (input == null || input === '') return null;
    now = now || new Date();
    if (input instanceof Date) return isNaN(input) ? null : { date: input, precise: true };
    if (typeof input === 'number') {
      const ms = input < 1e12 ? input * 1000 : input; // epoch วินาที หรือ ms
      return { date: new Date(ms), precise: true };
    }
    const s = String(input).trim();

    // ISO 8601 — ถ้าไม่มี timezone ให้ถือเป็นเวลาไทย
    let m = s.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?(Z|[+-]\d{2}:?\d{2})?$/);
    if (m) {
      if (m[4] === undefined) return { date: bkkDate(+m[1], +m[2] - 1, +m[3]), precise: false };
      if (m[7]) return { date: new Date(s.replace(' ', 'T')), precise: true };
      return { date: bkkDate(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]), precise: true };
    }
    if (/^\d{10,13}$/.test(s)) return parseTime(+s, now);

    // เวลาสัมพัทธ์ภาษาไทย/อังกฤษ
    if (/^(เมื่อสักครู่|เมื่อครู่|just now|ตอนนี้)$/i.test(s)) return { date: now, precise: true };
    m = s.match(/^(\d+)\s*(วินาที|นาที|ชั่วโมง|ชม\.?|วัน|สัปดาห์|อาทิตย์|เดือน|ปี|seconds?|mins?|minutes?|hours?|hrs?|days?|weeks?)\s*(ที่แล้ว|ก่อน|ago)?$/i);
    if (m) {
      const n = +m[1], u = m[2].toLowerCase();
      const unitMs =
        /วินาที|sec/.test(u) ? 1e3 :
        /นาที|min/.test(u) ? 6e4 :
        /ชั่วโมง|ชม|hour|hr/.test(u) ? 3.6e6 :
        /วัน|day/.test(u) ? 8.64e7 :
        /สัปดาห์|อาทิตย์|week/.test(u) ? 6.048e8 :
        /เดือน/.test(u) ? 2.592e9 : 3.1536e10;
      // ระดับ "ชั่วโมงที่แล้ว" ยังพอใช้ (คลาดเคลื่อน < 1 ชม.) ถ้าไม่เกิน 23 ชม.
      const precise = unitMs < 3.6e6 || (unitMs === 3.6e6 && n <= 23);
      return { date: new Date(now.getTime() - n * unitMs), precise };
    }

    // "เมื่อวาน 20:15" / "วันนี้ 08:00"
    m = s.match(/^(วันนี้|เมื่อวาน|เมื่อวานนี้|today|yesterday)\s*(?:เวลา\s*)?(\d{1,2})[:.](\d{2})/i);
    if (m) {
      const back = /เมื่อวาน|yesterday/i.test(m[1]) ? 1 : 0;
      const t = new Date(now.getTime() + TZ_OFFSET_MIN * 60000 - back * 8.64e7);
      return { date: bkkDate(t.getUTCFullYear(), t.getUTCMonth(), t.getUTCDate(), +m[2], +m[3]), precise: true };
    }

    // "16 พ.ย. 2569 20:15" / "16 พฤศจิกายน 69 เวลา 20.15 น."
    m = s.match(/^(\d{1,2})\s*([ก-๙.]+)\s*(\d{2,4})(?:\s*(?:เวลา)?\s*(\d{1,2})[:.](\d{2}))?/);
    if (m && TH_MONTHS[m[2]] !== undefined) {
      const y = normYear(m[3]);
      if (m[4] === undefined) return { date: bkkDate(y, TH_MONTHS[m[2]], +m[1]), precise: false };
      return { date: bkkDate(y, TH_MONTHS[m[2]], +m[1], +m[4], +m[5]), precise: true };
    }

    // "16/11/2569 20:15"
    m = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2,4})(?:\s+(\d{1,2})[:.](\d{2}))?/);
    if (m) {
      const y = normYear(m[3]);
      if (m[4] === undefined) return { date: bkkDate(y, +m[2] - 1, +m[1]), precise: false };
      return { date: bkkDate(y, +m[2] - 1, +m[1], +m[4], +m[5]), precise: true };
    }

    const d = new Date(s);
    return isNaN(d) ? null : { date: d, precise: /\d{1,2}:\d{2}/.test(s) };
  }

  // ── Tags ────────────────────────────────────────────────────────────────
  function normTag(t) {
    return String(t || '')
      .replace(/^[#＃]+/, '')
      .replace(/\s+/g, '')
      .trim()
      .toLowerCase();
  }

  function splitTags(v) {
    if (Array.isArray(v)) return v.flatMap(splitTags);
    if (v && typeof v === 'object') return splitTags(v.name || v.title || v.tag || v.label || '');
    return String(v || '')
      .split(/[,|;/、\n]+|\s(?=[#＃])/)
      .map(normTag)
      .filter(Boolean);
  }

  // แนวเรื่องที่ MyNovel ส่งมาเป็นรหัสภาษาอังกฤษ (bookTypes) -> ชื่อไทย; แท็กอื่นแสดงเป็น #แท็ก
  const TYPE_TH = { fantasy: 'แฟนตาซี', romance: 'โรแมนติก', drama: 'ดราม่า', martial_arts: 'กำลังภายใน', historical: 'ย้อนยุค/อิงประวัติศาสตร์',
    system: 'ระบบ', regression: 'ย้อนเวลา', transmigration: 'ทะลุมิติ', reincarnation: 'เกิดใหม่', revenge: 'แก้แค้น', supernatural: 'เหนือธรรมชาติ',
    adventure: 'ผจญภัย', comedy: 'ตลก', family: 'ครอบครัว', strong_female_lead: 'นางเอกเก่ง', strong_male_lead: 'พระเอกเก่ง', action: 'แอ็กชัน',
    horror: 'สยองขวัญ', mystery: 'สืบสวน', thriller: 'ระทึกขวัญ', 'sci-fi': 'ไซไฟ', scifi: 'ไซไฟ', sci_fi: 'ไซไฟ', school: 'วัยเรียน',
    slice_of_life: 'ชีวิตประจำวัน', yaoi: 'วาย', boys_love: 'วาย', bl: 'วาย', yuri: 'ยูริ', girls_love: 'ยูริ', harem: 'ฮาเร็ม',
    cultivation: 'บำเพ็ญเพียร', isekai: 'ต่างโลก', game: 'เกม', sports: 'กีฬา', military: 'ทหาร', urban: 'เมือง', urban_life: 'ชีวิตเมือง',
    rural_life: 'ชีวิตชนบท', modern: 'ปัจจุบัน', ancient: 'จีนโบราณ', palace: 'ชีวิตในวัง', business: 'ธุรกิจ', business_management: 'บริหารกิจการ',
    medical: 'การแพทย์', apocalypse: 'วันสิ้นโลก', zombie: 'ซอมบี้', villain: 'ตัวร้าย', tragedy: 'โศกนาฏกรรม', psychological: 'จิตวิทยา',
    mature: 'ผู้ใหญ่', heartwarming: 'อบอุ่นหัวใจ', smart_protagonist: 'ตัวเอกฉลาด', farming: 'ทำฟาร์ม', cooking: 'ทำอาหาร', parenting: 'เลี้ยงลูก' };
  function tagLabel(t) {
    t = String(t);
    if (TYPE_TH[t]) return TYPE_TH[t] + ' (แนว)';
    return /^[a-z0-9_-]+$/.test(t) ? t.replace(/_/g, ' ') + ' (แนว)' : '#' + t;
  }

  // ── Normalize raw import ────────────────────────────────────────────────
  function toNum(v) {
    if (v == null || v === '') return undefined;
    if (typeof v === 'number') return v;
    const s = String(v).replace(/,/g, '').trim();
    const m = s.match(/^([\d.]+)\s*([kKmMพหลื่นแสนล้าน]*)/);
    if (!m) return undefined;
    let n = parseFloat(m[1]);
    const u = m[2];
    if (/k|พัน/i.test(u)) n *= 1e3;
    else if (/หมื่น/.test(u)) n *= 1e4;
    else if (/แสน/.test(u)) n *= 1e5;
    else if (/m|ล้าน/i.test(u)) n *= 1e6;
    return isNaN(n) ? undefined : n;
  }

  function normKind(k) {
    k = String(k || '').toLowerCase();
    if (/comment|คอมเมนต์|ความคิดเห็น|reply/.test(k)) return 'comment';
    if (/chapter|episode|ตอน|publish/.test(k)) return 'chapter';
    if (/like|heart|ถูกใจ|vote/.test(k)) return 'like';
    if (/view|read|อ่าน/.test(k)) return 'view';
    return 'other';
  }

  function normalize(raw, now) {
    const events = [], books = [];
    const seenE = new Set(), seenB = new Map();
    let dropped = 0;
    for (const e of raw.events || []) {
      // seenAt = เวลาที่ collector เห็นข้อความสัมพัทธ์ ("2 ชั่วโมงที่แล้ว")
      const ref = e.seenAt ? new Date(e.seenAt) : now;
      const p = parseTime(e.ts ?? e.time ?? e.createdAt ?? e.created_at ?? e.date, ref);
      if (!p) { dropped++; continue; }
      const ev = {
        ts: p.date,
        precise: e.precise === false ? false : p.precise,
        kind: normKind(e.kind || e.type),
        bookId: e.bookId != null ? String(e.bookId) : undefined,
        user: e.user != null ? String(e.user) : undefined,
        w: e.w != null ? toNum(e.w) : undefined, // น้ำหนัก (เช่น จำนวนวิวที่เพิ่มในชั่วโมงนั้น)
      };
      const key = e.id != null ? 'id:' + e.id : [ev.ts.getTime(), ev.kind, ev.bookId, ev.user].join('|');
      if (seenE.has(key)) continue;
      seenE.add(key);
      events.push(ev);
    }
    for (const b of raw.books || []) {
      const title = String(b.title || b.name || '').trim();
      const id = String(b.id ?? b.bookId ?? title);
      if (!id) continue;
      const nb = {
        id, title: title || id,
        // category (novel/cartoon) เป็นหมวดใหญ่ ไม่ใช่แท็ก -> เก็บแยกไว้ใน category
        tags: [...new Set(splitTags(b.tags ?? b.hashtags ?? b.tag ?? []).concat(splitTags(b.genre ?? [])))],
        category: b.category != null ? String(b.category) : undefined,
        views: toNum(b.views ?? b.view ?? b.reads),
        growth: b.growth != null ? toNum(b.growth) : undefined,      // วิวที่เพิ่มในช่วงล่าสุด
        growthHours: b.growthHours != null ? toNum(b.growthHours) : undefined,
        rank: toNum(b.rank),
        list: b.list || b.source || undefined,
      };
      const prev = seenB.get(id);
      if (prev) { // merge: เก็บอันดับที่ดีที่สุด / tags รวม
        prev.tags = [...new Set(prev.tags.concat(nb.tags))];
        if (nb.rank && (!prev.rank || nb.rank < prev.rank)) prev.rank = nb.rank;
        if (nb.views && (!prev.views || nb.views > prev.views)) prev.views = nb.views;
        continue;
      }
      seenB.set(id, nb);
      books.push(nb);
    }
    return { events, books, dropped };
  }

  // CSV แบบง่าย (รองรับ "quoted,field")
  function parseCSV(text) {
    const rows = [];
    let row = [], cur = '', q = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (q) {
        if (c === '"' && text[i + 1] === '"') { cur += '"'; i++; }
        else if (c === '"') q = false;
        else cur += c;
      } else if (c === '"') q = true;
      else if (c === ',') { row.push(cur); cur = ''; }
      else if (c === '\n' || c === '\r') {
        if (c === '\r' && text[i + 1] === '\n') i++;
        row.push(cur); cur = '';
        if (row.some(x => x !== '')) rows.push(row);
        row = [];
      } else cur += c;
    }
    row.push(cur);
    if (row.some(x => x !== '')) rows.push(row);
    if (!rows.length) return [];
    const head = rows[0].map(h => h.trim());
    return rows.slice(1).map(r => Object.fromEntries(head.map((h, i) => [h, (r[i] ?? '').trim()])));
  }

  // CSV หรือ JSON -> raw {events, books}
  function importText(text) {
    text = text.replace(/^﻿/, '').trim();
    if (!text) return { events: [], books: [] };
    if (text[0] === '{' || text[0] === '[') {
      const j = JSON.parse(text);
      if (Array.isArray(j)) return classifyRows(j);
      return { events: j.events || [], books: j.books || [] };
    }
    return classifyRows(parseCSV(text));
  }

  function classifyRows(rows) {
    const events = [], books = [];
    for (const r of rows) {
      const hasTime = r.ts || r.time || r.createdAt || r.created_at || r.date;
      const hasBook = r.title || r.name || r.tags || r.hashtags;
      if (hasTime) events.push(r);
      if (hasBook && (r.tags || r.hashtags || r.rank || r.views)) books.push(r);
    }
    return { events, books };
  }

  // ── Time analysis ───────────────────────────────────────────────────────
  /**
   * opts.kinds: ประเภท event ที่นับ
   * opts.equalizeBooks: ถ่วงน้ำหนักให้แต่ละเรื่องรวมกันได้ 1 เท่ากัน
   *   (กันเรื่องดังเรื่องเดียวที่มีคอมเมนต์ถล่มบิดภาพทั้งเว็บ)
   */
  function timeMatrix(events, opts) {
    opts = opts || {};
    const kinds = opts.kinds || ['comment', 'like', 'view'];
    const sel = events.filter(e => e.precise && kinds.includes(e.kind));
    const base = e => (e.w != null && e.w >= 0 ? e.w : 1);
    const perBook = {};
    if (opts.equalizeBooks) for (const e of sel) { const k = e.bookId || '?'; perBook[k] = (perBook[k] || 0) + base(e); }
    const wOf = e => (opts.equalizeBooks ? base(e) / (perBook[e.bookId || '?'] || 1) : base(e));
    // วิว (มีน้ำหนักเป็นหลักพัน) กับ คอมเมนต์/ไลก์ (นับ 1) อยู่คนละสเกล:
    // ถ้าเลือกทั้งคู่ ปรับวิวให้ผลรวมเท่ากับฝั่งคอมเมนต์ -> แต่ละฝั่งมีอิทธิพล 50%
    let viewScale = 1;
    const vSum = sel.filter(e => e.kind === 'view').reduce((a, e) => a + wOf(e), 0);
    const oSum = sel.filter(e => e.kind !== 'view').reduce((a, e) => a + wOf(e), 0);
    if (vSum > 0 && oSum > 0) viewScale = oSum / vSum;
    const m = Array.from({ length: 7 }, () => new Array(24).fill(0));
    const counts = Array.from({ length: 7 }, () => new Array(24).fill(0));
    const days = new Set();
    for (const e of sel) {
      const { dow, hour } = bkkParts(e.ts);
      m[dow][hour] += wOf(e) * (e.kind === 'view' ? viewScale : 1);
      counts[dow][hour]++;
      days.add(Math.floor((e.ts.getTime() + TZ_OFFSET_MIN * 60000) / 8.64e7));
    }
    const total = m.flat().reduce((a, b) => a + b, 0);
    const byHour = new Array(24).fill(0).map((_, h) => m.reduce((a, r) => a + r[h], 0));
    const byDow = m.map(r => r.reduce((a, b) => a + b, 0));
    return { matrix: m, counts, byHour, byDow, total, n: sel.length, distinctDays: days.size,
      books: new Set(sel.map(e => e.bookId).filter(b => b && b !== '*')).size };
  }

  /**
   * ยอดวิวสะสม (snapshot ทุก ~1 ชม.) -> วิวที่เพิ่มขึ้นในแต่ละชั่วโมง
   * rows: [{ ts, id, views }]  (เฉพาะยอดวิวที่เป็นตัวเลขเต็ม ไม่ใช่ "1.2k")
   * - แบ่งส่วนต่างตามสัดส่วนเวลาที่คาบเกี่ยวแต่ละชั่วโมง (รอบ cron มาช้า/ข้ามได้)
   * - ข้ามช่วงที่ห่างเกิน maxGapHours และส่วนต่างติดลบ (ยอดรีเซ็ต)
   * คืน events แบบรวมทุกเรื่องต่อชั่วโมง (bookId '*') + สถิติไว้ตรวจว่ายอดวิวอัปเดตเรียลไทม์จริงไหม
   */
  /**
   * ยอดวิวที่เพิ่มของแต่ละเรื่องในช่วงล่าสุด (ค่าเริ่มต้น 24 ชม.) จาก snapshot รายชั่วโมง
   * rows: [{ ts, id, views }] -> Map(id -> { gain, hours })
   * ถ้ามีข้อมูลไม่ถึง 24 ชม. ใช้เท่าที่มี (ต้องห่างกันอย่างน้อย minHours)
   */
  function viewGrowth(rows, opts) {
    opts = opts || {};
    const win = (opts.windowHours || 24) * 3.6e6, minSpan = (opts.minHours || 1) * 3.6e6;
    const byId = new Map();
    for (const r of rows) {
      const p = parseTime(r.ts), v = toNum(r.views);
      if (!p || v == null || r.id == null) continue;
      if (!byId.has(r.id)) byId.set(r.id, []);
      byId.get(r.id).push({ t: p.date.getTime(), v });
    }
    const out = new Map();
    for (const [id, list] of byId) {
      list.sort((a, b) => a.t - b.t);
      const last = list[list.length - 1];
      const first = list.find(x => x.t >= last.t - win);
      if (!first || last.t - first.t < minSpan) continue;
      const gain = last.v - first.v;
      if (gain < 0) continue;
      out.set(id, { gain, hours: Math.round((last.t - first.t) / 3.6e6 * 10) / 10 });
    }
    return out;
  }

  /**
   * ตัวจดยอดวิวแบบสะสม (ใช้ในสคริปต์บนเบราว์เซอร์ ที่เก็บได้ไม่มาก)
   * tracker = { pts: {id: [[t, views], ...]},  // จุดของแต่ละเรื่อง เก็บแค่ ~26 ชม.ล่าสุด (ไว้คิดวิวพุ่ง 24 ชม.)
   *             hours: {hourStartMs: viewsGained}, // วิวที่เพิ่มรวมทุกเรื่องต่อชั่วโมง (ไว้หาเวลาทอง) เก็บ 90 วัน
   *             stats: {intervals, positive} }
   * - จุดที่ห่างจากจุดก่อนไม่ถึง minSpacing (10 นาที) จะไม่บันทึก กันข้อมูลบวมเวลาเปิดหลายหน้า
   * - ช่วงที่ห่างเกิน maxGap (6 ชม.) ไม่นำมาแบ่งลงชั่วโมง (ไม่รู้ว่าคนอ่านช่วงไหนในช่วงยาวนั้น)
   */
  function newTracker() { return { pts: {}, hours: {}, stats: { intervals: 0, positive: 0 } }; }

  function addViewPoint(tr, id, t, views, opts) {
    opts = opts || {};
    const minSpacing = (opts.minSpacingMin ?? 10) * 6e4, maxGap = (opts.maxGapHours ?? 6) * 3.6e6;
    const v = toNum(views);
    if (id == null || v == null || !isFinite(t)) return false;
    const list = tr.pts[id] || (tr.pts[id] = []);
    const last = list[list.length - 1];
    if (last) {
      const dt = t - last[0];
      if (dt < minSpacing) return false;
      const d = v - last[1];
      if (dt <= maxGap && d >= 0) {
        tr.stats.intervals++;
        if (d > 0) {
          tr.stats.positive++;
          let x = last[0];
          while (x < t) {
            const bucket = Math.floor(x / 3.6e6) * 3.6e6;
            const end = Math.min(t, bucket + 3.6e6);
            tr.hours[bucket] = Math.round(((tr.hours[bucket] || 0) + d * (end - x) / dt) * 100) / 100;
            x = end;
          }
        }
      }
    }
    list.push([t, v]);
    // เก็บจุดย้อนหลังแค่ 26 ชม. (แต่เหลือจุดล่าสุดไว้เสมอ)
    const keepFrom = t - 26 * 3.6e6;
    while (list.length > 1 && list[0][0] < keepFrom) list.shift();
    return true;
  }

  function pruneTracker(tr, now) {
    const hoursFrom = now - 90 * 8.64e7, ptsFrom = now - 7 * 8.64e7;
    for (const k of Object.keys(tr.hours)) if (+k < hoursFrom) delete tr.hours[k];
    for (const id of Object.keys(tr.pts)) {
      const list = tr.pts[id];
      if (!list.length || list[list.length - 1][0] < ptsFrom) delete tr.pts[id]; // เรื่องที่ไม่เห็นเกิน 7 วัน
    }
  }

  // tracker -> { events: [วิวต่อชั่วโมง], growth: Map(id -> {gain, hours}) } ในรูปแบบเดียวกับไฟล์จาก GitHub Actions
  function trackerOutput(tr) {
    const events = Object.keys(tr.hours).map(Number).sort((a, b) => a - b)
      .map(b => ({ ts: new Date(b + 1.8e6).toISOString(), kind: 'view', bookId: '*', w: tr.hours[b] }));
    const growth = new Map();
    for (const [id, list] of Object.entries(tr.pts)) {
      if (list.length < 2) continue;
      const last = list[list.length - 1];
      const first = list.find(p => p[0] >= last[0] - 24 * 3.6e6);
      if (!first || last[0] - first[0] < 3.6e6) continue; // ต้องห่างกันอย่างน้อย 1 ชม.
      const gain = last[1] - first[1];
      if (gain >= 0) growth.set(id, { gain, hours: Math.round((last[0] - first[0]) / 3.6e6 * 10) / 10 });
    }
    return { events, growth };
  }

  function viewDeltas(rows, opts) {
    opts = opts || {};
    const maxGap = (opts.maxGapHours || 6) * 3.6e6;
    const byId = new Map();
    for (const r of rows) {
      const p = parseTime(r.ts);
      const v = toNum(r.views);
      if (!p || v == null || r.id == null) continue;
      if (!byId.has(r.id)) byId.set(r.id, []);
      byId.get(r.id).push({ t: p.date.getTime(), v });
    }
    const acc = new Map();
    const stats = { intervals: 0, positive: 0, skippedGap: 0, negative: 0, books: byId.size, posByHour: new Array(24).fill(0) };
    for (const list of byId.values()) {
      list.sort((a, b) => a.t - b.t);
      for (let i = 1; i < list.length; i++) {
        const a = list[i - 1], b = list[i];
        const dt = b.t - a.t;
        if (dt <= 0) continue;
        if (dt > maxGap) { stats.skippedGap++; continue; }
        const d = b.v - a.v;
        if (d < 0) { stats.negative++; continue; }
        stats.intervals++;
        if (d === 0) continue;
        stats.positive++;
        stats.posByHour[bkkParts(new Date(b.t)).hour]++;
        let t = a.t;
        while (t < b.t) {
          const bucket = Math.floor(t / 3.6e6) * 3.6e6;
          const end = Math.min(b.t, bucket + 3.6e6);
          acc.set(bucket, (acc.get(bucket) || 0) + d * (end - t) / dt);
          t = end;
        }
      }
    }
    const events = [...acc.entries()].sort((x, y) => x[0] - y[0])
      .map(([bucket, w]) => ({ ts: new Date(bucket + 1.8e6).toISOString(), kind: 'view', bookId: '*', w: Math.round(w * 100) / 100 }));
    const warnings = [];
    if (stats.intervals >= 30 && stats.positive / stats.intervals < 0.25)
      warnings.push(`ยอดวิวเพิ่มแค่ ${Math.round(stats.positive / stats.intervals * 100)}% ของรอบที่เก็บ — เว็บอาจอัปเดตยอดวิวเป็นรอบ ๆ ไม่ใช่เรียลไทม์ กราฟจากวิวอาจคลาดเคลื่อน`);
    // ต้องมีข้อมูลกระจายอย่างน้อย 8 ชั่วโมงก่อน ไม่งั้นเก็บมาแค่ไม่กี่ชั่วโมงก็ "กระจุก" เองเสมอ (เตือนผิด)
    if (stats.positive >= 30 && stats.posByHour.filter(x => x > 0).length >= 8) {
      const top = Math.max(...stats.posByHour);
      if (top / stats.positive > 0.4) warnings.push(`ยอดวิวเพิ่มกระจุกที่ ${stats.posByHour.indexOf(top)}:00 (${Math.round(top / stats.positive * 100)}%) — น่าจะเป็นรอบอัปเดตตัวเลขของเว็บ ไม่ใช่ช่วงที่คนอ่านจริง`);
    }
    return { events, stats, warnings };
  }

  /**
   * ค่าเฉลี่ยวิวต่อชั่วโมงของวัน (0–23) จากเหตุการณ์ kind 'view' (1 รายการ = 1 ชั่วโมงจริง)
   * ใช้ "ค่าเฉลี่ยเฉพาะชั่วโมงที่มีข้อมูล" แทนผลรวม: ถ้าเก็บข้อมูลแค่บางช่วง (เช่น เปิดเว็บแต่ตอนค่ำ)
   * ผลรวมจะทำให้ช่วงนั้นดูเยอะเกินจริง เพราะถูกนับหลายวันกว่าช่วงอื่น
   */
  function hourlyAverage(events) {
    const sum = new Array(24).fill(0), n = new Array(24).fill(0);
    for (const e of events) {
      if (e.kind !== 'view' || !e.precise) continue;
      const h = bkkParts(e.ts).hour;
      sum[h] += e.w != null ? e.w : 1;
      n[h]++;
    }
    return { avg: sum.map((x, h) => (n[h] ? x / n[h] : null)), n, hours: n.reduce((a, b) => a + b, 0) };
  }

  // หาช่วง window ชั่วโมงติดกัน (วนรอบเที่ยงคืนได้) ที่มีสัดส่วนสูงสุด
  function bestWindow(byHour, width) {
    const total = byHour.reduce((a, b) => a + b, 0) || 1;
    let best = { start: 0, share: -1 };
    for (let s = 0; s < 24; s++) {
      let sum = 0;
      for (let k = 0; k < width; k++) sum += byHour[(s + k) % 24];
      if (sum / total > best.share) best = { start: s, share: sum / total };
    }
    return { start: best.start, end: (best.start + width) % 24, width, share: best.share };
  }

  function hoursInRange(start, end) {
    const out = [];
    for (let h = start; h !== end; h = (h + 1) % 24) { out.push(h); if (out.length > 24) break; }
    return out;
  }

  /**
   * เทียบ "ช่วงที่คาด" กับ "ข้อมูลจริง"
   * lift = สัดส่วนจริงของชั่วโมงนั้น / (1/24)   (lift 1.5 = มากกว่าค่าเฉลี่ย 50%)
   */
  function expectationReport(byHour, expStart, expEnd) {
    const total = byHour.reduce((a, b) => a + b, 0);
    const expected = hoursInRange(expStart, expEnd);
    const width = Math.max(1, expected.length);
    const share = h => (total ? byHour[h] / total : 0);
    const expShare = expected.reduce((a, h) => a + share(h), 0);
    const actual = bestWindow(byHour, width);
    const lift = byHour.map((_, h) => share(h) * 24);
    const surprises = lift
      .map((l, h) => ({ hour: h, lift: l }))
      .filter(x => !expected.includes(x.hour) && x.lift >= 1.3)
      .sort((a, b) => b.lift - a.lift);
    const letdowns = expected
      .map(h => ({ hour: h, lift: lift[h] }))
      .filter(x => x.lift < 0.9)
      .sort((a, b) => a.lift - b.lift);
    return {
      expected: { start: expStart, end: expEnd, width, share: expShare, baseline: width / 24 },
      actual, lift, surprises, letdowns,
      // ช่วงที่คาด จับกิจกรรมได้กี่ % ของช่วงที่ดีที่สุดที่กว้างเท่ากัน
      capture: actual.share > 0 ? expShare / actual.share : 0,
    };
  }

  /**
   * ช่องว่างดีมานด์-ซัพพลาย รายชั่วโมง
   * gap > 0 = ผู้อ่าน active มาก แต่นักเขียนลงตอนน้อย -> ช่วงน่าลงตอน
   */
  function supplyGap(events) {
    const demand = timeMatrix(events, { kinds: ['comment', 'like', 'view'] }).byHour;
    const supply = timeMatrix(events, { kinds: ['chapter'] }).byHour;
    const td = demand.reduce((a, b) => a + b, 0), ts = supply.reduce((a, b) => a + b, 0);
    if (!td || !ts) return null;
    return demand.map((d, h) => ({
      hour: h, demand: d / td, supply: supply[h] / ts, gap: d / td - supply[h] / ts,
    }));
  }

  // ── Tag / genre analysis ────────────────────────────────────────────────
  /**
   * ranked  = หนังสือที่มี rank (อยู่ในหน้าอันดับ)
   * score   = Σ (N - rank + 1)/N  -> อันดับ 1 ได้ 1.0, ท้ายตารางได้ ~0
   * supply  = จำนวนเรื่องทั้งหมด (ทุก list) ที่ติดแท็กนี้
   * opportunity = (ส่วนแบ่งในอันดับ) / (ส่วนแบ่งในจำนวนเรื่องทั้งหมด)
   *   > 1 = แท็กนี้ติดอันดับเกินสัดส่วนจำนวนเรื่อง -> คนอ่านเยอะแต่คู่แข่งน้อย
   */
  function tagStats(books, opts) {
    opts = opts || {};
    const minBooks = opts.minBooks || 2;
    const ranked = books.filter(b => b.rank > 0);
    const N = ranked.reduce((a, b) => Math.max(a, b.rank), 0) || 1;
    const map = new Map();
    const get = t => {
      if (!map.has(t)) map.set(t, { tag: t, count: 0, rankedCount: 0, score: 0, views: [], bestRank: Infinity, totalViews: 0, growth: 0, growthBooks: 0 });
      return map.get(t);
    };
    for (const b of books) for (const t of b.tags) {
      const s = get(t);
      s.count++;
      if (b.views != null) { s.views.push(b.views); s.totalViews += b.views; }
      if (b.growth != null) { s.growth += b.growth; s.growthBooks++; }
      if (b.rank > 0) {
        s.rankedCount++;
        s.score += (N - b.rank + 1) / N;
        s.bestRank = Math.min(s.bestRank, b.rank);
      }
    }
    const totalBooks = books.length || 1;
    // ตัวหารต้องเป็น "ต่อเรื่อง" ทั้งคู่ (ไม่ใช่ต่อแท็ก) ไม่งั้นเรื่องที่มี 3 แท็กถูกนับ 3 ครั้ง
    // แล้ว opportunity จะต่ำกว่าจริง ~เท่าจำนวนแท็กเฉลี่ยต่อเรื่อง -> baseline ของ opportunity = 1
    const totalScore = ranked.reduce((a, b) => a + (N - b.rank + 1) / N, 0) || 1;
    const out = [...map.values()].map(s => {
      const v = s.views.slice().sort((a, b) => a - b);
      const median = v.length ? (v.length % 2 ? v[(v.length - 1) / 2] : (v[v.length / 2 - 1] + v[v.length / 2]) / 2) : null;
      const rankShare = s.score / totalScore;
      const supplyShare = s.count / totalBooks;
      return {
        tag: s.tag, count: s.count, rankedCount: s.rankedCount,
        score: s.score, rankShare, supplyShare,
        opportunity: supplyShare ? rankShare / supplyShare : 0,
        medianViews: median, totalViews: s.totalViews,
        growth: s.growthBooks ? s.growth : null,                       // วิวเพิ่มรวม (ช่วงล่าสุด) ของทุกเรื่องในแท็ก
        growthPerBook: s.growthBooks ? s.growth / s.growthBooks : null, // เฉลี่ยต่อเรื่อง = แท็กนี้ดึงคนอ่านได้แค่ไหน
        bestRank: isFinite(s.bestRank) ? s.bestRank : null,
        lowSample: s.count < minBooks,
      };
    });
    out.sort((a, b) => b.score - a.score || b.count - a.count);
    return out;
  }

  // แท็กที่มักมาคู่กัน (ใช้คิดคอนเซ็ปต์เรื่อง)
  function tagPairs(books, limit) {
    const m = new Map();
    for (const b of books) {
      const t = [...new Set(b.tags)].sort();
      for (let i = 0; i < t.length; i++) for (let j = i + 1; j < t.length; j++) {
        const k = t[i] + ' + ' + t[j];
        const w = b.rank > 0 ? 2 : 1; // คู่ที่อยู่ในหน้าอันดับให้น้ำหนักมากกว่า
        m.set(k, (m.get(k) || 0) + w);
      }
    }
    return [...m.entries()].map(([pair, w]) => ({ pair, weight: w }))
      .filter(x => x.weight >= 2)
      .sort((a, b) => b.weight - a.weight).slice(0, limit || 15);
  }

  // ── Data quality (VERIFY) ───────────────────────────────────────────────
  function quality(data) {
    const ev = data.events;
    const precise = ev.filter(e => e.precise);
    // วิวรายชั่วโมงเป็นยอดรวมทุกเรื่อง (bookId '*') นับแยก ไม่ปนกับคอมเมนต์/ไลก์
    const reader = precise.filter(e => e.kind !== 'chapter' && e.kind !== 'view');
    const viewHours = precise.filter(e => e.kind === 'view').length;
    const chapters = precise.filter(e => e.kind === 'chapter');
    const tm = timeMatrix(ev, { kinds: ['comment', 'like', 'view'] });
    const topBookShare = (() => {
      const c = {};
      for (const e of reader) c[e.bookId || '?'] = (c[e.bookId || '?'] || 0) + 1;
      const max = Math.max(0, ...Object.values(c));
      return reader.length ? max / reader.length : 0;
    })();
    const warnings = [];
    // เกณฑ์ "พอดูแนวโน้มออก" (ไม่ต้องรอหลายสัปดาห์): คอมเมนต์/ไลก์ ≥ 100 หรือ วิวรายชั่วโมง ≥ 48 ชม.
    const enough = reader.length >= 100 || viewHours >= 48;
    const good = (reader.length >= 400 || viewHours >= 24 * 7) && tm.distinctDays >= 7;
    const level = good ? 'ดี' : enough && tm.distinctDays >= 2 ? 'พอใช้' : 'ต่ำ';
    if (!enough) warnings.push(`ข้อมูลยังน้อย (คอมเมนต์/ไลก์ ${reader.length} รายการ, วิวรายชั่วโมง ${viewHours} ชม.) — ต้องมีคอมเมนต์ ≥ 100 หรือวิว ≥ 48 ชม. ถึงจะพอดูแนวโน้มได้`);
    if (tm.distinctDays && tm.distinctDays < 2) warnings.push('ข้อมูลมีแค่วันเดียว — เก็บอีก 1–2 วันจะเห็นรูปแบบชัดขึ้น');
    if (topBookShare > 0.3) warnings.push(`${Math.round(topBookShare * 100)}% ของกิจกรรมมาจากเรื่องเดียว — แนะนำเปิด "ถ่วงน้ำหนักให้แต่ละเรื่องเท่ากัน"`);
    if (ev.length - precise.length > 0) warnings.push(`${ev.length - precise.length} รายการรู้แค่วันที่ (เช่น "3 วันที่แล้ว") — ไม่นำมาคิดรายชั่วโมง`);
    if (!chapters.length) warnings.push('ไม่มีเวลาลงตอน (chapter) — วิเคราะห์ "ช่องว่างดีมานด์-ซัพพลาย" ไม่ได้');
    if (data.books.filter(b => b.rank > 0).length < 20) warnings.push('หนังสือที่มีอันดับน้อยกว่า 20 เรื่อง — ผลแท็กยอดนิยมยังไม่น่าเชื่อถือ');
    if (data.dropped) warnings.push(`อ่านเวลาไม่ออก ${data.dropped} รายการ (ถูกข้าม)`);
    return { level, totalEvents: ev.length, precise: precise.length, reader: reader.length, viewHours,
      chapters: chapters.length, books: data.books.length,
      ranked: data.books.filter(b => b.rank > 0).length,
      distinctDays: tm.distinctDays, topBookShare, warnings };
  }

  // ── Demo data (สมมติ ล้วน ๆ — ไว้ลองหน้าจอเท่านั้น) ───────────────────────
  function demoData(seed) {
    let s = seed || 42;
    const rnd = () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
    const pick = a => a[Math.floor(rnd() * a.length)];
    // รูปทรงสมมติ: พีคค่ำ + พีครองหลังเที่ยงคืน + ช่วงพักเที่ยง
    const hourW = [5, 4, 2.5, 1.2, .6, .4, .6, 1.2, 2, 2.2, 2.4, 2.8, 4, 3.4, 2.6, 2.6, 3, 3.4, 4, 5, 6.5, 7.5, 7.8, 6.8];
    const pubW = [1, .5, .2, .1, .1, .1, .3, 1, 2, 3, 3.5, 3, 3, 2.5, 2.5, 2.5, 3, 4, 6, 7, 6, 4, 2, 1.5];
    const wpick = w => { const t = w.reduce((a, b) => a + b, 0); let r = rnd() * t; for (let i = 0; i < w.length; i++) { r -= w[i]; if (r <= 0) return i; } return w.length - 1; };
    const tagPool = ['โรแมนติก', 'แฟนตาซี', 'ย้อนยุค', 'ทะลุมิติ', 'วาย', 'ยูริ', 'สืบสวน', 'สยองขวัญ', 'กำลังภายใน', 'ระบบ', 'เกิดใหม่', 'ดราม่า', 'คอมเมดี้', 'ชีวิตประจำวัน', 'ไซไฟ', 'ล้างแค้น', 'ข้ามภพ', 'ท่านอ๋อง', 'ประธาน', 'ชีวิตในวัง'];
    const pop = { 'ทะลุมิติ': 3, 'ย้อนยุค': 2.6, 'วาย': 2.4, 'เกิดใหม่': 2.2, 'ระบบ': 2, 'โรแมนติก': 1.6, 'ล้างแค้น': 1.8, 'ชีวิตในวัง': 1.7 };
    const books = [];
    for (let i = 1; i <= 160; i++) {
      const tags = [...new Set([pick(tagPool), pick(tagPool), pick(tagPool)].slice(0, 2 + Math.floor(rnd() * 2)))];
      const boost = tags.reduce((a, t) => a * (pop[t] || 1), 1);
      const views = Math.round(boost * (2000 + rnd() * 60000));
      books.push({ id: 'b' + i, title: 'เรื่องตัวอย่าง ' + i, tags, views, growth: Math.round(views * boost * (0.002 + rnd() * 0.01)), growthHours: 24 });
    }
    books.slice().sort((a, b) => b.views * (0.6 + rnd()) - a.views * (0.6 + rnd()))
      .slice(0, 50).forEach((b, i) => { b.rank = i + 1; b.list = 'ranking'; });
    const events = [];
    const now = Date.UTC(2026, 10, 16, 0, 0) - TZ_OFFSET_MIN * 60000;
    for (let i = 0; i < 4000; i++) {
      const day = Math.floor(rnd() * 28);
      const dow = new Date(now - day * 8.64e7 + TZ_OFFSET_MIN * 60000).getUTCDay();
      const w = hourW.map((v, h) => ((dow === 0 || dow === 6) && h >= 9 && h <= 16 ? v * 1.6 : v));
      const h = wpick(w);
      events.push({ ts: new Date(now - day * 8.64e7 + h * 3.6e6 + Math.floor(rnd() * 3.6e6)).toISOString(),
        kind: rnd() < 0.7 ? 'comment' : 'like', bookId: pick(books.slice(0, 80)).id, user: 'u' + Math.floor(rnd() * 900) });
    }
    for (let i = 0; i < 700; i++) {
      const day = Math.floor(rnd() * 28), h = wpick(pubW);
      events.push({ ts: new Date(now - day * 8.64e7 + h * 3.6e6 + Math.floor(rnd() * 3.6e6)).toISOString(), kind: 'chapter', bookId: pick(books).id });
    }
    return { events, books };
  }

  return { parseTime, normTag, splitTags, toNum, normalize, parseCSV, importText,
    timeMatrix, hourlyAverage, tagLabel, viewDeltas, viewGrowth, newTracker, addViewPoint, pruneTracker, trackerOutput, bestWindow, expectationReport, supplyGap, tagStats, tagPairs, quality,
    demoData, bkkParts, hoursInRange, DAYS_TH };
});
