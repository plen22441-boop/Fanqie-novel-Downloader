// ==UserScript==
// @name         Rose Smart Downloader
// @namespace    fanfan-novel-downloader
// @version      3.2.0
// @description  สแกนสารบัญ ดาวน์โหลดทุกตอนเป็น TXT พร้อมรายงาน QC และ Debug (ใช้ได้หลายเว็บ)
// @author       Rose
// @match        *://*/*
// @grant        none
// @run-at       document-idle
// ==/UserScript==
// เคล็ดลับ: ถ้าไม่อยากให้ปุ่ม 📖 โผล่ทุกเว็บ ให้เปลี่ยน @match ด้านบนเป็นเฉพาะเว็บนิยายที่ใช้
// เช่น  // @match  https://www.example-novel.com/*

(function () {
  'use strict';
  if (window.top !== window.self) return;
  if (window.__roseSmart) { window.__roseSmart.open(); return; }

  const ID = 'rose-smart-v32';
  const KEY = 'rose-smart:' + location.hostname;
  const DBG = 'rose-smart-debug:' + location.hostname;

  const SELECTORS = ['#content', '#chaptercontent', '#chapterContent', '.content', '.chapter-content', '.chapterContent',
    '.read-content', '.reader-content', '.article-content', '.book-content', '.bookcontent', '.novelcontent',
    '.txt', '.txtnav', 'article', 'main'];
  // เฉพาะ "บรรทัดสั้น" ที่ตรงเท่านั้นถึงจะถูกตัดทิ้ง เพื่อไม่ให้เนื้อเรื่องที่บังเอิญมีคำว่า 下载/评论 หายไป
  const NOISE = /(上一章|下一章|上一页|下一页|返回目录|返回书页|加入书架|推荐票|月票|最新网址|手机阅读|请收藏|本章未完|点击下一页|章节错误|章节报错|求月票|求推荐|书友)/;
  const WEAK_NOISE = /^[\s[【(（]*(目录|广告|评论|报错|纠错|下载\s*app|app\s*下载)[\s\]】)）]*$/i;
  const CN = { 零: 0, 〇: 0, 一: 1, 二: 2, 两: 2, 兩: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9 };

  const S = {
    threads: 3, retries: 3, minChars: 500, delay: 300, pageSize: 100,
    title: '', pages: [], chapters: [], results: new Map(), missing: [], dups: 0,
    running: false, stop: false, memory: load(KEY, {})
  };
  Object.assign(S, S.memory.lastSettings || {});

  const events = [];
  let saveTimer = null;

  // ---------- helpers ----------
  function load(k, d) { try { return JSON.parse(localStorage.getItem(k) || '') || d; } catch (e) { return d; } }
  function save(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* storage full/blocked */ } }
  function event(type, msg) {
    events.push({ time: new Date().toLocaleString(), type, message: String(msg && msg.message ? msg.message : msg), url: location.href });
    if (events.length > 200) events.shift();
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => save(DBG, debugObj()), 1000);
  }
  function clean(t) { return String(t || '').replace(/ /g, ' ').replace(/\r/g, '').replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim(); }
  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
  function safe(n) { return clean(n).replace(/[\\/:*?"<>|]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 80) || 'Rose Novel'; }
  function normUrl(u) { return String(u).split('#')[0].replace(/\/$/, ''); }
  function results() { return [...S.results.values()]; }
  function failedList() { return results().filter(r => !r.ok); }
  function shortList() { return results().filter(r => r.ok && r.short); }

  window.addEventListener('error', e => event('JS_ERROR', (e.message || '') + ' at ' + (e.filename || '') + ':' + (e.lineno || '')));
  window.addEventListener('unhandledrejection', e => event('PROMISE_ERROR', e.reason || 'Unhandled promise rejection'));

  function cnNum(raw) {
    const t = String(raw || '').replace(/[第章节回集卷]/g, '').trim();
    if (/^\d+$/.test(t)) return Number(t);
    const unit = { 十: 10, 百: 100, 千: 1000, 万: 10000 };
    let total = 0, sec = 0, num = 0;
    for (const ch of t) {
      if (CN[ch] != null) num = CN[ch];
      else if (unit[ch]) {
        if (unit[ch] === 10000) { sec = (sec + num) * 10000; total += sec; sec = 0; }
        else sec += (num || 1) * unit[ch];
        num = 0;
      }
    }
    return total + sec + num || null;
  }
  function chapNum(text, url) {
    const s = (text || '') + ' ' + (url || '');
    let m = s.match(/第\s*([0-9]{1,5})\s*[章节回集卷]/);
    if (m) return Number(m[1]);
    m = s.match(/第\s*([零〇一二两兩三四五六七八九十百千万]{1,12})\s*[章节回集卷]/);
    return m ? cnNum(m[1]) : null;
  }
  function bookTitle(doc) {
    for (const q of ['h1', '.booktitle h1', '.book-info h1', '.info h1', '.bookname h1']) {
      const t = clean(doc.querySelector(q)?.textContent);
      if (t && t.length <= 80) return t;
    }
    return clean((doc.title || '').split(/[(_\-—|]/)[0]).slice(0, 80) || 'Rose Novel';
  }

  // ---------- catalog ----------
  function isChap(a, base, pageSet) {
    const text = clean(a.textContent || a.title || ''), href = a.getAttribute('href') || '';
    if (!href || href.startsWith('javascript:') || href.startsWith('#')) return false;
    if (!text || text.length > 90) return false;
    if (/上一页|下一页|首页|尾页|目录|书架|登录|注册|推荐|排行榜|作者|返回/.test(text)) return false;
    if (/^\d{1,4}$/.test(text) || /^\d+\s*[-~—]\s*\d+\s*章?$/.test(text)) return false; // ลิงก์เลขหน้าสารบัญ
    let u;
    try { u = new URL(href, base).href; } catch (e) { return false; }
    if (pageSet.has(normUrl(u))) return false;
    return /第\s*([0-9零〇一二两兩三四五六七八九十百千万]+)\s*[章节回集卷]/.test(text) ||
      (/\/(read|chapter|chapters|book|txt|index)\//i.test(u) && /\/\d+\.html\/?$/i.test(u));
  }
  function links(doc, base, pageSet) {
    const out = [];
    [...doc.querySelectorAll('a')].forEach((a, i) => {
      if (!isChap(a, base, pageSet)) return;
      const ti = clean(a.textContent || a.title || ''), url = new URL(a.getAttribute('href'), base).href;
      out.push({ order: i, num: chapNum(ti, url), title: ti, url });
    });
    return out;
  }
  // รักษาลำดับตามหน้าเว็บ (รองรับหลายเล่มที่เลขตอนเริ่มใหม่) / กลับด้านถ้าเรียงใหม่→เก่า / เรียงตามเลขตอนเมื่อลำดับเพี้ยนมาก
  function orderChapters(list) {
    const seen = new Map();
    let dups = 0;
    list.forEach(x => {
      const k = normUrl(x.url);
      if (seen.has(k)) { dups++; seen.delete(k); } // เก็บตำแหน่งสุดท้าย กันบล็อก "ตอนล่าสุด" ด้านบนสารบัญดึงลำดับเพี้ยน
      seen.set(k, x);
    });
    S.dups = dups;
    let arr = [...seen.values()];
    const count = a => {
      const n = a.filter(x => x.num != null);
      let up = 0, down = 0;
      for (let i = 1; i < n.length; i++) { if (n[i].num > n[i - 1].num) up++; else if (n[i].num < n[i - 1].num) down++; }
      return { up, down, total: Math.max(1, n.length - 1) };
    };
    let c = count(arr);
    if (c.down > c.up) { arr.reverse(); c = count(arr); }
    if (c.down / c.total > 0.02) {
      let prev = 0;
      arr.forEach(x => { x.key = x.num != null ? x.num : prev + 0.001; prev = x.key; });
      arr.sort((a, b) => (a.key - b.key) || (a.order - b.order));
    }
    return arr;
  }
  function totalChapters(doc) {
    const t = clean(doc.body?.innerText || '');
    for (const r of [/共\s*([0-9]{1,5})\s*章/, /共\s*([0-9]{1,5})\s*节/, /章节目录[\s\S]{0,40}?共\s*([0-9]{1,5})/]) {
      const m = t.match(r);
      if (m) return Number(m[1]);
    }
    return null;
  }
  function catalogPages(doc, base) {
    const map = new Map();
    const add = u => { const k = normUrl(u); if (!map.has(k)) map.set(k, u); };
    const tot = totalChapters(doc);
    add(base);
    doc.querySelectorAll('select option[value], a[href]').forEach(el => {
      const v = el.getAttribute('value') || el.getAttribute('href') || '', tx = clean(el.textContent || '');
      if (!v || v.startsWith('javascript:') || v.startsWith('#')) return;
      if (/\d+\s*[-~—]\s*\d+\s*章/.test(tx) || /\/index\/.+?\/\d+\.html\/?$/i.test(v)) { try { add(new URL(v, base).href); } catch (e) { /* bad href */ } }
    });
    const m = new URL(base).pathname.match(/^(.*\/index\/(?:\d+\/)*\d+\/)(\d+)\.html\/?$/i);
    if (m && tot) {
      for (let p = 1; p <= Math.max(1, Math.ceil(tot / S.pageSize)); p++) {
        const u = new URL(base);
        u.pathname = m[1] + p + '.html/';
        add(u.href);
      }
    }
    const list = [...map.values()];
    const pn = u => Number((u.match(/(\d+)\.html\/?$/) || [])[1]);
    if (list.every(u => !isNaN(pn(u)))) list.sort((a, b) => pn(a) - pn(b));
    return list;
  }

  // ---------- fetching ----------
  async function fetchDoc(url, timeout) {
    const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), timeout || 20000);
    try {
      const r = await fetch(url, { credentials: 'include', cache: 'no-store', signal: ctl.signal, headers: { accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8' } });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const buf = await r.arrayBuffer();
      let cs = ((r.headers.get('content-type') || '').match(/charset=([\w-]+)/i) || [])[1];
      if (!cs) cs = (new TextDecoder('latin1').decode(buf.slice(0, 3000)).match(/<meta[^>]+charset=["']?([\w-]+)/i) || [])[1];
      let html;
      try { html = new TextDecoder(cs || 'utf-8').decode(buf); } catch (e) { html = new TextDecoder('utf-8').decode(buf); }
      if (/cf-browser-verification|Just a moment\.\.\.|challenge-platform/i.test(html.slice(0, 6000))) throw new Error('Blocked by anti-bot page');
      return new DOMParser().parseFromString(html, 'text/html');
    } catch (e) {
      throw e.name === 'AbortError' ? new Error('Timeout') : e;
    } finally { clearTimeout(timer); }
  }

  // ---------- chapter content ----------
  // DOMParser เอกสารไม่มี layout → innerText = textContent ทำให้ <br>/<p> ไม่ขึ้นบรรทัดใหม่ ต้องแทรก \n เอง
  function nodeText(node) {
    const c = node.cloneNode(true);
    c.querySelectorAll('script,style,iframe,ins,nav,header,footer,button,select,noscript,.ad,.ads,.banner').forEach(x => x.remove());
    c.querySelectorAll('br').forEach(b => b.replaceWith('\n'));
    c.querySelectorAll('p,div,li,h1,h2,h3,h4,tr').forEach(b => b.append('\n'));
    return c.textContent;
  }
  function norm(raw) {
    return clean(raw).split('\n').map(clean).filter(x => x && !(x.length <= 40 && NOISE.test(x)) && !WEAK_NOISE.test(x)).join('\n');
  }
  function pickContent(doc) {
    const list = [...new Set(S.memory.bestContentSelector ? [S.memory.bestContentSelector, ...SELECTORS] : SELECTORS)];
    const cands = [];
    for (const q of list) {
      const n = doc.querySelector(q);
      if (!n) continue;
      const text = norm(nodeText(n));
      if (!text) continue;
      const linkLen = [...n.querySelectorAll('a')].reduce((s, a) => s + (a.textContent || '').length, 0);
      const density = linkLen / Math.max(1, (n.textContent || '').length);
      const zh = (text.match(/[一-鿿]/g) || []).length;
      cands.push({ selector: q, text, density, score: zh * (1 - Math.min(0.9, density * 2)) });
    }
    // ใช้ selector แรกที่ "เจาะจง" และเนื้อหาพอ ก่อน (กัน main/article ที่ครอบทั้งหน้ามาชนะ)
    let best = cands.find(c => c.text.length >= S.minChars && c.density < 0.2);
    if (!best && cands.length) best = cands.slice().sort((a, b) => b.score - a.score)[0];
    if (!best) {
      const b = doc.body.cloneNode(true);
      b.querySelectorAll('a').forEach(x => x.remove());
      best = { selector: 'body', text: norm(nodeText(b)) };
    }
    if (best.selector !== 'body' && best.text.length >= S.minChars && S.memory.bestContentSelector !== best.selector) {
      S.memory.bestContentSelector = best.selector;
      save(KEY, S.memory);
    }
    return best;
  }
  // ตอนที่แบ่งหลายหน้า (xxx.html → xxx_2.html) ปุ่ม "下一页" จะชี้ไปหน้าถัดไปของตอนเดียวกัน
  function chapKey(u) { return new URL(u).pathname.replace(/\.html?\/?$/i, '').replace(/[_-]\d+$/, '').replace(/\/$/, ''); }
  function nextPart(doc, cur) {
    for (const a of doc.querySelectorAll('a[href]')) {
      if (!/^(下一页|下一頁|下页)$/.test(clean(a.textContent))) continue;
      try {
        const u = new URL(a.getAttribute('href'), cur).href;
        if (normUrl(u) !== normUrl(cur) && chapKey(u) === chapKey(cur)) return u;
      } catch (e) { /* bad href */ }
    }
    return null;
  }
  async function fetchChapter(url) {
    let doc = await fetchDoc(url), c = pickContent(doc);
    const first = doc, parts = [c.text], seen = new Set([normUrl(url)]);
    let cur = url;
    for (let i = 0; i < 12; i++) {
      const nx = nextPart(doc, cur);
      if (!nx || seen.has(normUrl(nx))) break;
      seen.add(normUrl(nx));
      cur = nx;
      doc = await fetchDoc(nx);
      parts.push(pickContent(doc).text);
    }
    return { doc: first, text: parts.join('\n'), selector: c.selector, parts: parts.length };
  }
  async function one(ch) {
    let last, best = null;
    for (let i = 1; i <= S.retries; i++) {
      try {
        const { doc, text: raw, selector, parts } = await fetchChapter(ch.url);
        const title = ch.title || clean(doc.querySelector('h1')?.textContent) || 'Untitled';
        const lines = raw.split('\n');
        if (lines[0] && lines[0].length < 80 && (title.includes(lines[0]) || lines[0].includes(title))) lines.shift(); // ตัดชื่อตอนซ้ำ
        const text = lines.join('\n');
        const r = { ok: true, num: ch.num, title, url: ch.url, text, chars: text.length, selector, parts, short: text.length < S.minChars };
        if (!r.short) return r;
        if (!best || r.chars > best.chars) best = r;
        last = new Error('Short content ' + r.chars);
      } catch (e) { last = e; }
      if (i < S.retries) await sleep(600 * i);
    }
    return best || { ok: false, num: ch.num, title: ch.title, url: ch.url, error: last ? last.message : 'Unknown error' };
  }

  // ---------- actions ----------
  function analyzeMissing() {
    const nums = S.chapters.map(x => x.num).filter(Boolean), set = new Set(nums);
    S.missing = [];
    if (!nums.length) return;
    for (let i = Math.min(...nums); i <= Math.max(...nums); i++) if (!set.has(i)) S.missing.push(i);
  }
  async function scanAll() {
    if (S.running) return;
    S.running = true; S.stop = false;
    try {
      S.title = bookTitle(document);
      S.pages = catalogPages(document, location.href);
      S.chapters = []; S.results.clear();
      bar(0); paint();
      log('Book: ' + S.title);
      log('Catalog pages: ' + S.pages.length);
      const pageSet = new Set(S.pages.map(normUrl)), all = [];
      for (let i = 0; i < S.pages.length && !S.stop; i++) {
        try {
          const d = normUrl(S.pages[i]) === normUrl(location.href) ? document : await fetchDoc(S.pages[i]);
          const f = links(d, S.pages[i], pageSet);
          f.forEach(x => { x.order += i * 100000; });
          all.push(...f);
          log('Scan page ' + (i + 1) + '/' + S.pages.length + ': ' + f.length);
        } catch (e) { log('Scan page ' + (i + 1) + ' failed: ' + e.message); event('SCAN_FAIL', e.message); }
        bar((i + 1) / S.pages.length * 15);
        await sleep(250);
      }
      S.chapters = orderChapters(all);
      analyzeMissing();
      log('Scan done: ' + S.chapters.length + ' chapters' + (S.missing.length ? ', missing ' + S.missing.length : ''));
      paint();
    } finally { S.running = false; }
  }
  // mode: 'all' = ดาวน์โหลดใหม่ทั้งหมด, 'resume' = ทำต่อ/ลองใหม่เฉพาะตอนที่ยังไม่มี ล้มเหลว หรือสั้นผิดปกติ
  async function downloadAll(mode) {
    if (S.running) return;
    if (!S.chapters.length) await scanAll();
    if (S.running || !S.chapters.length) return;
    S.running = true; S.stop = false;
    try {
      if (mode === 'all') S.results.clear();
      const targets = S.chapters.filter(c => { const r = S.results.get(c.url); return !r || !r.ok || r.short; });
      if (!targets.length) { log('No chapters to download'); return; }
      log((mode === 'all' ? 'Download: ' : 'Resume/Retry: ') + targets.length + ' chapters, threads ' + S.threads);
      let idx = 0, done = 0;
      const workers = Array.from({ length: S.threads }, async () => {
        while (idx < targets.length && !S.stop) {
          const ch = targets[idx++], r = await one(ch);
          S.results.set(ch.url, r);
          if (!r.ok) { log('FAIL ' + (ch.title || ch.url) + ': ' + r.error); event('DOWNLOAD_FAIL', (ch.title || ch.url) + ' | ' + r.error); }
          else if (r.short) { log('SHORT ' + r.title + ': ' + r.chars); event('SHORT_CHAPTER', r.title + ' | ' + r.chars); }
          done++;
          bar(15 + (done / targets.length) * 80);
          paintCounts();
          await sleep(S.delay * (0.5 + Math.random()));
        }
      });
      await Promise.all(workers);
      log(S.stop ? 'Stopped. Saving what we have so far.' : 'Done. TXT + QC JSON downloaded.');
      await makeFiles();
      bar(100);
      paint();
    } finally { S.running = false; }
  }

  // ---------- output ----------
  function qc() {
    const ordered = S.chapters.map(c => S.results.get(c.url)).filter(Boolean), ok = ordered.filter(r => r.ok), fail = ordered.filter(r => !r.ok);
    const nums = ok.map(r => r.num).filter(Boolean), miss = [];
    if (nums.length) {
      const set = new Set(nums);
      for (let i = Math.min(...nums); i <= Math.max(...nums); i++) if (!set.has(i)) miss.push(i);
    }
    return {
      tool: 'Rose Smart Downloader V3.2', host: location.hostname, book: S.title, source: location.href, generatedAt: new Date().toISOString(),
      settings: { threads: S.threads, retries: S.retries, minChars: S.minChars, delay: S.delay },
      catalogPages: S.pages.length, found: S.chapters.length, ok: ok.length, notDownloaded: S.chapters.length - ordered.length, failed: fail.length, missing: miss,
      suspiciousShort: ok.filter(r => r.short).map(r => ({ num: r.num, title: r.title, chars: r.chars, url: r.url })),
      failedItems: fail.map(r => ({ num: r.num, title: r.title, error: r.error, url: r.url })),
      duplicateLinks: S.dups, memory: S.memory, debug: events.slice(-80)
    };
  }
  async function makeFiles() {
    const Q = qc(), ok = S.chapters.map(c => S.results.get(c.url)).filter(r => r && r.ok);
    const report = ['ROSE QC REPORT', 'Tool: Rose Smart Downloader V3.2', 'Book: ' + S.title, 'Source: ' + location.href,
      'Catalog pages: ' + Q.catalogPages, 'Found: ' + Q.found, 'OK: ' + Q.ok, 'Not downloaded: ' + Q.notDownloaded, 'Failed: ' + Q.failed,
      'Missing: ' + (Q.missing.length ? Q.missing.join(', ') : 'none'), 'Suspicious short chapters: ' + Q.suspiciousShort.length,
      'Duplicate links ignored: ' + Q.duplicateLinks,
      Q.failedItems.length ? 'FAILED ITEMS:' : 'FAILED ITEMS: none',
      ...Q.failedItems.map(x => (x.title || x.num || '?') + ' | ' + x.error), '', '==============================', ''].join('\n');
    dl(safe(S.title) + ' - Rose Smart TXT.txt', report + ok.map(r => clean(r.title || ('第' + r.num + '章')) + '\n\n' + r.text).join('\n\n\n'), 'text/plain;charset=utf-8', true);
    await sleep(1200); // มือถือมักบล็อกดาวน์โหลดสองไฟล์ติดกัน
    dl(safe(S.title) + ' - QC Report.json', JSON.stringify(Q, null, 2), 'application/json;charset=utf-8', false);
  }
  function dl(name, text, type, bom) {
    const blob = new Blob(bom ? ['﻿', text] : [text], { type });
    const url = URL.createObjectURL(blob), a = document.createElement('a');
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 4000);
  }

  // ---------- debug ----------
  function debugObj() {
    const p = document.getElementById(ID);
    return {
      tool: 'Rose Smart Downloader Debug 3.2', time: new Date().toISOString(), page: location.href, pageTitle: document.title,
      counts: p ? (p.querySelector('.counts')?.textContent || '') : '', log: p ? (p.querySelector('.log')?.textContent || '') : '',
      state: {
        book: S.title, catalogPages: S.pages.length, found: S.chapters.length, ok: results().filter(r => r.ok).length, missing: S.missing,
        short: shortList().map(r => ({ num: r.num, title: r.title, chars: r.chars, url: r.url })),
        failedItems: failedList().map(r => ({ num: r.num, title: r.title, error: r.error, url: r.url })),
        duplicateLinks: S.dups, memory: S.memory
      },
      events: events.slice(-80)
    };
  }
  async function copyDebug() {
    const text = JSON.stringify(debugObj(), null, 2);
    save(DBG, debugObj());
    try { await navigator.clipboard.writeText(text); alert('Copied debug report. ส่งมาให้ฉันได้เลยค่ะ'); } catch (e) { prompt('Copy this debug report:', text); }
  }
  function downDebug() {
    save(DBG, debugObj());
    dl('Rose_Debug_Report.json', JSON.stringify(debugObj(), null, 2), 'application/json;charset=utf-8', false);
  }

  // ---------- UI ----------
  function bar(v) { const b = document.querySelector('#' + ID + ' .bar span'); if (b) b.style.width = Math.max(0, Math.min(100, v)) + '%'; }
  function log(msg) {
    const box = document.querySelector('#' + ID + ' .log'), line = '[' + new Date().toLocaleTimeString() + '] ' + msg;
    if (box) box.textContent = (line + '\n' + box.textContent).slice(0, 7000);
  }
  function paintCounts() {
    const e = document.querySelector('#' + ID + ' .counts');
    if (e) e.textContent = 'Found: ' + S.chapters.length + ' | OK: ' + results().filter(r => r.ok).length + ' | Failed: ' + failedList().length + ' | Missing: ' + S.missing.length + ' | Short: ' + shortList().length;
  }
  function paint() {
    const t = document.querySelector('#' + ID + ' .title');
    if (t) t.textContent = 'Book: ' + (S.title || bookTitle(document));
    paintCounts();
  }
  function readSettings(p) {
    const n = (sel, lo, hi, d) => Math.max(lo, Math.min(hi, Number(p.querySelector(sel).value || d)));
    S.threads = n('.threads', 1, 8, 3); S.retries = n('.retries', 1, 5, 3); S.minChars = n('.minchars', 100, 3000, 500); S.delay = n('.delay', 0, 5000, 300);
    S.memory.lastSettings = { threads: S.threads, retries: S.retries, minChars: S.minChars, delay: S.delay };
    save(KEY, S.memory);
  }
  function ui() {
    document.getElementById(ID)?.remove();
    document.getElementById(ID + '-style')?.remove();
    document.getElementById(ID + '-fab')?.remove();
    const st = document.createElement('style');
    st.id = ID + '-style';
    st.textContent = `#${ID}{position:fixed;right:12px;bottom:12px;z-index:2147483647;width:min(92vw,460px);background:#fff;color:#111;border:1px solid #cfd8dc;border-radius:10px;box-shadow:0 10px 32px rgba(0,0,0,.22);font:14px/1.45 Arial,sans-serif;overflow:hidden}#${ID} .head{background:#176b80;color:#fff;padding:10px 12px;font-weight:700;display:flex;justify-content:space-between;align-items:center}#${ID} .close{border:0;background:#fff;color:#176b80;border-radius:6px;padding:3px 9px;font-weight:700}#${ID} .body{padding:12px}#${ID} .title{font-weight:700;margin-bottom:4px}#${ID} .counts{margin-bottom:8px}#${ID} .row{display:flex;gap:6px;flex-wrap:wrap;margin:7px 0}#${ID} button{border:1px solid #9aa7ad;background:#f8fbfc;border-radius:6px;padding:7px 9px;color:#111}#${ID} button.primary{background:#176b80;color:#fff;border-color:#176b80}#${ID} label{display:flex;align-items:center;gap:4px;font-weight:700}#${ID} input{width:50px;border:1px solid #cfd8dc;border-radius:5px;padding:5px}#${ID} .bar{height:10px;background:#eef2f3;border-radius:999px;overflow:hidden;margin:9px 0}#${ID} .bar span{display:block;height:100%;width:0;background:#1e88a8;transition:width .2s}#${ID} .log{white-space:pre-wrap;background:#f7f7f7;border:1px solid #ddd;border-radius:8px;min-height:90px;max-height:170px;overflow:auto;padding:8px;font-family:monospace}#${ID}-fab{position:fixed;left:10px;bottom:10px;z-index:2147483646;width:38px;height:38px;border-radius:50%;border:1px solid #176b80;background:#fff;opacity:.55;font-size:18px;padding:0;line-height:1}`;
    document.documentElement.appendChild(st);

    const fab = document.createElement('button');
    fab.id = ID + '-fab'; fab.textContent = '📖'; fab.title = 'Rose Smart Downloader';
    document.body.appendChild(fab);

    const p = document.createElement('div');
    p.id = ID;
    p.style.display = 'none';
    p.innerHTML = `<div class="head"><span>Rose Smart Downloader V3.2</span><button class="close">X</button></div><div class="body"><div class="title"></div><div class="counts">Found: 0 | OK: 0 | Failed: 0 | Missing: 0 | Short: 0</div><div class="row"><label>Threads <input class="threads" type="number" min="1" max="8"></label><label>Retry <input class="retries" type="number" min="1" max="5"></label><label>Min <input class="minchars" type="number" min="100" max="3000"></label><label>Delay <input class="delay" type="number" min="0" max="5000" step="100"></label></div><div class="row"><button class="scan">Scan All Pages</button><button class="download primary">Download All + QC</button><button class="retry">Resume / Retry</button><button class="stop">Stop</button><button class="copy-debug">Copy Debug</button><button class="download-debug">Download Debug</button></div><div class="bar"><span></span></div><div class="log">Ready. Open catalog page, then tap Scan All Pages.</div></div>`;
    document.body.appendChild(p);
    p.querySelector('.title').textContent = 'Book: ' + bookTitle(document);
    p.querySelector('.threads').value = S.threads; p.querySelector('.retries').value = S.retries;
    p.querySelector('.minchars').value = S.minChars; p.querySelector('.delay').value = S.delay;

    const open = () => { p.style.display = 'block'; fab.style.display = 'none'; };
    const close = () => { p.style.display = 'none'; fab.style.display = 'block'; };
    fab.onclick = open;
    p.querySelector('.close').onclick = close;
    p.querySelector('.scan').onclick = () => { readSettings(p); scanAll(); };
    p.querySelector('.download').onclick = () => { readSettings(p); downloadAll('all'); };
    p.querySelector('.retry').onclick = () => { readSettings(p); downloadAll('resume'); };
    p.querySelector('.stop').onclick = () => { S.stop = true; log('Stopping after current chapters...'); };
    p.querySelector('.copy-debug').onclick = copyDebug;
    p.querySelector('.download-debug').onclick = downDebug;
    window.__roseSmart = { open };
    event('READY', 'V3.2 loaded');
  }
  ui();
})();
