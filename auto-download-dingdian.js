/* ===== Auto Novel Downloader — วางใน Console แล้วโหลดเลย =====
   เว็บ: dingdianzww.org/52507/
   โหลดอัตโนมัติ ไม่ต้องกดอะไร → เสร็จแล้วดาวน์โหลด .txt ให้เอง
   ================================================================ */

(async function () {
  'use strict';

  // ─── ตั้งค่า ──────────────────────────────────────────────────
  const START_CH   = 1;      // เริ่มจากตอนที่
  const MAX_CH     = 9999;   // โหลดสูงสุดกี่ตอน
  const DELAY      = 200;    // หน่วง ms ระหว่างตอน
  const RETRY_WAIT = 3000;   // หน่วง ms เมื่อ error
  // ──────────────────────────────────────────────────────────────

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const RATELIMIT = /访问过于频繁|检测到异常请求|请稍后再试|too many requests|rate.?limit/i;
  const BLOCK     = /Just a moment|安全验证|人机验证|Verify you are human|Access Denied/i;
  const NEXT_RE   = /下一[章节回篇]|next\s*chapter/i;
  const JUNK_RE   = /当前位置|上一章|下一章|回目录|©\s*20\d\d|document\.domain|GoogleAnalytics|function\(i,s,o|ga\("create|\(function\(/i;

  const SELS = [
    '#content','#chapter-content','#chaptercontent','#chapterContent',
    '.chapter-content','.chaptercontent','.content-chapter',
    '#article','.article-content','#articleBody',
    '#novelContent','.novel-content','#readcontent',
    '.readcontent','#readContent','.read-content',
    '#txt','.txt','#text','.text-content',
    '#booktext','.book-text','#bookContent',
    '.entry-content','.post-content','.page-content',
    '#mainContent','.main-content','article',
  ];

  function clean(s) {
    return (s || '').replace(/ /g, ' ').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
  }

  function isJunk(s) { return JUNK_RE.test(s); }

  function scoreEl(el) {
    const raw = (el.textContent || '').trim();
    if (raw.length < 50) return 0;
    const lines = raw.split(/\n+/).map(s => s.trim()).filter(s => s.length > 1);
    if (!lines.length) return 0;
    const junk = lines.filter(s => isJunk(s)).length;
    return raw.length * (1 - (junk / lines.length) * 2);
  }

  function findContent(doc) {
    let best = null, bestS = 0;
    for (const sel of SELS) {
      const el = doc.querySelector(sel);
      if (!el) continue;
      const s = scoreEl(el);
      if (s > bestS) { bestS = s; best = el; }
    }
    if (best && bestS > 200) return best;
    doc.querySelectorAll('div,section,article').forEach(el => {
      const s = scoreEl(el);
      if (s > bestS) { bestS = s; best = el; }
    });
    return best;
  }

  function getParas(box) {
    const ps = [...box.querySelectorAll('p')]
      .map(p => clean(p.textContent)).filter(s => s.length > 1 && !isJunk(s));
    if (ps.length >= 3) return ps;
    const tmp = box.ownerDocument.createElement('div');
    tmp.innerHTML = (box.innerHTML || '').replace(/<br\s*\/?>/gi, '\n');
    const lines = clean(tmp.textContent).split(/\n+/).map(s => s.trim()).filter(s => s.length > 2 && !isJunk(s));
    return lines;
  }

  function findNext(doc, baseUrl) {
    for (const a of doc.querySelectorAll('a')) {
      const t = clean(a.textContent);
      const href = a.getAttribute('href');
      if (!href || href === '#') continue;
      if (NEXT_RE.test(t)) return new URL(href, baseUrl).href;
    }
    return null;
  }

  async function fetchPage(url) {
    const r = await fetch(url, { credentials: 'include', cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const html = await r.text();
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const base = doc.createElement('base'); base.href = url; doc.head.prepend(base);
    const body = doc.body?.innerText || '';
    if (RATELIMIT.test(doc.title) || RATELIMIT.test(body.slice(0, 300))) throw new Error('rate-limited');
    if (BLOCK.test(doc.title)) throw new Error('blocked');
    doc.querySelectorAll('script,style,noscript,nav,header,footer,aside,iframe').forEach(e => e.remove());
    return doc;
  }

  // ─── Progress bar UI (เล็กมาก) ────────────────────────────────
  const bar = document.createElement('div');
  bar.style.cssText = 'position:fixed;top:0;left:0;width:100%;z-index:2147483647;font:bold 14px sans-serif;background:#FF0080;color:#fff;padding:8px 14px;text-align:center;box-shadow:0 2px 12px rgba(255,0,128,.5);';
  bar.textContent = 'กำลังเริ่มโหลด…';
  document.body.appendChild(bar);

  function status(t) { bar.textContent = t; console.log(t); }

  // ─── สแกนสารบัญก่อน ────────────────────────────────────────────
  let chapters = [];
  const catalogUrl = location.href.replace(/\/$/, '') + '/';

  status('กำลังสแกนสารบัญ…');
  try {
    const doc = await fetchPage(catalogUrl);
    const links = [...doc.querySelectorAll('a[href]')].filter(a => {
      const h = a.getAttribute('href') || '';
      return /\/\d+\.html$/.test(h) || /\/\d+\/$/.test(h);
    });
    const seen = new Set();
    for (const a of links) {
      const href = new URL(a.getAttribute('href'), catalogUrl).href;
      if (seen.has(href)) continue; seen.add(href);
      const t = clean(a.textContent);
      chapters.push({ url: href, title: t || `ตอนที่ ${chapters.length + 1}` });
    }
  } catch (e) {
    status('สแกนสารบัญไม่ได้: ' + e.message);
  }

  // ─── ดึงชื่อเรื่อง ─────────────────────────────────────────────
  const titleEl = document.querySelector('h1,h2,.title,#title,.bookTitle,.book-title');
  const novelName = clean(titleEl?.textContent || document.title.replace(/[-_|–—].*$/, '').trim()) || 'novel';

  const results = [];
  let ok = 0, fail = 0;

  // ─── Mode A: มีสารบัญ → โหลดทีละตอน ──────────────────────────
  if (chapters.length > 0) {
    const todo = chapters.slice(START_CH - 1, START_CH - 1 + MAX_CH);
    status(`พบ ${chapters.length} ตอน — เริ่มโหลด ${todo.length} ตอน…`);

    for (let i = 0; i < todo.length; i++) {
      const ch = todo[i];
      status(`โหลด ${i + 1}/${todo.length} — ${ch.title}`);
      let retries = 0;
      while (retries <= 3) {
        try {
          const doc = await fetchPage(ch.url);
          const box = findContent(doc);
          const paras = box ? getParas(box) : [];
          const title = clean(doc.querySelector('h1,h2,.chapter-title,.title')?.textContent || ch.title);
          results.push(`\n\n${title}\n\n` + paras.join('\n\n'));
          ok++;
          break;
        } catch (e) {
          retries++;
          if (RATELIMIT.test(e.message) && retries <= 3) {
            const w = 5000 * retries;
            status(`⚠ rate-limit — หยุด ${w / 1000}s…`);
            await sleep(w);
          } else {
            results.push(`\n\n${ch.title}\n\n[โหลดไม่ได้: ${e.message}]`);
            fail++;
            break;
          }
        }
      }
      await sleep(DELAY);
    }

  // ─── Mode B: ไม่มีสารบัญ → ไล่ลิงก์ "下一章" ──────────────────
  } else {
    status('ไม่มีสารบัญ — ลองไล่ลิงก์ตอนต่อไป…');
    let url = location.href;
    for (let i = 0; i < MAX_CH; i++) {
      status(`โหลดตอนที่ ${START_CH + i}…`);
      try {
        const doc = await fetchPage(url);
        const box = findContent(doc);
        const paras = box ? getParas(box) : [];
        const title = clean(doc.querySelector('h1,h2,.chapter-title,.title')?.textContent || `ตอนที่ ${START_CH + i}`);
        results.push(`\n\n${title}\n\n` + paras.join('\n\n'));
        ok++;
        const next = findNext(doc, url);
        if (!next) { status('ไม่พบลิงก์ตอนต่อไป — จบ'); break; }
        url = next;
        await sleep(DELAY);
      } catch (e) {
        if (RATELIMIT.test(e.message)) {
          status('⚠ rate-limit — หยุด 8s…');
          await sleep(8000);
          i--;
        } else {
          results.push(`\n\nตอนที่ ${START_CH + i}\n\n[error: ${e.message}]`);
          fail++;
          await sleep(RETRY_WAIT);
        }
      }
    }
  }

  // ─── เสร็จ → ดาวน์โหลด .txt อัตโนมัติ ─────────────────────────
  const text = '﻿' + novelName + '\n\n' + results.join('\n');
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = novelName.replace(/[\\/:*?"<>|]/g, '_') + '.txt';
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);

  status(`✅ เสร็จ! ได้ ${ok} ตอน (ผิดพลาด ${fail}) — ไฟล์ ${a.download} ดาวน์โหลดแล้ว`);
  bar.style.background = '#2ecc40';

  // เสียงเตือน
  try {
    const ctx = new AudioContext();
    const beep = (f, s, d) => { const o = ctx.createOscillator(); const g = ctx.createGain(); o.connect(g); g.connect(ctx.destination); o.frequency.value = f; g.gain.setValueAtTime(0.8, ctx.currentTime + s); g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + s + d); o.start(ctx.currentTime + s); o.stop(ctx.currentTime + s + d + 0.05); };
    beep(880, 0, .18); beep(1100, .2, .18); beep(1320, .4, .3);
    setTimeout(() => ctx.close(), 1200);
  } catch (_) {}

})();
