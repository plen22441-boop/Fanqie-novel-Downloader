// ==UserScript==
// @name         MyNovel Feed Checker
// @namespace    https://mynovel.co/
// @version      2.0
// @description  แสดง feed velocity + แนะนำ interval โพสต์บน mynovel.co (with debug)
// @author       plen22441
// @match        https://mynovel.co/*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  // ── 1. Parse Thai time text → minutes ─────────────────────────
  const PATTERNS = [
    { re: /น้อยกว่า\s*1\s*นาที/,            fn: ()    => 0.5 },
    { re: /(\d+)\s*วินาที(?:ที่แล้ว)?/,     fn: m     => +m[1] / 60 },
    { re: /(\d+)\s*นาที(?:ที่แล้ว)?/,       fn: m     => +m[1] },
    { re: /(\d+)\s*ชั่วโมง(?:ที่แล้ว)?/,    fn: m     => +m[1] * 60 },
    { re: /(\d+)\s*วัน(?:ที่แล้ว)?/,        fn: m     => +m[1] * 1440 },
    { re: /(\d+)\s*สัปดาห์(?:ที่แล้ว)?/,   fn: m     => +m[1] * 10080 },
  ];

  function parseTime(text) {
    for (const { re, fn } of PATTERNS) {
      const m = text.match(re);
      if (m) return fn(m);
    }
    return null;
  }

  // ── 2. Multi-strategy DOM scan ─────────────────────────────────
  function scanPage() {
    const found = [];
    const sources = [];   // for debug

    // Strategy A: walk every text node
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const t = node.textContent.trim();
      const min = parseTime(t);
      if (min !== null && t.length < 40) {
        found.push(min);
        sources.push({ via: 'text', raw: t, min });
      }
    }

    // Strategy B: <time> elements
    document.querySelectorAll('time').forEach(el => {
      const t = el.textContent.trim() || el.getAttribute('datetime') || '';
      const min = parseTime(t);
      if (min !== null) {
        found.push(min);
        sources.push({ via: '<time>', raw: t, min });
      }
    });

    // Strategy C: aria-label / title attributes that contain Thai time
    document.querySelectorAll('[aria-label],[title]').forEach(el => {
      const t = (el.getAttribute('aria-label') || el.getAttribute('title') || '').trim();
      const min = parseTime(t);
      if (min !== null && t.length < 60) {
        found.push(min);
        sources.push({ via: 'attr', raw: t, min });
      }
    });

    // dedupe: round to 1 decimal, keep unique
    const seen = new Set();
    const unique = [];
    const uniqueSrc = [];
    sources.forEach((s, i) => {
      const key = s.min.toFixed(1);
      if (!seen.has(key)) {
        seen.add(key);
        unique.push(s.min);
        uniqueSrc.push(s);
      }
    });

    return {
      times: unique.sort((a, b) => a - b),
      debug: uniqueSrc.sort((a, b) => a.min - b.min),
    };
  }

  // ── 3. Velocity & recommendation ──────────────────────────────
  function calcVelocity(times) {
    const recent = times.filter(t => t <= 10);
    if (recent.length < 2) return null;
    const span = Math.max(...recent) || 1;
    return recent.length / span;
  }

  function safeInterval(v, rank) {
    if (!v || v <= 0) return '?';
    return Math.min(Math.max(1, Math.round(rank / v)), 15);
  }

  // ── 4. Widget styles ───────────────────────────────────────────
  const S = {
    wrap: [
      'position:fixed', 'bottom:80px', 'right:14px', 'z-index:2147483647',
      'background:#13151f', 'color:#e8eaf0',
      'border-radius:16px', 'border:1px solid #252836',
      'box-shadow:0 8px 32px rgba(0,0,0,.6)',
      'width:240px', 'font-family:Sarabun,sans-serif',
      'overflow:hidden', 'transition:width .2s',
      'font-size:13px', 'line-height:1.5',
    ].join(';'),
  };

  const COLOR = { ok: '#22c55e', warn: '#f59e0b', hot: '#ef4444', dim: '#8b92a5', accent: '#ff6b2b' };

  function levelOf(v) {
    if (!v)       return { icon: '❓', label: 'กำลังหาข้อมูล', c: COLOR.dim };
    if (v >= 2.5) return { icon: '🔥', label: 'Peak — ต้องถี่',  c: COLOR.hot };
    if (v >= 1.0) return { icon: '⚡', label: 'คนเยอะ',         c: COLOR.warn };
    return         { icon: '😴', label: 'ช่วงเงียบ',             c: COLOR.ok };
  }

  // ── 5. Render ──────────────────────────────────────────────────
  let state = { open: false, debug: false, data: null, ts: null };

  function render() {
    const { open, debug, data, ts } = state;
    const v = data ? calcVelocity(data.times) : null;
    const { icon, label, c } = levelOf(v);
    const t3  = safeInterval(v, 3);
    const t5  = safeInterval(v, 5);
    const t10 = safeInterval(v, 10);
    const count = data ? data.times.length : 0;
    const timeStr = ts ? `${String(ts.getHours()).padStart(2,'0')}:${String(ts.getMinutes()).padStart(2,'0')}` : '—';

    // header row
    let html = `
      <div id="__mnfc_head" style="padding:11px 14px;display:flex;align-items:center;gap:8px;cursor:pointer">
        <span style="font-size:16px">${icon}</span>
        <div style="flex:1;min-width:0">
          <div style="font-weight:700;color:${c}">${label}</div>
          <div style="color:${COLOR.dim};font-size:11px">
            ${v ? `${v.toFixed(1)}/นาที` : 'ยังไม่อ่านข้อมูล'}
            · พบ <b style="color:#e8eaf0">${count}</b> รายการ
          </div>
        </div>
        <span style="color:${COLOR.dim};font-size:10px">${open ? '▼' : '▲'}</span>
      </div>`;

    if (open) {
      // interval grid
      html += `<div style="padding:0 12px 12px;border-top:1px solid #252836;padding-top:10px">
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:10px">
          ${ivCell('Top 3', t3)}${ivCell('Top 5', t5)}${ivCell('Top 10', t10)}
        </div>`;

      // timestamps found
      if (data && data.times.length) {
        const tStr = data.times.map(t =>
          `<span style="background:#1e2130;border-radius:5px;padding:1px 6px;font-family:monospace">${
            t < 1 ? '<1น.' : t + 'น.'}</span>`
        ).join(' ');
        html += `<div style="font-size:11px;color:${COLOR.dim};margin-bottom:8px">
          Timestamps ที่อ่านได้:<br><div style="margin-top:4px;line-height:2">${tStr}</div>
        </div>`;
      } else {
        html += `<div style="background:#2a1515;border-radius:8px;padding:8px 10px;color:#ef8080;font-size:12px;margin-bottom:8px">
          ⚠️ อ่าน timestamp ไม่เจอ<br>
          <span style="color:${COLOR.dim}">ลองเปิดหน้า "ล่าสุด" หรือ "หน้าหลัก" ของ mynovel.co แล้วกดรีเฟรช</span>
        </div>`;
      }

      // buttons row
      html += `<div style="display:flex;gap:6px">
        <button id="__mnfc_refresh" style="${btnStyle(COLOR.accent)}">🔄 รีเฟรช</button>
        <button id="__mnfc_debug"   style="${btnStyle(debug ? '#3b82f6' : '#252836')}">🐛 Debug</button>
      </div>`;

      // debug panel
      if (debug && data) {
        const rows = data.debug.slice(0, 15).map(s =>
          `<tr><td style="color:${COLOR.dim};padding-right:8px">${s.via}</td>
               <td style="color:#e8eaf0">${s.raw.slice(0,30)}</td>
               <td style="color:${COLOR.accent};text-align:right">${s.min.toFixed(1)}น.</td></tr>`
        ).join('');
        html += `<div style="margin-top:10px;background:#0d0f19;border-radius:8px;padding:8px;overflow:auto;max-height:150px">
          <table style="width:100%;font-size:11px;border-collapse:collapse">${rows || '<tr><td style="color:'+COLOR.dim+'">ไม่พบข้อมูล</td></tr>'}</table>
        </div>`;
      }

      html += `<div style="margin-top:8px;font-size:10px;color:${COLOR.dim};text-align:right">
        อัปเดต ${timeStr} · ทุก 60 วินาที
      </div></div>`;
    }

    wrap.innerHTML = html;

    // bind events
    wrap.querySelector('#__mnfc_head').onclick = () => { state.open = !state.open; render(); };
    if (open) {
      wrap.querySelector('#__mnfc_refresh').onclick = e => { e.stopPropagation(); doScan(); };
      wrap.querySelector('#__mnfc_debug').onclick   = e => { e.stopPropagation(); state.debug = !state.debug; render(); };
    }
  }

  function ivCell(label, val) {
    return `<div style="background:#1a1d2e;border-radius:10px;padding:7px 4px;text-align:center">
      <div style="font-size:18px;font-weight:700;color:${COLOR.accent};font-family:monospace">${val}</div>
      <div style="font-size:10px;color:${COLOR.dim}">${label}</div>
    </div>`;
  }

  function btnStyle(bg) {
    return `flex:1;padding:7px 4px;background:${bg};color:#e8eaf0;border:none;` +
      `border-radius:8px;font-size:12px;font-family:Sarabun,sans-serif;` +
      `cursor:pointer;font-weight:600`;
  }

  // ── 6. Scan & update ───────────────────────────────────────────
  function doScan() {
    state.data = scanPage();
    state.ts   = new Date();
    render();
  }

  // ── 7. Mount ───────────────────────────────────────────────────
  const wrap = document.createElement('div');
  wrap.id = '__mnfc_wrap__';
  wrap.style.cssText = S.wrap;
  document.body.appendChild(wrap);

  // first scan after a short delay (wait for SPA content)
  setTimeout(doScan, 1500);

  // auto-refresh every 60s
  setInterval(doScan, 60000);

  // re-scan on SPA navigation
  let lastUrl = location.href;
  setInterval(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      setTimeout(doScan, 1500);
    }
  }, 1000);

  render(); // show loading state immediately

})();
