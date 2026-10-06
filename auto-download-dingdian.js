/* ===== Auto Novel Downloader v3 — dingdianzww.org =====
   วางใน Console แล้วกด Enter → โหลดเอง → ดาวน์โหลด .txt
   ใช้ iframe แทน fetch เพื่อหลีก 403
   ====================================================== */

(async function () {
  'use strict';

  // ─── ตั้งค่า ────────────────────────────────────────────
  const START_CH = 1;       // เริ่มจากตอนที่
  const MAX_CH   = 520;     // โหลดกี่ตอน
  const DELAY    = 1500;    // หน่วง ms ระหว่างตอน (ช้าหน่อยกัน 403)
  // ────────────────────────────────────────────────────────

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const JUNK = /当前位置|上一章|下一章|回目录|©\s*20\d\d|document\.domain|GoogleAnalytics|function\(i,s,o|ga\("create|\(function\(/i;

  const SELS = [
    '#content','#chapter-content','#chaptercontent','#chapterContent',
    '.chapter-content','.chaptercontent','#article','.article-content',
    '#novelContent','.novel-content','#readcontent','#readContent',
    '#txt','.txt','#text','.text-content','#booktext','.book-text',
    '#bookContent','.entry-content','.post-content','article',
    '#mainContent','.main-content','.page-content',
  ];

  function clean(s) {
    return (s || '').replace(/ /g, ' ').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
  }

  // โหลดหน้าผ่าน iframe (ส่ง cookie + referer เหมือนเปิดเอง)
  function loadPage(url) {
    return new Promise((resolve, reject) => {
      const f = document.createElement('iframe');
      f.style.cssText = 'position:fixed;left:-9999px;top:-9999px;width:1px;height:1px;opacity:0;';
      const timer = setTimeout(() => { f.remove(); reject(new Error('timeout')); }, 20000);
      f.onload = () => {
        clearTimeout(timer);
        try {
          const doc = f.contentDocument || f.contentWindow.document;
          resolve(doc);
        } catch (e) { reject(new Error('cross-origin blocked')); }
        setTimeout(() => f.remove(), 300);
      };
      f.onerror = () => { clearTimeout(timer); f.remove(); reject(new Error('load error')); };
      f.src = url;
      document.body.appendChild(f);
    });
  }

  function scoreEl(el) {
    const raw = (el.textContent || '').trim();
    if (raw.length < 50) return 0;
    const lines = raw.split(/\n+/).map(s => s.trim()).filter(s => s.length > 1);
    if (!lines.length) return 0;
    const junk = lines.filter(s => JUNK.test(s)).length;
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
      .map(p => clean(p.textContent)).filter(s => s.length > 1 && !JUNK.test(s));
    if (ps.length >= 3) return ps;
    const tmp = box.ownerDocument.createElement('div');
    tmp.innerHTML = (box.innerHTML || '').replace(/<br\s*\/?>/gi, '\n');
    return clean(tmp.textContent).split(/\n+/).map(s => s.trim()).filter(s => s.length > 2 && !JUNK.test(s));
  }

  // ─── แถบสถานะ ──────────────────────────────────────────
  const bar = document.createElement('div');
  bar.style.cssText = 'position:fixed;top:0;left:0;width:100%;z-index:2147483647;' +
    'font:bold 13px sans-serif;background:#FF0080;color:#fff;padding:8px 14px;' +
    'text-align:center;box-shadow:0 2px 12px rgba(255,0,128,.5);';
  document.body.appendChild(bar);
  function status(t) { bar.textContent = t; console.log(t); }

  // ─── สแกนสารบัญ ────────────────────────────────────────
  status('กำลังสแกนสารบัญ…');
  let chapters = [];
  try {
    const catUrl = location.href.replace(/\/$/, '') + '/';
    const doc = await loadPage(catUrl);
    const links = [...doc.querySelectorAll('a[href]')].filter(a => {
      const h = a.getAttribute('href') || '';
      return /\/\d+\.html/.test(h) || /\/\d+\/?$/.test(h);
    });
    const seen = new Set();
    for (const a of links) {
      const href = new URL(a.getAttribute('href'), catUrl).href;
      if (seen.has(href)) continue; seen.add(href);
      chapters.push({ url: href, title: clean(a.textContent) || `ตอนที่ ${chapters.length + 1}` });
    }
    status(`พบ ${chapters.length} ตอน`);
  } catch (e) {
    status('สแกนสารบัญไม่ได้: ' + e.message);
  }

  // ─── ชื่อเรื่อง ────────────────────────────────────────
  const titleEl = document.querySelector('h1,h2,.title,#title,.bookTitle,.book-title');
  const novelName = clean(titleEl?.textContent || document.title.replace(/[-_|–—].*$/, '')).trim() || 'novel';

  // ─── โหลดทุกตอน ────────────────────────────────────────
  const results = [];
  let ok = 0, fail = 0;
  const todo = chapters.slice(START_CH - 1, START_CH - 1 + MAX_CH);

  if (!todo.length) {
    status('ไม่พบตอน — ลองเปิดหน้าสารบัญของนิยายก่อน');
    return;
  }

  // บันทึก progress ใน localStorage กัน browser ปิด
  const SAVE_KEY = 'nd-auto-' + location.pathname.replace(/\//g, '-');
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(SAVE_KEY) || '{}'); } catch (_) {}
  const resumeCount = Object.keys(saved).length;
  if (resumeCount > 0) status(`พบ progress เก่า ${resumeCount} ตอน — ดาวน์โหลดต่อ…`);

  for (let i = 0; i < todo.length; i++) {
    const ch = todo[i];

    // ข้ามตอนที่โหลดไว้แล้ว
    if (saved[i] !== undefined) {
      results[i] = saved[i];
      ok++;
      continue;
    }

    status(`โหลด ${i + 1}/${todo.length} — ${ch.title}`);

    let retries = 0;
    while (retries <= 3) {
      try {
        const doc = await loadPage(ch.url);
        // ลบ element ขยะ
        doc.querySelectorAll('script,style,noscript,nav,header,footer,aside,iframe,.ads,.ad').forEach(e => e.remove());
        const box = findContent(doc);
        const paras = box ? getParas(box) : [];
        const title = clean(doc.querySelector('h1,h2,.chapter-title,.title')?.textContent || ch.title);
        const text = `\n\n${title}\n\n` + paras.join('\n\n');
        results[i] = text;
        ok++;
        // บันทึกทุก 5 ตอน
        if (ok % 5 === 0) {
          saved[i] = text;
          try { localStorage.setItem(SAVE_KEY, JSON.stringify(saved)); } catch (_) {}
        }
        saved[i] = text;
        break;
      } catch (e) {
        retries++;
        const wait = 3000 * retries;
        status(`⚠ ตอน ${i + 1} error (${e.message}) — รอ ${wait / 1000}s แล้วลองใหม่…`);
        await sleep(wait);
        if (retries > 3) {
          results[i] = `\n\n${ch.title}\n\n[โหลดไม่ได้: ${e.message}]`;
          fail++;
        }
      }
    }

    // หน่วงระหว่างตอน
    await sleep(DELAY + Math.random() * 500);
  }

  // ─── เสร็จ → ดาวน์โหลด .txt ──────────────────────────
  const text = '﻿' + novelName + '\n\n' + results.filter(Boolean).join('\n');
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = novelName.replace(/[\\/:*?"<>|]/g, '_') + '.txt';
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);

  // ลบ progress
  try { localStorage.removeItem(SAVE_KEY); } catch (_) {}

  status(`✅ เสร็จ! ได้ ${ok} ตอน (ผิดพลาด ${fail}) — ไฟล์ดาวน์โหลดแล้ว`);
  bar.style.background = '#2ecc40';

  // เสียงเตือน
  try {
    const ctx = new AudioContext();
    const beep = (f, s, d) => { const o = ctx.createOscillator(); const g = ctx.createGain(); o.connect(g); g.connect(ctx.destination); o.frequency.value = f; g.gain.setValueAtTime(0.8, ctx.currentTime + s); g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + s + d); o.start(ctx.currentTime + s); o.stop(ctx.currentTime + s + d + 0.05); };
    beep(880, 0, .18); beep(1100, .2, .18); beep(1320, .4, .3);
    setTimeout(() => ctx.close(), 1200);
  } catch (_) {}

})();
