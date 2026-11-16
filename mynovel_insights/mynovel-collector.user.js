// ==UserScript==
// @name         MyNovel Insights Collector
// @namespace    mynovel-insights
// @version      1.0.0
// @description  เก็บเวลาคอมเมนต์/ลงตอน + แท็ก/อันดับ จากหน้าที่คุณเปิดดูเอง แล้ว export เป็น JSON ไปวิเคราะห์ใน index.html
// @match        *://mynovel.co/*
// @match        *://*.mynovel.co/*
// @run-at       document-start
// @grant        none
// ==/UserScript==

/*
 * วิธีทำงาน (ไม่ยิง request เพิ่มเอง — อ่านแค่สิ่งที่หน้าเว็บโหลดมาให้คุณอยู่แล้ว):
 *  1) ดักผล fetch/XHR ที่เป็น JSON แล้วหา object ที่มีเวลา (createdAt ฯลฯ) หรือมีแท็ก
 *  2) สแกน DOM หา <time datetime>, ข้อความเวลาภาษาไทย และ #แท็ก
 * ข้อมูลเก็บใน localStorage ของเบราว์เซอร์คุณเท่านั้น
 *
 * ⚠️ ผู้เขียนสคริปต์ไม่ได้ทดสอบกับ HTML/API จริงของ mynovel.co (เข้าไม่ได้จากที่พัฒนา)
 *    ถ้าตัวนับไม่ขึ้น ให้กด "Debug" แล้วดู console ว่า JSON ที่ได้มีหน้าตาอย่างไร
 */
(function () {
  'use strict';
  const KEY = 'mni_data_v1';
  const MAX_EVENTS = 60000;
  const W = window;

  const TIME_KEYS = ['createdAt', 'created_at', 'createDate', 'create_date', 'publishedAt', 'published_at',
    'publishAt', 'publish_at', 'publishDate', 'releasedAt', 'commentedAt', 'postedAt', 'posted_at', 'createdTime', 'created_time'];
  const TAG_KEYS = ['tags', 'hashtags', 'hashTags', 'tag', 'tagList', 'tag_list', 'categories', 'category', 'genres', 'genre', 'subCategory'];
  const VIEW_KEYS = ['views', 'view', 'viewCount', 'view_count', 'totalView', 'total_view', 'readCount', 'read_count', 'reads', 'viewTotal'];
  const ID_KEYS = ['novelId', 'novel_id', 'bookId', 'book_id', 'storyId', 'story_id'];

  let store = load();
  let debug = false;
  let jsonHits = 0; // ถ้า JSON จับได้แล้ว ไม่ต้องสแกนข้อความ DOM ซ้ำ (กันนับคอมเมนต์เดียวกันสองครั้ง)

  function load() {
    try { return JSON.parse(localStorage.getItem(KEY)) || { events: {}, books: {} }; }
    catch (e) { return { events: {}, books: {} }; }
  }
  let saveTimer = null;
  function save() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      const keys = Object.keys(store.events);
      if (keys.length > MAX_EVENTS) for (const k of keys.slice(0, keys.length - MAX_EVENTS)) delete store.events[k];
      try { localStorage.setItem(KEY, JSON.stringify(store)); } catch (e) { console.warn('[MNI] save failed', e); }
      render();
    }, 400);
  }

  const lc = s => String(s || '').toLowerCase();
  const isRankPage = () => /rank|top|popular|trend|hot|อันดับ|ยอดนิยม/i.test(decodeURIComponent(location.href));

  function pickFirst(o, keys) { for (const k of keys) if (o[k] != null && o[k] !== '') return o[k]; return undefined; }

  function guessKind(path, o) {
    const p = lc(path.join('.'));
    if (/comment|reply|review/.test(p) || (o.content !== undefined && (o.user || o.member || o.author) && !o.title)) return 'comment';
    if (/chapter|episode|\bep\b|eps/.test(p) || o.chapterNo != null || o.episodeNo != null || o.chapter_number != null || o.ep != null) return 'chapter';
    if (/like|vote|heart|gift|donate/.test(p)) return 'like';
    return 'other';
  }

  function bookIdFor(o, path, ctxId) {
    return pickFirst(o, ID_KEYS) ?? ctxId ?? pageBookId();
  }

  function walk(o, path, ctx, depth) {
    if (!o || typeof o !== 'object' || depth > 12) return;
    if (Array.isArray(o)) {
      const listName = path[path.length - 1] || '';
      o.forEach((x, i) => walk(x, path.concat(listName), Object.assign({}, ctx, { index: i, listName }), depth + 1));
      return;
    }
    const title = o.title || o.name || o.novelName || o.novel_name;
    const tagVal = pickFirst(o, TAG_KEYS);
    const ownId = o.id ?? o._id ?? o.slug;

    // หนังสือ: มีชื่อ + แท็ก/หมวด
    if (title && tagVal != null && typeof title === 'string') {
      const id = String(pickFirst(o, ID_KEYS) ?? ownId ?? title);
      const tags = [].concat(tagVal).map(t => (t && typeof t === 'object') ? (t.name || t.title || t.tag || t.label) : t).filter(Boolean);
      const prev = store.books[id] || {};
      const rankish = /rank|top|popular|trend|hot/i.test(lc(path.join('.'))) || isRankPage();
      const rank = o.rank ?? o.ranking ?? o.position ?? (rankish && ctx.index != null ? ctx.index + 1 : undefined);
      store.books[id] = {
        id, title,
        tags: [...new Set((prev.tags || []).concat(tags.map(String)))],
        views: pickFirst(o, VIEW_KEYS) ?? prev.views,
        rank: rank != null ? (prev.rank ? Math.min(prev.rank, +rank) : +rank) : prev.rank,
        list: rank != null ? location.pathname : prev.list,
      };
      ctx = Object.assign({}, ctx, { bookId: id });
    }

    // event: มีฟิลด์เวลา
    const ts = pickFirst(o, TIME_KEYS);
    if (ts != null && !(title && tagVal != null)) {
      const kind = guessKind(path, o);
      const user = o.userId ?? o.user_id ?? (o.user && (o.user.id ?? o.user._id)) ?? (o.member && o.member.id);
      const bid = bookIdFor(o, path, ctx.bookId);
      const key = (ownId != null ? kind + ':' + ownId : [kind, ts, bid, user].join('|'));
      if (kind !== 'other') jsonHits++;
      if (!store.events[key]) store.events[key] = { ts, kind, bookId: bid, user, src: 'json' };
    }
    for (const k in o) if (o[k] && typeof o[k] === 'object') walk(o[k], path.concat(k), ctx, depth + 1);
  }

  function ingestJSON(text, url) {
    if (!text || (text[0] !== '{' && text[0] !== '[')) return;
    let j; try { j = JSON.parse(text); } catch (e) { return; }
    const before = Object.keys(store.events).length + Object.keys(store.books).length;
    walk(j, [lc(url).split('?')[0].split('/').slice(-2).join('.')], {}, 0);
    const after = Object.keys(store.events).length + Object.keys(store.books).length;
    if (jsonHits) purgeDomDupes();
    if (debug) console.log('[MNI]', url, after - before, 'new', j);
    if (after !== before) save();
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

  // ── DOM scan (สำรอง) ──
  const TH_TIME = /(\d{1,2}\s*(?:ม\.ค\.|ก\.พ\.|มี\.ค\.|เม\.ย\.|พ\.ค\.|มิ\.ย\.|ก\.ค\.|ส\.ค\.|ก\.ย\.|ต\.ค\.|พ\.ย\.|ธ\.ค\.)\s*\d{2,4}(?:\s*(?:เวลา)?\s*\d{1,2}[:.]\d{2})?|\d+\s*(?:นาที|ชั่วโมง|ชม\.)\s*(?:ที่แล้ว|ก่อน)|เมื่อวาน\s*\d{1,2}[:.]\d{2})/;

  function scanDOM() {
    // Next.js: ข้อมูลหน้าแรกฝังใน __NEXT_DATA__
    const nd = document.getElementById('__NEXT_DATA__');
    if (nd && !nd.dataset.mni) { nd.dataset.mni = '1'; ingestJSON(nd.textContent, location.pathname); }

    let added = 0;
    const domOk = jsonHits === 0;
    const kindOf = el => {
      const c = lc((el.closest('[class*="omment"],[class*="hapter"],[class*="pisode"],[id*="omment"]') || {}).className);
      return /omment/.test(c) ? 'comment' : /hapter|pisode/.test(c) ? 'chapter' : 'other';
    };
    if (domOk) document.querySelectorAll('time[datetime]').forEach(el => {
      const ts = el.getAttribute('datetime');
      const key = 'dom|' + ts + '|' + location.pathname + '|' + (el.closest('[data-id]') || {}).dataset?.id;
      if (!store.events[key]) { store.events[key] = { ts, kind: kindOf(el), bookId: pageBookId(), src: 'dom' }; added++; }
    });
    // ข้อความเวลาไทยในกล่องคอมเมนต์/ตอน (ข้อความสัมพัทธ์ถูกแปลงเป็นเวลาจริงทันทีที่เห็น)
    if (domOk) document.querySelectorAll('[class*="omment"] *, [class*="hapter"] *, [class*="pisode"] *').forEach(el => {
      if (el.children.length || el.dataset.mni) return;
      const m = (el.textContent || '').trim().match(TH_TIME);
      if (!m || el.textContent.length > 60) return;
      el.dataset.mni = '1';
      const box = el.closest('[class*="omment"],[class*="hapter"],[class*="pisode"]');
      // ตัดข้อความเวลาออกจาก fingerprint ("2 ชม.ที่แล้ว" เปลี่ยนไปเรื่อย ๆ จะทำให้นับซ้ำ)
      const fp = (box && box.textContent || '').replace(m[0], '').replace(/\s+/g, ' ').slice(0, 80);
      const key = 'domtxt|' + location.pathname + '|' + fp;
      if (!store.events[key]) { store.events[key] = { ts: m[1], seenAt: new Date().toISOString(), kind: kindOf(el), bookId: pageBookId(), src: 'domtext' }; added++; }
    });
    // หน้าเรื่อง: h1 + #แท็ก
    const h1 = document.querySelector('h1');
    const tagEls = [...document.querySelectorAll('a')].filter(a => /^[#＃]/.test((a.textContent || '').trim()) || /[?&/]tags?[=/]/.test(a.getAttribute('href') || ''));
    if (h1 && tagEls.length && tagEls.length < 40) {
      const id = pageBookId() || h1.textContent.trim();
      const prev = store.books[id] || {};
      const tags = tagEls.map(a => a.textContent.trim()).filter(t => t && t.length < 30);
      const before = (prev.tags || []).length;
      store.books[id] = Object.assign({ id, title: h1.textContent.trim() }, prev,
        { tags: [...new Set((prev.tags || []).concat(tags))] });
      if (store.books[id].tags.length !== before) added++;
    }
    if (added) save();
  }
  function pageBookId() {
    const m = location.pathname.match(/\/(?:novel|book|story|novels|books)\/([^/?#]+)/i);
    return m ? m[1] : undefined;
  }

  // ── แผงควบคุม ──
  let panel;
  function render() {
    if (!panel) return;
    const ev = Object.values(store.events);
    const c = k => ev.filter(e => e.kind === k).length;
    const books = Object.values(store.books);
    panel.querySelector('.mni-stat').textContent =
      `คอมเมนต์ ${c('comment')} · ลงตอน ${c('chapter')} · ไลก์ ${c('like')} · อื่น ๆ ${c('other')} | เรื่อง ${books.length} (มีอันดับ ${books.filter(b => b.rank).length})`;
  }
  function exportData() {
    // ข้อความสัมพัทธ์ ("2 ชั่วโมงที่แล้ว") ส่ง seenAt ไปด้วย ให้ตัววิเคราะห์คำนวณเวลาจริง
    const out = {
      exportedAt: new Date().toISOString(), source: location.host,
      events: Object.entries(store.events).map(([id, e]) => Object.assign({ id }, e)),
      books: Object.values(store.books),
    };
    const blob = new Blob([JSON.stringify(out)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'mynovel-insights-' + new Date().toISOString().slice(0, 10) + '.json';
    document.body.appendChild(a); a.click(); a.remove();
  }
  function mountPanel() {
    if (panel || !document.body) return;
    panel = document.createElement('div');
    panel.innerHTML = `
      <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
        <b>📊 Insights</b><span class="mni-stat"></span>
      </div>
      <div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap">
        <button data-a="exp">Export JSON</button>
        <button data-a="scan">สแกนหน้านี้</button>
        <button data-a="dbg">Debug</button>
        <button data-a="clr">ล้างข้อมูล</button>
        <button data-a="min">ย่อ</button>
      </div>`;
    Object.assign(panel.style, {
      position: 'fixed', right: '12px', bottom: 'calc(12px + env(safe-area-inset-bottom))', zIndex: 2147483647,
      background: '#1a1a19', color: '#f0efec', font: '13px/1.4 system-ui,sans-serif', padding: '10px 12px',
      borderRadius: '10px', boxShadow: '0 4px 16px rgba(0,0,0,.3)', maxWidth: 'min(92vw,420px)',
    });
    panel.querySelectorAll('button').forEach(b => Object.assign(b.style, {
      minHeight: '36px', padding: '4px 10px', borderRadius: '6px', border: '1px solid #555', background: '#2c2c2a', color: '#f0efec', cursor: 'pointer',
    }));
    panel.addEventListener('click', e => {
      const a = e.target.dataset && e.target.dataset.a;
      if (a === 'exp') exportData();
      if (a === 'scan') scanDOM();
      if (a === 'dbg') { debug = !debug; e.target.textContent = debug ? 'Debug: ON' : 'Debug'; console.log('[MNI] store', store); }
      if (a === 'clr' && confirm('ล้างข้อมูลที่เก็บไว้ทั้งหมด?')) { store = { events: {}, books: {} }; localStorage.removeItem(KEY); render(); }
      if (a === 'min') {
        const rows = panel.children[1];
        rows.style.display = rows.style.display === 'none' ? 'flex' : 'none';
      }
    });
    document.body.appendChild(panel);
    render();
  }

  document.addEventListener('DOMContentLoaded', () => { mountPanel(); scanDOM(); });
  // SPA: เปลี่ยนหน้าโดยไม่รีโหลด / โหลดคอมเมนต์เพิ่มตอนเลื่อน
  let t = null;
  (function observe() {
    // ตอน document-start บางตัวจัดการสคริปต์ยังไม่มี <html> ให้ observe
    if (!document.documentElement) return setTimeout(observe, 50);
    new MutationObserver(() => { clearTimeout(t); t = setTimeout(() => { mountPanel(); scanDOM(); }, 1200); })
      .observe(document.documentElement, { childList: true, subtree: true });
  })();
})();
