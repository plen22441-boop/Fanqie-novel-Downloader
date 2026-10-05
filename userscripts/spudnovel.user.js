// ==UserScript==
// @name         Spudnovel TXT Downloader
// @namespace    fanqie-novel-downloader
// @version      1.0
// @description  โหลดนิยายจาก spudnovel.com เป็นไฟล์ .txt (ผ่านด่านตรวจด้วยเบราว์เซอร์ของคุณเอง)
// @match        https://spudnovel.com/site/detail*
// @match        https://www.spudnovel.com/site/detail*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  const TEST = typeof window.__SPUD_TEST !== 'undefined';
  const SEP = '─'.repeat(40);
  const CHALLENGE = /Just a moment|正在进行安全验证|请稍候|cf-challenge|Verify Yourself|身份验证/;
  const NAV = /^(上一[章页頁]|下一[章页頁]|目录|目錄|返回|书页|加入书架|加入书签|设置|A[+-]|背景|阅读背景|错乱章节催更！?|章节错误|举报|收藏|书名：?|作者：?|本章字数：?|更新时间：?|开始阅读|立即阅读)$/;
  const AD = /https?:\/\/|www\.|spudnovel|土豆小说|\.(?:com|net|cc|org)\b|最新章节|请收藏|手机阅读|APP/i;
  const NUMLEAD = /^[0-9０-９]|^[一二三四五六七八九十百零〇]{1,4}\s*[、．.:：]/;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const st = { chapters: [], results: [], errors: [], failed: new Set(), meta: {}, toc: {}, busy: false };

  const isChallenge = (h) => h.length < 30000 && CHALLENGE.test(h);
  const parseHtml = (h) => new DOMParser().parseFromString(h, 'text/html');
  const cleanTitle = (t) => t.replace(/^第\s*[0-9一二三四五六七八九十百千零〇]+\s*章\s*/, '').trim();

  // ---------- TOC ----------
  function buildToc() {
    const anchors = [...document.querySelectorAll('a[href*="/site/chapter?id="]')];
    const label = /^(开始阅读|立即阅读|最新章节|继续阅读)/;
    const byId = new Map();
    anchors.forEach((a) => {
      const id = +new URL(a.href).searchParams.get('id');
      const t = a.textContent.trim().replace(/\s+/g, ' ');
      const cur = byId.get(id);
      if (!cur || (label.test(cur.title) && !label.test(t))) byId.set(id, { id, url: a.href, title: t });
    });
    const total = byId.size;
    const sets = new Map();
    anchors.forEach((a) => {
      const id = +new URL(a.href).searchParams.get('id');
      for (let e = a.parentElement; e; e = e.parentElement) {
        if (!sets.has(e)) sets.set(e, new Set());
        sets.get(e).add(id);
      }
    });
    let box = null, boxCost = Infinity;
    sets.forEach((s, e) => {
      if (s.size >= total * 0.6) {
        const cost = e.querySelectorAll('*').length;
        if (cost < boxCost) { box = e; boxCost = cost; }
      }
    });
    const inBox = [];
    const seen = new Set();
    (box ? [...box.querySelectorAll('a[href*="/site/chapter?id="]')] : anchors).forEach((a) => {
      const id = +new URL(a.href).searchParams.get('id');
      if (!seen.has(id)) { seen.add(id); inBox.push(byId.get(id)); }
    });
    const nums = inBox.map((c) => (c.title.match(/第\s*(\d+)\s*章/) || [])[1]).filter(Boolean).map(Number);
    let reversed = false;
    if (nums.length > 2 && nums[0] > nums[nums.length - 1]) { inBox.reverse(); reversed = true; }
    const extra = [...byId.values()].filter((c) => !seen.has(c.id)).sort((a, b) => a.id - b.id);
    const list = inBox.concat(extra);
    const hint = (document.body.textContent.match(/共\s*(\d+)\s*章/) || [])[1];
    st.toc = { total, inBox: inBox.length, extra: extra.length, reversed, hint: hint ? +hint : null,
      box: box ? box.tagName.toLowerCase() + (box.id ? '#' + box.id : '') + (box.className ? '.' + String(box.className).trim().split(/\s+/).join('.') : '') : null };
    const h1 = document.querySelector('h1');
    st.meta.title = ((h1 && h1.textContent.trim()) || document.title.split('全文')[0].split('_')[0]).trim();
    const au = document.querySelector('a[href*="/site/list?q="]');
    st.meta.author = au ? au.textContent.trim() : '未知作者';
    st.meta.bookId = new URL(location.href).searchParams.get('id') || 'book';
    st.chapters = list;
    st.results = new Array(list.length).fill(null);
    return list;
  }

  // ---------- fetching ----------
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
            if (!isChallenge(html) && d.body.textContent.trim().length > 300) { clearInterval(iv); f.remove(); res(html); return; }
          }
        } catch (e) { /* cross-origin: keep waiting */ }
        if (Date.now() - t0 > 60000) { clearInterval(iv); f.remove(); rej(new Error('ด่านตรวจไม่ผ่านภายใน 60 วินาที')); }
      }, 1000);
    });
  }

  async function loadDoc(url) {
    const r = await fetch(url, { credentials: 'include' });
    const t = await r.text();
    if (r.status === 403 || r.status === 503 || isChallenge(t)) {
      return { html: await ifrQueue(() => viaIframe(url)), mode: 'iframe' };
    }
    return { html: t, mode: 'fetch' };
  }

  // ---------- extraction ----------
  function nextPageLink(doc, cur) {
    const curId = new URL(cur).searchParams.get('id');
    for (const a of doc.querySelectorAll('a[href]')) {
      if (!/^下一[页頁]\s*[>›»]?$/.test(a.textContent.trim())) continue;
      const h = a.getAttribute('href');
      if (!h || /^(javascript|#)/.test(h)) continue;
      const u = new URL(h, cur);
      if (u.origin !== location.origin || u.href === cur) continue;
      const nid = u.searchParams.get('id');
      if (curId && nid && nid !== curId) continue;
      return u.href;
    }
    return null;
  }

  function pickContainer(doc) {
    doc.querySelectorAll('script,style,noscript,iframe,nav,header,footer,form,button,select,ins,.ad,.ads,.adsbygoogle').forEach((e) => e.remove());
    const sels = ['#chaptercontent', '#content', '.chapter-content', '.read-content', '.reader-content', '.page-content', '.chapter-body', '.article-content', '.text-content', 'article'];
    for (const s of sels) {
      const el = doc.querySelector(s);
      if (el && el.textContent.trim().length > 200) return { el, sel: s };
    }
    let best = null, score = 0;
    doc.querySelectorAll('div,article,section,main,td').forEach((el) => {
      let own = 0;
      el.childNodes.forEach((n) => {
        if (n.nodeType === 3) own += n.textContent.trim().length;
        else if (n.nodeType === 1 && /^(P|SPAN|FONT)$/.test(n.tagName)) own += n.textContent.trim().length;
      });
      if (own > score) { score = own; best = el; }
    });
    if (!best || score < 150) return null;
    return { el: best, sel: 'auto:' + best.tagName.toLowerCase() + (best.id ? '#' + best.id : '') + (best.className ? '.' + String(best.className).trim().split(/\s+/).join('.') : '') };
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
    for (let l of lines) {
      l = l.trim();
      if (!l) continue;
      if (NAV.test(l)) { dropped.push(l); continue; }
      if (!out.length && (l === title || l === bare || (/^第\s*\d+\s*章/.test(l) && l.length < 40))) { dropped.push(l); continue; }
      if (AD.test(l)) {
        dropped.push(l);
        const keep = (l.match(/[^。！？!?]+[。！？!?]*/g) || [l]).filter((s) => !AD.test(s)).join('').trim();
        if (!keep) continue;
        l = keep;
      }
      out.push(l);
    }
    return out;
  }

  async function downloadChapter(ch) {
    let url = ch.url, pages = 0, lines = [], declared = null, sel = '', mode = '';
    const dropped = [], seen = new Set();
    while (url && pages < 30 && !seen.has(url)) {
      seen.add(url);
      let { html, mode: m } = await loadDoc(url);
      let doc = parseHtml(html);
      let nxt = nextPageLink(doc, url);
      const dm = doc.body && doc.body.textContent.match(/字数[:：]?\s*(\d+)/);
      let box = pickContainer(parseHtml(html));
      if (!box || box.el.textContent.trim().length < 150) {
        html = await ifrQueue(() => viaIframe(url));
        m = 'iframe';
        doc = parseHtml(html);
        nxt = nextPageLink(doc, url);
        box = pickContainer(parseHtml(html));
      }
      if (!box) throw new Error('ไม่พบส่วนเนื้อหา');
      if (!pages) { declared = dm ? +dm[1] : null; sel = box.sel; mode = m; }
      lines = lines.concat(cleanLines(linesOf(box.el), ch.title, dropped));
      pages++;
      url = nxt;
    }
    const chars = lines.join('').length;
    if (chars < 200) throw new Error('เนื้อหาสั้นผิดปกติ (' + chars + ')');
    return { lines, pages, chars, declared, sel, mode, dropped };
  }

  async function runBatch(idxs, ui) {
    let next = 0, done = 0;
    const worker = async () => {
      for (;;) {
        const k = next++;
        if (k >= idxs.length) return;
        const i = idxs[k];
        for (let a = 0; a < 4; a++) {
          try { st.results[i] = await downloadChapter(st.chapters[i]); st.failed.delete(i); break; }
          catch (e) { st.errors[i] = String(e.message || e); if (a === 3) st.failed.add(i); else await sleep(1000 * 2 ** a); }
        }
        done++;
        ui('กำลังโหลด ' + done + '/' + idxs.length + ' (ล้มเหลว ' + st.failed.size + ')');
        await sleep(150 + Math.random() * 250);
      }
    };
    await Promise.all([worker(), worker(), worker()]);
  }

  // ---------- output ----------
  function assemble(idxs) {
    const out = [st.meta.title, '作者：' + st.meta.author, ''];
    (idxs || st.chapters.map((_, i) => i)).forEach((i, n) => {
      const ch = st.chapters[i], r = st.results[i];
      out.push('第' + (idxs ? i + 1 : i + 1) + '章 ' + cleanTitle(ch.title), '');
      if (r) r.lines.forEach((l) => out.push(NUMLEAD.test(l) ? '・' + l : l));
      else out.push('【โหลดไม่สำเร็จ】');
      out.push('', SEP, '');
    });
    return out.join('\n');
  }

  function report(idxs) {
    const t = st.toc, o = ['=== REPORT ===',
      'ชื่อ: ' + st.meta.title + ' | ผู้แต่ง: ' + st.meta.author,
      'TOC: unique=' + t.total + ' inBox=' + t.inBox + ' extra=' + t.extra + ' reversed=' + t.reversed + ' hint=' + t.hint + ' box=' + t.box];
    idxs.forEach((i) => {
      const r = st.results[i], ch = st.chapters[i];
      if (!r) { o.push('#' + i + ' ' + ch.title + ' FAIL: ' + st.errors[i]); return; }
      const j = r.lines.join('');
      o.push('#' + i + ' ' + ch.title + ' id=' + ch.id + ' mode=' + r.mode + ' pages=' + r.pages + ' chars=' + r.chars +
        ' declared=' + r.declared + ' sel=' + r.sel + ' head=' + JSON.stringify(j.slice(0, 30)) + ' tail=' + JSON.stringify(j.slice(-30)) +
        ' dropped=' + JSON.stringify(r.dropped.slice(0, 5).map((x) => x.slice(0, 40))));
    });
    return o.join('\n');
  }

  function saveText(name, text) {
    if (TEST) { window.__SPUD_OUT = { name, text }; return; }
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 5000);
  }

  const safeName = () => (st.meta.title + '_' + st.meta.bookId).replace(/[\\/:*?"<>|]/g, '_');

  async function runTest(ui) {
    if (!st.chapters.length) buildToc();
    const n = st.chapters.length;
    const idxs = [...new Set([0, Math.min(1, n - 1), n - 1])];
    await runBatch(idxs, ui);
    saveText(safeName() + '_test.txt', report(idxs) + '\n\n' + assemble(idxs));
    ui('ทดสอบเสร็จ: บันทึกไฟล์ _test.txt แล้ว ส่งไฟล์นั้นให้ผู้ช่วยตรวจ');
  }

  async function runAll(ui) {
    if (!st.chapters.length) buildToc();
    let lock = null;
    try { lock = await navigator.wakeLock.request('screen'); } catch (e) { /* optional */ }
    const idxs = st.chapters.map((_, i) => i).filter((i) => !st.results[i]);
    await runBatch(idxs, ui);
    if (lock) try { await lock.release(); } catch (e) { /* ignore */ }
    saveText(safeName() + '.txt', assemble());
    ui(st.failed.size ? 'เสร็จ แต่ล้มเหลว ' + st.failed.size + ' ตอน กด "ลองตอนที่ล้มซ้ำ"' : 'เสร็จครบทุกตอน บันทึกไฟล์แล้ว');
  }

  // ---------- UI ----------
  function mountUi() {
    const box = document.createElement('div');
    box.style.cssText = 'position:fixed;left:8px;right:8px;bottom:8px;z-index:2147483647;background:#fff;border:2px solid #c2185b;border-radius:10px;padding:8px;font:14px sans-serif;color:#222;box-shadow:0 2px 12px rgba(0,0,0,.35)';
    const msg = document.createElement('div');
    msg.textContent = 'พร้อมแล้ว: ผ่านด่านตรวจของเว็บก่อน แล้วกดทดสอบ 3 ตอน';
    msg.style.marginBottom = '6px';
    box.appendChild(msg);
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
      box.appendChild(b);
    };
    mk('ทดสอบ 3 ตอน', () => runTest(ui));
    mk('โหลดทั้งเรื่อง', () => runAll(ui));
    mk('ลองตอนที่ล้มซ้ำ', () => runAll(ui));
    mk('บันทึกไฟล์ตอนนี้', async () => { saveText(safeName() + '_partial.txt', assemble()); ui('บันทึกไฟล์บางส่วนแล้ว'); });
    document.body.appendChild(box);
  }

  if (TEST) window.__SPUD = { buildToc, runTest, runAll, st, assemble, downloadChapter };
  else mountUi();
})();
