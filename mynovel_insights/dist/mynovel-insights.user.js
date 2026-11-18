// ==UserScript==
// @name         MyNovel Insights
// @namespace    mynovel-insights
// @version      2.0.0
// @description  ดูเวลาทอง แท็ก/แนวที่ฮิต และเรื่องที่ยอดวิวพุ่งของ MyNovel — เก็บจากเบราว์เซอร์ของคุณเอง ไม่ต้องใช้เซิร์ฟเวอร์
// @match        *://mynovel.co/*
// @match        *://*.mynovel.co/*
// @run-at       document-start
// @grant        none
// @updateURL    https://raw.githubusercontent.com/plen22441-boop/Fanqie-novel-Downloader/main/mynovel_insights/dist/mynovel-insights.user.js
// @downloadURL  https://raw.githubusercontent.com/plen22441-boop/Fanqie-novel-Downloader/main/mynovel_insights/dist/mynovel-insights.user.js
// ==/UserScript==

// ───── insights-core.js (ไฟล์นี้สร้างอัตโนมัติด้วย build-userscript.js — แก้ที่ต้นฉบับ) ─────
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

// ───── mynovel-collector.user.js ─────

/*
 * ไฟล์นี้คือ "ต้นฉบับ" — ไฟล์ที่ติดตั้งจริงคือ dist/mynovel-insights.user.js
 * (รวม insights-core.js ไว้ข้างในแล้ว สร้างด้วย: node mynovel_insights/build-userscript.js)
 *
 * วิธีทำงาน
 *  1) ดักผล JSON ที่หน้าเว็บ MyNovel โหลดมาอยู่แล้ว (api-mynovel.co): ชื่อเรื่อง แท็ก แนว ยอดวิว เวลาลงตอน
 *  2) จดยอดวิวของแต่ละเรื่องพร้อมเวลา -> คำนวณ "วิวที่เพิ่มต่อชั่วโมง" (เวลาทอง) และ "วิวพุ่ง 24 ชม."
 *  3) ถ้าเปิดแท็บ MyNovel ทิ้งไว้ สคริปต์ดึงรายการเรื่องมาแรง/อัปเดตล่าสุดเองทุก ~1 ชม. (3 request/ชม.)
 *  4) กดปุ่ม 📊 มุมขวาล่างเพื่อดูผลได้ทันที
 * ข้อมูลเก็บใน localStorage ของเบราว์เซอร์คุณเท่านั้น ไม่ส่งไปที่ไหน
 */
(function () {
  'use strict';
  const W = window;
  const C = () => W.InsightsCore; // มาจาก insights-core.js (รวมไว้ใน dist หรือ CI ฉีดเข้ามาก่อน)
  const KEY = 'mni_data_v1';
  const AUTO_KEY = 'mni_last_auto';
  const AUTO_EVERY = 55 * 60 * 1000;
  const KEEP_EVENTS_MS = 60 * 8.64e7;
  const DASHBOARD_URL = 'https://plen22441-boop.github.io/Fanqie-novel-Downloader/';
  let apiBase = 'https://api-mynovel.co';

  // MyNovel (api-mynovel.co) ใช้ชื่อ bookName / bookTags / bookTypes / bookViews / chapterPublishedAt
  const TIME_KEYS = ['chapterPublishedAt', 'commentedAt', 'createdAt', 'created_at', 'createDate', 'create_date', 'publishedAt', 'published_at',
    'publishAt', 'publish_at', 'publishDate', 'releasedAt', 'postedAt', 'posted_at', 'createdTime', 'created_time'];
  const TAG_KEYS = ['bookTags', 'bookTypes', 'tags', 'hashtags', 'hashTags', 'tag', 'tagList', 'tag_list', 'categories', 'genres', 'genre'];
  const VIEW_KEYS = ['bookViews', 'views', 'view', 'viewCount', 'view_count', 'totalView', 'total_view', 'readCount', 'read_count', 'reads', 'viewTotal'];
  const ID_KEYS = ['novelId', 'novel_id', 'bookId', 'book_id', 'storyId', 'story_id'];

  let store = load();
  let debug = false;
  let jsonHits = 0; // ถ้า JSON จับได้แล้ว ไม่ต้องสแกนข้อความ DOM ซ้ำ (กันนับคอมเมนต์เดียวกันสองครั้ง)

  function emptyStore() { return { v: 2, events: {}, books: {}, vt: null }; }
  function load() {
    let s;
    try { s = JSON.parse(localStorage.getItem(KEY)); } catch (e) { s = null; }
    if (!s || typeof s !== 'object') return emptyStore();
    if (s.v !== 2) { // ข้อมูลจากเวอร์ชันแรก: ทิ้งเวลาที่เดาประเภทไม่ได้ และแบนเนอร์ที่เคยถูกนับเป็นหนังสือ
      for (const k of Object.keys(s.events || {})) if (s.events[k].kind === 'other') delete s.events[k];
      for (const k of Object.keys(s.books || {})) if (s.books[k].views == null && /banner/.test((s.books[k].tags || []).join())) delete s.books[k];
      s.v = 2;
    }
    s.events = s.events || {}; s.books = s.books || {};
    return s;
  }
  function tracker() {
    if (!store.vt && C()) store.vt = C().newTracker();
    return store.vt;
  }
  let saveTimer = null;
  function save() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      const now = Date.now();
      for (const [k, e] of Object.entries(store.events)) { // ตัดเวลาลงตอนที่เก่าเกิน 60 วัน
        const t = Date.parse(e.ts);
        if (isFinite(t) && now - t > KEEP_EVENTS_MS) delete store.events[k];
      }
      if (store.vt && C()) C().pruneTracker(store.vt, now);
      store.updatedAt = new Date(now).toISOString();
      try { localStorage.setItem(KEY, JSON.stringify(store)); }
      catch (e) { // พื้นที่เต็ม: ลดรายการเวลาลงตอนลงครึ่งหนึ่งแล้วลองใหม่
        const keys = Object.keys(store.events);
        for (const k of keys.slice(0, Math.floor(keys.length / 2))) delete store.events[k];
        try { localStorage.setItem(KEY, JSON.stringify(store)); } catch (e2) { console.warn('[MNI] save failed', e2); }
      }
      if (sheetOpen) renderSheet();
      updateBadge();
    }, 500);
  }

  const lc = s => String(s || '').toLowerCase();
  // CI ตั้ง window.__MNI_FORCE_RANK = true สำหรับหน้าที่ config บอกว่าเป็นหน้าอันดับ
  const isRankPage = () => W.__MNI_FORCE_RANK === true || /rank|top|popular|trend|hot|อันดับ|ยอดนิยม/i.test(decodeURIComponent(location.href));
  function pickFirst(o, keys) { for (const k of keys) if (o[k] != null && o[k] !== '') return o[k]; return undefined; }
  const exactViews = v => (typeof v === 'number' ? v : (/^\s*\d[\d,]*\s*$/.test(String(v ?? '')) ? +String(v).replace(/[,\s]/g, '') : undefined));

  function guessKind(path, o) {
    const p = lc(path.join('.'));
    if (/comment|reply|review/.test(p) || (o.content !== undefined && (o.user || o.member || o.author) && !o.title)) return 'comment';
    if (o.chapterId != null || o.chapterPublishedAt != null || /chapter|episode|\bep\b|eps/.test(p) || o.chapterNo != null || o.episodeNo != null || o.chapter_number != null || o.ep != null) return 'chapter';
    if (/like|vote|heart|gift|donate/.test(p)) return 'like';
    return 'other';
  }
  function pageBookId() {
    const m = location.pathname.match(/\/(?:novel|book|story|novels|books)\/([^/?#]+)/i);
    return m ? m[1] : undefined;
  }

  function walk(o, path, ctx, depth) {
    if (!o || typeof o !== 'object' || depth > 12) return;
    if (Array.isArray(o)) {
      const listName = path[path.length - 1] || '';
      o.forEach((x, i) => walk(x, path.concat(listName), Object.assign({}, ctx, { index: i, listName }), depth + 1));
      return;
    }
    const title = o.bookName || o.title || o.name || o.novelName || o.novel_name;
    // รวมแท็กจากทุกช่องที่มี (MyNovel มีทั้ง bookTags = #แท็ก และ bookTypes = แนว)
    const tagKeys = TAG_KEYS.filter(k => o[k] != null);
    const tagVal = tagKeys.length ? tagKeys.flatMap(k => [].concat(o[k])) : (o.bookName ? [] : undefined);
    const ownId = o.chapterId ?? o.commentId ?? o.id ?? o._id;
    // ต้องมีรหัสหนังสือด้วย กันแบนเนอร์/คอลเลกชันที่มี title + category ถูกนับเป็นหนังสือ
    const isBook = typeof title === 'string' && tagVal != null && (o.bookName != null || pickFirst(o, ID_KEYS) != null) && o.chapterId == null;

    if (isBook) {
      const id = String(pickFirst(o, ID_KEYS) ?? ownId ?? title);
      const tags = tagVal.map(t => (t && typeof t === 'object') ? (t.name || t.title || t.tag || t.label) : t).filter(Boolean);
      const prev = store.books[id] || {};
      const now = Date.now();
      const rankish = /rank|top|popular|trend|hot/i.test(lc(path.join('.'))) || isRankPage();
      const rank = o.rank ?? o.ranking ?? o.position ?? (rankish && ctx.index != null ? ctx.index + 1 : undefined);
      // อันดับเก่ากว่า 48 ชม. ถือว่าหมดอายุ (เดิมเก็บอันดับดีที่สุดตลอดกาล ทำให้อันดับค้าง)
      const prevRankFresh = prev.rankAt && now - Date.parse(prev.rankAt) < 48 * 3.6e6;
      const views = pickFirst(o, VIEW_KEYS);
      store.books[id] = {
        id, title,
        tags: [...new Set((prev.tags || []).concat(tags.map(String)))],
        views: views ?? prev.views,
        rank: rank != null ? (prevRankFresh && prev.rank ? Math.min(prev.rank, +rank) : +rank) : (prevRankFresh ? prev.rank : undefined),
        rankAt: rank != null ? new Date(now).toISOString() : (prevRankFresh ? prev.rankAt : undefined),
        list: rank != null ? location.pathname : prev.list,
        category: o.category ?? prev.category,
        seenAt: new Date(now).toISOString(),
      };
      const ev = exactViews(views);
      // จดห่างกันอย่างน้อย 20 นาที: พอสำหรับวิวต่อชั่วโมง และไม่กินพื้นที่ localStorage (~5MB)
      if (ev != null && tracker()) C().addViewPoint(store.vt, id, now, ev, { minSpacingMin: 20 });
      // เวลาอัปเดตตอนล่าสุดของเรื่อง = ข้อมูลฝั่ง "คนลงตอน"
      const lu = o.lastChapterUpdatedAt;
      if (lu && !/^1970/.test(lu) && !store.events['chapter:' + id + ':' + lu]) store.events['chapter:' + id + ':' + lu] = { ts: lu, kind: 'chapter', bookId: id, src: 'json' };
      ctx = Object.assign({}, ctx, { bookId: id });
    }

    const ts = pickFirst(o, TIME_KEYS);
    if (ts != null && !isBook) {
      const kind = guessKind(path, o);
      const user = o.userId ?? o.user_id ?? (o.user && (o.user.id ?? o.user._id)) ?? (o.member && o.member.id);
      const bid = pickFirst(o, ID_KEYS) ?? ctx.bookId ?? pageBookId();
      const key = (ownId != null ? kind + ':' + ownId : [kind, ts, bid, user].join('|'));
      // ไม่เก็บเวลาที่เดาประเภทไม่ได้ (เช่น วันที่สร้างแบนเนอร์) — เป็นแค่สัญญาณรบกวน
      if (kind !== 'other') {
        jsonHits++;
        if (!store.events[key]) store.events[key] = { ts, kind, bookId: bid, user, src: 'json' };
      }
    }
    for (const k in o) if (o[k] && typeof o[k] === 'object') walk(o[k], path.concat(k), ctx, depth + 1);
  }

  function ingestJSON(text, url) {
    if (!text || (text[0] !== '{' && text[0] !== '[')) return;
    let j; try { j = JSON.parse(text); } catch (e) { return; }
    try { const u = new URL(url, location.href); if (/\/api\/books/.test(u.pathname)) apiBase = u.origin; } catch (e) {}
    walk(j, [lc(url).split('?')[0].split('/').slice(-2).join('.')], {}, 0);
    if (jsonHits) purgeDomDupes();
    if (debug) console.log('[MNI]', url, j);
    save();
  }

  // JSON แม่นกว่า DOM: ถ้าหน้านี้ได้ JSON แล้ว ลบรายการจาก DOM ของหน้านี้ทิ้ง (กันนับคอมเมนต์เดียวกันซ้ำ)
  function purgeDomDupes() {
    const tag = '|' + location.pathname + '|';
    for (const k in store.events) {
      const e = store.events[k];
      if ((e.src === 'dom' || e.src === 'domtext') && k.includes(tag)) delete store.events[k];
    }
  }

  // ── ดัก fetch / XHR (อ่านอย่างเดียว ไม่แก้ response) ──
  const ofetch = W.fetch;
  if (ofetch) W.fetch = function () {
    return ofetch.apply(this, arguments).then(res => {
      try {
        const ct = res.headers.get('content-type') || '';
        if (/json/.test(ct)) res.clone().text().then(t => ingestJSON(t, res.url)).catch(() => {});
      } catch (e) {}
      return res;
    });
  };
  const oopen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (m, url) {
    this.addEventListener('load', () => {
      try {
        if (this.responseType === '' || this.responseType === 'text') ingestJSON(this.responseText, String(url));
        else if (this.responseType === 'json') ingestJSON(JSON.stringify(this.response), String(url));
      } catch (e) {}
    });
    return oopen.apply(this, arguments);
  };

  // ── ดึงข้อมูลเองเมื่อเปิดแท็บทิ้งไว้ (ทุก ~1 ชม. ทุกแท็บรวมกันครั้งเดียว) ──
  const REFRESH_PATHS = ['/api/books/trending', '/api/books/stories/latest', '/api/books?orderByField=lastChapterUpdatedAt&orderByDirection=desc'];
  let lastRefreshMsg = '';
  async function refreshNow(manual) {
    if (!ofetch) return;
    try { localStorage.setItem(AUTO_KEY, String(Date.now())); } catch (e) {}
    let ok = 0;
    for (const p of REFRESH_PATHS) {
      try {
        const r = await W.fetch(apiBase + p, { credentials: 'omit' }); // ผ่านตัวดักข้างบน -> ถูกบันทึกอัตโนมัติ
        if (r.ok) ok++;
      } catch (e) { /* เครือข่ายหลุด/ถูกบล็อก ข้ามไป */ }
    }
    lastRefreshMsg = ok ? `ดึงข้อมูลล่าสุดแล้ว (${ok}/${REFRESH_PATHS.length})` : 'ดึงข้อมูลไม่สำเร็จ — ลองเปิดหน้าแรกของ MyNovel แทน';
    if (manual && sheetOpen) renderSheet();
  }
  function autoTick() {
    let last = 0;
    try { last = +localStorage.getItem(AUTO_KEY) || 0; } catch (e) {}
    if (Date.now() - last >= AUTO_EVERY) refreshNow(false);
  }
  setInterval(autoTick, 5 * 60 * 1000);

  // ── DOM scan (สำรอง สำหรับหน้าที่ไม่มี JSON) ──
  const TH_TIME = /(\d{1,2}\s*(?:ม\.ค\.|ก\.พ\.|มี\.ค\.|เม\.ย\.|พ\.ค\.|มิ\.ย\.|ก\.ค\.|ส\.ค\.|ก\.ย\.|ต\.ค\.|พ\.ย\.|ธ\.ค\.)\s*\d{2,4}(?:\s*(?:เวลา)?\s*\d{1,2}[:.]\d{2})?|\d+\s*(?:นาที|ชั่วโมง|ชม\.)\s*(?:ที่แล้ว|ก่อน)|เมื่อวาน\s*\d{1,2}[:.]\d{2})/;
  function scanDOM() {
    const nd = document.getElementById('__NEXT_DATA__');
    if (nd && !nd.dataset.mni) { nd.dataset.mni = '1'; ingestJSON(nd.textContent, location.pathname); }
    if (jsonHits) return;
    let added = 0;
    const kindOf = el => {
      const c = lc((el.closest('[class*="omment"],[class*="hapter"],[class*="pisode"],[id*="omment"]') || {}).className);
      return /omment/.test(c) ? 'comment' : /hapter|pisode/.test(c) ? 'chapter' : 'other';
    };
    document.querySelectorAll('time[datetime]').forEach(el => {
      const ts = el.getAttribute('datetime'), kind = kindOf(el);
      if (kind === 'other') return;
      const key = 'dom|' + ts + '|' + location.pathname + '|' + (el.closest('[data-id]') || {}).dataset?.id;
      if (!store.events[key]) { store.events[key] = { ts, kind, bookId: pageBookId(), src: 'dom' }; added++; }
    });
    document.querySelectorAll('[class*="omment"] *, [class*="hapter"] *, [class*="pisode"] *').forEach(el => {
      if (el.children.length || el.dataset.mni) return;
      const m = (el.textContent || '').trim().match(TH_TIME);
      if (!m || el.textContent.length > 60) return;
      el.dataset.mni = '1';
      const box = el.closest('[class*="omment"],[class*="hapter"],[class*="pisode"]');
      const fp = (box && box.textContent || '').replace(m[0], '').replace(/\s+/g, ' ').slice(0, 80);
      const key = 'domtxt|' + location.pathname + '|' + fp;
      const kind = kindOf(el);
      if (kind !== 'other' && !store.events[key]) { store.events[key] = { ts: m[1], seenAt: new Date().toISOString(), kind, bookId: pageBookId(), src: 'domtext' }; added++; }
    });
    if (added) save();
  }

  // ── รวมข้อมูลเป็นรูปแบบเดียวกับไฟล์จาก GitHub Actions (ใช้ทั้งแผงสรุปและ Export) ──
  function snapshot() {
    const out = C() && store.vt ? C().trackerOutput(store.vt) : { events: [], growth: new Map() };
    const now = Date.now();
    const books = Object.values(store.books).map(b => Object.assign({}, b, {
      rank: b.rankAt && now - Date.parse(b.rankAt) < 48 * 3.6e6 ? b.rank : undefined,
      growth: out.growth.has(b.id) ? out.growth.get(b.id).gain : undefined,
      growthHours: out.growth.has(b.id) ? out.growth.get(b.id).hours : undefined,
    }));
    return {
      exportedAt: new Date(now).toISOString(), source: location.host,
      meta: { viewStats: store.vt ? store.vt.stats : null },
      events: Object.entries(store.events).map(([id, e]) => Object.assign({ id }, e)).concat(out.events),
      books,
    };
  }
  function exportData() {
    const blob = new Blob([JSON.stringify(snapshot())], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'mynovel-insights-' + new Date().toISOString().slice(0, 10) + '.json';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }

  // ── หน้าจอ: ปุ่ม 📊 + แผ่นสรุปผล (อยู่ใน Shadow DOM ไม่ชนกับสไตล์ของเว็บ) ──
  let host, root, sheetOpen = false, cat = 'novel', confirmClear = false;
  try { cat = localStorage.getItem('mni_cat') || 'novel'; } catch (e) {}
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = n => n == null ? '—' : n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : String(Math.round(n));
  const hh = h => String(h).padStart(2, '0') + ':00';

  const CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; font-family: system-ui, -apple-system, "Noto Sans Thai", "Sarabun", sans-serif; }
    .fab { position: fixed; right: calc(14px + env(safe-area-inset-right, 0px)); bottom: calc(14px + env(safe-area-inset-bottom, 0px));
      width: 52px; height: 52px; border-radius: 26px; border: 0; background: #2a78d6; color: #fff; font-size: 22px;
      box-shadow: 0 4px 14px rgba(0,0,0,.35); cursor: pointer; z-index: 2147483646; }
    .fab .dot { position: absolute; top: 4px; right: 4px; min-width: 18px; height: 18px; border-radius: 9px; background: #1baf7a;
      font: 600 11px/18px system-ui; padding: 0 4px; }
    .sheet { position: fixed; left: 0; right: 0; bottom: 0; max-height: 82vh; overflow-y: auto; -webkit-overflow-scrolling: touch;
      background: #1a1a19; color: #f0efec; border-radius: 16px 16px 0 0; box-shadow: 0 -6px 24px rgba(0,0,0,.4);
      padding: 14px max(16px, env(safe-area-inset-left, 0px)) calc(18px + env(safe-area-inset-bottom, 0px)) max(16px, env(safe-area-inset-right, 0px));
      z-index: 2147483647; font-size: 14px; line-height: 1.5; }
    @media (min-width: 720px) { .sheet { left: auto; right: 16px; bottom: 16px; width: 440px; border-radius: 16px; max-height: 86vh; } }
    .top { display: flex; align-items: center; gap: 8px; position: sticky; top: -14px; background: #1a1a19; padding: 4px 0 8px; }
    .top b { font-size: 16px; flex: 1; }
    button { font: inherit; min-height: 44px; padding: 8px 12px; border-radius: 10px; border: 1px solid #44443f; background: #2c2c2a; color: #f0efec; cursor: pointer; }
    button.pri { background: #2a78d6; border-color: #2a78d6; color: #fff; }
    button.x { min-width: 44px; padding: 0; font-size: 18px; }
    .muted { color: #a8a79f; font-size: 12.5px; }
    h3 { font-size: 14.5px; margin: 16px 0 6px; }
    .lvl { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 12px; font-weight: 600; }
    .lvl.low { background: #4a3a10; color: #f2d58a; } .lvl.mid { background: #173a5c; color: #9ec5f4; } .lvl.good { background: #123d2c; color: #8fdcb8; }
    .gold { font-size: 22px; font-weight: 700; margin: 2px 0; }
    .bars { display: grid; grid-template-columns: repeat(24, 1fr); gap: 2px; align-items: end; height: 70px; margin-top: 6px; }
    .bars i { display: block; background: #3987e5; border-radius: 3px 3px 0 0; min-height: 2px; }
    .bars i.no { background: repeating-linear-gradient(45deg, #33332f 0 3px, transparent 3px 6px); height: 100% !important; opacity: .5; }
    .bars i.best { background: #eda100; }
    .ax { display: grid; grid-template-columns: repeat(24, 1fr); gap: 2px; font-size: 10px; color: #8f8e86; text-align: center; }
    ol { list-style: none; margin: 0; padding: 0; }
    li { display: grid; grid-template-columns: 22px minmax(0,1fr) auto; gap: 8px; align-items: center; padding: 7px 0; border-bottom: 1px solid #2f2f2c; }
    li .n { color: #8f8e86; text-align: right; font-variant-numeric: tabular-nums; }
    li .t { min-width: 0; } li .t b { display: block; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    li small { display: block; color: #a8a79f; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    li .v { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; font-weight: 600; }
    .chips { display: flex; gap: 6px; flex-wrap: wrap; }
    .chips button { min-height: 36px; padding: 4px 12px; border-radius: 999px; }
    .chips button.on { background: #f0efec; color: #1a1a19; }
    .tags { display: flex; flex-wrap: wrap; gap: 6px; }
    .tag { background: #2c2c2a; border: 1px solid #3a3a36; border-radius: 999px; padding: 4px 10px; font-size: 13px; }
    .tag em { font-style: normal; color: #8fdcb8; margin-left: 4px; }
    .row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }
    .row button { flex: 1 1 140px; }
    a { color: #6da7ec; }
    .warn { background: #2e2610; color: #f2d58a; border-radius: 10px; padding: 8px 10px; font-size: 12.5px; margin-top: 10px; }
  `;

  function mount() {
    if (host || !document.body) return;
    host = document.createElement('div');
    host.id = 'mni-insights';
    root = host.attachShadow({ mode: 'open' });
    root.innerHTML = `<style>${CSS}</style><button class="fab" aria-label="เปิด MyNovel Insights">📊<span class="dot" hidden></span></button><div class="sheet" hidden></div>`;
    root.querySelector('.fab').addEventListener('click', () => toggle(true));
    root.querySelector('.sheet').addEventListener('click', onSheetClick);
    document.body.appendChild(host);
    updateBadge();
  }
  function toggle(open) {
    sheetOpen = open;
    root.querySelector('.sheet').hidden = !open;
    root.querySelector('.fab').hidden = open;
    confirmClear = false;
    if (open) renderSheet();
  }
  function updateBadge() {
    if (!root) return;
    const dot = root.querySelector('.dot');
    const n = Object.keys(store.books).length;
    dot.hidden = !n;
    dot.textContent = n > 999 ? '999+' : String(n);
  }
  function onSheetClick(e) {
    const b = e.target.closest('button');
    if (!b) return;
    const a = b.dataset.a;
    if (a === 'close') toggle(false);
    else if (a === 'cat') { cat = b.dataset.v; try { localStorage.setItem('mni_cat', cat); } catch (er) {} renderSheet(); }
    else if (a === 'refresh') { lastRefreshMsg = 'กำลังดึงข้อมูล…'; renderSheet(); refreshNow(true); }
    else if (a === 'export') exportData();
    else if (a === 'clear') {
      if (!confirmClear) { confirmClear = true; renderSheet(); return; }
      store = emptyStore(); try { localStorage.removeItem(KEY); } catch (er) {}
      confirmClear = false; renderSheet(); updateBadge();
    } else if (a === 'debug') { debug = !debug; console.log('[MNI] store', store, snapshot()); b.textContent = debug ? 'Debug: เปิด (ดูใน console)' : 'Debug'; }
  }

  function renderSheet() {
    const sheet = root && root.querySelector('.sheet');
    if (!sheet) return;
    const core = C();
    if (!core) { sheet.innerHTML = '<div class="top"><b>📊 MyNovel Insights</b><button class="x" data-a="close">✕</button></div><p>โหลดตัวคำนวณไม่สำเร็จ — ติดตั้งสคริปต์จากไฟล์ dist/mynovel-insights.user.js ใหม่อีกครั้ง</p>'; return; }
    const keepScroll = sheet.scrollTop; // ข้อมูลอัปเดตเองระหว่างอ่าน -> ไม่ให้เด้งกลับขึ้นบน
    requestAnimationFrame(() => { sheet.scrollTop = keepScroll; });
    const data = core.normalize(snapshot());
    const books = data.books.filter(b => cat === 'all' || !b.category || b.category === cat);
    const ha = core.hourlyAverage(data.events);
    const known = ha.avg.map(x => x ?? 0);
    const coverage = ha.n.filter(x => x > 0).length;
    // เวลาทองต้องมีข้อมูลครบทั้ง 3 ชั่วโมงในช่วงนั้น ไม่งั้นช่วงที่ไม่มีข้อมูล (=0) จะลากค่าเฉลี่ยลง/บิดผล
    let best = null;
    if (coverage >= 3) for (let s = 0; s < 24; s++) {
      const hs = [s, (s + 1) % 24, (s + 2) % 24];
      if (hs.some(h => ha.avg[h] == null)) continue;
      const sum = hs.reduce((a, h) => a + ha.avg[h], 0);
      if (!best || sum > best.sum) best = { start: s, sum };
    }
    const maxAvg = Math.max(1, ...known);
    const days = new Set(data.events.filter(e => e.kind === 'view').map(e => Math.floor((e.ts.getTime() + 7 * 3.6e6) / 8.64e7))).size;
    const lvl = ha.hours >= 72 && coverage >= 22 ? ['good', 'ดี'] : ha.hours >= 24 && coverage >= 12 ? ['mid', 'พอใช้'] : ['low', 'ต่ำ'];
    const growth = books.filter(b => b.growth > 0).sort((a, b) => b.growth - a.growth).slice(0, 7);
    const topViews = books.filter(b => b.views != null).sort((a, b) => b.views - a.views).slice(0, 5);
    const tags = core.tagStats(books);
    const hotTags = tags.filter(t => t.count >= 3 && t.growthPerBook > 0).sort((a, b) => b.growthPerBook - a.growthPerBook).slice(0, 8);
    const rankTags = tags.filter(t => t.rankedCount >= 2).slice(0, 8);
    const item = (b, i, big, sub) => `<li><span class="n">${i + 1}</span><div class="t"><b>${esc(b.title)}</b><small>${esc(b.tags.slice(0, 3).map(core.tagLabel).join(' · ') || '—')}</small></div><div class="v">${big}<small>${sub}</small></div></li>`;
    const updated = store.updatedAt ? new Date(store.updatedAt).toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit' }) : '—';

    sheet.innerHTML = `
      <div class="top"><b>📊 MyNovel Insights</b><button class="x" data-a="close" aria-label="ปิด">✕</button></div>
      <div class="muted">เก็บแล้ว ${ha.hours} ชั่วโมง (${coverage}/24 ช่วงเวลา, ${days} วัน) · ${Object.keys(store.books).length} เรื่อง · อัปเดต ${updated}
        · ความน่าเชื่อถือ <span class="lvl ${lvl[0]}">${lvl[1]}</span></div>
      <div class="chips" style="margin-top:8px">${[['novel', 'นิยาย'], ['cartoon', 'การ์ตูน'], ['all', 'ทั้งหมด']].map(([v, l]) => `<button data-a="cat" data-v="${v}" class="${cat === v ? 'on' : ''}">${l}</button>`).join('')}</div>

      <h3>⏰ เวลาทอง (วิวที่เพิ่มเฉลี่ยต่อชั่วโมง)</h3>
      ${best ? `<div class="gold">${hh(best.start)}–${hh((best.start + 3) % 24)}</div><div class="muted">ลงตอนก่อนช่วงนี้ 30–60 นาที ให้ขึ้นหน้าอัปเดตทันตอนคนเข้ามา</div>`
        : `<div class="muted">ยังไม่พอ — ต้องมียอดวิวอย่างน้อย 3 ชั่วโมงติดกัน เปิดแท็บ MyNovel ทิ้งไว้ สคริปต์จะเก็บเองทุกชั่วโมง</div>`}
      <div class="bars">${ha.avg.map((x, h) => x == null ? `<i class="no" title="${hh(h)} ยังไม่มีข้อมูล"></i>`
        : `<i class="${best && [best.start, (best.start + 1) % 24, (best.start + 2) % 24].includes(h) ? 'best' : ''}" style="height:${Math.max(3, x / maxAvg * 100)}%" title="${hh(h)} ≈ ${Math.round(x)} วิว/ชม."></i>`).join('')}</div>
      <div class="ax">${Array.from({ length: 24 }, (_, h) => `<span>${h % 3 === 0 ? h : ''}</span>`).join('')}</div>
      ${coverage < 24 ? `<div class="muted">ลายทาง = ช่วงที่ยังไม่มีข้อมูล (${24 - coverage} ช่วง)</div>` : ''}

      <h3>🔥 วิวพุ่ง (24 ชม.ล่าสุด)</h3>
      ${growth.length ? `<ol>${growth.map((b, i) => item(b, i, '+' + fmt(b.growth), (b.growthHours < 23 ? b.growthHours + ' ชม. · ' : '') + 'รวม ' + fmt(b.views))).join('')}</ol>`
        : '<div class="muted">ยังคำนวณไม่ได้ — ต้องเห็นยอดวิวเรื่องเดิมซ้ำห่างกันอย่างน้อย 1 ชม.</div>'}

      <h3>🏷️ แท็ก/แนวที่ดึงคนอ่าน (วิวพุ่งเฉลี่ยต่อเรื่อง)</h3>
      ${hotTags.length ? `<div class="tags">${hotTags.map(t => `<span class="tag">${esc(core.tagLabel(t.tag))}<em>+${fmt(t.growthPerBook)}</em></span>`).join('')}</div><div class="muted">นับเฉพาะแท็กที่มีอย่างน้อย 3 เรื่อง</div>`
        : '<div class="muted">ยังไม่มีข้อมูลวิวพุ่ง</div>'}
      ${rankTags.length ? `<h3>📈 แท็ก/แนวที่ติดรายการมาแรง</h3><div class="tags">${rankTags.map(t => `<span class="tag">${esc(core.tagLabel(t.tag))}<em>${t.rankedCount}/${t.count}</em></span>`).join('')}</div><div class="muted">ตัวเลข = เรื่องที่ติดมาแรง / เรื่องทั้งหมดที่เห็นในแท็กนั้น</div>` : ''}

      <h3>🏆 ยอดวิวรวมสูงสุด</h3>
      ${topViews.length ? `<ol>${topViews.map((b, i) => item(b, i, fmt(b.views), b.rank ? 'มาแรง #' + b.rank : '')).join('')}</ol>` : '<div class="muted">ยังไม่มีข้อมูล — เปิดหน้าแรกของ MyNovel</div>'}

      ${lvl[0] === 'low' ? '<div class="warn">ข้อมูลยังน้อย ผลเป็นแค่แนวโน้มคร่าว ๆ — เปิดแท็บ MyNovel ทิ้งไว้หลายช่วงเวลา (เช้า/บ่าย/ค่ำ/ดึก) 2–3 วันจะเชื่อถือได้มากขึ้น</div>' : ''}
      <div class="row">
        <button class="pri" data-a="refresh">เก็บข้อมูลตอนนี้</button>
        <button data-a="export">Export ไฟล์</button>
      </div>
      <div class="muted" style="margin-top:6px">${esc(lastRefreshMsg)}</div>
      <div class="muted" style="margin-top:8px">ดูแบบละเอียด: กด Export แล้วเปิด <a href="${DASHBOARD_URL}" target="_blank" rel="noopener">หน้าวิเคราะห์เต็ม</a> → เลือกไฟล์</div>
      <div class="row">
        <button data-a="clear">${confirmClear ? 'แตะอีกครั้งเพื่อยืนยันล้างข้อมูล' : 'ล้างข้อมูล'}</button>
        <button data-a="debug">${debug ? 'Debug: เปิด (ดูใน console)' : 'Debug'}</button>
      </div>`;
  }

  document.addEventListener('DOMContentLoaded', () => { mount(); scanDOM(); setTimeout(autoTick, 15000); });
  // SPA: เปลี่ยนหน้าโดยไม่รีโหลด / โหลดข้อมูลเพิ่มตอนเลื่อน
  let t = null;
  (function observe() {
    if (!document.documentElement) return setTimeout(observe, 50);
    new MutationObserver(muts => {
      if (host && muts.every(m => host.contains(m.target))) return; // ไม่สนการเปลี่ยนแปลงในแผงของเราเอง
      clearTimeout(t); t = setTimeout(() => { mount(); scanDOM(); }, 1200);
    }).observe(document.documentElement, { childList: true, subtree: true });
  })();
})();
