// ==UserScript==
// @name         Novel TXT Downloader (universal)
// @namespace    fanqie-novel-downloader
// @version      2.6
// @description  โหลดนิยายจากเว็บนิยายจีนทั่วไปเป็นไฟล์ .txt ผ่านเบราว์เซอร์ของคุณเอง
// @match        *://*/*
// @noframes
// @grant        GM_registerMenuCommand
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  const TEST = typeof window.__NOVEL_TEST !== 'undefined';
  const ZW = /[​-‏⁠﻿­]/g;
  const SEP = '─'.repeat(40);
  const CHALLENGE = /Just a moment|正在进行安全验证|正在驗證|请稍候|cf-challenge|Verify Yourself|身份验证|人机验证|安全验证/;
  const CH_TXT = /第\s*[0-9零〇一二三四五六七八九十百千万两]+\s*[章节節回卷集话話篇]|^(序|楔子|引子|前言|后记|後記|尾声|尾聲|番外|终章|終章|大结局|大結局|完结感言)|^\d{1,5}\s*[.、．\s]|^Chapter\s*\d+/i;
  const NAV_LINK = /^(上一[章页頁节節]|下一[章页頁节節]|上[页頁]|下[页頁]|首[页頁]|尾[页頁]|末[页頁]|目[录錄]|返回.*|书[架页]|書[架頁]|登[录錄]|注册|註冊|排行榜?|分[类類]|全本|更多.*|最新章[节節]|查看.*|点击.*|點擊.*|开始阅读|立即阅读|繁體|简体)$/;
  const NAV_LINE = /^(上一[章页頁节節]|下一[章页頁节節]|上[页頁]|下[页頁]|目[录錄]|返回.*|书页|書頁|加入书[架签]|加入書[架籤]|设置|設置|A[+-]|阅读背景|错乱章节催更！?|章节错误|章節錯誤|举报|舉報|收藏|书名[：:]?|作者[：:]?|本章字数[：:]?|更新时间[：:]?|开始阅读|立即阅读|报错|催更|书签|没有了|沒有了|指南)$/;
  const UI_JUNK = /^(.*方向键可?切换章节|左右滑动可?切换章节|不吐不快|后?发表评论|我要评论|点击.{0,6}评论|.*扫码.*|.*二维码.*)$/;
  const REC = /^(猜你喜欢|相关推荐|热门推荐|新书推荐|同类推荐|大家都在看|推荐阅读|相关小说)$/;
  const URL_LEAD = /(?:速看|点击|点我|访问|登录|收藏|追更|围观|阅读链接|阅读地址|链接|入口在此|直达故事世界|指尖一点|先睹为快|书迷速归|欢迎访问|来|上|看看|探索)[，,：:]?\s*(?:https?:\/{0,2}|\/\/|www\.)[\x21-\x7e]*/g;
  const URL_BARE = /(?:https?:\/{0,2}|www\.)[\x21-\x7e]*/g;
  const META = /^小说名[：:].*(更新时间|章节字数)|^(更新时间|更新日期|发布时间|更新時間)[：:]\s*\d{4}|^(本章字数|章节字数|字数|字數)[：:]\s*\d+|^.{0,40}更新时间[：:]?\s*\d{4}-\d{1,2}-\d{1,2}.{0,60}$/;
  const AD_BASE = /https?:|www\.|[a-z0-9-]{2,}\.(?:com|net|cc|org|cn|info|me|tw|la|vip)\b|精彩不容错过|全本放送|免费读全本|章[节節]更新提醒|精彩章[节節]《|下一章更精彩|沉浸阅读|阅读链接|阅读地址|立即解锁|先睹为快|剧情重大转折|探索现代言情|您收到了一个新的章[节節]更新|根据您的阅读历史|我们郑重向您推荐|追书不迷路|书迷速归|入口在此|人人书库|享受阅读时光|万千好书|名列前茅|经典语录频出|宝藏书籍|倾心之作|独家首发|奇妙旅程|文笔惊艳|口碑炸裂|好评如潮|最新章[节節]|请收藏|請收藏|手机阅读|手機閱讀|请记住|請記住|天才一秒|APP下载|笔趣阁|筆趣閣|求月票|求推荐票|求订阅|求訂閱|章[节節]更新提醒|书友们都去/i;
  const CONTENT_SELS = ['#chaptercontent', '#content', '#BookText', '#booktxt', '#htmlContent', '#nr1', '#nr', '#text_area', '#chapterContent', '#acontent', '#novelcontent', '.txtnav', '.chapter-content', '.read-content', '.reader-content', '.page-content', '.chapter-body', '.article-content', '.text-content', '.showtxt', '.novelcontent', '.content', 'article'];
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
  const st = { stat: { fetch: 0, iframe: 0, p429: 0, p403: 0, ms: 0, n: 0, okStreak: 0, lastCut: 0 }, workers: 6, limit: 6, restored: 0, chapters: [], results: [], errors: [], failed: new Set(), meta: {}, toc: {}, busy: false, ad: AD_BASE };

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
        if (Date.now() - t0 > 60000) { clearInterval(iv); f.remove(); rej(new Error('ด่านตรวจไม่ผ่านภายใน 60 วินาที')); }
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
    if (r.status === 429) { st.stat.p429++; cut(); await sleep(4000); throw new Error('HTTP 429'); }
    if (r.status === 403 || r.status === 503 || isChallenge(r.text)) {
      st.stat.p403++; cut(); st.stat.iframe++;
      return { html: await ifrQueue(() => viaIframe(url)), mode: 'iframe' };
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

  // TOC pages switched by JavaScript (select change / "next" button without a real URL)
  async function harvestLive(key, ui) {
    const cur = () => boxItems(anchorsOf(document, location.href).filter((i) => shapeKey(i.url) === key)).out.map((i) => ({ url: i.url, title: i.title }));
    const sig = (a) => (a.length ? a[0].url + '|' + a[a.length - 1].url + '|' + a.length : '');
    const out = [], have = new Set(cur().map((c) => c.url));
    const add = (arr) => { let n = 0; arr.forEach((c) => { if (!have.has(c.url)) { have.add(c.url); out.push(c); n++; } }); return n; };
    const waitChange = async (before) => { for (let k = 0; k < 160; k++) { await sleep(150); const x = sig(cur()); if (x && x !== before) return true; } return false; };
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
          changed = await waitChange(before);
        }
        if (!changed) continue;
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
      nx.click();
      let moved = await waitChange(before);
      if (!moved) { nx.click(); moved = await waitChange(before); }
      if (!moved) break;
      if (!add(cur())) break;
      ui('สแกนสารบัญ (กดหน้าถัดไป) พบเพิ่ม ' + out.length + ' ตอน');
    }
    return { out, mode: out.length ? 'click-next' : 'none' };
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
    st.toc = { paging, dbg: { sel: dbgSel, next: dbgNext }, key: det.key, count: list.length, hint: det.hint, box: det.box, reversed, pages: pagesN, filled: fs.filled, src: det === fromSrc ? 'source' : 'live' };
    const first = list[0], last = list[list.length - 1];
    const ctl = dbgSel[0] || dbgNext[0] || '';
    const diag = ' | หน้า: ' + paging + (paging === 'none' && ctl ? ' (เจอตัวควบคุมหน้าแต่เปลี่ยนไม่ได้: ' + ctl.replace(/\s+/g, ' ').slice(0, 110) + ')' : '');
    ui('พบ ' + list.length + ' ตอน' + (det.hint ? ' (เว็บแจ้ง ' + det.hint + ')' : '') + note + (fs.filled ? ' [เติมเลขตอน]' : '') +
      ' | แรก: ' + (first.title || first.url).slice(0, 18) + ' | ท้าย: ' + (last.title || last.url).slice(0, 18) + diag);
    return true;
  }

  // ---------- extraction ----------
  function isNextPage(first, pageNo, next) {
    const f = new URL(first), n = new URL(next);
    if (f.origin !== n.origin) return false;
    if (f.pathname === n.pathname) {
      for (const k of ['page', 'p', 'pg', 'pn', 'pageno']) {
        const fv = f.searchParams.get(k), nv = n.searchParams.get(k);
        if (nv !== null && +nv === pageNo + 1 && (fv === null || +fv === pageNo)) return true;
      }
    }
    const strip = (p) => p.replace(/\.(html?|shtml|php)$/i, '');
    const fb = strip(f.pathname), nb = strip(n.pathname);
    for (const sep of ['_', '-', '/']) if (nb === fb + sep + (pageNo + 1) && f.search === n.search) return true;
    return false;
  }

  function nextPageOf(doc, first, cur, pageNo) {
    for (const a of doc.querySelectorAll('a[href]')) {
      if (!/^(下一[页頁节節]|下[页頁])\s*[>›»]?$/.test(textOf(a))) continue;
      const h = a.getAttribute('href');
      if (!h || /^(javascript|#)/i.test(h)) continue;
      try { const u = new URL(h, cur).href; if (isNextPage(first, pageNo, u)) return u; } catch (e) { /* skip */ }
    }
    return null;
  }

  function autoBest(doc, minLen) {
    let best = null, score = 0;
    doc.querySelectorAll('div,article,section,main,td').forEach((el) => {
      let own = 0;
      el.childNodes.forEach((n) => {
        if (n.nodeType === 3) own += n.textContent.trim().length;
        else if (n.nodeType === 1 && /^(P|SPAN|FONT)$/.test(n.tagName)) own += n.textContent.trim().length;
      });
      if (own > score) { score = own; best = el; }
    });
    return best && score >= minLen ? { el: best, score, sel: 'auto:' + best.tagName.toLowerCase() + (best.id ? '#' + best.id : '') + (best.className ? '.' + String(best.className).trim().split(/\s+/).join('.') : '') } : null;
  }

  function pickContainer(doc, minLen) {
    minLen = minLen || 80;
    doc.querySelectorAll('script,style,noscript,iframe,nav,header,footer,form,button,select,ins,.ad,.ads,.adsbygoogle').forEach((e) => e.remove());
    let known = null;
    for (const s of CONTENT_SELS) {
      const el = doc.querySelector(s);
      if (el) { const len = el.textContent.trim().length; if (len > minLen) { known = { el, sel: s, len }; break; } }
    }
    const auto = autoBest(doc, Math.min(80, minLen));
    if (known && (!auto || known.len >= auto.score * 0.6)) return known;
    return auto || known;
  }

  function linesOf(el) {
    const structured = !!el.querySelector('p,br');
    const out = [];
    let cur = '';
    const flush = () => { const t = cur.replace(/ /g, ' ').trim(); if (t) out.push(t); cur = ''; };
    (function walk(n) {
      n.childNodes.forEach((c) => {
        if (c.nodeType === 3) {
          if (structured) cur += c.textContent.replace(/\s*\n\s*/g, '');
          else c.textContent.split(/\r?\n/).forEach((p, i) => { if (i) flush(); cur += p; });
        } else if (c.nodeType === 1) {
          if (c.tagName === 'BR') flush();
          else if (/^(P|DIV|H[1-6]|LI|SECTION|ARTICLE|BLOCKQUOTE|TR)$/.test(c.tagName)) { flush(); walk(c); flush(); }
          else walk(c);
        }
      });
    })(el);
    flush();
    return out;
  }

  function cleanLines(lines, title, dropped) {
    const out = [];
    const bare = cleanTitle(title);
    const T = st.meta && st.meta.title && st.meta.title.length >= 4 ? st.meta.title : '';
    const TOK = '\u0001';
    const PROMO = /《|》|https?:|www\.|阅读|推荐|收藏|作品|新作|书籍|等你|首发|安利|口碑|好评|免费|追更|书迷|APP|更新|入口|章节|专访/;
    const isAd = (x) => st.ad.test(x) || (x.includes(TOK) && PROMO.test(x));
    lines = lines.map((x) => x.replace(ZW, '').trim()).filter((x) => x && !UI_JUNK.test(x));
    const ri = lines.findIndex((x, k) => REC.test(x) && k > lines.length * 0.5);
    if (ri >= 0) { dropped.push('[recommend] ' + lines.slice(ri, ri + 3).join(' ').slice(0, 40)); lines = lines.slice(0, ri); }
    const cut = lines.findIndex((x, k) => /^[*＊※]+$/.test(x.replace(ZW, '').trim()) && k >= lines.length - 8);
    if (cut >= 0) { dropped.push('[author-note] ' + lines.slice(cut).join(' ').slice(0, 60)); lines = lines.slice(0, cut); }
    for (let l of lines) {
      l = l.replace(ZW, '').trim();
      if (!l) continue;
      if (META.test(l)) { dropped.push(l.slice(0, 30)); continue; }
      if (NAV_LINE.test(l)) { dropped.push(l); continue; }
      if (!out.length && l.length < 60 && (l === title || l === bare || (bare.length >= 2 && (l.includes(bare) || bare.includes(l))))) { dropped.push(l); continue; }
      l = l.replace(URL_LEAD, '').replace(URL_BARE, '').replace(/([，,、；;])[，,、；;]+/g, '$1').trim();
      if (!l) { dropped.push('[url-only]'); continue; }
      const hasT = !!T && l.includes(T);
      if (hasT) l = l.split(T).join(TOK);
      if (isAd(l)) {
        dropped.push(l.slice(0, 50).split(TOK).join('<T>'));
        const sents = l.match(/[^。！？!?]+[。！？!?”」]*/g) || [l];
        const keep = [];
        sents.forEach((sn, si) => {
          if (!isAd(sn)) { keep.push(sn); return; }
          const clauses = sn.split(/(?<=[，,、；;])/);
          const bad = clauses.findIndex((c) => isAd(c));
          const pre = clauses.slice(0, Math.max(0, bad)).join('');
          const realAfter = sents.slice(si + 1).some((x) => !isAd(x));
          if (pre.length >= 4 && (si > 0 || realAfter)) keep.push(pre);
        });
        l = keep.join('').trim();
        if (!l) continue;
      }
      if (hasT) l = l.split(TOK).join(T);
      out.push(l);
    }
    return out;
  }

  function titleFromDoc(doc) {
    const h = doc.querySelector('h1');
    const t = h ? textOf(h) : '';
    if (t && t.length < 60) return t;
    return ((doc.title || '').split(/[_\-|—]/)[0] || '').trim();
  }

  async function downloadChapter(ch) {
    const first = ch.url;
    let url = first, pages = 0, lines = [], declared = null, sel = '', mode = '', gotTitle = '';
    const dropped = [], seen = new Set();
    while (url && pages < 40 && !seen.has(url)) {
      seen.add(url);
      let { html, mode: m } = await loadHtml(url);
      let doc = parseHtml(html);
      let nxt = nextPageOf(doc, first, url, pages + 1);
      const dm = doc.body && /(?:本章|章节)?字数[：:]?\s*(\d+)/.exec(doc.body.textContent);
      let ttl = titleFromDoc(doc);
      let box = pickContainer(parseHtml(html), pages ? 20 : 80);
      if (pages && !box) break;
      if (!pages && (!box || box.el.textContent.trim().length < 80)) {
        html = await ifrQueue(() => viaIframe(url));
        m = 'iframe';
        doc = parseHtml(html);
        nxt = nextPageOf(doc, first, url, pages + 1);
        ttl = titleFromDoc(doc) || ttl;
        box = pickContainer(parseHtml(html));
      }
      if (!box) throw new Error('ไม่พบส่วนเนื้อหา');
      if (!pages) { declared = dm ? +dm[1] : null; sel = box.sel; mode = m; gotTitle = ttl; }
      const rawLines = linesOf(box.el);
      if (!st.meta.author || st.meta.author === '未知作者') {
        const am = /作者[“"]?([\u4e00-\u9fff]{2,8})[”"]?(?:亲推|最新作品|推荐阅读|说[：:])/.exec(rawLines.join('')) || /大神([\u4e00-\u9fff]{2,8})携新作/.exec(rawLines.join('')) || /([\u4e00-\u9fff]{2,8})笔下的世界/.exec(rawLines.join(''));
        if (am) st.meta.author = am[1];
      }
      lines = lines.concat(cleanLines(rawLines, ch.title || gotTitle, dropped));
      pages++;
      url = nxt;
    }
    const chars = lines.join('').length;
    if (chars < 200) throw new Error('เนื้อหาสั้นผิดปกติ (' + chars + ')');
    return { lines, pages, chars, declared, sel, mode, dropped, title: gotTitle };
  }

  async function runBatch(idxs, ui) {
    let next = 0, done = 0;
    const T0 = Date.now();
    st.limit = st.workers;
    st.stat.okStreak = 0;
    const worker = async (id) => {
      for (;;) {
        while (id >= st.limit && next < idxs.length) await sleep(500);
        const k = next++;
        if (k >= idxs.length) return;
        const i = idxs[k];
        const t0 = Date.now();
        for (let a = 0; a < 4; a++) {
          try {
            const r = await downloadChapter(st.chapters[i]);
            st.stat.n++; st.stat.ms += Date.now() - t0;
            if (++st.stat.okStreak >= 8 && st.limit < st.workers) { st.limit++; st.stat.okStreak = 0; }
            st.results[i] = r;
            st.failed.delete(i);
            idbSet(st.chapters[i].url, Object.assign({ v: VERSION }, r));
            break;
          } catch (e) { st.errors[i] = String(e.message || e); if (a === 3) st.failed.add(i); else await sleep(1000 * 2 ** a); }
        }
        done++;
        const el = (Date.now() - T0) / 1000, left = Math.round(((idxs.length - done) * el / done) / 60);
        ui(done + '/' + idxs.length + ' | ล้ม ' + st.failed.size + ' | ขนาน ' + Math.min(st.limit, st.workers) + '/' + st.workers +
          ' | เฉลี่ย ' + (st.stat.n ? (st.stat.ms / st.stat.n / 1000).toFixed(1) : '-') + ' วิ/ตอน | เหลือ ~' + left + ' นาที | 429:' + st.stat.p429 + ' 403:' + st.stat.p403 + ' iframe:' + st.stat.iframe);
        if (!document.hidden) await sleep(30 + Math.random() * 120);
      }
    };
    await Promise.all(Array.from({ length: st.workers }, (_, id) => worker(id)));
  }

  async function restoreCache(ui) {
    let n = 0;
    for (let i = 0; i < st.chapters.length; i++) {
      if (st.results[i]) continue;
      const c = await idbGet(st.chapters[i].url);
      if (c && c.v === VERSION && c.lines && c.lines.length) { st.results[i] = c; n++; }
    }
    st.restored = n;
    if (n) ui('กู้คืน ' + n + ' ตอนจากแคชในเครื่อง (โหลดต่อจากที่ค้าง)');
  }

  // ---------- output ----------
  function headingTitle(i) {
    const ch = st.chapters[i], r = st.results[i];
    return cleanTitle(ch.title || (r && r.title) || '');
  }
  const NUMLEAD = /^[0-9０-９]|^[一二三四五六七八九十百零〇]{1,4}\s*[、．.:：]|^第\s*[0-9０-９一二三四五六七八九十百千零〇两]+\s*[章回节節话話集]/;
  function assemble(idxs) {
    const out = [st.meta.title, '作者：' + st.meta.author, ''];
    (idxs || st.chapters.map((_, i) => i)).forEach((i) => {
      const r = st.results[i];
      out.push('第' + (i + 1) + '章 ' + headingTitle(i), '');
      if (r) r.lines.forEach((l) => out.push(NUMLEAD.test(l) ? '・' + l : l));
      else out.push('【โหลดไม่สำเร็จ】');
      out.push('', SEP, '');
    });
    return out.join('\n');
  }

  function report(idxs) {
    const t = st.toc, o = ['=== REPORT ===', 'host=' + location.hostname + ' | ' + st.meta.title + ' | ' + st.meta.author,
      'TOC: count=' + t.count + ' hint=' + t.hint + ' pages=' + t.pages + ' reversed=' + t.reversed + ' filled=' + t.filled + ' paging=' + t.paging + ' dbg=' + JSON.stringify(t.dbg) + ' src=' + t.src + ' key=' + t.key + ' box=' + t.box];
    idxs.forEach((i) => {
      const r = st.results[i], ch = st.chapters[i];
      if (!r) { o.push('#' + i + ' ' + ch.title + ' FAIL: ' + st.errors[i]); return; }
      const j = r.lines.join('');
      o.push('#' + i + ' ' + ch.title + ' url=' + ch.url + ' mode=' + r.mode + ' pages=' + r.pages + ' chars=' + r.chars + ' declared=' + r.declared +
        ' sel=' + r.sel + ' head=' + JSON.stringify(j.slice(0, 30)) + ' tail=' + JSON.stringify(j.slice(-30)) +
        ' dropped=' + JSON.stringify(r.dropped.slice(0, 6).map((x) => x.slice(0, 40))));
    });
    return o.join('\n');
  }

  function saveText(name, text) {
    if (TEST) { window.__NOVEL_OUT = { name, text }; return; }
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 5000);
  }
  const safeName = () => (st.meta.title + '_' + location.hostname.replace(/^www\./, '')).replace(/[\\/:*?"<>|]/g, '_');

  async function runTest(ui) {
    if (!st.chapters.length && !(await scan(ui))) return;
    const n = st.chapters.length;
    const idxs = [...new Set([0, Math.min(1, n - 1), Math.floor(n / 2), n - 1])];
    await runBatch(idxs, ui);
    saveText(safeName() + '_test.txt', report(idxs) + '\n\n' + assemble(idxs));
    ui('ทดสอบเสร็จ: บันทึกไฟล์ _test.txt แล้ว ส่งไฟล์นั้นให้ผู้ช่วยตรวจ');
  }

  async function runAll(ui) {
    if (!st.chapters.length && !(await scan(ui))) return;
    let lock = null;
    const getLock = async () => { try { lock = await navigator.wakeLock.request('screen'); } catch (e) { /* optional */ } };
    await getLock();
    const onVis = () => { if (!document.hidden) getLock(); };
    document.addEventListener('visibilitychange', onVis);
    await restoreCache(ui);
    await runBatch(st.chapters.map((_, i) => i).filter((i) => !st.results[i]), ui);
    document.removeEventListener('visibilitychange', onVis);
    if (lock) try { await lock.release(); } catch (e) { /* ignore */ }
    saveText(safeName() + '.txt', assemble());
    ui(st.failed.size ? 'เสร็จ แต่ล้มเหลว ' + st.failed.size + ' ตอน กด "ลองตอนที่ล้มซ้ำ"' : 'เสร็จครบทุกตอน บันทึกไฟล์แล้ว');
  }

  // ---------- UI ----------
  let panel = null;
  function mountUi() {
    if (panel) { panel.style.display = panel.style.display === 'none' ? 'block' : 'none'; return; }
    panel = document.createElement('div');
    panel.setAttribute('translate', 'no');
    panel.style.cssText = 'position:fixed;left:8px;right:8px;bottom:8px;z-index:2147483647;background:#fff;border:2px solid #c2185b;border-radius:10px;padding:8px;font:14px sans-serif;color:#222;box-shadow:0 2px 12px rgba(0,0,0,.35)';
    const msg = document.createElement('div');
    msg.textContent = 'พร้อมแล้ว: ผ่านด่านตรวจและปิดการแปลหน้าเว็บก่อน แล้วกดสแกน (ระหว่างโหลดให้เปิดจอและอยู่ในเบราว์เซอร์)';
    msg.style.cssText = 'margin-bottom:6px;word-break:break-all';
    panel.appendChild(msg);
    const ui = (s) => { msg.textContent = s; };
    const mk = (label, fn) => {
      const b = document.createElement('button');
      b.textContent = label;
      b.style.cssText = 'margin:2px;padding:8px 10px;border:0;border-radius:6px;background:#c2185b;color:#fff;font-size:14px';
      b.onclick = async () => {
        if (st.busy) return;
        st.busy = true;
        try { await fn(); } catch (e) { ui('ผิดพลาด: ' + (e.message || e)); }
        st.busy = false;
      };
      panel.appendChild(b);
    };
    mk('สแกนสารบัญ', () => scan(ui));
    mk('ทดสอบ 4 ตอน', () => runTest(ui));
    mk('โหลดทั้งเรื่อง', () => runAll(ui));
    mk('ลองตอนที่ล้มซ้ำ', () => runAll(ui));
    mk('กลับลำดับ', async () => { st.chapters.reverse(); st.chapters.forEach((c, i) => { c.i = i; }); st.results.reverse(); ui('กลับลำดับแล้ว แรก: ' + (st.chapters[0].title || st.chapters[0].url).slice(0, 20)); });
    const spd = document.createElement('button');
    const speeds = [3, 6, 10, 16];
    const label = () => 'ความเร็ว: ' + st.workers;
    spd.textContent = label();
    spd.style.cssText = 'margin:2px;padding:8px 10px;border:0;border-radius:6px;background:#455a64;color:#fff;font-size:14px';
    spd.onclick = () => { st.workers = speeds[(speeds.indexOf(st.workers) + 1) % speeds.length]; spd.textContent = label(); };
    panel.appendChild(spd);
    mk('ล้างแคช', async () => { await idbClear(); st.results = new Array(st.chapters.length).fill(null); ui('ล้างแคชแล้ว'); });
    mk('บันทึกไฟล์ตอนนี้', async () => { saveText(safeName() + '_partial.txt', assemble()); ui('บันทึกไฟล์บางส่วนแล้ว'); });
    mk('ปิด', async () => { panel.style.display = 'none'; });
    document.body.appendChild(panel);
  }

  function maybeShowButton() {
    const d = detect(document, location.href);
    if (!d || d.items.length < 20 || document.getElementById('__novel_btn')) return;
    const b = document.createElement('button');
    b.id = '__novel_btn';
    b.textContent = '📥';
    b.setAttribute('translate', 'no');
    b.style.cssText = 'position:fixed;right:10px;bottom:70px;z-index:2147483646;width:44px;height:44px;border-radius:22px;border:0;background:#c2185b;color:#fff;font-size:20px;opacity:.85';
    b.onclick = mountUi;
    document.body.appendChild(b);
  }

  if (TEST) window.__NOVEL = { scan, runTest, runAll, st, assemble, downloadChapter, detect, fetchText, loadHtml, pickContainer, linesOf, cleanLines, parseHtml };
  else {
    if (typeof GM_registerMenuCommand === 'function') GM_registerMenuCommand('เปิดแผงโหลดนิยาย', mountUi);
    setTimeout(maybeShowButton, 1500);
    setTimeout(maybeShowButton, 5000);
  }
})();
