// ==UserScript==
// @name         MyNovel Feed Checker
// @namespace    https://mynovel.co/
// @version      1.1
// @description  แสดง feed velocity + แนะนำ interval โพสต์บน mynovel.co
// @author       plen22441
// @match        https://mynovel.co/*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  // ── parse Thai time strings → minutes ──────────────────────────
  const TIME_RE = /น้อยกว่า\s*1\s*นาที|(\d+)\s*(วินาที|นาที|ชั่วโมง|วัน)/;

  function toMinutes(text) {
    if (/น้อยกว่า/.test(text)) return 0.5;
    const m = text.match(/(\d+)\s*(วินาที|นาที|ชั่วโมง|วัน)/);
    if (!m) return null;
    const n = parseInt(m[1]);
    if (m[2] === 'วินาที') return n / 60;
    if (m[2] === 'นาที')   return n;
    if (m[2] === 'ชั่วโมง') return n * 60;
    if (m[2] === 'วัน')    return n * 1440;
    return null;
  }

  function collectTimes() {
    const times = [];
    const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walk.nextNode())) {
      const t = node.textContent.trim();
      if (TIME_RE.test(t)) {
        const min = toMinutes(t);
        if (min !== null && min <= 120) times.push(min);
      }
    }
    // deduplicate and sort
    return [...new Set(times.map(String))].map(Number).sort((a, b) => a - b);
  }

  function calcVelocity(times) {
    if (times.length < 2) return null;
    const recent = times.filter(t => t <= 10);
    if (recent.length < 1) return null;
    const span = Math.max(...recent) || 1;
    return recent.length / span;  // posts per minute
  }

  function safeInterval(velocity, rank) {
    if (!velocity || velocity <= 0) return '?';
    return Math.min(Math.max(1, Math.round(rank / velocity)), 15);
  }

  function levelInfo(v) {
    if (!v)       return { icon: '❓', label: 'ไม่พบข้อมูล', color: '#8b92a5' };
    if (v >= 2.5) return { icon: '🔥', label: 'Peak สูงมาก',  color: '#ef4444' };
    if (v >= 1.0) return { icon: '⚡', label: 'คนเยอะ',       color: '#f59e0b' };
    return         { icon: '😴', label: 'ช่วงเงียบ',          color: '#22c55e' };
  }

  // ── build widget HTML ───────────────────────────────────────────
  function renderWidget(open) {
    const times = collectTimes();
    const v = calcVelocity(times);
    const { icon, label, color } = levelInfo(v);

    const t3  = safeInterval(v, 3);
    const t5  = safeInterval(v, 5);
    const t10 = safeInterval(v, 10);
    const vStr = v ? v.toFixed(1) + '/นาที' : '—';

    const body = open ? `
      <div style="padding:10px 14px 14px;border-top:1px solid #2a2f3d;font-size:13px;line-height:1.8">
        <div style="color:#8b92a5;font-size:11px;margin-bottom:8px">
          อ่านได้ ${times.length} เรื่องจากหน้านี้
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:10px">
          ${cell('Top 3', t3 + ' น.')}
          ${cell('Top 5', t5 + ' น.')}
          ${cell('Top 10', t10 + ' น.')}
        </div>
        <div style="color:#8b92a5;font-size:11px">
          ${times.slice(0,8).map(t => t < 1 ? '<1น.' : t + 'น.').join('  ')}
          ${times.length > 8 ? '...' : ''}
        </div>
      </div>` : '';

    return `
      <div id="__mnfc_head__"
           style="padding:10px 14px;display:flex;align-items:center;justify-content:space-between;cursor:pointer;gap:10px">
        <span style="font-size:15px">${icon}</span>
        <div style="flex:1;min-width:0">
          <div style="font-weight:700;font-size:13px;color:${color}">${label}</div>
          <div style="font-size:11px;color:#8b92a5">${vStr} · โพสต์ทุก <b style="color:#ff7c42">${t5} น.</b> (Top 5)</div>
        </div>
        <span id="__mnfc_arrow__" style="color:#8b92a5;font-size:11px">${open ? '▼' : '▲'}</span>
      </div>
      ${body}`;
  }

  function cell(label, val) {
    return `<div style="background:#0f1117;border-radius:8px;padding:6px 4px;text-align:center">
      <div style="font-size:15px;font-weight:700;color:#ff7c42">${val}</div>
      <div style="font-size:10px;color:#8b92a5">${label}</div>
    </div>`;
  }

  // ── create DOM ──────────────────────────────────────────────────
  let open = false;

  const wrap = document.createElement('div');
  wrap.id = '__mnfc__';
  wrap.style.cssText = [
    'position:fixed', 'bottom:20px', 'right:16px', 'z-index:2147483647',
    'background:#1a1d27', 'color:#edf0f7',
    'border-radius:14px', 'border:1px solid #2a2f3d',
    'box-shadow:0 4px 24px rgba(0,0,0,.5)',
    'width:220px', 'font-family:Sarabun,sans-serif',
    'overflow:hidden', 'transition:box-shadow .15s',
    'user-select:none', '-webkit-user-select:none',
  ].join(';');

  document.body.appendChild(wrap);

  function refresh() {
    wrap.innerHTML = renderWidget(open);
    wrap.querySelector('#__mnfc_head__').addEventListener('click', () => {
      open = !open;
      refresh();
    });
  }

  refresh();

  // re-read after page navigation (SPA) — observe URL changes
  let lastUrl = location.href;
  setInterval(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      setTimeout(refresh, 1200); // wait for new content
    }
  }, 800);

  // re-read every 60 seconds automatically
  setInterval(refresh, 60000);

})();
