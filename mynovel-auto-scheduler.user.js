// ==UserScript==
// @name         MyNovel Auto Scheduler Helper v10.10.0 Speed Boost
// @namespace    https://mynovel.co/
// @version      10.10.0
// @description  ตั้งเวลา MyNovel ทีละตอนจากล่างขึ้นบน — เพิ่มโหมดเร็ว (Turbo) สำหรับลง 50-100 ตอน, ลด delay ทุกจุด, แก้บั๊กยิงคลิกซ้อน 2 ครั้ง, แก้การตรวจช่องวันเวลา, เพิ่มการเลื่อนเดือนในปฏิทิน
// @match        *://mynovel.co/*
// @match        *://*.mynovel.co/*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(() => {
  'use strict';

  const VERSION = '10.10.0';
  const ID = 'mn-auto-helper-panel';
  const FAB_ID = 'mn-auto-helper-fab';

  try { window.__MN_SCHEDULER_CLEANUP__ && window.__MN_SCHEDULER_CLEANUP__(); } catch (_) {}
  if (window.__MN_SCHEDULER_VERSION__ === VERSION && document.getElementById(ID)) return;
  window.__MN_SCHEDULER_VERSION__ = VERSION;

  document.querySelectorAll(
    '[id^="mn-auto-helper-"],[id^="mn-extreme-ui-"],#mn-fab-btn'
  ).forEach(el => el.remove());

  /* ───────────────────────── ค่าคงที่ / ตัวช่วยพื้นฐาน ───────────────────────── */

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
      pollMs: 90,
      beforeTapMs: 55,
      afterTapMs: 130,
      afterSuccessMs: 320,
      retryBaseMs: 700,
      afterSetNativeMs: 220,
      afterSetHourMs: 120,
      afterMonthNavMs: 240,
      afterPickDayMs: 320,
      afterClosePickerMs: 240,
      selectOnlyPauseMs: 140
    },
    fast: {
      pollMs: 50,
      beforeTapMs: 25,
      afterTapMs: 60,
      afterSuccessMs: 120,
      retryBaseMs: 400,
      afterSetNativeMs: 100,
      afterSetHourMs: 50,
      afterMonthNavMs: 120,
      afterPickDayMs: 150,
      afterClosePickerMs: 100,
      selectOnlyPauseMs: 60
    },
    turbo: {
      pollMs: 30,
      beforeTapMs: 10,
      afterTapMs: 35,
      afterSuccessMs: 60,
      retryBaseMs: 250,
      afterSetNativeMs: 60,
      afterSetHourMs: 30,
      afterMonthNavMs: 70,
      afterPickDayMs: 80,
      afterClosePickerMs: 60,
      selectOnlyPauseMs: 30
    }
  });

  let SPEED = { ...SPEED_PROFILES.fast };

  function setSpeedProfile(name) {
    const profile = SPEED_PROFILES[name];
    if (profile) Object.assign(SPEED, profile);
  }

  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
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

  async function waitFor(fn, timeout = 8000, error = 'หมดเวลารอ MyNovel ตอบกลับ') {
    const started = Date.now();
    let last = null;
    while (Date.now() - started < timeout) {
      try {
        last = fn();
        if (last) return last;
      } catch (_) {}
      await sleep(SPEED.pollMs);
    }
    throw new Error(error);
  }

  /* ───────────────────────── การกด ───────────────────────── */

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

  /* ───────────────────────── ค้นหาองค์ประกอบบนหน้า ───────────────────────── */

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

  /* ───────────────────────── การเลือกตอน ───────────────────────── */

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

  /* ───────────────────────── กล่องโต้ตอบ "ตั้งเวลาเผยแพร่" ───────────────────────── */

  const CONFIRM_LABELS = ['ยืนยันตั้งเวลา', 'ยืนยัน', 'ตกลง', 'ทำสิ่งนี้เลยสิ'];

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

  /* ───────────────────────── ช่อง "กำหนดเวลาเผยแพร่" ───────────────────────── */

  const PLACEHOLDER_RE = /^เลือกวัน/;

  function fieldText(el) {
    if (!el) return '';
    if (el.tagName === 'INPUT') return clean(el.value);
    const inner = $$('input', el).filter(visible)[0];
    if (inner && inner.value) return clean(inner.value);
    return clean(txt(el));
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
          .filter(el => !CONFIRM_LABELS.includes(clean(txt(el))) && clean(txt(el)) !== 'ยกเลิก')[0];
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

  /* ───────────────────────── ปฏิทิน + ช่องเวลา ───────────────────────── */

  function picker() {
    const scopes = $$('[data-radix-popper-content-wrapper],[data-radix-popover-content],[role="dialog"]')
      .filter(visible);

    const pool = [];
    if (scopes.length) {
      for (const root of scopes) pool.push(root, ...$$('*', root));
    } else {
      pool.push(...$$('body *'));
    }

    return uniq(pool)
      .filter(visible)
      .filter(el => {
        const t = txt(el);
        if (!MONTH_EN_RE.test(t) && !MONTH_TH_RE.test(t)) return false;
        const inputs = $$('input', el).filter(visible);
        return inputs.length >= 2 || inputs.some(i => i.type === 'time');
      })
      .sort(byArea)[0] || null;
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

  /* ───────────────────────── ผลลัพธ์หลังกดยืนยัน ───────────────────────── */

  async function waitOutcome(episode, target, timeout = 10000) {
    const started = Date.now();
    while (Date.now() - started < timeout) {
      if (episodeLooksScheduled(episode, target)) return 'ok';

      const body = txt(document.body);
      if (body.includes('ตั้งเวลาเผยแพร่ 1 ตอนสำเร็จ') || body.includes('ตั้งเวลาเผยแพร่สำเร็จ')) {
        return 'ok';
      }

      const live = modal();
      if (!live) return 'closed';

      if (/กรุณาเลือกวันและเวลา/.test(txt(live)) && !fieldIsFilled(findDateField(live, null))) {
        return 'rejected';
      }

      await sleep(SPEED.pollMs);
    }
    return 'timeout';
  }

  /* ───────────────────────── ขั้นตอนตั้งเวลา 1 ตอน ───────────────────────── */

  async function applySchedule(scheduleModal, target, episode, attempt) {
    const dateField = await waitFor(
      () => findDateField(scheduleModal, null),
      4000,
      'ไม่พบช่องเลือกวันและเวลา'
    );

    const dayFirst = attempt < 3;

    await openPicker(dateField);
    await gotoTargetMonth(target);

    if (dayFirst) {
      await pickDay(target, dateField);
      const reopened = await openPicker(dateField);
      await setTimeInPicker(reopened, target);
    } else {
      await setTimeInPicker(picker(), target);
      await gotoTargetMonth(target);
      await pickDay(target, dateField);
    }

    await closePickerSafely(scheduleModal);
    await sleep(SPEED.afterClosePickerMs);

    const liveModal = await waitFor(modal, 4000, 'หน้าต่างตั้งเวลาหายไปก่อนกดยืนยัน');
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
          .filter(el => CONFIRM_LABELS.includes(clean(txt(el))))
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

    const uncertain = new Error(
      'กดยืนยันแล้วแต่ MyNovel ไม่ตอบกลับภายในเวลาที่รอ\n' +
      'หยุดไว้ก่อนเพื่อป้องกันการตั้งตอนนี้ซ้ำ กรุณาตรวจสอบสถานะตอนบนเว็บ'
    );
    uncertain.code = 'MN_CONFIRM_OUTCOME_UNKNOWN';
    throw uncertain;
  }

  /* ───────────────────────── UI ───────────────────────── */

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
#${ID} .body{padding:12px!important}
#${ID} .row{display:grid!important;grid-template-columns:1fr 1fr!important;gap:8px!important}
#${ID} label{display:block!important;margin:7px 0 4px!important;color:#40536a!important;font-size:12px!important;font-weight:800!important}
#${ID} input,#${ID} select{box-sizing:border-box!important;width:100%!important;padding:9px!important;border:1px solid #cfdae7!important;border-radius:9px!important;background:#fbfdff!important;color:#142033!important;font:inherit!important}
#${ID} button.action{width:100%!important;min-height:42px!important;margin-top:9px!important;padding:10px!important;border:0!important;border-radius:10px!important;font:inherit!important;font-weight:900!important}
#${ID} .scan{background:#edf4fa!important;color:#27425d!important}
#${ID} .start{background:#1596f5!important;color:#fff!important}
#${ID} .stop{background:#fff2f1!important;color:#a61b14!important;border:1px solid #efcbc8!important}
#${ID} .note{margin-top:7px!important;color:#52647a!important;font-size:11px!important;line-height:1.4!important}
#${ID} .status{max-height:132px!important;margin-top:8px!important;padding:8px!important;border-radius:9px!important;background:#102035!important;color:#e8f3ff!important;font-size:12px!important;line-height:1.5!important;overflow-y:auto!important;white-space:pre-line!important}
#${ID} .speed-row{display:grid!important;grid-template-columns:1fr 1fr!important;gap:8px!important;margin-top:4px!important}
#${ID} .speed-badge{display:inline-block!important;margin-left:6px!important;padding:1px 6px!important;border-radius:6px!important;font-size:10px!important;font-weight:900!important;vertical-align:middle!important}
#${ID} .speed-badge.normal{background:#e0e7ef!important;color:#3a4d63!important}
#${ID} .speed-badge.fast{background:#d4edff!important;color:#0b6bcb!important}
#${ID} .speed-badge.turbo{background:#fff3cd!important;color:#856404!important}
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
          <option value="fast" selected>เร็ว (~2 วิ/ตอน)</option>
          <option value="turbo">เร็วสุด (~1 วิ/ตอน)</option>
        </select>
      </div>
    </div>
    <div class="note">เลือกตอนใน MyNovel แล้วกดเริ่ม สคริปต์จะไล่ตั้งทีละตอนจากล่างขึ้นบน<br>โหมดเร็วสุด: ลง 100 ตอนภายใน ~2 นาที (ถ้าเว็บตอบช้าจะ retry ให้อัตโนมัติ)</div>
    <button class="action scan" id="mn-scan">ตรวจตอนที่เลือก</button>
    <button class="action start" id="mn-start">เริ่มตั้งเวลา</button>
    <button class="action stop" id="mn-stop">หยุดหลังตอนปัจจุบัน</button>
    <div class="status" id="mn-status">พร้อมใช้งาน — เลือกตอนใน MyNovel แล้วกดเริ่ม</div>
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
      fab.remove();
      host.remove();
    };

    const dateInput = host.querySelector('#mn-date');
    const timeInput = host.querySelector('#mn-time');
    const gapInput = host.querySelector('#mn-gap');
    const speedSelect = host.querySelector('#mn-speed');
    const scanButton = host.querySelector('#mn-scan');
    const startButton = host.querySelector('#mn-start');
    const stopButton = host.querySelector('#mn-stop');
    const closeButton = host.querySelector('#mn-close');
    const statusBox = host.querySelector('#mn-status');

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

      setSpeedProfile(speedSelect.value);
      const speedLabel = speedSelect.options[speedSelect.selectedIndex].text;

      if (!confirm(
        `ตั้งเวลา ${queue.length} ตอน\n` +
        `ลำดับ: ${queue.join(' → ')}\n\n` +
        `เริ่มที่ ${dateInput.value} ${timeInput.value}\n` +
        `ห่างกัน ${gap} นาที\n` +
        `ความเร็ว: ${speedLabel}\n\n` +
        `ดำเนินการต่อหรือไม่?`
      )) return;

      stopRequested = false;
      startButton.disabled = true;
      scanButton.disabled = true;
      speedSelect.disabled = true;

      let done = 0;
      const startTime = Date.now();
      reset(`เริ่มตั้งเวลา ${queue.length} ตอน [${speedLabel}]`);

      try {
        await closeOldModal();

        for (let index = 0; index < queue.length; index++) {
          if (stopRequested) {
            log(`หยุดแล้ว — สำเร็จ ${done}/${queue.length} ตอน`);
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

          for (let attempt = 1; attempt <= 3; attempt++) {
            const restore = hideOwnUiDuringDialog();
            try {
              await closeOldModal();
              await selectOnly(episode);
              result = await applySchedule(await openModal(), target, episode, attempt);
              break;
            } catch (error) {
              lastError = error;
              if (error?.code === 'MN_CONFIRM_OUTCOME_UNKNOWN') throw error;
              restore();
              log(`  ↻ ลองใหม่ครั้งที่ ${attempt}: ${error.message || error}`);
              await closeOldModal();
              await sleep(SPEED.retryBaseMs * attempt);
              continue;
            } finally {
              restore();
            }
          }

          if (!result) throw lastError || new Error(`ตั้งเวลาตอน ${episode} ไม่สำเร็จ`);

          done++;
          const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
          const avgSec = (done > 0 ? ((Date.now() - startTime) / 1000 / done).toFixed(1) : '?');
          const remaining = queue.length - index - 1;
          const eta = remaining > 0 ? ` ETA ~${(remaining * avgSec).toFixed(0)}s` : '';

          const note = result === 'ok'
            ? ''
            : result === 'ok-different-time'
              ? ' (ตั้งสำเร็จ แต่เวลาที่การ์ดแสดงไม่ตรง โปรดตรวจ)'
              : ' (MyNovel ปิดหน้าต่างแล้ว แต่ยังอ่านผลจากการ์ดไม่ได้)';
          log(`  ✓ ตอน ${episode} → ${hm} [${elapsed}s, ~${avgSec}s/ep${eta}]${note}`, true);
          await sleep(SPEED.afterSuccessMs);
        }

        if (!stopRequested && done === queue.length) {
          const totalSec = ((Date.now() - startTime) / 1000).toFixed(1);
          log(`เสร็จสิ้น — ตั้งเวลาครบ ${done}/${queue.length} ตอน (ใช้เวลา ${totalSec}s)`);
        }
      } catch (error) {
        log(`หยุดที่ ${done}/${queue.length} ตอน\n${error.message || error}`);
      } finally {
        startButton.disabled = false;
        scanButton.disabled = false;
        speedSelect.disabled = false;
      }
    };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();
