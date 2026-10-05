// ==UserScript==
// @name         全本小说网 Novel Downloader (Float Button)
// @namespace    fanfan-novel-downloader
// @version      1.0.0
// @description  ดาวน์โหลดนิยายจาก quanben-xiaoshuo.com — ปุ่มลอย, Fast Fetch + iframe Fallback, ไม่ขาดตอน
// @author       Fanfan
// @match        https://www.quanben-xiaoshuo.com/n/*
// @match        https://quanben-xiaoshuo.com/n/*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  const APP = 'qb-downloader';
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  // ── ตรวจหน้าปัจจุบัน ─────────────────────────────────────────────────────
  // URL pattern: /n/<slug>           → หน้าสารบัญ
  //              /n/<slug>/<ch>.html → หน้าตอน
  const pathParts = location.pathname.replace(/^\//, '').split('/'); // ['n','slug'] or ['n','slug','ch.html']
  const novelSlug = pathParts[1] || '';
  const isIndexPage = pathParts.length === 2; // /n/slug
  const catalogUrl  = `${location.origin}/n/${novelSlug}/`;

  let stopped = false, running = false;
  let catalog = [];   // [{number, title, url}]
  let results = [];   // [{number, title, content, status}]

  // ── ตรวจเนื้อหาถูก block ─────────────────────────────────────────────────
  const BLOCK_RE = /Just a moment|安全验证|人机验证|Verify|Access Denied|Forbidden|403|404/i;

  function clean(s) {
    return String(s || '').replace(/\r/g, '').replace(/ /g, ' ')
      .replace(/[ \t]+/g, ' ').split('\n').map(x => x.trim()).filter(Boolean).join('\n');
  }
  function safeTitle(s) {
    return String(s || '').replace(/[\\/:*?"<>|]/g, '_').trim().slice(0, 120) || 'novel';
  }
  function novelTitle() {
    const h = document.querySelector('h1, .book-title, .bookname, .title');
    return safeTitle(h?.textContent) || safeTitle(novelSlug);
  }

  // ── สแกนสารบัญ ──────────────────────────────────────────────────────────
  async function fetchCatalog() {
    const resp = await fetch(catalogUrl, { credentials: 'include', cache: 'no-store' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const html = await resp.text();
    const doc  = new DOMParser().parseFromString(html, 'text/html');

    // selector หลายแบบที่เว็บนิยายจีนใช้
    const selectors = [
      '.chapter-list a', '#chapter-list a', '.list-chapter a',
      '.catalog-list a', '#catalog a', '.directory a',
      'ul.list a', '.list a', 'a[href*="/' + novelSlug + '/"]'
    ];

    let links = [];
    for (const sel of selectors) {
      links = [...doc.querySelectorAll(sel)].filter(a => {
        const p = new URL(a.href, location.origin).pathname;
        return p.startsWith(`/n/${novelSlug}/`) && p !== `/n/${novelSlug}/`;
      });
      if (links.length > 2) break;
    }
    if (!links.length) throw new Error('ไม่พบลิงก์ตอนในสารบัญ');

    const seen = new Set();
    const entries = [];
    links.forEach((a, i) => {
      const href = new URL(a.href, location.origin).href;
      if (seen.has(href)) return;
      seen.add(href);
      const numMatch = /\/(\d+)(?:\.html)?$/.exec(new URL(a.href, location.origin).pathname);
      const number   = numMatch ? Number(numMatch[1]) : i + 1;
      entries.push({ number, title: clean(a.textContent) || `第${number}章`, url: href });
    });
    return entries.sort((a, b) => a.number - b.number);
  }

  // ── Fast Fetch (ไม่สร้าง DOM ค้าง) ──────────────────────────────────────
  async function fastFetch(url) {
    const resp = await fetch(url, { credentials: 'include', cache: 'no-store' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const html = await resp.text();
    if (BLOCK_RE.test(html.slice(0, 2000))) throw new Error('blocked');

    const doc = new DOMParser().parseFromString(html, 'text/html');

    // หัวตอน
    const titleEl = doc.querySelector('h1.title, .chapter-title, h1, .chaptertitle');
    const chTitle = clean(titleEl?.textContent || '');

    // เนื้อหา
    const contentSelectors = [
      '#chaptercontent', '#chapter-content', '.chapter-content',
      '#content', '.content', '.article-content', '.readcontent',
      '.novel-content', '.text-content', '.chapterBody'
    ];
    let paras = [];
    for (const sel of contentSelectors) {
      const box = doc.querySelector(sel);
      if (!box) continue;
      paras = [...box.querySelectorAll('p')].map(p => clean(p.textContent)).filter(Boolean);
      if (!paras.length) paras = clean(box.textContent).split(/\n+/).filter(s => s.length > 2);
      if (paras.length) break;
    }
    if (!paras.length) {
      // fallback: body text ทั้งหมด กรองบรรทัดสั้น
      paras = clean(doc.body?.textContent || '').split(/\n+/).filter(s => s.length > 10);
    }

    return { title: chTitle, paras };
  }

  // ── iframe Fallback (สำหรับเว็บที่ต้อง render JS) ──────────────────────
  function iframeFetch(url) {
    return new Promise((resolve, reject) => {
      const frame = document.createElement('iframe');
      frame.style.cssText = 'position:fixed;width:1px;height:1px;left:-9999px;top:-9999px;opacity:.01;pointer-events:none';
      let done = false;
      const timer = setTimeout(() => finish(new Error('timeout')), 25000);

      function finish(err) {
        if (done) return; done = true; clearTimeout(timer);
        try {
          if (err) { frame.remove(); reject(err); return; }
          const doc = frame.contentDocument;
          if (!doc) { frame.remove(); reject(new Error('no contentDocument')); return; }
          if (BLOCK_RE.test(doc.body?.innerText?.slice(0, 1000) || '')) {
            frame.remove(); reject(new Error('blocked')); return;
          }
          const titleEl = doc.querySelector('h1.title, .chapter-title, h1, .chaptertitle');
          const chTitle = clean(titleEl?.innerText || '');
          const contentSelectors = [
            '#chaptercontent', '#chapter-content', '.chapter-content',
            '#content', '.content', '.article-content', '.readcontent'
          ];
          let paras = [];
          for (const sel of contentSelectors) {
            const box = doc.querySelector(sel);
            if (!box) continue;
            paras = [...box.querySelectorAll('p')].map(p => clean(p.innerText)).filter(Boolean);
            if (!paras.length) paras = clean(box.innerText).split(/\n+/).filter(s => s.length > 2);
            if (paras.length) break;
          }
          if (!paras.length) paras = clean(doc.body?.innerText || '').split(/\n+/).filter(s => s.length > 10);
          frame.remove();
          resolve({ title: chTitle, paras });
        } catch (e) { frame.remove(); reject(e); }
      }

      frame.onload = () => setTimeout(() => finish(null), 600);
      frame.onerror = () => finish(new Error('load error'));
      frame.src = url;
      document.body.append(frame);
    });
  }

  // ── ดึงเนื้อหาตอน: Fast Fetch ก่อน, ถ้าพลาดใช้ iframe ──────────────────
  async function fetchChapter(url, attempt = 1) {
    try {
      const r = await fastFetch(url);
      if (r.paras.length < 3) throw new Error('too short from fetch');
      return { ...r, method: 'fetch' };
    } catch (_) {
      try {
        const r = await iframeFetch(url);
        return { ...r, method: 'iframe' };
      } catch (e) {
        if (attempt < 3 && !stopped) {
          await sleep(attempt * 1500);
          return fetchChapter(url, attempt + 1);
        }
        throw e;
      }
    }
  }

  // ── UI ─────────────────────────────────────────────────────────────────────
  const panel = document.createElement('section');
  panel.id = APP;
  panel.innerHTML = `
    <div class="qb-head">
      <span>⚡ โหลดนิยาย</span>
      <button id="qb-min">−</button>
    </div>
    <div id="qb-body">
      <div id="qb-info">ตรวจหาสารบัญ…</div>
      <div class="qb-row">
        <button class="qb-cnt" data-n="50">50</button>
        <button class="qb-cnt" data-n="100">100</button>
        <button class="qb-cnt" data-n="200">200</button>
        <button class="qb-cnt" data-n="300">300</button>
      </div>
      <div class="qb-row">
        <input id="qb-from" type="number" min="1" placeholder="ตอนเริ่ม" value="1">
        <input id="qb-limit" type="number" min="1" placeholder="จำนวน" value="100">
        <input id="qb-delay" type="number" min="200" placeholder="หน่วง ms" value="500">
      </div>
      <div class="qb-row">
        <button id="qb-run">▶ เริ่มเก็บเร็ว</button>
        <button id="qb-stop" disabled>■ หยุด</button>
      </div>
      <progress id="qb-prog" max="100" value="0"></progress>
      <div id="qb-status">พร้อม • Fast Fetch + iframe Fallback</div>
      <div class="qb-row">
        <button id="qb-copy" disabled>Copy ทั้งหมด</button>
        <button id="qb-dl" disabled>ดาวน์โหลด TXT</button>
      </div>
      <div id="qb-log"></div>
    </div>`;
  document.body.append(panel);

  const css = document.createElement('style');
  css.textContent = `
    #${APP}{position:fixed;z-index:2147483647;right:10px;bottom:10px;width:min(360px,calc(100vw - 20px));background:#1a1a2e;color:#e0e0f0;border:2px solid #f5a623;border-radius:16px;box-shadow:0 12px 40px #000a;font:14px/1.5 system-ui,sans-serif;overflow:hidden}
    #${APP} *{box-sizing:border-box}
    #${APP} .qb-head{display:flex;justify-content:space-between;align-items:center;background:#f5a623;color:#1a1a2e;padding:10px 14px;font-weight:800;font-size:15px}
    #${APP} #qb-body{padding:12px;display:flex;flex-direction:column;gap:8px}
    #${APP} #qb-info{font-size:12px;color:#aaa;text-align:center;background:#0f0f1e;border-radius:8px;padding:6px 10px;word-break:break-all}
    #${APP} .qb-row{display:flex;gap:6px;flex-wrap:wrap}
    #${APP} button{flex:1;border:0;border-radius:10px;padding:9px 8px;background:#f5a623;color:#1a1a2e;font-weight:700;cursor:pointer;font-size:13px}
    #${APP} button:disabled{opacity:.35;cursor:default}
    #${APP} button.qb-cnt{background:#2d2d50;color:#f5a623;border:1px solid #f5a62366}
    #${APP} button.qb-cnt.active{background:#f5a623;color:#1a1a2e}
    #${APP} #qb-min{flex:none;width:32px;padding:2px;background:#fff3;font-size:18px;border-radius:8px}
    #${APP} input{flex:1;min-width:70px;padding:8px;border:1px solid #444;border-radius:9px;background:#0f0f1e;color:#e0e0f0;font-size:13px;text-align:center}
    #${APP} progress{width:100%;height:10px;border-radius:5px;accent-color:#f5a623}
    #${APP} #qb-status{font-size:12px;color:#f5a623;font-weight:600;text-align:center}
    #${APP} #qb-copy{background:#2d2d50;color:#e0e0f0;border:1px solid #555}
    #${APP} #qb-dl{background:#27ae60}
    #${APP} #qb-log{max-height:80px;overflow-y:auto;font-size:11px;color:#888;background:#0a0a18;border-radius:8px;padding:6px 8px;white-space:pre-wrap;word-break:break-all}`;
  document.head.append(css);

  const $ = s => panel.querySelector(s);
  const ui = {
    head: $('.qb-head span'), body: $('#qb-body'), info: $('#qb-info'),
    from: $('#qb-from'), limit: $('#qb-limit'), delay: $('#qb-delay'),
    run: $('#qb-run'), stop: $('#qb-stop'),
    prog: $('#qb-prog'), status: $('#qb-status'),
    copy: $('#qb-copy'), dl: $('#qb-dl'), log: $('#qb-log'),
    min: $('#qb-min'), cnts: [...panel.querySelectorAll('.qb-cnt')]
  };

  function addLog(msg) {
    ui.log.textContent = `[${new Date().toLocaleTimeString('th-TH',{hour12:false})}] ${msg}\n` + ui.log.textContent.slice(0, 1200);
  }
  function setStatus(msg) { ui.status.textContent = msg; addLog(msg); }
  function setRunning(v) {
    running = v;
    ui.run.disabled = v;
    ui.stop.disabled = !v;
  }

  // ── ไฮไลต์ปุ่ม count ─────────────────────────────────────────────────────
  ui.cnts.forEach(btn => {
    btn.onclick = () => {
      ui.cnts.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      ui.limit.value = btn.dataset.n;
    };
  });
  // default active
  panel.querySelector('[data-n="100"]').classList.add('active');

  // ── init: ดึงสารบัญอัตโนมัติ ─────────────────────────────────────────────
  async function init() {
    try {
      setStatus('กำลังสแกนสารบัญ…');
      catalog = await fetchCatalog();
      const last = catalog.at(-1)?.number || '?';
      ui.info.textContent = `📚 ${novelTitle()} — พบ ${catalog.length} ตอน (1–${last})`;
      setStatus(`พร้อม • ${catalog.length} ตอน • Fast Fetch + iframe Fallback`);
    } catch (e) {
      ui.info.textContent = `⚠️ สแกนสารบัญไม่สำเร็จ: ${e.message}`;
      setStatus('ใส่ตอนเริ่ม+จำนวนแล้วกด ▶ ก็ได้');
      addLog('สแกนสารบัญล้มเหลว: ' + e.message);
    }
  }

  // ── main run ────────────────────────────────────────────────────────────
  async function run() {
    if (running) return;
    const fromN  = Math.max(1, Number(ui.from.value) || 1);
    const limit  = Math.max(1, Number(ui.limit.value) || 100);
    const delay  = Math.max(200, Number(ui.delay.value) || 500);

    // เลือกตอนจาก catalog (ถ้ามี) หรือสร้าง URL จากตัวเลข
    let selected = catalog.filter(x => x.number >= fromN).slice(0, limit);
    if (!selected.length) {
      // ไม่มี catalog → สร้าง URL จากเลขตอน
      selected = Array.from({ length: limit }, (_, i) => {
        const n = fromN + i;
        return { number: n, title: `第${n}章`, url: `${location.origin}/n/${novelSlug}/${n}.html` };
      });
    }

    stopped = false; results = []; setRunning(true);
    ui.prog.max = selected.length; ui.prog.value = 0;
    ui.copy.disabled = ui.dl.disabled = true;

    for (let i = 0; i < selected.length && !stopped; i++) {
      const item = selected[i];
      setStatus(`โหลดตอน ${item.number} (${i + 1}/${selected.length})`);
      try {
        const data = await fetchChapter(item.url);
        results.push({ number: item.number, title: data.title || item.title, content: data.paras.join('\n\n'), method: data.method });
        addLog(`✓ ตอน ${item.number} [${data.method}] ${data.paras.length} ย่อหน้า`);
      } catch (e) {
        results.push({ number: item.number, title: item.title, content: '[โหลดไม่สำเร็จ: ' + e.message + ']', method: 'fail' });
        addLog(`✗ ตอน ${item.number}: ${e.message}`);
      }
      ui.prog.value = i + 1;
      if (i < selected.length - 1 && !stopped) await sleep(delay);
    }

    const ok   = results.filter(r => r.method !== 'fail').length;
    const fail = results.length - ok;
    setStatus(`เสร็จ ${ok} ตอน${fail ? ` (ล้มเหลว ${fail})` : ''} — พร้อมดาวน์โหลด`);
    ui.copy.disabled = ui.dl.disabled = !results.length;
    setRunning(false);
  }

  function buildTxt() {
    const title = novelTitle();
    const parts = [`${title}\n${'═'.repeat(30)}\n`];
    for (const r of results) {
      parts.push(`\n${r.title}\n${'─'.repeat(20)}\n\n${r.content}\n`);
    }
    const failed = results.filter(r => r.method === 'fail').map(r => r.number);
    if (failed.length) parts.push(`\n[ตอนที่โหลดไม่สำเร็จ: ${failed.join(', ')}]`);
    return parts.join('');
  }

  // ── Events ──────────────────────────────────────────────────────────────
  ui.run.onclick = run;
  ui.stop.onclick = () => { stopped = true; setStatus('กำลังหยุด…'); };
  ui.min.onclick = () => {
    const show = ui.body.style.display === 'none';
    ui.body.style.display = show ? '' : 'none';
    ui.min.textContent = show ? '−' : '+';
  };
  ui.copy.onclick = () => {
    navigator.clipboard.writeText(buildTxt()).then(() => setStatus('Copy สำเร็จ!')).catch(() => {
      const ta = document.createElement('textarea');
      ta.value = buildTxt(); document.body.append(ta); ta.select();
      document.execCommand('copy'); ta.remove(); setStatus('Copy สำเร็จ!');
    });
  };
  ui.dl.onclick = () => {
    const txt  = buildTxt();
    const name = `${safeTitle(novelTitle())}_${results[0]?.number || 1}-${results.at(-1)?.number || ''}.txt`;
    const blob = new Blob(['﻿' + txt], { type: 'text/plain;charset=utf-8' });
    const a = document.createElement('a'), url = URL.createObjectURL(blob);
    a.href = url; a.download = name; document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 3000);
  };

  // ── เริ่ม ────────────────────────────────────────────────────────────────
  init();
})();
