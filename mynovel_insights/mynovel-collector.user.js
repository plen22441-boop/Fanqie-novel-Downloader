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
