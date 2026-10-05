// ==UserScript==
// @name         Novel TXT Downloader - ส่วนที่ 2/2 (โหลดตอน+แผงควบคุม)
// @namespace    fanqie-novel-downloader
// @version      2.8
// @description  ส่วนที่ 2 จาก 2 ต้องติดตั้งคู่กับส่วนที่ 1
// @match        *://*/*
// @noframes
// @grant        unsafeWindow
// @grant        GM_registerMenuCommand
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  const W = typeof unsafeWindow !== 'undefined' ? unsafeWindow : window;
  const TEST = typeof window.__NOVEL_TEST !== 'undefined';
  (async () => {
    for (let k = 0; k < 40 && !W.__NDL1; k++) await new Promise((r) => setTimeout(r, 250));
    const A = W.__NDL1;
    if (!A) {
      if (typeof GM_registerMenuCommand === 'function') GM_registerMenuCommand('เปิดแผงโหลดนิยาย', () => alert('ไม่พบส่วนที่ 1 กรุณาติดตั้ง "ส่วนที่ 1/2" และเปิดใช้งานทั้งสองส่วน'));
      return;
    }
    const { st, VERSION, cleanTitle, detect, idbClear, idbGet, idbSet, ifrQueue, loadHtml, parseHtml, scan, sleep, textOf, viaIframe, fetchText, isChallenge } = A;
  const ZW = /[​-‏⁠﻿­]/g;
  const SEP = '─'.repeat(40);
  const NAV_LINE = /^(上一[章页頁节節]|下一[章页頁节節]|上[页頁]|下[页頁]|目[录錄]|返回.*|书页|書頁|加入书[架签]|加入書[架籤]|设置|設置|A[+-]|阅读背景|错乱章节催更！?|章节错误|章節錯誤|举报|舉報|收藏|书名[：:]?|作者[：:]?|本章字数[：:]?|更新时间[：:]?|开始阅读|立即阅读|报错|催更|书签|没有了|沒有了|指南)$/;
  const UI_JUNK = /^(.*方向键可?切换章节|左右滑动可?切换章节|不吐不快|后?发表评论|我要评论|点击.{0,6}评论|.*扫码.*|.*二维码.*)$/;
  const REC = /^(猜你喜欢|相关推荐|热门推荐|新书推荐|同类推荐|大家都在看|推荐阅读|相关小说)$/;
  const URL_LEAD = /(?:速看|点击|点我|访问|登录|收藏|追更|围观|阅读链接|阅读地址|链接|入口在此|直达故事世界|指尖一点|先睹为快|书迷速归|欢迎访问|来|上|看看|探索)[，,：:]?\s*(?:https?:\/{0,2}|\/\/|www\.)[\x21-\x7e]*/g;
  const URL_BARE = /(?:https?:\/{0,2}|www\.)[\x21-\x7e]*/g;
  const META = /^小说名[：:].*(更新时间|章节字数)|^(更新时间|更新日期|发布时间|更新時間)[：:]\s*\d{4}|^(本章字数|章节字数|字数|字數)[：:]\s*\d+|^.{0,40}更新时间[：:]?\s*\d{4}-\d{1,2}-\d{1,2}.{0,60}$/;
  const CONTENT_SELS = ['#chaptercontent', '#content', '#BookText', '#booktxt', '#htmlContent', '#nr1', '#nr', '#text_area', '#chapterContent', '#acontent', '#novelcontent', '.txtnav', '.chapter-content', '.read-content', '.reader-content', '.page-content', '.chapter-body', '.article-content', '.text-content', '.showtxt', '.novelcontent', '.content', 'article'];
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

  async function waitGate(ui) {
    const g = st.gate;
    while (g.captcha || Date.now() < g.until) {
      if (g.captcha) {
        ui('ติด captcha/ด่านตรวจ: เปิดแท็บใหม่ไปที่เว็บนี้แล้วผ่านด่าน ระบบจะตรวจเองทุก 5 วินาทีแล้วทำต่อ (หรือกด "ต่อ")');
        await sleep(5000);
        try {
          const r = await fetchText(g.probe);
          if (r.ok && !isChallenge(r.text) && !/GOEDGE_WAF|ui-captcha|Verify Yourself|身份验证/.test(r.text.slice(0, 6000))) { g.captcha = false; g.until = Date.now() + 3000; }
        } catch (e) { /* keep waiting */ }
      } else {
        ui('เว็บจำกัดความเร็ว พักรอ ' + Math.ceil((g.until - Date.now()) / 1000) + ' วินาที แล้วทำต่อ');
        await sleep(1000);
      }
    }
  }

  function trip(kind, url) {
    const g = st.gate;
    g.level = Math.min(g.level + 1, 6);
    if (kind === 'CAPTCHA') { g.captcha = true; g.probe = url; }
    else g.until = Math.max(g.until, Date.now() + Math.min(300000, 15000 * 2 ** (g.level - 1)));
    st.limit = Math.max(2, Math.floor(st.limit / 2));
    st.stat.okStreak = 0;
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
        let a = 0, trips = 0;
        while (a < 4) {
          await waitGate(ui);
          try {
            const r = await downloadChapter(st.chapters[i]);
            if (r.declared && r.chars < r.declared * 0.6 && a < 1) { a++; st.errors[i] = 'PARTIAL'; await sleep(1500); continue; }
            if (r.declared && r.chars < r.declared * 0.6) st.stat.partial++;
            st.stat.n++; st.stat.ms += Date.now() - t0;
            if (++st.stat.okStreak >= 8 && st.limit < st.workers) { st.limit++; st.stat.okStreak = 0; }
            if (st.stat.okStreak >= 20 && st.gate.level > 0) { st.gate.level--; st.stat.okStreak = 0; }
            st.results[i] = r;
            st.failed.delete(i);
            idbSet(st.chapters[i].url, Object.assign({ v: VERSION }, r));
            break;
          } catch (e) {
            const m = String(e.message || e);
            st.errors[i] = m;
            if (/^(CAPTCHA|RATE|BLOCK)$/.test(m)) {
              trip(m, st.chapters[i].url);
              if (++trips > 15) { st.failed.add(i); break; }
              continue;
            }
            a++;
            if (a >= 4) st.failed.add(i); else await sleep(1000 * 2 ** (a - 1));
          }
        }
        done++;
        const el = (Date.now() - T0) / 1000, left = Math.round(((idxs.length - done) * el / done) / 60);
        ui(done + '/' + idxs.length + ' | ล้ม ' + st.failed.size + ' | ขนาน ' + Math.min(st.limit, st.workers) + '/' + st.workers +
          ' | เฉลี่ย ' + (st.stat.n ? (st.stat.ms / st.stat.n / 1000).toFixed(1) : '-') + ' วิ/ตอน | เหลือ ~' + left + ' นาที | 429:' + st.stat.p429 + ' 403:' + st.stat.p403 + ' | ไม่ครบ:' + st.stat.partial);
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
    for (let round = 0; round < 2 && st.failed.size; round++) {
      const w = st.workers;
      st.workers = 2;
      await sleep(5000);
      await runBatch([...st.failed], ui);
      st.workers = w;
    }
    document.removeEventListener('visibilitychange', onVis);
    if (lock) try { await lock.release(); } catch (e) { /* ignore */ }
    saveText(safeName() + '.txt', assemble());
    ui((st.failed.size ? 'เสร็จ แต่ล้มเหลว ' + st.failed.size + ' ตอน กด "ลองตอนที่ล้มซ้ำ"' : 'เสร็จครบทุกตอน บันทึกไฟล์แล้ว') + (st.stat.partial ? ' | ตอนที่น่าจะไม่ครบ ' + st.stat.partial : ''));
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
    mk('ต่อ', async () => { st.gate.captcha = false; st.gate.until = 0; ui('สั่งทำต่อแล้ว'); });
    mk('กลับลำดับ', async () => { st.chapters.reverse(); st.chapters.forEach((c, i) => { c.i = i; }); st.results.reverse(); ui('กลับลำดับแล้ว แรก: ' + (st.chapters[0].title || st.chapters[0].url).slice(0, 20)); });
    const spd = document.createElement('button');
    const speeds = [3, 6, 10, 16];
    const label = () => 'ความเร็ว: ' + st.workers;
    spd.textContent = label();
    spd.style.cssText = 'margin:2px;padding:8px 10px;border:0;border-radius:6px;background:#455a64;color:#fff;font-size:14px';
    spd.onclick = () => { st.workers = speeds[(speeds.indexOf(st.workers) + 1) % speeds.length]; spd.textContent = label(); };
    panel.appendChild(spd);
    mk('ล้างแคช', async () => { await idbClear(); st.results = new Array(st.chapters.length).fill(null); ui('ล้างแคชแล้ว'); });
    mk('ข้อมูลดีบัก', async () => {
      const sl = document.querySelector('select');
      saveText('debug_' + location.hostname + '.txt', JSON.stringify(st.toc, null, 1) + '\n\nURL: ' + location.href + '\n\nSELECT PARENT:\n' + (sl && sl.parentElement ? sl.parentElement.outerHTML.slice(0, 3000) : 'none'));
      ui('บันทึกไฟล์ดีบักแล้ว ส่งให้ผู้ช่วยได้');
    });
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

    if (TEST) { window.__NOVEL = { scan, runTest, runAll, st, assemble, downloadChapter, detect, fetchText, loadHtml, pickContainer, linesOf, cleanLines, parseHtml }; return; }
    if (typeof GM_registerMenuCommand === 'function') GM_registerMenuCommand('เปิดแผงโหลดนิยาย', mountUi);
    setTimeout(maybeShowButton, 1500);
    setTimeout(maybeShowButton, 5000);
  })();
})();
