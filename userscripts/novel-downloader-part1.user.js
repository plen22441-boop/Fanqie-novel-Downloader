// ==UserScript==
// @name         Novel TXT Downloader - ส่วนที่ 1/2 (สารบัญ+เครือข่าย)
// @namespace    fanqie-novel-downloader
// @version      2.9
// @description  ส่วนที่ 1 จาก 2 ต้องติดตั้งคู่กับส่วนที่ 2
// @match        *://*/*
// @noframes
// @grant        unsafeWindow
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  const CHALLENGE = /Just a moment|正在进行安全验证|正在驗證|请稍候|cf-challenge|Verify Yourself|身份验证|人机验证|安全验证/;
  const CH_TXT = /第\s*[0-9零〇一二三四五六七八九十百千万两]+\s*[章节節回卷集话話篇]|^(序|楔子|引子|前言|后记|後記|尾声|尾聲|番外|终章|終章|大结局|大結局|完结感言)|^\d{1,5}\s*[.、．\s]|^Chapter\s*\d+/i;
  const NAV_LINK = /^(上一[章页頁节節]|下一[章页頁节節]|上[页頁]|下[页頁]|首[页頁]|尾[页頁]|末[页頁]|目[录錄]|返回.*|书[架页]|書[架頁]|登[录錄]|注册|註冊|排行榜?|分[类類]|全本|更多.*|最新章[节節]|查看.*|点击.*|點擊.*|开始阅读|立即阅读|繁體|简体)$/;
  const AD_BASE = /https?:|www\.|[a-z0-9-]{2,}\.(?:com|net|cc|org|cn|info|me|tw|la|vip)\b|精彩不容错过|全本放送|免费读全本|章[节節]更新提醒|精彩章[节節]《|下一章更精彩|沉浸阅读|阅读链接|阅读地址|立即解锁|先睹为快|剧情重大转折|探索现代言情|您收到了一个新的章[节節]更新|根据您的阅读历史|我们郑重向您推荐|追书不迷路|书迷速归|入口在此|人人书库|享受阅读时光|万千好书|名列前茅|经典语录频出|宝藏书籍|倾心之作|独家首发|奇妙旅程|文笔惊艳|口碑炸裂|好评如潮|最新章[节節]|请收藏|請收藏|手机阅读|手機閱讀|请记住|請記住|天才一秒|APP下载|笔趣阁|筆趣閣|求月票|求推荐票|求订阅|求訂閱|章[节節]更新提醒|书友们都去/i;
  const VERSION = '2.5'; // cache format: bump only when extraction or cleaning changes
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  let dbp = null;
  const idb = () => dbp || (dbp = new Promise((res, rej) => {
    const r = indexedDB.open('novel-dl-cache', 1);
    r.onupgradeneeded = () => r.result.createObjectStore('c');
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  }));
  async function idbGet(k) {
    try { const db = await idb(); return await new Promise((res) => { const q = db.transaction('c').objectStore('c').get(k); q.onsuccess = () => res(q.result); q.onerror = () => res(null); }); } catch (e) { return null; }
  }
  async function idbSet(k, v) {
    try { const db = await idb(); await new Promise((res) => { const t = db.transaction('c', 'readwrite'); t.objectStore('c').put(v, k); t.oncomplete = () => res(); t.onerror = () => res(); }); } catch (e) { /* cache is optional */ }
  }
  async function idbClear() {
    try { const db = await idb(); await new Promise((res) => { const t = db.transaction('c', 'readwrite'); t.objectStore('c').clear(); t.oncomplete = () => res(); t.onerror = () => res(); }); } catch (e) { /* ignore */ }
  }
  const st = { gate: { until: 0, level: 0, captcha: false, probe: '' }, stat: { partial: 0,  fetch: 0, iframe: 0, p429: 0, p403: 0, ms: 0, n: 0, okStreak: 0, lastCut: 0 }, workers: 6, limit: 6, restored: 0, chapters: [], results: [], errors: [], failed: new Set(), meta: {}, toc: {}, busy: false, ad: AD_BASE };

  const isChallenge = (h) => h.length < 30000 && CHALLENGE.test(h);
  const parseHtml = (h) => new DOMParser().parseFromString(h, 'text/html');
  const textOf = (n) => (n.textContent || '').replace(/\s+/g, ' ').trim();
  const cleanTitle = (t) => t.replace(/^\d{1,5}\s*[.、．]\s*/, '').replace(/^第\s*[0-9零〇一二三四五六七八九十百千万两]+\s*章\s*/, '').trim();

  // ---------- network ----------
  function decodeBody(buf, ct) {
    let cs = (/charset=([\w-]+)/i.exec(ct || '') || [])[1];
    if (!cs) {
      const head = new TextDecoder('latin1').decode(buf.slice(0, 3000));
      cs = (/<meta[^>]+charset=["']?([\w-]+)/i.exec(head) || [])[1];
    }
    cs = (cs || 'utf-8').toLowerCase();
    if (/^(gbk|gb2312|gb18030|x-gbk)$/.test(cs)) cs = 'gb18030';
    try { return new TextDecoder(cs).decode(buf); } catch (e) { return new TextDecoder('utf-8').decode(buf); }
  }

  async function fetchText(url) {
    const r = await fetch(url, { credentials: 'include' });
    const buf = await r.arrayBuffer();
    return { status: r.status, ok: r.ok, text: decodeBody(buf, r.headers.get('content-type')) };
  }

  let ifrChain = Promise.resolve();
  const ifrQueue = (fn) => { const p = ifrChain.then(fn, fn); ifrChain = p.catch(() => {}); return p; };
  function viaIframe(url) {
    return new Promise((res, rej) => {
      const f = document.createElement('iframe');
      f.style.cssText = 'position:fixed;left:-9999px;top:0;width:900px;height:700px;opacity:0';
      f.src = url;
      document.body.appendChild(f);
      const t0 = Date.now();
      const iv = setInterval(() => {
        try {
          const d = f.contentDocument;
          if (d && d.body) {
            const html = d.documentElement.outerHTML;
            if (!isChallenge(html) && d.body.textContent.trim().length > 100) { clearInterval(iv); f.remove(); res(html); return; }
          }
        } catch (e) { /* keep waiting */ }
        if (Date.now() - t0 > 25000) { clearInterval(iv); f.remove(); rej(new Error('ด่านตรวจไม่ผ่านภายใน 25 วินาที')); }
      }, 1000);
    });
  }

  function cut() {
    const t = Date.now();
    if (t - st.stat.lastCut < 5000) return;
    st.stat.lastCut = t;
    st.stat.okStreak = 0;
    st.limit = Math.max(Math.min(3, st.workers), st.limit - 2);
  }

  async function loadHtml(url) {
    const r = await fetchText(url);
    if (r.status === 429) { st.stat.p429++; cut(); throw new Error('RATE'); }
    if (r.status === 403 || r.status === 503 || isChallenge(r.text)) {
      st.stat.p403++; cut();
      if (/GOEDGE_WAF|ui-captcha|Verify Yourself|身份验证|人机验证|验证码/.test(r.text.slice(0, 6000))) throw new Error('CAPTCHA');
      st.stat.iframe++;
      try { return { html: await ifrQueue(() => viaIframe(url)), mode: 'iframe' }; } catch (e) { throw new Error('BLOCK'); }
    }
    st.stat.fetch++;
    return { html: r.text, mode: 'fetch' };
  }

  // ---------- TOC detection ----------
  function shapeKey(href) {
    const u = new URL(href);
    return u.pathname.replace(/\d+/g, 'N') + (u.search ? '?' + u.search.slice(1).replace(/\d+/g, 'N') : '');
  }

  function anchorsOf(root, base) {
    const out = [];
    root.querySelectorAll('a[href]').forEach((a) => {
      const raw = a.getAttribute('href');
      if (!raw || /^(javascript|#|mailto|tel)/i.test(raw)) return;
      let u;
      try { u = new URL(raw, base); } catch (e) { return; }
      if (u.origin !== location.origin) return;
      out.push({ a, url: u.href, title: textOf(a) });
    });
    return out;
  }

  function boxItems(items) {
    const total = new Set(items.map((i) => i.url)).size;
    const sets = new Map();
    items.forEach((it) => {
      for (let e = it.a.parentElement; e; e = e.parentElement) {
        if (!sets.has(e)) sets.set(e, new Set());
        sets.get(e).add(it.url);
      }
    });
    let box = null, cost = Infinity;
    sets.forEach((s, e) => {
      if (s.size >= total * 0.6) {
        const c = e.querySelectorAll('*').length;
        if (c < cost) { box = e; cost = c; }
      }
    });
    const seen = new Set(), out = [];
    const pool = box ? items.filter((it) => box.contains(it.a)) : items;
    pool.forEach((it) => { if (!seen.has(it.url)) { seen.add(it.url); out.push(it); } });
    return { out, box };
  }

  function detect(root, base) {
    const items = anchorsOf(root, base);
    const groups = new Map();
    items.forEach((it) => {
      const k = shapeKey(it.url);
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(it);
    });
    const pageSeg = location.pathname.split('/').filter(Boolean)[0] || '';
    let best = null;
    groups.forEach((g, k) => {
      const uniq = new Set(g.map((i) => i.url)).size;
      if (uniq < 5) return;
      const titled = g.filter((i) => i.title);
      const ch = titled.filter((i) => CH_TXT.test(i.title)).length / Math.max(1, titled.length);
      const nav = titled.filter((i) => NAV_LINK.test(i.title)).length / Math.max(1, titled.length);
      const brk = titled.filter((i) => /^《.*》$/.test(i.title)).length / Math.max(1, titled.length);
      if (brk > 0.5 || nav > 0.5) return;
      if (ch < 0.15 && uniq < 30) return;
      const seg = g.filter((i) => (new URL(i.url).pathname.split('/').filter(Boolean)[0] || '') === pageSeg).length / g.length;
      const score = uniq * (0.5 + ch) * (seg > 0.5 ? 1.2 : 1) * (1 - nav);
      if (!best || score > best.score) best = { key: k, items: g, score };
    });
    if (!best) return null;
    const { out, box } = boxItems(best.items);
    const hint = (root.body.textContent.match(/共\s*(\d+)\s*[章节節]/) || [])[1];
    return { key: best.key, items: out, all: best.items.map((i) => i.url), hint: hint ? +hint : null,
      box: box ? box.tagName.toLowerCase() + (box.id ? '#' + box.id : '') + (box.className ? '.' + String(box.className).trim().split(/\s+/).join('.') : '') : null };
  }

  const NEXT_LINK = /^(下一[页頁]|下[页頁]|下一页\s*[>›»]|[>›»]|next)$/i;
  function pageLinks(doc, base) {
    const urls = [];
    doc.querySelectorAll('select').forEach((s) => {
      const vals = [...s.options].map((o) => o.value).filter((v) => v && !/^(javascript|#)/i.test(v));
      if (vals.length >= 2 && vals.every((v) => /[\/.?]/.test(v))) {
        vals.forEach((v) => { try { const u = new URL(v, base); if (u.origin === location.origin) urls.push(u.href); } catch (e) { /* skip */ } });
      }
    });
    return urls;
  }
  function nextLink(doc, base) {
    for (const a of doc.querySelectorAll('a[href]')) {
      if (!NEXT_LINK.test(textOf(a))) continue;
      const h = a.getAttribute('href');
      if (!h || /^(javascript|#)/i.test(h)) continue;
      try { const u = new URL(h, base); if (u.origin === location.origin && u.href !== base) return u.href; } catch (e) { /* skip */ }
    }
    return null;
  }

  function tap(el) {
    const o = { bubbles: true, cancelable: true, view: window };
    ['pointerdown', 'mousedown', 'touchstart', 'pointerup', 'mouseup', 'touchend', 'click'].forEach((t) => {
      let ev;
      try { ev = t.startsWith('touch') ? new TouchEvent(t, o) : t.startsWith('pointer') ? new PointerEvent(t, o) : new MouseEvent(t, o); } catch (e) { ev = new Event(t, o); }
      el.dispatchEvent(ev);
    });
    const jq = (typeof unsafeWindow !== 'undefined' ? unsafeWindow : window).jQuery;
    if (jq) { try { jq(el).trigger('click'); } catch (e) { /* ignore */ } }
  }

  // TOC pages switched by JavaScript (select change / "next" button without a real URL)
  async function harvestLive(key, ui) {
    const cur = () => boxItems(anchorsOf(document, location.href).filter((i) => shapeKey(i.url) === key)).out.map((i) => ({ url: i.url, title: i.title }));
    const sig = (a) => (a.length ? a[0].url + '|' + a[a.length - 1].url + '|' + a.length : '');
    const out = [], have = new Set(cur().map((c) => c.url));
    const add = (arr) => { let n = 0; arr.forEach((c) => { if (!have.has(c.url)) { have.add(c.url); out.push(c); n++; } }); return n; };
    const nres = () => performance.getEntriesByType('resource').length;
    const waitChange = async (before) => { const r0 = nres(); for (let k = 0; k < 160; k++) { await sleep(150); if (k === 20 && nres() === r0) return false; const x = sig(cur()); if (x && x !== before) return true; } return false; };
    const sels = [...document.querySelectorAll('select')].filter((e) => e.options.length >= 2 && e.options.length <= 400 && ![...e.options].every((o) => /^(javascript|#)/i.test(o.value)));
    for (const sel of sels) {
      const start = sel.selectedIndex;
      let gained = 0;
      for (let k = 0; k < sel.options.length; k++) {
        if (k === start) continue;
        const before = sig(cur());
        let changed = false;
        for (let tr = 0; tr < 2 && !changed; tr++) {
          sel.selectedIndex = k;
          sel.dispatchEvent(new Event('input', { bubbles: true }));
          sel.dispatchEvent(new Event('change', { bubbles: true }));
          const jq = (typeof unsafeWindow !== 'undefined' ? unsafeWindow : window).jQuery;
          if (jq) { try { jq(sel).val(sel.value).trigger('change'); } catch (e) { /* ignore */ } }
          changed = await waitChange(before);
        }
        if (!changed) { if (!gained && k === (start === 0 ? 1 : 0)) break; continue; }
        gained += add(cur());
        ui('สแกนสารบัญ หน้า ' + (k + 1) + '/' + sel.options.length + ' (พบเพิ่ม ' + out.length + ' ตอน)');
      }
      if (gained) { sel.selectedIndex = start; sel.dispatchEvent(new Event('change', { bubbles: true })); return { out, mode: 'select-change' }; }
    }
    const findNext = () => {
      for (const e of document.querySelectorAll('a,button,span,div,li,input[type=button]')) {
        const t = (e.value || e.textContent || '').replace(/\s+/g, '');
        if (!/^(下一[页頁]|下[页頁]|next)$/i.test(t)) continue;
        if (e.disabled || /disabled|disable|gray|off/i.test(String(e.className || ''))) continue;
        const href = e.getAttribute && e.getAttribute('href');
        if (href && !/^(javascript|#)/i.test(href)) continue;
        return e;
      }
      return null;
    };
    for (let g = 0; g < 400; g++) {
      const nx = findNext();
      if (!nx) break;
      const before = sig(cur());
      tap(nx);
      let moved = await waitChange(before);
      if (!moved) { tap(nx); moved = await waitChange(before); }
      if (!moved) break;
      if (!add(cur())) break;
      ui('สแกนสารบัญ (กดหน้าถัดไป) พบเพิ่ม ' + out.length + ' ตอน');
    }
    return { out, mode: out.length ? 'click-next' : 'none' };
  }

  // Guess page URLs (?page=N, _N, /N ...) when the page selector exists but does nothing visible
  async function guessPages(key, firstSet) {
    const sel = [...document.querySelectorAll('select')].find((e) => e.options.length >= 2 && e.options.length <= 400 && [...e.options].every((o) => /^\d+$/.test(o.value)));
    if (!sel) return { out: [], tried: [] };
    const vals = [...sel.options].map((o) => o.value);
    const u = new URL(location.href);
    const ext = (u.pathname.match(/\.(?:html?|shtml|php)$/i) || [''])[0];
    const stem = u.pathname.replace(/\.(?:html?|shtml|php)$/i, '').replace(/[_\-\/]\d+$/, '').replace(/\/$/, '');
    const gens = [];
    ['page', 'p', 'pg', 'pn'].forEach((k) => gens.push((v) => { const x = new URL(u.href); x.searchParams.set(k, v); return x.href; }));
    ['_', '-', '/'].forEach((sep) => gens.push((v) => u.origin + stem + sep + v + ext + u.search));
    gens.push((v) => u.origin + stem + '/' + v + '/' + u.search);
    if (/\d+(?=(\.\w+)?\/?$)/.test(u.pathname)) gens.push((v) => u.origin + u.pathname.replace(/\d+(?=(\.\w+)?\/?$)/, v) + u.search);
    const grab = async (url) => {
      try {
        const r = await fetchText(url);
        if (!r.ok || isChallenge(r.text)) return null;
        const its = anchorsOf(parseHtml(r.text), url).filter((i) => shapeKey(i.url) === key);
        return boxItems(its).out.map((i) => ({ url: i.url, title: i.title }));
      } catch (e) { return null; }
    };
    const tried = [];
    const probe = vals[1];
    for (let g = 0; g < gens.length; g++) {
      const url = gens[g](probe);
      const got = await grab(url);
      tried.push(url.replace(location.origin, '') + ' -> ' + (got ? got.length : 'x'));
      if (got && got.length >= 5 && !firstSet.has(got[0].url)) {
        const out = [];
        for (const v of vals) {
          if (v === vals[0]) continue;
          const pg = await grab(gens[g](v));
          if (pg) pg.forEach((c) => { if (!firstSet.has(c.url)) { firstSet.add(c.url); out.push(c); } });
        }
        return { out, tried, mode: 'guess' };
      }
    }
    return { out: [], tried };
  }

  async function addPage(ui) {
    const d = detect(document, location.href);
    if (!d) { ui('ไม่พบรายชื่อตอนในหน้านี้'); return false; }
    const key = st.toc && st.toc.key ? st.toc.key : d.key;
    const items = boxItems(anchorsOf(document, location.href).filter((i) => shapeKey(i.url) === key)).out.map((i) => ({ url: i.url, title: i.title }));
    const have = new Set(st.chapters.map((c) => c.url));
    let added = 0;
    const list = st.chapters.map((c) => ({ url: c.url, title: c.title }));
    items.forEach((c) => { if (!have.has(c.url)) { have.add(c.url); list.push(c); added++; } });
    const nums = list.map((c) => numOf(c.title));
    if (nums.every((n) => n !== null) && list.length > 4) list.sort((a, b) => numOf(a.title) - numOf(b.title));
    st.chapters = list.map((c, i) => ({ i, url: c.url, title: c.title }));
    st.results = new Array(list.length).fill(null);
    if (!st.meta.title) st.meta = metaOf(document);
    st.toc = Object.assign({ key, paging: 'manual', dbg: {} }, st.toc, { count: list.length });
    ui('รวมแล้ว ' + list.length + ' ตอน (เพิ่มจากหน้านี้ ' + added + ') | แรก: ' + (list[0].title || '').slice(0, 14) + ' | ท้าย: ' + (list[list.length - 1].title || '').slice(0, 14) + ' | เปลี่ยนไปหน้าถัดไปแล้วกดอีกครั้ง');
    return true;
  }

  const numOf = (t) => { const m = /第\s*(\d+)\s*[章节節回]/.exec(t) || /^(\d{1,5})\s*[.、．]/.exec(t); return m ? +m[1] : null; };

  function fillSequential(list, all) {
    if (list.length < 3 || list.length > 80) return { list, filled: false };
    const key = shapeKey(list[0].url);
    if (!list.every((c) => shapeKey(c.url) === key)) return { list, filled: false };
    const re = /(\d+)(\D*)$/;
    const nums = (all && all.length ? all : list.map((c) => c.url)).map((cu) => { const u = new URL(cu); const m = re.exec(u.pathname + u.search); return m ? +m[1] : null; });
    if (nums.some((n) => n === null)) return { list, filled: false };
    const max = Math.max(...nums), min = Math.min(...nums);
    if (min !== 1 || max > 5000 || list.length >= max * 0.5) return { list, filled: false };
    const u0 = new URL(list[0].url);
    const full = u0.pathname + u0.search;
    const m0 = re.exec(full);
    const out = [];
    for (let n = 1; n <= max; n++) {
      const path = full.slice(0, m0.index) + n + m0[2];
      out.push({ url: u0.origin + path, title: '' });
    }
    return { list: out, filled: true };
  }

  function metaOf(doc) {
    const pick = (sels) => { for (const s of sels) { const e = doc.querySelector(s); const v = e && (e.content || e.textContent); if (v && v.trim()) return v.trim(); } return ''; };
    let title = pick(['meta[property="og:novel:book_name"]', 'meta[property="og:title"]', 'h1', 'title']);
    title = title.split(/[_\-|—]|最新章|全文|在线阅读|目录|目錄|小说/)[0].trim() || title.trim();
    let author = pick(['meta[property="og:novel:author"]', 'meta[name="author"]']);
    if (!author) {
      const al = doc.querySelector('a[href*="author"],a[href*="/list?q="]');
      if (al && textOf(al).length <= 20) author = textOf(al);
    }
    if (!author) { const m = /作\s*者[：:]\s*([^\s|，,]{1,20})/.exec(doc.body ? doc.body.textContent : ''); author = m ? m[1] : ''; }
    author = author.split(/最新|更新|状态|狀態|类型|類型|分类|分類|字数|字數|简介|簡介|第\d/)[0].trim();
    const lbl = (doc.title || '').split(/[_\-|—]/).map((s) => s.trim()).filter((s) => s && s.length <= 12 && !title.includes(s));
    const host = location.hostname.replace(/^www\./, '').split('.')[0];
    const toks = [...new Set([host, ...lbl])].filter((x) => x.length >= 3 && !/^\d+$/.test(x) && !author.includes(x)).map((x) => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    st.ad = toks.length ? new RegExp(AD_BASE.source + '|' + toks.join('|'), 'i') : AD_BASE;
    return { title: title || '未知书名', author: author || '未知作者', bookId: (location.pathname + location.search).replace(/[^\w]+/g, '_').replace(/^_|_$/g, '') || 'book' };
  }

  async function scan(ui) {
    ui('กำลังสแกนสารบัญ...');
    st.chapters = []; st.results = []; st.errors = []; st.failed = new Set();
    let src = null;
    try { const r = await fetchText(location.href); if (r.ok && !isChallenge(r.text)) src = parseHtml(r.text); } catch (e) { /* use live */ }
    const live = detect(document, location.href);
    const fromSrc = src ? detect(src, location.href) : null;
    let det = fromSrc && (!live || fromSrc.items.length >= live.items.length) ? fromSrc : live;
    let doc = det === fromSrc && src ? src : document;
    if (!det) { ui('ไม่พบสารบัญในหน้านี้ เปิดหน้าสารบัญเต็ม (หรือกดแสดงสารบัญ) แล้วกดสแกนใหม่'); return false; }
    let note = '';
    if (det.items.length < 30) {
      const link = anchorsOf(doc, location.href).find((x) => /(完整|全部|全文)?(章[节節]|目[录錄])(列表)?|查看全部|显示全部|全部章/.test(x.title) && x.title.length <= 12 && x.url !== location.href && !det.items.some((i) => i.url === x.url));
      if (link) {
        try {
          const r = await fetchText(link.url);
          const d2 = parseHtml(r.text);
          const det2 = detect(d2, link.url);
          if (det2 && det2.items.length > det.items.length) { det = det2; doc = d2; note = ' (จากหน้า ' + link.title + ')'; }
        } catch (e) { /* keep */ }
      }
    }
    let list = det.items.map((i) => ({ url: i.url, title: i.title }));
    let pagesN = 1;
    const queue = [], seenPages = new Set([location.href]);
    const addPages = (d) => pageLinks(d, location.href).forEach((u) => { if (!seenPages.has(u)) { seenPages.add(u); queue.push(u); } });
    addPages(doc);
    if (doc !== document) addPages(document);
    const hadSelect = queue.length > 0;
    let cur = location.href;
    const nl = nextLink(doc, cur) || (doc !== document ? nextLink(document, cur) : null);
    if (nl && !seenPages.has(nl) && !queue.length) { queue.push(nl); seenPages.add(nl); }
    let guard = 0;
    while (queue.length && guard++ < 150) {
      const u = queue.shift();
      try {
        const r = await fetchText(u);
        if (!r.ok || isChallenge(r.text)) continue;
        const d = parseHtml(r.text);
        const its = anchorsOf(d, u).filter((i) => shapeKey(i.url) === det.key);
        const b = boxItems(its).out;
        const have = new Set(list.map((c) => c.url));
        b.forEach((i) => { if (!have.has(i.url)) list.push({ url: i.url, title: i.title }); });
        pagesN++;
        if (!hadSelect) {
          const n2 = nextLink(d, u);
          if (n2 && !seenPages.has(n2)) { seenPages.add(n2); queue.push(n2); }
        }
      } catch (e) { /* skip page */ }
    }
    let paging = pagesN > 1 ? 'urls' : 'none';
    if (pagesN === 1) {
      const h = await harvestLive(det.key, ui);
      if (h.out.length) {
        const have = new Set(list.map((c) => c.url));
        h.out.forEach((c) => { if (!have.has(c.url)) list.push(c); });
        paging = h.mode;
      }
    }
    let guessTried = [];
    if (pagesN === 1 && paging === 'none') {
      const g = await guessPages(det.key, new Set(list.map((c) => c.url)));
      guessTried = g.tried;
      if (g.out.length) { list = list.concat(g.out); paging = 'guess'; }
    }
    const dbgSel = [...document.querySelectorAll('select')].slice(0, 2).map((e) => e.outerHTML.slice(0, 220));
    const dbgNext = [...document.querySelectorAll('a,button,span,div,li')].filter((e) => /^(下一[页頁]|下[页頁])$/.test((e.textContent || '').replace(/\s+/g, ''))).slice(0, 2).map((e) => e.outerHTML.slice(0, 160));
    const nums = list.map((c) => numOf(c.title)).filter((n) => n !== null);
    let rev = 0, inc = 0;
    for (let i = 1; i < nums.length; i++) { if (nums[i] < nums[i - 1]) rev++; else if (nums[i] > nums[i - 1]) inc++; }
    let reversed = false;
    if (nums.length > 4 && rev > inc * 2) { list.reverse(); reversed = true; }
    const fs = fillSequential(list, det.all);
    list = fs.list;
    if (src && det !== fromSrc) {
      const map = new Map((fromSrc ? fromSrc.items : []).map((i) => [i.url, i.title]));
      list.forEach((c) => { if (map.get(c.url)) c.title = map.get(c.url); });
    }
    st.chapters = list.map((c, i) => ({ i, url: c.url, title: c.title }));
    st.results = new Array(list.length).fill(null);
    st.meta = metaOf(src || document);
    st.toc = { paging, dbg: { sel: dbgSel, next: dbgNext, guess: guessTried }, key: det.key, count: list.length, hint: det.hint, box: det.box, reversed, pages: pagesN, filled: fs.filled, src: det === fromSrc ? 'source' : 'live' };
    const first = list[0], last = list[list.length - 1];
    const ctl = dbgSel[0] || dbgNext[0] || '';
    const diag = ' | หน้า: ' + paging + (paging === 'none' && ctl ? ' (เจอตัวควบคุมหน้าแต่เปลี่ยนไม่ได้: ' + ctl.replace(/\s+/g, ' ').slice(0, 110) + ')' : '');
    ui('พบ ' + list.length + ' ตอน' + (det.hint ? ' (เว็บแจ้ง ' + det.hint + ')' : '') + note + (fs.filled ? ' [เติมเลขตอน]' : '') +
      ' | แรก: ' + (first.title || first.url).slice(0, 18) + ' | ท้าย: ' + (last.title || last.url).slice(0, 18) + diag);
    return true;
  }

  const W = typeof unsafeWindow !== 'undefined' ? unsafeWindow : window;
  W.__NDL1 = { st, VERSION, cleanTitle, detect, idbClear, idbGet, idbSet, ifrQueue, loadHtml, parseHtml, scan, sleep, textOf, viaIframe, fetchText, isChallenge, addPage };
})();
