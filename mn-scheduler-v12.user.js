// ==UserScript==
// @name         MyNovel Auto Scheduler Helper v12.2.0
// @namespace    https://mynovel.co/
// @version      12.2.0
// @description  ตั้งเวลา MyNovel — โหมดปุ๊บปุ๊บ, ปรับความเร็วอัตโนมัติ, ตรวจหาเวลาต่อ, Wake Lock, เสียงแจ้งเตือน, หลายเรื่องพร้อมกัน
// @match        *://mynovel.co/*
// @match        *://*.mynovel.co/*
// @grant        none
// @run-at       document-idle
// ==/UserScript==
(() => {
  'use strict';
  const VERSION = '12.2.0';
  const ID = 'mn-auto-helper-panel';
  const FAB_ID = 'mn-auto-helper-fab';
  const STORE_KEY = 'mn-auto-helper-settings';
  const MULTI_KEY = 'mn-multi-jobs';
  try { window.__MN_SCHEDULER_CLEANUP__ && window.__MN_SCHEDULER_CLEANUP__(); } catch (_) {}
  if (window.__MN_SCHEDULER_VERSION__ === VERSION && document.getElementById(ID)) return;
  window.__MN_SCHEDULER_VERSION__ = VERSION;
  document.querySelectorAll(
    '[id^="mn-auto-helper-"],[id^="mn-extreme-ui-"],#mn-fab-btn'
  ).forEach(el => el.remove());
  const MONTHS_EN = Object.freeze({
    january: 0, february: 1, march: 2, april: 3, may: 4, june: 5,
    july: 6, august: 7, september: 8, october: 9, november: 10, december: 11
  });
  const MONTHS_TH = Object.freeze({
    'มกราคม': 0, 'กุมภาพันธ์': 1, 'มีนาคม': 2, 'เมษายน': 3, 'พฤษภาคม': 4, 'มิถุนายน': 5,
    'กรกฎาคม': 6, 'สิงหาคม': 7, 'กันยายน': 8, 'ตุลาคม': 9, 'พฤศจิกายน': 10, 'ธันวาคม': 11,
    'ม.ค.': 0, 'ก.พ.': 1, 'มี.ค.': 2, 'เม.ย.': 3, 'พ.ค.': 4, 'มิ.ย.': 5,
    'ก.ค.': 6, 'ส.ค.': 7, 'ก.ย.': 8, 'ต.ค.': 9, 'พ.ย.': 10, 'ธ.ค.': 11
  });
  const MONTHS_EN_NAMES = Object.freeze(Object.keys(MONTHS_EN).map(
    name => name.charAt(0).toUpperCase() + name.slice(1)
  ));
  const MONTHS_TH_NAMES = Object.freeze([
    'มกราคม', 'กุมภาพันธ์', 'มีนาคม', 'เมษายน', 'พฤษภาคม', 'มิถุนายน',
    'กรกฎาคม', 'สิงหาคม', 'กันยายน', 'ตุลาคม', 'พฤศจิกายน', 'ธันวาคม'
  ]);
  const MONTH_EN_RE =
    /\b(January|February|March|April|May|June|July|August|September|October|November|December)\b/i;
  const MONTH_TH_RE =
    /(มกราคม|กุมภาพันธ์|มีนาคม|เมษายน|พฤษภาคม|มิถุนายน|กรกฎาคม|สิงหาคม|กันยายน|ตุลาคม|พฤศจิกายน|ธันวาคม|ม\.ค\.|ก\.พ\.|มี\.ค\.|เม\.ย\.|พ\.ค\.|มิ\.ย\.|ก\.ค\.|ส\.ค\.|ก\.ย\.|ต\.ค\.|พ\.ย\.|ธ\.ค\.)/;
  const SPEED_PROFILES = Object.freeze({
    normal: {
      pollMs: 90, beforeTapMs: 55, afterTapMs: 130, afterSuccessMs: 320, retryBaseMs: 700,
      afterSetNativeMs: 220, afterSetHourMs: 120, afterMonthNavMs: 240, afterPickDayMs: 320,
      afterClosePickerMs: 240, selectOnlyPauseMs: 140
    },
    fast: {
      pollMs: 50, beforeTapMs: 25, afterTapMs: 60, afterSuccessMs: 120, retryBaseMs: 400,
      afterSetNativeMs: 100, afterSetHourMs: 50, afterMonthNavMs: 120, afterPickDayMs: 150,
      afterClosePickerMs: 100, selectOnlyPauseMs: 60
    },
    turbo: {
      pollMs: 30, beforeTapMs: 10, afterTapMs: 35, afterSuccessMs: 60, retryBaseMs: 250,
      afterSetNativeMs: 60, afterSetHourMs: 30, afterMonthNavMs: 70, afterPickDayMs: 80,
      afterClosePickerMs: 60, selectOnlyPauseMs: 30
    },
    ultra: {
      pollMs: 16, beforeTapMs: 0, afterTapMs: 0, afterSuccessMs: 0, retryBaseMs: 150,
      afterSetNativeMs: 0, afterSetHourMs: 0, afterMonthNavMs: 0, afterPickDayMs: 0,
      afterClosePickerMs: 0, selectOnlyPauseMs: 0
    }
  });
  const LADDER = Object.freeze(['ultra', 'turbo', 'fast', 'normal']);
  const SPEED = { ...SPEED_PROFILES.ultra };
  function setSpeedProfile(name) {
    const profile = SPEED_PROFILES[name];
    if (profile) Object.assign(SPEED, profile);
  }
  // Web Worker-based sleep: not throttled in background tabs on mobile Firefox
  const _workerBlob = new Blob([`
    self.onmessage = function(e) {
      var id = e.data.id, ms = e.data.ms;
      setTimeout(function(){ self.postMessage(id); }, ms);
    };
  `], { type: 'application/javascript' });
  const _timerWorker = (() => {
    try { return new Worker(URL.createObjectURL(_workerBlob)); } catch(_) { return null; }
  })();
  const _timerCbs = new Map();
  if (_timerWorker) {
    let _tid = 0;
    _timerWorker.onmessage = e => { const cb = _timerCbs.get(e.data); _timerCbs.delete(e.data); if (cb) cb(); };
    window._mnWorkerSleep = (ms) => new Promise(resolve => {
      const id = ++_tid;
      _timerCbs.set(id, resolve);
      _timerWorker.postMessage({ id, ms });
    });
  }
  const sleep = ms => {
    if (ms <= 0) return Promise.resolve();
    if (window._mnWorkerSleep) return window._mnWorkerSleep(ms);
    return new Promise(resolve => setTimeout(resolve, ms));
  };
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const txt = el => (el?.innerText || el?.textContent || '').replace(/\s+/g, ' ').trim();
  const clean = value => String(value || '').replace(/\s+/g, '');
  const visible = el => {
    if (!el || !el.isConnected) return false;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    const style = getComputedStyle(el);
    return style.display !== 'none' &&
      style.visibility !== 'hidden' &&
      style.opacity !== '0';
  };
  const enabled = el => !!el &&
    !el.disabled &&
    el.getAttribute('aria-disabled') !== 'true' &&
    el.dataset.disabled !== 'true';
  const isOwnUI = el => !!el && !!(el.closest('#' + ID) || el.closest('#' + FAB_ID));
  const uniq = list => list.filter((el, index, all) => all.indexOf(el) === index);
  const byArea = (a, b) => {
    const ra = a.getBoundingClientRect();
    const rb = b.getBoundingClientRect();
    return ra.width * ra.height - rb.width * rb.height;
  };
  function retryable(message) {
    const error = new Error(message);
    error.code = 'MN_RETRY';
    return error;
  }
  function waitFor(fn, timeout = 8000, error = 'หมดเวลารอ MyNovel ตอบกลับ') {
    return new Promise((resolve, reject) => {
      let finished = false;
      let scheduled = false;
      let pollTimer = null;
      let deadline = null;
      let observer = null;
      const finish = (ok, value) => {
        if (finished) return;
        finished = true;
        clearTimeout(pollTimer);
        clearTimeout(deadline);
        if (observer) observer.disconnect();
        if (ok) resolve(value);
        else reject(new Error(error));
      };
      const check = () => {
        if (finished) return true;
        try {
          const value = fn();
          if (value) { finish(true, value); return true; }
        } catch (_) {}
        return false;
      };
      if (check()) return;
      observer = new MutationObserver(() => {
        if (scheduled || finished) return;
        scheduled = true;
        queueMicrotask(() => { scheduled = false; check(); });
      });
      observer.observe(document.documentElement, {
        subtree: true, childList: true, attributes: true, characterData: true
      });
      const loop = () => {
        if (finished) return;
        if (!check()) pollTimer = setTimeout(loop, SPEED.pollMs);
      };
      pollTimer = setTimeout(loop, SPEED.pollMs);
      deadline = setTimeout(() => { if (!check()) finish(false); }, timeout);
    });
  }
  const settle = (fn, timeout = 1500) => waitFor(fn, timeout).catch(() => null);
  const INTERACTIVE = 'button,[role="button"],[role="checkbox"],[role="gridcell"],input,select,textarea,label,td,a';
  function clickableTarget(el) {
    if (!el) return null;
    if (el.matches(INTERACTIVE)) return el;
    let node = el.parentElement;
    for (let i = 0; node && i < 3; node = node.parentElement, i++) {
      if (node.matches('button,[role="button"],[role="checkbox"],[role="gridcell"],input,select,label,td')) {
        return node;
      }
    }
    return el;
  }
  function fireMouseSequence(target) {
    const rect = target.getBoundingClientRect();
    const clientX = Math.round(rect.left + rect.width / 2);
    const clientY = Math.round(rect.top + rect.height / 2);
    const fire = (type, Ctor, buttons) => {
      try {
        target.dispatchEvent(new Ctor(type, {
          bubbles: true, cancelable: true, view: window,
          clientX, clientY, screenX: clientX, screenY: clientY,
          pointerId: 1, pointerType: 'touch', isPrimary: true,
          button: 0, buttons
        }));
      } catch (_) {}
    };
    const Pointer = window.PointerEvent || MouseEvent;
    fire('pointerdown', Pointer, 1);
    fire('mousedown', MouseEvent, 1);
    fire('pointerup', Pointer, 0);
    fire('mouseup', MouseEvent, 0);
  }
  async function tap(el, { scroll = true } = {}) {
    if (!el) throw new Error('ไม่พบจุดที่ต้องกด');
    const target = clickableTarget(el);
    if (scroll && !target.closest('[role="dialog"],[data-radix-popper-content-wrapper]')) {
      const rect = target.getBoundingClientRect();
      if (rect.top < 8 || rect.bottom > window.innerHeight - 8) {
        try { target.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (_) {}
      }
    }
    await sleep(SPEED.beforeTapMs);
    try { target.focus?.({ preventScroll: true }); } catch (_) {}
    fireMouseSequence(target);
    try { target.click(); } catch (_) {
      try {
        target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
      } catch (__) {}
    }
    await sleep(SPEED.afterTapMs);
  }
  function buttonByText(label, root = document, exact = false) {
    return $$('button,[role="button"],a', root)
      .filter(visible)
      .filter(el => !isOwnUI(el))
      .filter(el => exact ? txt(el) === label : txt(el).includes(label))
      .sort((a, b) => txt(a).length - txt(b).length)[0] || null;
  }
  function isChecked(el) {
    return el?.checked === true ||
      el?.getAttribute('aria-checked') === 'true' ||
      el?.dataset.state === 'checked';
  }
  function cardFor(checkBox) {
    for (let node = checkBox.parentElement, i = 0; node && i < 10; node = node.parentElement, i++) {
      const t = txt(node);
      if (t.length > 2000) return null;
      if (!/ตอน\s*\d+/.test(t)) continue;
      const boxes = $$('input[type="checkbox"],[role="checkbox"]', node).filter(visible);
      return boxes.length === 1 ? node : null;
    }
    return null;
  }
  function episodeCards() {
    const seen = new Set();
    const result = [];
    for (const cb of $$('input[type="checkbox"],[role="checkbox"]').filter(visible)) {
      if (isOwnUI(cb)) continue;
      const card = cardFor(cb);
      if (!card) continue;
      const match = txt(card).match(/ตอน\s*(\d+)/);
      const episode = match ? Number(match[1]) : NaN;
      if (!Number.isFinite(episode) || seen.has(episode)) continue;
      seen.add(episode);
      result.push({ episode, card, cb, top: card.getBoundingClientRect().top });
    }
    return result;
  }
  const selected = () => episodeCards().filter(item => isChecked(item.cb));
  const findEpisode = episode => episodeCards().find(item => item.episode === episode) || null;
  function timeText(date) {
    return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
  }
  function episodeHasSchedule(episode) {
    const item = findEpisode(episode);
    if (!item) return false;
    return clean(txt(item.card)).includes('กำหนดเผยแพร่');
  }
  function episodeLooksScheduled(episode, target) {
    const item = findEpisode(episode);
    if (!item) return false;
    const compact = clean(txt(item.card));
    const hm = timeText(target);
    return compact.includes('กำหนดเผยแพร่') &&
      (compact.includes(hm) || compact.includes(hm.replace(':', '：')));
  }
  function parseScheduledDateFromCard(card) {
    const full = txt(card);
    const at = full.indexOf('กำหนดเผยแพร่');
    if (at < 0) return null;
    const t = full.slice(at, at + 60);
    const timeMatch = t.match(/(\d{1,2}):(\d{2})(?!:\d)/);
    if (!timeMatch) return null;
    const hour = Number(timeMatch[1]);
    const minute = Number(timeMatch[2]);
    const dayMatch = t.match(/กำหนดเผยแพร่\s+(\d{1,2})/);
    const day = dayMatch ? Number(dayMatch[1]) : null;
    const thMonthMatch = t.match(MONTH_TH_RE);
    const enMonthMatch = t.match(MONTH_EN_RE);
    let month = null;
    if (thMonthMatch) month = MONTHS_TH[thMonthMatch[1]];
    else if (enMonthMatch) month = MONTHS_EN[enMonthMatch[1].toLowerCase()];
    const yearMatches = t.match(/\d{4}/g);
    let year = null;
    if (yearMatches) {
      const years = yearMatches.map(Number).filter(y => y >= 1900);
      if (years.length) {
        const y = years[0];
        year = y >= 2400 ? y - 543 : y;
      }
    }
    if (day === null || month === null || year === null) return null;
    return new Date(year, month, day, hour, minute, 0, 0);
  }
  function findLastScheduledTime() {
    const sorted = [...episodeCards()].sort((a, b) => b.episode - a.episode);
    for (const item of sorted) {
      const d = parseScheduledDateFromCard(item.card);
      if (d) return { date: d, episode: item.episode };
    }
    return null;
  }
  let _wakeLock = null;
  let _wakeWanted = false;
  async function acquireWakeLock() {
    if (!('wakeLock' in navigator)) return false;
    try {
      _wakeLock = await navigator.wakeLock.request('screen');
      _wakeLock.addEventListener('release', () => { _wakeLock = null; });
      return true;
    } catch (_) { return false; }
  }
  async function releaseWakeLock() {
    _wakeWanted = false;
    if (_wakeLock) { try { await _wakeLock.release(); } catch (_) {} _wakeLock = null; }
  }
  const onVisibility = async () => {
    if (_wakeWanted && document.visibilityState === 'visible' && _wakeLock === null) {
      await acquireWakeLock();
    }
  };
  document.addEventListener('visibilitychange', onVisibility);
  function playDoneSound() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      [523.25, 659.25, 783.99].forEach((freq, i) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.type = 'sine';
        osc.frequency.value = freq;
        const start = ctx.currentTime + i * 0.18;
        gain.gain.setValueAtTime(0, start);
        gain.gain.linearRampToValueAtTime(0.4, start + 0.04);
        gain.gain.linearRampToValueAtTime(0, start + 0.28);
        osc.start(start);
        osc.stop(start + 0.3);
      });
    } catch (_) {}
  }
  async function tapCancelSelection() {
    const btn = $$('button,[role="button"],a,div,span')
      .filter(visible)
      .filter(el => !isOwnUI(el))
      .filter(el => /^[×✕✖xX]?ยกเลิก(การ)?เลือก$/.test(clean(txt(el))))
      .sort((a, b) => txt(a).length - txt(b).length)[0];
    if (!btn) return false;
    await tap(btn);
    try {
      await waitFor(() => selected().length === 0, 2000);
      return true;
    } catch (_) {
      return false;
    }
  }
  async function setCheckbox(episode, want) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const item = findEpisode(episode);
      if (!item) return false;
      if (isChecked(item.cb) === want) return true;
      await tap(item.cb);
      try {
        await waitFor(() => {
          const now = findEpisode(episode);
          return now && isChecked(now.cb) === want;
        }, 1200);
        return true;
      } catch (_) {}
    }
    return false;
  }
  async function selectOnly(episode) {
    await waitFor(() => findEpisode(episode), 5000, `ไม่พบตอน ${episode} บนหน้าปัจจุบัน`);
    for (let round = 0; round < 6; round++) {
      const current = selected();
      const extras = current.filter(item => item.episode !== episode);
      const targetOn = current.some(item => item.episode === episode);
      if (targetOn && extras.length === 0) return;
      if (extras.length >= 3) {
        await tapCancelSelection();
      } else {
        for (const extra of extras) await setCheckbox(extra.episode, false);
      }
      if (!selected().some(item => item.episode === episode)) {
        await setCheckbox(episode, true);
      }
      await sleep(SPEED.selectOnlyPauseMs);
    }
    const left = selected().map(item => item.episode);
    throw retryable(
      `เลือกตอน ${episode} เพียงตอนเดียวไม่สำเร็จ` +
      (left.length ? ` (ค้างอยู่: ${left.join(', ')})` : '')
    );
  }
  const CONFIRM_RE = /^(ยืนยันตั้งเวลา|ยืนยัน|ตกลง|ทำสิ่งนี้เลยสิ)(\d+ตอน)?$/;
  const isConfirmLabel = el => CONFIRM_RE.test(clean(txt(el)));
  function modal() {
    const hasConfirm = t =>
      t.includes('ยืนยันตั้งเวลา') || t.includes('กำหนดเวลาเผยแพร่') || t.includes('ทำสิ่งนี้เลยสิ');
    const dialog = $$('[role="dialog"]').filter(visible).find(el => {
      const t = txt(el);
      return t.includes('ตั้งเวลาเผยแพร่') && hasConfirm(t);
    });
    if (dialog) return dialog;
    const titles = $$('h1,h2,h3,h4,div,span')
      .filter(visible)
      .filter(el => clean(txt(el)) === 'ตั้งเวลาเผยแพร่');
    for (const title of titles) {
      for (let el = title, i = 0; el && i < 10; el = el.parentElement, i++) {
        if (hasConfirm(txt(el))) return el;
      }
    }
    return null;
  }
  async function openModal() {
    const matchesScheduleLabel = el => {
      const t = clean(txt(el));
      return t === 'ตั้งเวลา' || (t.endsWith('ตั้งเวลา') && t.length <= 12);
    };
    const fromActionBar = () => {
      const bars = $$('div,section,footer,nav,aside')
        .filter(visible)
        .filter(el => !isOwnUI(el))
        .filter(el => {
          const t = txt(el);
          return /เลือกแล้ว\s*\d+\s*ตอน/.test(t) && t.includes('ตั้งเวลา') && t.length < 1600;
        })
        .sort((a, b) => a.textContent.length - b.textContent.length);
      for (const bar of bars) {
        const hit = $$('button,[role="button"],a,div,span', bar)
          .filter(visible)
          .filter(el => !isOwnUI(el))
          .filter(matchesScheduleLabel)
          .sort((a, b) => txt(a).length - txt(b).length)[0];
        if (hit) return hit;
      }
      return null;
    };
    const globalFallback = () => $$('button,[role="button"],a')
      .filter(visible)
      .filter(el => !isOwnUI(el))
      .filter(matchesScheduleLabel)
      .filter(el => !cardFor(el))
      .sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top)[0] || null;
    const button = await waitFor(
      () => fromActionBar() || globalFallback(),
      8000,
      'ไม่พบปุ่ม "ตั้งเวลา" บนแถบคำสั่งของ MyNovel'
    );
    await tap(button);
    return await waitFor(modal, 5000, 'กดปุ่มตั้งเวลาแล้ว แต่หน้าต่างตั้งเวลายังไม่เปิด');
  }
  async function closeOldModal() {
    const old = modal();
    if (!old) return;
    const cancel = buttonByText('ยกเลิก', old, true) ||
      buttonByText('ยกเลิก', old) || buttonByText('ปิด', old);
    if (cancel) {
      await tap(cancel);
      try { await waitFor(() => !modal(), 2500); } catch (_) {}
    }
  }
  const PLACEHOLDER_RE = /^เลือกวัน/;
  function fieldText(el) {
    if (!el) return '';
    const norm = v => String(v || '').replace(/\s+/g, ' ').trim();
    if (el.tagName === 'INPUT') return norm(el.value);
    const inner = $$('input', el).filter(visible)[0];
    if (inner && inner.value) return norm(inner.value);
    return norm(txt(el));
  }
  function findDateField(scheduleModal, cached) {
    if (cached && cached.isConnected && visible(cached)) return cached;
    if (!scheduleModal) return null;
    const byPlaceholder = $$('button,[role="button"],input,label,div,span,p', scheduleModal)
      .filter(visible)
      .filter(el => {
        const t = clean(txt(el)) || clean(el.placeholder);
        return t.includes('เลือกวัน') && t.includes('เวลา') && !t.includes('กรุณา');
      })
      .sort((a, b) => txt(a).length - txt(b).length)[0];
    if (byPlaceholder) {
      return byPlaceholder.closest('button,[role="button"]') || byPlaceholder;
    }
    const label = $$('label,div,span,p', scheduleModal)
      .filter(visible)
      .filter(el => /^กำหนดเวลาเผยแพร่\*?$/.test(clean(txt(el))))
      .sort((a, b) => txt(a).length - txt(b).length)[0];
    if (label) {
      for (let box = label.parentElement, i = 0; box && i < 4; box = box.parentElement, i++) {
        const btn = $$('button,[role="button"],input', box)
          .filter(visible)
          .filter(el => !isConfirmLabel(el) && clean(txt(el)) !== 'ยกเลิก')[0];
        if (btn) return btn;
      }
    }
    return null;
  }
  function fieldIsFilled(el) {
    const t = fieldText(el);
    if (!t || PLACEHOLDER_RE.test(t)) return false;
    return /\d{1,2}[:：]\d{2}/.test(t);
  }
  function fieldTimeMatches(el, target) {
    const match = fieldText(el).replace(/：/g, ':').match(/(\d{1,2}):(\d{2})/);
    if (!match) return false;
    return Number(match[1]) === target.getHours() && Number(match[2]) === target.getMinutes();
  }
  function fieldDateEquals(el, target) {
    const text = fieldText(el);
    if (!text) return false;
    const day = target.getDate();
    const month = target.getMonth();
    const yearCE = target.getFullYear();
    const yearBE = yearCE + 543;
    const withoutTime = text.replace(/\d{1,2}[:：]\d{2}(?:[:：]\d{2})?/g, ' ');
    const numeric = withoutTime.match(/(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{1,4})/);
    if (numeric) {
      const [, a, b, c] = numeric.map(Number);
      return (a === day && b === month + 1 && (c === yearCE || c === yearBE)) ||
        ((a === yearCE || a === yearBE) && b === month + 1 && c === day);
    }
    const en = withoutTime.match(MONTH_EN_RE);
    const th = withoutTime.match(MONTH_TH_RE);
    const named = en ? MONTHS_EN[en[1].toLowerCase()] : (th ? MONTHS_TH[th[1]] : null);
    if (named === null || named === undefined || named !== month) return false;
    const years = (withoutTime.match(/\d{4}/g) || []).map(Number).filter(y => y >= 1900);
    return new RegExp(`(?:^|\\D)0?${day}(?:\\D|$)`).test(withoutTime) &&
      (!years.length || years.some(y => y === yearCE || y === yearBE));
  }
  function fieldDateConflict(el, target) {
    const text = fieldText(el);
    if (!text) return null;
    const day = target.getDate();
    const month = target.getMonth();
    const yearCE = target.getFullYear();
    const yearBE = yearCE + 543;
    const withoutTime = text.replace(/\d{1,2}[:：]\d{2}(?:[:：]\d{2})?/g, ' ');
    const years = (withoutTime.match(/\d{4}/g) || []).map(Number).filter(y => y >= 1900);
    if (years.length && !years.some(y => y === yearCE || y === yearBE)) {
      return `ปีในช่องคือ ${years.join('/')} แต่ต้องการ ${yearCE} (พ.ศ. ${yearBE})`;
    }
    const en = withoutTime.match(MONTH_EN_RE);
    if (en && MONTHS_EN[en[1].toLowerCase()] !== month) {
      return `เดือนในช่องคือ ${en[1]} แต่ต้องการ ${MONTHS_EN_NAMES[month]}`;
    }
    const th = withoutTime.match(MONTH_TH_RE);
    if (th && MONTHS_TH[th[1]] !== month) {
      return `เดือนในช่องคือ ${th[1]} แต่ต้องการ ${MONTHS_TH_NAMES[month]}`;
    }
    const numeric = withoutTime.match(/(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{1,4})/);
    if (numeric) {
      const [, a, b, c] = numeric.map(Number);
      const dmy = a === day && b === month + 1 && (c === yearCE || c === yearBE || c === yearCE % 100);
      const ymd = (a === yearCE || a === yearBE) && b === month + 1 && c === day;
      if (!dmy && !ymd) {
        return `วันในช่องคือ "${numeric[0]}" แต่ต้องการ ${day}/${month + 1}/${yearCE}`;
      }
    }
    return null;
  }
  const NON_TEXT_INPUT = ['date', 'datetime-local', 'checkbox', 'radio', 'hidden', 'search', 'button', 'file'];
  function looksLikeCalendar(el) {
    let count = 0;
    for (const cell of el.querySelectorAll('button,[role="gridcell"],td,div,span')) {
      if (cell.children.length > 1) continue;
      if (/^\d{1,2}$/.test((cell.textContent || '').trim())) count++;
      if (count >= 25) return true;
    }
    return false;
  }
  function picker() {
    const inputs = $$('input')
      .filter(i => !NON_TEXT_INPUT.includes(i.type))
      .filter(visible)
      .filter(i => !isOwnUI(i));
    const seen = new Set();
    const found = [];
    for (const input of inputs) {
      let el = input.parentElement;
      for (let depth = 0; el && depth < 9; el = el.parentElement, depth++) {
        if (seen.has(el)) continue;
        seen.add(el);
        const text = el.textContent || '';
        if (text.length > 2500) break;
        if (!MONTH_EN_RE.test(text) && !MONTH_TH_RE.test(text)) continue;
        if (!visible(el) || isOwnUI(el)) continue;
        const own = $$('input', el).filter(visible).filter(i => !NON_TEXT_INPUT.includes(i.type));
        if (own.length < 2 && !own.some(i => i.type === 'time')) continue;
        if (!looksLikeCalendar(el)) continue;
        found.push(el);
      }
    }
    return found.sort(byArea)[0] || null;
  }
  function pickerMonthYear(datePicker) {
    const text = txt(datePicker);
    const en = text.match(
      /\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b/i
    );
    if (en) return { month: MONTHS_EN[en[1].toLowerCase()], year: Number(en[2]) };
    const th = text.match(new RegExp(MONTH_TH_RE.source + '\\s*(\\d{4})'));
    if (th) {
      const year = Number(th[2]);
      return { month: MONTHS_TH[th[1]], year: year >= 2400 ? year - 543 : year };
    }
    return null;
  }
  function monthNavButtons(root) {
    const btns = $$('button,[role="button"]', root).filter(visible).filter(enabled);
    const label = b => [
      b.getAttribute('aria-label'), b.getAttribute('name'),
      b.className, b.id, txt(b)
    ].join(' ').toLowerCase();
    let prev = btns.find(b => /previous|prev|ก่อนหน้า|ย้อนกลับ/.test(label(b)));
    let next = btns.find(b => b !== prev && /next|ถัดไป|ต่อไป/.test(label(b)));
    if (!prev || !next) {
      const icons = btns
        .filter(b => !txt(b) && $$('svg,img', b).length)
        .sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left);
      if (icons.length >= 2) {
        prev = prev || icons[0];
        next = next || icons[icons.length - 1];
      }
    }
    return { prev, next };
  }
  function dayButtonInPicker(datePicker, dayNumber) {
    const day = String(dayNumber);
    const rank = el => {
      const cls = String(el.className || '');
      const outside = /outside|muted|disabled|other-month/i.test(cls) ? 4 : 0;
      if (el.tagName === 'BUTTON' || el.getAttribute('role') === 'button') return outside;
      if (el.tagName === 'TD' || el.getAttribute('role') === 'gridcell') return outside + 2;
      return outside + 1;
    };
    return uniq(
      $$('button,[role="button"],[role="gridcell"],td,div,span', datePicker)
        .filter(visible)
        .filter(el => txt(el) === day)
        .map(el => el.querySelector('button,[role="button"]') || el)
    )
      .filter(enabled)
      .sort((a, b) => rank(a) - rank(b) || byArea(a, b))[0] || null;
  }
  function isDaySelected(datePicker, dayNumber) {
    const btn = dayButtonInPicker(datePicker, dayNumber);
    if (!btn) return false;
    if (btn.getAttribute('aria-selected') === 'true') return true;
    if (btn.getAttribute('aria-pressed') === 'true') return true;
    if (btn.dataset.selected === 'true' || btn.dataset.selectedSingle === 'true') return true;
    if (btn.dataset.state === 'selected' || btn.dataset.state === 'on') return true;
    const cls = String(btn.className || '');
    return /(?:^|[\s_-])(?:day_|rdp-)?(?:selected|active)(?:[\s_-]|$)/i.test(cls) ||
      /(?:^|\s)bg-primary(?:[/\s]|$)/.test(cls);
  }
  function daySignature(btn) {
    if (!btn) return '';
    let bg = '';
    try { bg = getComputedStyle(btn).backgroundColor; } catch (_) {}
    return [
      btn.className, bg,
      btn.getAttribute('aria-selected'), btn.getAttribute('aria-pressed'),
      btn.dataset.state, btn.dataset.selected, btn.dataset.selectedSingle
    ].join('|');
  }
  function setNative(field, value) {
    const proto = field instanceof HTMLSelectElement
      ? HTMLSelectElement.prototype
      : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    if (setter) setter.call(field, String(value));
    else field.value = String(value);
    field.dispatchEvent(new Event('input', { bubbles: true }));
    field.dispatchEvent(new Event('change', { bubbles: true }));
  }
  function timeFieldsIn(root) {
    const timeInput = $$('input[type="time"]', root).filter(visible)[0];
    if (timeInput) return { kind: 'time', timeInput };
    const skip = ['date', 'datetime-local', 'checkbox', 'radio', 'hidden', 'search', 'button'];
    const inputs = $$('input', root).filter(visible).filter(i => !skip.includes(i.type));
    const selects = $$('select', root).filter(visible);
    const hint = field => [
      field.getAttribute('aria-label'), field.name, field.id, field.placeholder,
      field.getAttribute('data-unit'), txt(field.closest('label')), txt(field.parentElement)
    ].join(' ').toLowerCase();
    const score = (field, kind) => {
      const hay = hint(field);
      const max = Number(field.getAttribute('max'));
      let s = 0;
      if (kind === 'hour') {
        if (/hour|hh|ชั่วโมง|ชม/.test(hay)) s += 10;
        if (max === 23 || max === 12) s += 6;
      } else {
        if (/minute|\bmin\b|mm|นาที/.test(hay)) s += 10;
        if (max === 59) s += 6;
      }
      return s;
    };
    const pick = (pool, kind, exclude) => pool
      .filter(f => f !== exclude)
      .map(f => [score(f, kind), f])
      .filter(pair => pair[0] > 0)
      .sort((a, b) => b[0] - a[0])
      .map(pair => pair[1])[0] || null;
    if (selects.length >= 2) {
      const hour = pick(selects, 'hour', null) || selects[selects.length - 2];
      const minute = pick(selects, 'minute', hour) || selects[selects.length - 1];
      if (hour && minute && hour !== minute) return { kind: 'pair', hour, minute };
    }
    let hour = pick(inputs, 'hour', null);
    let minute = pick(inputs, 'minute', hour);
    if (!hour || !minute) {
      if (inputs.length < 2) return null;
      hour = inputs[inputs.length - 2];
      minute = inputs[inputs.length - 1];
    }
    return { kind: 'pair', hour, minute };
  }
  async function setTimeInPicker(datePicker, target) {
    const hour = String(target.getHours()).padStart(2, '0');
    const minute = String(target.getMinutes()).padStart(2, '0');
    for (let attempt = 0; attempt < 2; attempt++) {
      const fields = timeFieldsIn(datePicker);
      if (!fields) throw retryable('ไม่พบช่องชั่วโมงและนาทีในปฏิทิน');
      if (fields.kind === 'time') {
        setNative(fields.timeInput, `${hour}:${minute}`);
        await sleep(SPEED.afterSetNativeMs);
        if (fields.timeInput.value.startsWith(`${hour}:${minute}`)) return true;
        continue;
      }
      setNative(fields.hour, hour);
      await sleep(SPEED.afterSetHourMs);
      setNative(fields.minute, minute);
      await sleep(SPEED.afterSetNativeMs);
      const ok = Number(fields.hour.value) === target.getHours() &&
        Number(fields.minute.value) === target.getMinutes();
      if (ok) return true;
    }
    return false;
  }
  async function openPicker(dateField) {
    const already = picker();
    if (already) return already;
    await tap(dateField, { scroll: false });
    return await waitFor(picker, 5000, 'กดช่องวันเวลาแล้ว แต่ MyNovel ไม่เปิดปฏิทิน');
  }
  async function gotoTargetMonth(target) {
    for (let step = 0; step < 26; step++) {
      const p = picker();
      if (!p) throw retryable('ปฏิทินปิดไปก่อนที่จะเลือกวัน');
      const current = pickerMonthYear(p);
      if (!current) return p;
      const diff = (target.getFullYear() * 12 + target.getMonth()) -
        (current.year * 12 + current.month);
      if (diff === 0) return p;
      const nav = monthNavButtons(p);
      const btn = diff > 0 ? nav.next : nav.prev;
      if (!btn) {
        throw retryable(
          `ปฏิทินอยู่เดือน ${current.month + 1}/${current.year} ` +
          `แต่ต้องการ ${target.getMonth() + 1}/${target.getFullYear()} และไม่พบปุ่มเลื่อนเดือน`
        );
      }
      await tap(btn, { scroll: false });
      await settle(() => {
        const q = picker();
        const c = q && pickerMonthYear(q);
        return !q || !c || c.year !== current.year || c.month !== current.month;
      });
      await sleep(SPEED.afterMonthNavMs);
    }
    throw retryable('เลื่อนเดือนในปฏิทินไปไม่ถึงเดือนเป้าหมาย');
  }
  async function pickDay(target, dateField) {
    const day = target.getDate();
    const before = picker();
    if (!before) return true;
    if (fieldDateEquals(dateField, target)) return true;
    if (fieldIsFilled(dateField) && isDaySelected(before, day)) return true;
    const btn = dayButtonInPicker(before, day);
    if (!btn) throw retryable(`ไม่พบวันที่ ${day} ในปฏิทิน`);
    const signature = daySignature(btn);
    await tap(btn, { scroll: false });
    await settle(() => {
      const p = picker();
      if (!p) return true;
      if (fieldIsFilled(dateField)) return true;
      if (isDaySelected(p, day)) return true;
      const fresh = dayButtonInPicker(p, day);
      return !!fresh && daySignature(fresh) !== signature;
    });
    await sleep(SPEED.afterPickDayMs);
    const after = picker();
    if (!after) return true;
    if (fieldIsFilled(dateField)) return true;
    if (isDaySelected(after, day)) return true;
    const fresh = dayButtonInPicker(after, day);
    return !!fresh && daySignature(fresh) !== signature;
  }
  function pressEscape() {
    const options = { bubbles: true, cancelable: true, key: 'Escape', code: 'Escape', keyCode: 27, which: 27 };
    try { document.activeElement?.blur?.(); } catch (_) {}
    for (const type of ['keydown', 'keyup']) {
      try { document.dispatchEvent(new KeyboardEvent(type, options)); } catch (_) {}
    }
  }
  async function closePickerSafely(scheduleModal) {
    if (!picker()) return;
    const anchor = $$('h1,h2,h3,h4,p,div,span', scheduleModal)
      .filter(visible)
      .filter(el => clean(txt(el)).startsWith('ตั้งเวลาเผยแพร่'))
      .sort((a, b) => txt(a).length - txt(b).length)[0];
    if (anchor) {
      fireMouseSequence(anchor);
      try {
        await waitFor(() => !picker(), 1000);
        return;
      } catch (_) {}
    }
    pressEscape();
    try { await waitFor(() => !picker(), 1500); } catch (_) {}
    if (!modal()) throw retryable('ปฏิทินปิดพร้อมหน้าต่างตั้งเวลา จะเปิดใหม่');
  }
  async function waitOutcome(episode, target, timeout = 10000) {
    try {
      return await waitFor(() => {
        if (episodeLooksScheduled(episode, target)) return 'ok';
        const body = txt(document.body);
        if (/ตั้งเวลาเผยแพร่\s*\d*\s*ตอน\s*(สำเร็จ|เสร็จแล้ว|เรียบร้อย)|ตั้งเวลาเผยแพร่สำเร็จ/.test(body)) {
          return 'ok';
        }
        const live = modal();
        if (!live) return 'closed';
        if (/กรุณาเลือกวันและเวลา/.test(txt(live)) && !fieldIsFilled(findDateField(live, null))) {
          return 'rejected';
        }
        return null;
      }, timeout);
    } catch (_) {
      return 'timeout';
    }
  }
  async function applySchedule(scheduleModal, target, episode, attempt) {
    const dateField = await waitFor(
      () => findDateField(scheduleModal, null),
      4000,
      'ไม่พบช่องเลือกวันและเวลา'
    );
    const timeFirst = attempt < 3;
    await openPicker(dateField);
    await gotoTargetMonth(target);
    if (timeFirst) {
      await setTimeInPicker(picker(), target);
      await pickDay(target, dateField);
    } else {
      await pickDay(target, dateField);
      const open = picker() || await openPicker(dateField);
      await setTimeInPicker(open, target);
    }
    if (fieldIsFilled(dateField) && !fieldTimeMatches(dateField, target) && picker()) {
      await setTimeInPicker(picker(), target);
      await settle(() => fieldTimeMatches(dateField, target), 800);
    }
    await closePickerSafely(scheduleModal);
    await sleep(SPEED.afterClosePickerMs);
    const liveModal = await waitFor(modal, 4000, 'หน้าต่างตั้งเวลาหายไปก่อนกดยืนยัน');
    await settle(() => {
      const f = findDateField(liveModal, dateField);
      return fieldIsFilled(f) && fieldTimeMatches(f, target);
    }, 800);
    const field = findDateField(liveModal, dateField);
    if (!fieldIsFilled(field)) {
      throw retryable(`MyNovel ยังไม่รับวันเวลา (ช่องแสดง: "${fieldText(field) || 'ว่าง'}")`);
    }
    if (!fieldTimeMatches(field, target)) {
      throw retryable(
        `เวลาในช่องไม่ตรงเป้าหมาย ต้องการ ${timeText(target)} แต่ช่องแสดง "${fieldText(field)}"`
      );
    }
    const dateConflict = fieldDateConflict(field, target);
    if (dateConflict) throw retryable(`วันที่ในช่องไม่ตรงเป้าหมาย: ${dateConflict}`);
    const confirm = await waitFor(
      () => uniq(
        $$('button,[role="button"],a,div,span', liveModal)
          .filter(visible)
          .filter(isConfirmLabel)
          .map(el => el.closest('button,[role="button"],a') || el)
      )
        .filter(enabled)
        .sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top)[0] || null,
      4000,
      'ปุ่มยืนยันตั้งเวลายังไม่พร้อม'
    );
    await tap(confirm);
    const outcome = await waitOutcome(episode, target, 10000);
    if (outcome === 'ok') return 'ok';
    if (outcome === 'closed') {
      try { await waitFor(() => episodeLooksScheduled(episode, target), 2500); return 'ok'; } catch (_) {}
      return episodeHasSchedule(episode) ? 'ok-different-time' : 'ok-unverified';
    }
    if (outcome === 'rejected') {
      throw retryable('MyNovel ปฏิเสธ: ช่องวันเวลายังว่างตอนกดยืนยัน');
    }
    if (episodeLooksScheduled(episode, target)) return 'ok';
    return 'ok-unverified';
  }
  function hideOwnUiDuringDialog() {
    const nodes = [document.getElementById(ID), document.getElementById(FAB_ID)].filter(Boolean);
    const saved = nodes.map(el => ({ el, pe: el.style.pointerEvents, op: el.style.opacity }));
    for (const { el } of saved) {
      el.style.pointerEvents = 'none';
      el.style.opacity = '0';
    }
    return () => {
      for (const { el, pe, op } of saved) {
        el.style.pointerEvents = pe;
        el.style.opacity = op;
      }
    };
  }
  function makeTarget(dateValue, timeValue, index, gap) {
    const [year, month, day] = dateValue.split('-').map(Number);
    const [hour, minute] = timeValue.split(':').map(Number);
    return new Date(year, month - 1, day, hour, minute + index * gap, 0, 0);
  }
  function showPanel(panel, fab) {
    panel.dataset.open = '1';
    fab.textContent = '× ซ่อนแผง';
    fab.style.top = '12px';
  }
  function hidePanel(panel, fab) {
    delete panel.dataset.open;
    fab.textContent = '⏱ ตั้งเวลา';
    fab.style.top = '46vh';
  }
  const loadSettings = () => {
    try { return JSON.parse(localStorage.getItem(STORE_KEY)) || {}; } catch (_) { return {}; }
  };
  const saveSettings = data => {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(data)); } catch (_) {}
  };

  // ─── Multi-novel helpers ───────────────────────────────────────────────────
  const loadMultiJobs = () => {
    try { return JSON.parse(localStorage.getItem(MULTI_KEY)) || []; } catch (_) { return []; }
  };
  const saveMultiJobs = jobs => {
    try { localStorage.setItem(MULTI_KEY, JSON.stringify(jobs)); } catch (_) {}
  };
  function matchesCurrentUrl(url) {
    try {
      const u = new URL(url, location.origin);
      return u.pathname === location.pathname && u.search === location.search;
    } catch (_) { return false; }
  }
  function getAutoStartJob() {
    return loadMultiJobs().find(j => j.autoStart && matchesCurrentUrl(j.url)) || null;
  }
  function markJobDone(url) {
    const jobs = loadMultiJobs().map(j =>
      matchesCurrentUrl(j.url) || j.url === url
        ? { ...j, autoStart: false, status: 'done' }
        : j
    );
    saveMultiJobs(jobs);
  }
  // ──────────────────────────────────────────────────────────────────────────

  function boot() {
    if (document.getElementById(ID) || document.getElementById(FAB_ID)) return;
    const fab = document.createElement('button');
    fab.id = FAB_ID;
    fab.type = 'button';
    fab.textContent = '⏱ ตั้งเวลา';
    Object.assign(fab.style, {
      position: 'fixed',
      right: '0',
      top: '46vh',
      bottom: 'auto',
      zIndex: '2147483647',
      minWidth: '108px',
      minHeight: '48px',
      padding: '10px 12px',
      border: '2px solid #fff',
      borderRight: '0',
      borderRadius: '12px 0 0 12px',
      background: '#1596f5',
      color: '#fff',
      boxShadow: '0 8px 24px rgba(0,0,0,.35)',
      fontFamily: 'system-ui,-apple-system,"Noto Sans Thai",sans-serif',
      fontSize: '14px',
      fontWeight: '900'
    });
    for (const [prop, value] of [['display', 'block'], ['visibility', 'visible'],
      ['opacity', '1'], ['pointer-events', 'auto']]) {
      fab.style.setProperty(prop, value, 'important');
    }
    const host = document.createElement('div');
    host.id = ID;
    host.innerHTML = `
<style>
#${ID}{position:fixed!important;right:12px!important;bottom:14px!important;z-index:2147483647!important;width:min(360px,calc(100vw - 24px))!important;font-family:system-ui,-apple-system,"Noto Sans Thai",sans-serif!important;display:none!important}
#${ID}[data-open="1"]{display:block!important}
#${ID} .box{background:#fff!important;border:2px solid #1596f5!important;border-radius:14px!important;box-shadow:0 16px 48px rgba(0,0,0,.36)!important;overflow:hidden!important}
#${ID} .head{display:flex!important;align-items:center!important;justify-content:space-between!important;padding:10px 12px!important;background:#edf8ff!important;color:#12365a!important;font-size:14px!important;font-weight:900!important}
#${ID} .close{width:36px!important;height:36px!important;border:0!important;border-radius:9px!important;background:#fff!important;color:#1c5f96!important;font-size:20px!important;font-weight:900!important}
#${ID} .body{padding:12px!important;max-height:calc(100vh - 90px)!important;overflow-y:auto!important}
#${ID} .row{display:grid!important;grid-template-columns:1fr 1fr!important;gap:8px!important}
#${ID} label{display:block!important;margin:7px 0 4px!important;color:#40536a!important;font-size:12px!important;font-weight:800!important}
#${ID} input,#${ID} select{box-sizing:border-box!important;width:100%!important;padding:9px!important;border:1px solid #cfdae7!important;border-radius:9px!important;background:#fbfdff!important;color:#142033!important;font:inherit!important}
#${ID} button.action{width:100%!important;min-height:42px!important;margin-top:9px!important;padding:10px!important;border:0!important;border-radius:10px!important;font:inherit!important;font-weight:900!important}
#${ID} .scan{background:#edf4fa!important;color:#27425d!important}
#${ID} .detect{background:#e8f5e9!important;color:#1b5e20!important;border:1px solid #a5d6a7!important}
#${ID} .start{background:#1596f5!important;color:#fff!important}
#${ID} .stop{background:#fff2f1!important;color:#a61b14!important;border:1px solid #efcbc8!important}
#${ID} button.action:disabled{opacity:.55!important}
#${ID} .diag{background:#fff8e1!important;color:#7a5200!important;border:1px solid #ffe08a!important}
#${ID} textarea.diag-out{display:none!important;box-sizing:border-box!important;width:100%!important;height:110px!important;margin-top:8px!important;padding:8px!important;border:1px solid #cfdae7!important;border-radius:9px!important;font:11px/1.35 monospace!important;color:#142033!important;background:#fbfdff!important}
#${ID} textarea.diag-out[data-show="1"]{display:block!important}
#${ID} .note{margin-top:7px!important;color:#52647a!important;font-size:11px!important;line-height:1.4!important}
#${ID} .status{max-height:132px!important;margin-top:8px!important;padding:8px!important;border-radius:9px!important;background:#102035!important;color:#e8f3ff!important;font-size:12px!important;line-height:1.5!important;overflow-y:auto!important;white-space:pre-line!important}
#${ID} .speed-row{display:grid!important;grid-template-columns:1fr 1fr!important;gap:8px!important;margin-top:4px!important}
#${ID} .check{display:flex!important;align-items:center!important;gap:6px!important;margin-top:6px!important;cursor:pointer!important}
#${ID} .check input{width:auto!important;margin:0!important}
#${ID} .check span{font-size:12px!important;font-weight:700!important;color:#40536a!important}
#${ID} .divider{border:0!important;border-top:1px solid #d8e6f0!important;margin:10px 0!important}
#${ID} details summary{cursor:pointer!important;font-size:13px!important;font-weight:900!important;color:#1c5f96!important;padding:4px 0!important;list-style:none!important}
#${ID} details summary::-webkit-details-marker{display:none!important}
#${ID} details summary::before{content:"▶ "!important;font-size:10px!important}
#${ID} details[open] summary::before{content:"▼ "!important}
#${ID} .multi-list{max-height:150px!important;overflow-y:auto!important;margin:6px 0!important}
#${ID} .multi-item{display:flex!important;align-items:center!important;gap:6px!important;padding:5px 4px!important;border-bottom:1px solid #eef2f6!important;font-size:11px!important}
#${ID} .multi-item .mi-url{flex:1!important;overflow:hidden!important;text-overflow:ellipsis!important;white-space:nowrap!important;color:#142033!important}
#${ID} .multi-item .mi-status{font-weight:900!important;min-width:14px!important}
#${ID} .mi-del{border:0!important;background:#fee!important;color:#c00!important;border-radius:4px!important;padding:2px 6px!important;font-size:10px!important;cursor:pointer!important;min-height:auto!important;width:auto!important;margin:0!important}
#${ID} .url-row{display:flex!important;gap:6px!important;margin-top:4px!important}
#${ID} .url-row input{flex:1!important;font-size:11px!important;padding:7px!important}
#${ID} .url-row button{width:auto!important;min-height:34px!important;margin:0!important;padding:7px 10px!important;font-size:11px!important}
#${ID} .launch{background:#0b7c3e!important;color:#fff!important}
</style>
<div class="box">
  <div class="head">
    <span>MyNovel ตั้งเวลาอัตโนมัติ v${VERSION}</span>
    <button class="close" id="mn-close">×</button>
  </div>
  <div class="body">
    <div class="row">
      <div><label>วันเริ่ม</label><input id="mn-date" type="date"></div>
      <div><label>เวลาเริ่ม</label><input id="mn-time" type="time" value="17:00"></div>
    </div>
    <div class="speed-row">
      <div>
        <label>ห่างกัน (นาที)</label>
        <input id="mn-gap" type="number" min="1" max="1440" value="15">
      </div>
      <div>
        <label>ความเร็ว</label>
        <select id="mn-speed">
          <option value="normal">ปกติ (~4 วิ/ตอน)</option>
          <option value="fast">เร็ว (~2 วิ/ตอน)</option>
          <option value="turbo">เร็วสุด (~1 วิ/ตอน)</option>
          <option value="ultra" selected>ปุ๊บปุ๊บ (~0.5 วิ/ตอน)</option>
        </select>
      </div>
    </div>
    <label class="check">
      <input type="checkbox" id="mn-adaptive" checked>
      <span>ปรับความเร็วอัตโนมัติ (ช้าลงเมื่อพลาด / เร็วขึ้นเมื่อไหลลื่น)</span>
    </label>
    <label class="check">
      <input type="checkbox" id="mn-skip-error" checked>
      <span>ข้ามตอนที่ error แล้วทำต่อ</span>
    </label>
    <label class="check">
      <input type="checkbox" id="mn-wakelock" checked>
      <span>กันหน้าจอพัก (Wake Lock) ⚠️ อย่าสลับแอป</span>
    </label>
    <div class="note">เลือกตอนใน MyNovel แล้วกดเริ่ม — สคริปต์ไล่ตั้งจากล่างขึ้นบน<br>⚠️ ต้องคาหน้าเบราว์เซอร์ไว้ สลับแอปอื่น JS จะหยุดทำงาน</div>
    <button class="action scan" id="mn-scan">ตรวจตอนที่เลือก</button>
    <button class="action detect" id="mn-detect">ตรวจหาเวลาต่อจากตอนที่ตั้งไว้</button>
    <button class="action diag" id="mn-diag">🔍 วินิจฉัยหน้าเว็บ (เปิดหน้าต่างตั้งเวลาค้างไว้ก่อนกด)</button>
    <textarea class="diag-out" id="mn-diag-out" readonly></textarea>
    <button class="action start" id="mn-start">เริ่มตั้งเวลา</button>
    <button class="action stop" id="mn-stop">หยุดหลังตอนปัจจุบัน</button>
    <div class="status" id="mn-status">พร้อมใช้งาน — เลือกตอนใน MyNovel แล้วกดเริ่ม</div>

    <hr class="divider">
    <details id="mn-multi-details">
      <summary>📚 หลายเรื่องพร้อมกัน</summary>
      <div style="margin-top:8px">
        <div class="multi-list" id="mn-multi-list"></div>
        <div class="url-row">
          <input id="mn-novel-url" type="url" placeholder="วาง URL หน้าตอน (mynovel.co/dashboard/...)">
          <button class="action scan" id="mn-novel-add">+ เพิ่ม</button>
        </div>
        <label class="check" style="margin-top:8px">
          <input type="checkbox" id="mn-auto-select" checked>
          <span>เลือกตอนที่ยังไม่มีกำหนดเผยแพร่อัตโนมัติ</span>
        </label>
        <label class="check">
          <input type="checkbox" id="mn-auto-detect" checked>
          <span>ตรวจหาเวลาต่อจากที่ตั้งไว้อัตโนมัติ</span>
        </label>
        <label class="check">
          <input type="checkbox" id="mn-auto-run" checked>
          <span>เริ่มตั้งเวลาอัตโนมัติทันที</span>
        </label>
        <button class="action launch" id="mn-launch-all">🚀 เตรียมลิงก์ทุกเรื่อง</button>
        <button class="action stop" id="mn-clear-jobs" style="margin-top:4px">🗑 ล้างรายการ</button>
        <div id="mn-link-box" style="display:none;margin-top:8px;padding:6px;background:#f0f7ff;border:1px solid #90caf9;border-radius:9px"></div>
        <div class="note">กด "เตรียมลิงก์" แล้วแตะแต่ละลิงก์เพื่อเปิดแท็บใหม่ — แต่ละแท็บเริ่มอัตโนมัติ</div>
      </div>
    </details>
  </div>
</div>`;
    document.documentElement.appendChild(fab);
    document.documentElement.appendChild(host);
    const tabKeeper = new MutationObserver(() => {
      if (!fab.isConnected) document.documentElement.appendChild(fab);
      if (!host.isConnected) document.documentElement.appendChild(host);
    });
    tabKeeper.observe(document.documentElement, { childList: true });
    window.__MN_SCHEDULER_CLEANUP__ = () => {
      tabKeeper.disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
      fab.remove();
      host.remove();
      if (_timerWorker) { try { _timerWorker.terminate(); } catch(_){} }
    };
    const dateInput = host.querySelector('#mn-date');
    const timeInput = host.querySelector('#mn-time');
    const gapInput = host.querySelector('#mn-gap');
    const speedSelect = host.querySelector('#mn-speed');
    const adaptiveCheck = host.querySelector('#mn-adaptive');
    const skipErrorCheck = host.querySelector('#mn-skip-error');
    const wakeLockCheck = host.querySelector('#mn-wakelock');
    const scanButton = host.querySelector('#mn-scan');
    const detectButton = host.querySelector('#mn-detect');
    const startButton = host.querySelector('#mn-start');
    const diagButton = host.querySelector('#mn-diag');
    const diagOut = host.querySelector('#mn-diag-out');
    const stopButton = host.querySelector('#mn-stop');
    const closeButton = host.querySelector('#mn-close');
    const statusBox = host.querySelector('#mn-status');
    // multi-novel elements
    const novelUrlInput = host.querySelector('#mn-novel-url');
    const novelAddBtn = host.querySelector('#mn-novel-add');
    const multiListEl = host.querySelector('#mn-multi-list');
    const launchAllBtn = host.querySelector('#mn-launch-all');
    const clearJobsBtn = host.querySelector('#mn-clear-jobs');
    const autoSelectCheck = host.querySelector('#mn-auto-select');
    const autoDetectCheck = host.querySelector('#mn-auto-detect');
    const autoRunCheck = host.querySelector('#mn-auto-run');

    const saved = loadSettings();
    if (saved.time) timeInput.value = saved.time;
    if (saved.gap) gapInput.value = saved.gap;
    if (saved.speed && SPEED_PROFILES[saved.speed]) speedSelect.value = saved.speed;
    if (typeof saved.adaptive === 'boolean') adaptiveCheck.checked = saved.adaptive;
    if (typeof saved.skip === 'boolean') skipErrorCheck.checked = saved.skip;
    if (typeof saved.wake === 'boolean') wakeLockCheck.checked = saved.wake;
    const persist = () => saveSettings({
      time: timeInput.value,
      gap: Number(gapInput.value) || 15,
      speed: speedSelect.value,
      adaptive: adaptiveCheck.checked,
      skip: skipErrorCheck.checked,
      wake: wakeLockCheck.checked
    });
    [timeInput, gapInput, speedSelect, adaptiveCheck, skipErrorCheck, wakeLockCheck]
      .forEach(el => el.addEventListener('change', persist));
    speedSelect.addEventListener('change', () => setSpeedProfile(speedSelect.value));
    setSpeedProfile(speedSelect.value);
    const lines = [];
    const log = (line, replaceLast = false) => {
      if (replaceLast && lines.length) lines[lines.length - 1] = line;
      else lines.push(line);
      while (lines.length > 14) lines.shift();
      statusBox.textContent = lines.join('\n');
      statusBox.scrollTop = statusBox.scrollHeight;
    };
    const reset = line => { lines.length = 0; log(line); };
    const now = new Date();
    dateInput.value =
      `${now.getFullYear()}-` +
      `${String(now.getMonth() + 1).padStart(2, '0')}-` +
      `${String(now.getDate()).padStart(2, '0')}`;
    fab.onclick = () => {
      if (host.dataset.open === '1') hidePanel(host, fab);
      else showPanel(host, fab);
    };
    closeButton.onclick = () => hidePanel(host, fab);
    let stopRequested = false;
    const getQueue = () => selected()
      .sort((a, b) => b.top - a.top)
      .map(item => item.episode);
    scanButton.onclick = () => {
      const queue = getQueue();
      reset(queue.length
        ? `พบ ${queue.length} ตอน\nลำดับ: ${queue.join(' → ')}`
        : 'ยังไม่พบตอนที่เลือก');
    };
    detectButton.onclick = () => {
      const gap = Math.max(1, Math.min(1440, Number(gapInput.value) || 15));
      const found = findLastScheduledTime();
      if (!found) {
        reset('ไม่พบตอนที่ตั้งเวลาไว้บนหน้านี้');
        return;
      }
      const next = new Date(found.date.getTime() + gap * 60000);
      const yyyy = next.getFullYear();
      const mm = String(next.getMonth() + 1).padStart(2, '0');
      const dd = String(next.getDate()).padStart(2, '0');
      dateInput.value = `${yyyy}-${mm}-${dd}`;
      timeInput.value = `${String(next.getHours()).padStart(2, '0')}:${String(next.getMinutes()).padStart(2, '0')}`;
      persist();
      reset(`ตรวจพบ: ตอน ${found.episode} ตั้งไว้ ${timeText(found.date)}\n→ เริ่มตั้งจาก ${timeText(next)} (+${gap} นาที)`);
    };
    const describeNode = (el, depth, out, maxDepth) => {
      if (out.length > 320 || depth > maxDepth || isOwnUI(el)) return;
      const tag = el.tagName.toLowerCase();
      if (['script', 'style', 'path', 'noscript'].includes(tag)) return;
      if (tag === 'svg') { out.push('  '.repeat(depth) + '<svg>'); return; }
      if (!visible(el)) return;
      const attrs = [];
      for (const name of ['id', 'role', 'type', 'name', 'aria-label', 'aria-selected', 'aria-disabled',
        'data-state', 'data-disabled', 'placeholder', 'inputmode', 'maxlength']) {
        const v = el.getAttribute(name);
        if (v) attrs.push(`${name}="${v.slice(0, 40)}"`);
      }
      if (el.disabled) attrs.push('disabled');
      if (tag === 'input' || tag === 'textarea' || tag === 'select') attrs.push(`value="${el.value}"`);
      const cls = String(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className || '');
      if (cls) attrs.push(`class="${cls.slice(0, 70)}"`);
      const own = [...el.childNodes].filter(n => n.nodeType === 3)
        .map(n => n.textContent.replace(/\s+/g, ' ').trim()).join(' ').trim();
      out.push('  '.repeat(depth) + `<${tag}${attrs.length ? ' ' + attrs.join(' ') : ''}>` +
        (own ? ` "${own.slice(0, 50)}"` : ''));
      for (const child of el.children) describeNode(child, depth + 1, out, maxDepth);
    };
    diagButton.onclick = async () => {
      const out = [`MyNovel Scheduler v${VERSION} diagnostic`, `url: ${location.pathname}`, `ua: ${navigator.userAgent}`];
      const dlg = modal();
      out.push('', `=== MODAL: ${dlg ? 'พบ' : 'ไม่พบ (เปิดหน้าต่างตั้งเวลาก่อนกดปุ่มนี้)'} ===`);
      if (dlg) {
        describeNode(dlg, 0, out, 9);
        const field = findDateField(dlg, null);
        out.push('', `=== DATE FIELD: ${field ? 'พบ' : 'ไม่พบ'} text="${fieldText(field)}" ===`);
        const confirms = $$('button,[role="button"],a', dlg).filter(visible).map(el => `"${txt(el)}" confirm=${isConfirmLabel(el)}`);
        out.push('=== BUTTONS ===', ...confirms);
      }
      const pk = picker();
      out.push('', `=== PICKER: ${pk ? 'พบ' : 'ไม่พบ (กดช่องวันเวลาให้ปฏิทินเปิดก่อน)'} ===`);
      if (pk) {
        out.push(`parents: ${[pk.parentElement, pk.parentElement?.parentElement].filter(Boolean)
          .map(e => e.tagName.toLowerCase() + (e.getAttribute('role') ? '[role=' + e.getAttribute('role') + ']' : '') +
            (e.hasAttribute('data-radix-popper-content-wrapper') ? '[radix-popper]' : '')).join(' < ')}`);
        describeNode(pk, 0, out, 8);
      }
      const cards = episodeCards();
      out.push('', `=== EPISODES: ${cards.length} cards, selected: ${selected().map(i => i.episode).join(',') || '-'} ===`);
      const report = out.join('\n');
      diagOut.value = report;
      diagOut.dataset.show = '1';
      diagOut.focus();
      diagOut.select();
      let copied = false;
      try { await navigator.clipboard.writeText(report); copied = true; } catch (_) {
        try { copied = document.execCommand('copy'); } catch (__) {}
      }
      reset(copied
        ? `🔍 คัดลอกข้อมูลวินิจฉัยแล้ว (${out.length} บรรทัด) วางส่งให้ผู้พัฒนาได้เลย`
        : `🔍 สร้างข้อมูลวินิจฉัยแล้ว (${out.length} บรรทัด) กดค้างในกล่องข้อความแล้วเลือกคัดลอกทั้งหมด`);
    };
    stopButton.onclick = () => {
      stopRequested = true;
      log('· ขอหยุดแล้ว จะหยุดหลังตอนปัจจุบัน');
    };
    startButton.onclick = async () => {
      const queue = [...getQueue()];
      if (!queue.length) return reset('กรุณาเลือกตอนใน MyNovel ก่อน');
      if (!dateInput.value || !timeInput.value) return reset('กรุณาเลือกวันและเวลาเริ่ม');
      const gap = Math.max(1, Math.min(1440, Number(gapInput.value) || 15));
      gapInput.value = gap;
      persist();
      const userLevel = Math.max(0, LADDER.indexOf(speedSelect.value));
      let level = userLevel;
      let cleanStreak = 0;
      const adaptive = adaptiveCheck.checked;
      const applyLevel = () => setSpeedProfile(LADDER[level]);
      applyLevel();
      const speedLabel = speedSelect.options[speedSelect.selectedIndex].text;
      if (!confirm(
        `ตั้งเวลา ${queue.length} ตอน\n` +
        `ลำดับ: ${queue.join(' → ')}\n\n` +
        `เริ่มที่ ${dateInput.value} ${timeInput.value}\n` +
        `ห่างกัน ${gap} นาที\n` +
        `ความเร็ว: ${speedLabel}${adaptive ? ' (ปรับอัตโนมัติ)' : ''}\n\n` +
        `ดำเนินการต่อหรือไม่?`
      )) return;
      stopRequested = false;
      startButton.disabled = true;
      scanButton.disabled = true;
      detectButton.disabled = true;
      speedSelect.disabled = true;
      let wakeLockActive = false;
      if (wakeLockCheck.checked) {
        _wakeWanted = true;
        wakeLockActive = await acquireWakeLock();
        if (!wakeLockActive) log('⚠️ Wake Lock ไม่รองรับในเบราว์เซอร์นี้');
      }
      let done = 0;
      let skipped = 0;
      const startTime = Date.now();
      reset(`เริ่มตั้งเวลา ${queue.length} ตอน [${speedLabel}]${wakeLockActive ? ' 🔆' : ''}`);
      try {
        await closeOldModal();
        for (let index = 0; index < queue.length; index++) {
          if (stopRequested) {
            const skipNote = skipped > 0 ? `, ข้าม ${skipped}` : '';
            log(`หยุดแล้ว — สำเร็จ ${done}/${queue.length} ตอน${skipNote}`);
            break;
          }
          const episode = queue[index];
          const target = makeTarget(dateInput.value, timeInput.value, index, gap);
          const hm = timeText(target);
          if (episodeLooksScheduled(episode, target)) {
            done++;
            log(`${index + 1}/${queue.length} ตอน ${episode} — ตั้งไว้ ${hm} อยู่แล้ว ข้าม`);
            continue;
          }
          log(`${index + 1}/${queue.length} ตอน ${episode} → ${hm} …`);
          let result = null;
          let lastError = null;
          let attemptsUsed = 0;
          const maxRetries = 5;
          for (let attempt = 1; attempt <= maxRetries; attempt++) {
            attemptsUsed = attempt;
            const restore = hideOwnUiDuringDialog();
            try {
              await closeOldModal();
              await selectOnly(episode);
              result = await applySchedule(await openModal(), target, episode, attempt);
              break;
            } catch (error) {
              lastError = error;
              restore();
              if (adaptive && level < LADDER.length - 1) {
                level++;
                applyLevel();
              }
              if (attempt < maxRetries) {
                log(`  ↻ ลองใหม่ครั้งที่ ${attempt}/${maxRetries} [${LADDER[level]}]: ${error.message || error}`);
                await closeOldModal();
                await sleep(SPEED.retryBaseMs * attempt);
              }
              continue;
            } finally {
              restore();
            }
          }
          if (adaptive) {
            if (result && attemptsUsed === 1) {
              cleanStreak++;
              if (cleanStreak >= 6 && level > userLevel) {
                level--;
                cleanStreak = 0;
                applyLevel();
              }
            } else {
              cleanStreak = 0;
            }
          }
          if (!result) {
            if (skipErrorCheck.checked) {
              skipped++;
              log(`  ✗ ตอน ${episode} ข้าม (${lastError?.message || 'ไม่สำเร็จ'})`, true);
              await closeOldModal();
              await sleep(SPEED.afterSuccessMs);
              continue;
            }
            throw lastError || new Error(`ตั้งเวลาตอน ${episode} ไม่สำเร็จ`);
          }
          done++;
          const elapsedMs = Date.now() - startTime;
          const avgSec = elapsedMs / 1000 / done;
          const remaining = queue.length - index - 1;
          const eta = remaining > 0 ? ` ETA ~${Math.round(remaining * avgSec)}s` : '';
          const note = result === 'ok'
            ? ''
            : result === 'ok-different-time'
              ? ' (ตั้งสำเร็จ แต่เวลาที่การ์ดแสดงไม่ตรง โปรดตรวจ)'
              : ' (MyNovel ปิดหน้าต่างแล้ว แต่ยังอ่านผลจากการ์ดไม่ได้)';
          log(
            `  ✓ ตอน ${episode} → ${hm} [${(elapsedMs / 1000).toFixed(1)}s, ~${avgSec.toFixed(1)}s/ep${eta}]` +
            `${adaptive ? ` {${LADDER[level]}}` : ''}${note}`,
            true
          );
          await sleep(SPEED.afterSuccessMs);
        }
        if (!stopRequested) {
          const totalSec = ((Date.now() - startTime) / 1000).toFixed(1);
          const skipNote = skipped > 0 ? `, ข้าม ${skipped} ตอน` : '';
          log(`✅ เสร็จสิ้น — สำเร็จ ${done}/${queue.length} ตอน${skipNote} (${totalSec}s)`);
          playDoneSound();
        }
      } catch (error) {
        const skipNote = skipped > 0 ? `, ข้าม ${skipped}` : '';
        log(`หยุดที่ ${done}/${queue.length} ตอน${skipNote}\n${error.message || error}`);
        playDoneSound();
      } finally {
        await releaseWakeLock();
        setSpeedProfile(speedSelect.value);
        startButton.disabled = false;
        scanButton.disabled = false;
        detectButton.disabled = false;
        speedSelect.disabled = false;
      }
    };

    // ─── Multi-novel UI logic ────────────────────────────────────────────────
    function renderMultiList() {
      const jobs = loadMultiJobs();
      if (!jobs.length) {
        multiListEl.innerHTML = '<div style="color:#8899aa;font-size:11px;padding:4px 0">ยังไม่มีเรื่องในคิว</div>';
        return;
      }
      const statusIcon = s => s === 'done' ? '<span style="color:#4caf50">✓</span>' :
        s === 'running' ? '<span style="color:#ff9800">▶</span>' :
        '<span style="color:#1596f5">○</span>';
      multiListEl.innerHTML = jobs.map((j, i) => {
        const short = j.url.replace(/^https?:\/\/[^/]+/, '').replace(/\?.*$/, '');
        return `<div class="multi-item">
          <span class="mi-status">${statusIcon(j.status)}</span>
          <span class="mi-url" title="${j.url}">${short}</span>
          <button class="mi-del" data-remove="${i}">✕</button>
        </div>`;
      }).join('');
      multiListEl.querySelectorAll('[data-remove]').forEach(btn => {
        btn.onclick = () => {
          const jobs = loadMultiJobs();
          jobs.splice(Number(btn.dataset.remove), 1);
          saveMultiJobs(jobs);
          renderMultiList();
        };
      });
    }

    novelAddBtn.onclick = () => {
      const url = novelUrlInput.value.trim();
      if (!url) return reset('กรุณาวาง URL ก่อน');
      if (!url.includes('mynovel.co')) return reset('URL ต้องเป็นหน้า mynovel.co');
      const jobs = loadMultiJobs();
      if (jobs.some(j => j.url === url)) return reset('URL นี้มีในรายการแล้ว');
      jobs.push({ url, status: 'pending', autoStart: false });
      saveMultiJobs(jobs);
      novelUrlInput.value = '';
      renderMultiList();
      reset(`เพิ่มแล้ว (รวม ${jobs.length} เรื่อง)`);
    };

    clearJobsBtn.onclick = () => {
      if (!confirm('ล้างรายการทั้งหมด?')) return;
      saveMultiJobs([]);
      renderMultiList();
      reset('ล้างรายการแล้ว');
    };

    launchAllBtn.onclick = () => {
      const jobs = loadMultiJobs();
      if (!jobs.length) return reset('ยังไม่มีเรื่อง กด + เพิ่ม ก่อน');
      if (!dateInput.value || !timeInput.value) return reset('กรุณาเลือกวันและเวลาเริ่ม');
      const config = {
        date: dateInput.value,
        time: timeInput.value,
        gap: Math.max(1, Number(gapInput.value) || 15),
        speed: speedSelect.value,
        adaptive: adaptiveCheck.checked,
        skipError: skipErrorCheck.checked,
        autoSelect: autoSelectCheck.checked,
        autoDetect: autoDetectCheck.checked,
        autoRun: autoRunCheck.checked
      };
      const updated = jobs.map(j => ({ ...j, ...config, autoStart: true, status: 'pending' }));
      saveMultiJobs(updated);
      renderMultiList();
      // แสดงลิงก์ให้กดเปิดทีละแท็บ (รองรับ Firefox มือถือที่บล็อก popup)
      const linkBox = host.querySelector('#mn-link-box');
      linkBox.innerHTML = '<div style="font-size:11px;font-weight:800;color:#1c5f96;margin-bottom:4px">กดแต่ละลิงก์เพื่อเปิดแท็บใหม่:</div>' +
        updated.map((j, i) => {
          const short = j.url.replace(/^https?:\/\/[^/]+/, '').replace(/\?.*$/, '');
          return `<a href="${j.url}" target="_blank" style="display:block;padding:7px 8px;margin:3px 0;background:#edf8ff;border:1px solid #90caf9;border-radius:7px;color:#0d47a1;font-size:11px;text-decoration:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${i+1}. ${short}</a>`;
        }).join('');
      linkBox.style.display = 'block';
      reset(`บันทึกการตั้งค่าแล้ว — กดลิงก์ด้านล่างเพื่อเปิดแต่ละเรื่อง`);
    };

    renderMultiList();
    // ────────────────────────────────────────────────────────────────────────

    // ─── Auto-start (triggered when this tab was opened by launchAllBtn) ────
    const pendingJob = getAutoStartJob();
    if (pendingJob) {
      showPanel(host, fab);
      // fill settings from stored config
      dateInput.value = pendingJob.date || dateInput.value;
      timeInput.value = pendingJob.time || timeInput.value;
      gapInput.value = pendingJob.gap || gapInput.value;
      if (pendingJob.speed && SPEED_PROFILES[pendingJob.speed]) speedSelect.value = pendingJob.speed;
      adaptiveCheck.checked = pendingJob.adaptive !== false;
      skipErrorCheck.checked = pendingJob.skipError !== false;
      setSpeedProfile(speedSelect.value);
      // mark running
      const jobs = loadMultiJobs();
      const idx = jobs.findIndex(j => matchesCurrentUrl(j.url));
      if (idx >= 0) { jobs[idx].status = 'running'; saveMultiJobs(jobs); }
      reset('🤖 Auto: รอหน้าโหลด...');

      const autoStartTimeout = setTimeout(async () => {
        try {
          // auto-detect time if requested
          if (pendingJob.autoDetect) {
            const gap = Math.max(1, Number(gapInput.value) || 15);
            const found = findLastScheduledTime();
            if (found) {
              const next = new Date(found.date.getTime() + gap * 60000);
              dateInput.value = `${next.getFullYear()}-${String(next.getMonth()+1).padStart(2,'0')}-${String(next.getDate()).padStart(2,'0')}`;
              timeInput.value = `${String(next.getHours()).padStart(2,'0')}:${String(next.getMinutes()).padStart(2,'0')}`;
              persist();
              log(`🤖 ตรวจพบ: ตอน ${found.episode} → เริ่มที่ ${timeInput.value}`);
            }
          }
          // auto-select unscheduled episodes
          if (pendingJob.autoSelect) {
            const unscheduled = episodeCards().filter(item => !episodeHasSchedule(item.episode));
            if (!unscheduled.length) {
              reset('🤖 ไม่พบตอนที่ยังไม่ตั้งเวลา');
              markJobDone(pendingJob.url);
              return;
            }
            log(`🤖 เลือก ${unscheduled.length} ตอน...`);
            // cancel existing selection first
            await tapCancelSelection().catch(() => {});
            for (const item of unscheduled) {
              await setCheckbox(item.episode, true);
            }
            await sleep(300);
            log(`🤖 เลือกแล้ว ${selected().length} ตอน`);
          }
          // auto-run
          if (pendingJob.autoRun && getQueue().length > 0) {
            log('🤖 เริ่มตั้งเวลาอัตโนมัติ...');
            // watch statusBox for completion to mark done
            const obs = new MutationObserver(() => {
              const t = statusBox.textContent || '';
              if (t.includes('✅ เสร็จสิ้น') || t.includes('หยุดแล้ว')) {
                obs.disconnect();
                markJobDone(pendingJob.url);
              }
            });
            obs.observe(statusBox, { childList: true, characterData: true, subtree: true });
            startButton.click();
          } else if (pendingJob.autoRun) {
            reset('🤖 ไม่มีตอนให้เริ่ม — กรุณาเลือกตอนเอง');
            markJobDone(pendingJob.url);
          }
        } catch (err) {
          reset(`🤖 Auto-start error: ${err.message || err}`);
          markJobDone(pendingJob.url);
        }
      }, 3500);

      window.__MN_AUTO_START_TIMER__ = autoStartTimeout;
    }
    // ────────────────────────────────────────────────────────────────────────
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();
