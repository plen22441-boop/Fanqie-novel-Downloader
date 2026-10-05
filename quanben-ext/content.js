(function () {
  'use strict';

  const APP = 'qb-downloader';
  if (document.getElementById(APP)) return;

  const sleep = ms => new Promise(r => setTimeout(r, ms));

  // ── Dynamic URL state (SPA-safe) ────────────────────────────────────────────
  function getUrlState() {
    const parts = location.pathname.replace(/^\//, '').split('/');
    const slug = parts[1] || '';
    return {
      slug,
      catalogUrl: `${location.origin}/n/${slug}/`,
      isIndexPage: parts.length <= 2 || !parts[2],
      chapterNum: (parts[2] && /^\d+$/.test(parts[2])) ? Number(parts[2]) : null
    };
  }
  let S = getUrlState();

  let stopped = false, running = false;
  let catalog = [];
  let results = [];

  const BLOCK_RE = /Just a moment|安全验证|人机验证|Verify|Access Denied|Forbidden/i;
  const NEXT_RE  = /下一[章页]|next chapter/i;
  // Lines to throw away from extracted text
  const JUNK_RE  = /当前位置|上一章|下一章|回目录|©\s*20\d\d|quanben-xiaoshuo\.(net|com)|document\.domain|this\.location|GoogleAnalytics|function\(i,s,o|ga\("create|ga\("send|\(function\(/i;

  // ── บล็อกโฆษณา CSS ──────────────────────────────────────────────────────────
  const adCss = document.createElement('style');
  adCss.id = APP + '-ad';
  adCss.textContent = `
    .ad,.ads,.ad-box,.adbox,.advertisement,.advert,.adv,#adv,
    .ad_div,#ad_div,.ad-wrap,.ad-area,.ad-container,
    .adsbygoogle,ins.adsbygoogle,[class*="google-ad"],[id*="google-ad"],
    [class*="ad-banner"],[id*="ad-banner"],[class*="gg-"],[id*="gg-"],
    .float-ad,.pop-ad,.popup-ad,.overlay-ad,.modal-ad,
    .banner-ad,.sidebar-ad,.header-ad,.footer-ad,.top-ad,
    iframe[src*="googlesyndication"],iframe[src*="doubleclick"],
    iframe[src*="adservice"],iframe[src*="yieldmanager"],
    [id^="div-gpt-ad"],[class^="div-gpt-ad"],
    .notice-wrap,.tips-wrap,.qrcode-wrap {
      display:none!important;
      visibility:hidden!important;
      pointer-events:none!important;
      height:0!important;
      overflow:hidden!important;
    }`;
  document.head.append(adCss);

  // ── ฟังก์ชันช่วย ─────────────────────────────────────────────────────────────
  function clean(s) {
    return String(s || '').replace(/\r/g, '').replace(/ /g, ' ')
      .replace(/[ \t]+/g, ' ').split('\n').map(x => x.trim()).filter(Boolean).join('\n');
  }
  function safeTitle(s) {
    return String(s || '').replace(/[\\/:*?"<>|]/g, '_').trim().slice(0, 120) || 'novel';
  }
  function novelTitle() {
    const h = document.querySelector('h1, .book-title, .bookname, .title');
    return safeTitle(h?.textContent) || safeTitle(S.slug);
  }

  // ── สแกนสารบัญ ──────────────────────────────────────────────────────────────
  async function fetchCatalog() {
    let doc;
    if (S.isIndexPage) {
      doc = document;
    } else {
      const resp = await fetch(S.catalogUrl, { credentials: 'include', cache: 'no-store' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const html = await resp.text();
      const based = html.replace(/(<head[^>]*>)/i, `$1<base href="${S.catalogUrl}">`);
      doc = new DOMParser().parseFromString(based, 'text/html');
    }

    const seen = new Set();
    const entries = [];
    for (const a of doc.querySelectorAll('a[href]')) {
      const raw = a.getAttribute('href') || '';
      if (!raw) continue;
      let resolved;
      try { resolved = new URL(raw, S.catalogUrl); } catch { continue; }
      const p = resolved.pathname;
      if (!p.startsWith(`/n/${S.slug}/`)) continue;
      if (p === `/n/${S.slug}/` || p === `/n/${S.slug}`) continue;
      const href = resolved.href;
      if (seen.has(href)) continue;
      seen.add(href);
      const numMatch = /\/(\d+)(?:\.html)?\/?$/.exec(p);
      const number   = numMatch ? Number(numMatch[1]) : entries.length + 1;
      entries.push({ number, title: clean(a.textContent) || `第${number}章`, url: href });
    }
    if (!entries.length) throw new Error('ไม่พบลิงก์ตอนในสารบัญ');
    return entries.sort((a, b) => a.number - b.number);
  }

  // Remove script/style/nav noise from a parsed doc so textContent is clean
  function cleanDoc(doc) {
    const rm = 'script,style,noscript,nav,header,footer,aside,.breadcrumb,#breadcrumb,.chapter-nav,.page-path,.nav-btn,.copyright,[class*="ad"],[id*="ad"]';
    doc.querySelectorAll(rm).forEach(el => el.remove());
  }

  // Extract paragraphs from an element, handling <p>, <br>, and 　　 indents
  function parseParagraphs(box) {
    // Try <p> tags first
    const ps = [...box.querySelectorAll('p')]
      .map(p => clean(p.textContent || p.innerText || ''))
      .filter(s => s.length > 1 && !JUNK_RE.test(s));
    if (ps.length >= 3) return ps;

    // Replace <br> with newline then get textContent
    const tmpHtml = (box.innerHTML || '').replace(/<br\s*\/?>/gi, '\n');
    const tmp = box.ownerDocument.createElement('div');
    tmp.innerHTML = tmpHtml;
    const raw = tmp.textContent || box.textContent || box.innerText || '';

    // Try newline split first, then 　　 (Chinese paragraph indent)
    let lines = clean(raw).split(/\n+/).map(s => s.trim()).filter(s => s.length > 2 && !JUNK_RE.test(s));
    if (lines.length >= 3) return lines;

    lines = clean(raw).split(/　　/).map(s => s.trim()).filter(s => s.length > 2 && !JUNK_RE.test(s));
    return lines;
  }

  // ── ดึงเนื้อหาจาก doc ───────────────────────────────────────────────────────
  function extractContent(doc, pageUrl) {
    // Strip scripts/nav before any text extraction
    cleanDoc(doc);

    const titleEl = doc.querySelector('h1.title, .chapter-title, h1, .chaptertitle');
    const chTitle = clean((titleEl?.textContent || titleEl?.innerText || ''));

    const contentSels = [
      '#chaptercontent', '#chapter-content', '.chapter-content',
      '#readcontent', '.readcontent', '.read-content',
      '#content', '.content', '.article-content',
      '.novel-content', '.text-content', '.chapterBody', '#chapterBody',
      'article', '.article'
    ];
    let paras = [];
    for (const sel of contentSels) {
      const box = doc.querySelector(sel);
      if (!box) continue;
      const ps = parseParagraphs(box);
      if (ps.length >= 2) { paras = ps; break; }
    }
    if (!paras.length) {
      // Last resort: all <p> tags in the document with substantial Chinese text
      const allP = [...doc.querySelectorAll('p')]
        .map(p => clean(p.textContent || ''))
        .filter(s => s.length > 10 && /[一-鿿]/.test(s) && !JUNK_RE.test(s));
      if (allP.length >= 3) paras = allP;
    }
    if (!paras.length) {
      const body = doc.body;
      const raw = body?.textContent || body?.innerText || '';
      paras = clean(raw).split(/\n+|　　/).map(s => s.trim())
        .filter(s => s.length > 10 && !JUNK_RE.test(s));
    }

    let nextUrl = null;
    for (const a of doc.querySelectorAll('a[href]')) {
      const txt = (a.innerText || a.textContent || '').trim();
      if (NEXT_RE.test(txt)) {
        const raw = a.getAttribute('href') || '';
        try {
          const r = new URL(raw, pageUrl);
          if (r.pathname !== new URL(pageUrl).pathname) { nextUrl = r.href; break; }
        } catch {}
      }
    }

    return { title: chTitle, paras, nextUrl };
  }

  // ── Fast Fetch ───────────────────────────────────────────────────────────────
  async function fastFetch(url) {
    const resp = await fetch(url, { credentials: 'include', cache: 'no-store' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const html = await resp.text();
    if (BLOCK_RE.test(html.slice(0, 2000))) throw new Error('blocked');
    const based = html.replace(/(<head[^>]*>)/i, `$1<base href="${url}">`);
    const doc = new DOMParser().parseFromString(based, 'text/html');
    return { ...extractContent(doc, url), method: 'fetch' };
  }

  // ── iframe Fallback ──────────────────────────────────────────────────────────
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
          if (!doc) { frame.remove(); reject(new Error('no doc')); return; }
          if (BLOCK_RE.test((doc.body?.innerText || '').slice(0, 1000))) {
            frame.remove(); reject(new Error('blocked')); return;
          }
          frame.remove();
          resolve({ ...extractContent(doc, url), method: 'iframe' });
        } catch (e) { frame.remove(); reject(e); }
      }

      frame.onload = () => setTimeout(() => finish(null), 700);
      frame.onerror = () => finish(new Error('load error'));
      frame.src = url;
      document.body.append(frame);
    });
  }

  async function fetchChapter(url, attempt = 1) {
    try {
      const r = await fastFetch(url);
      if (r.paras.length < 3) throw new Error('too short');
      return r;
    } catch (_) {
      try { return await iframeFetch(url); }
      catch (e) {
        if (attempt < 3 && !stopped) { await sleep(attempt * 1500); return fetchChapter(url, attempt + 1); }
        throw e;
      }
    }
  }

  // ── UI ───────────────────────────────────────────────────────────────────────
  const panel = document.createElement('section');
  panel.id = APP;
  panel.innerHTML = `
    <div class="qb-head"><span>⚡ โหลดนิยาย</span><button id="qb-min">−</button></div>
    <div id="qb-body">
      <div id="qb-info">ตรวจหาสารบัญ…</div>

      <div class="qb-label">ลิงก์ตอนแรก <small>(ถ้าสแกนสารบัญไม่ได้ หรืออยู่ในตอนนั้นอยู่แล้ว)</small></div>
      <input id="qb-firsturl" type="url" placeholder="https://quanben-xiaoshuo.com/n/.../1/">

      <div class="qb-row">
        <button class="qb-cnt" data-n="50">50</button>
        <button class="qb-cnt" data-n="100">100</button>
        <button class="qb-cnt" data-n="200">200</button>
        <button class="qb-cnt" data-n="300">300</button>
      </div>
      <div class="qb-row">
        <input id="qb-from"  type="number" min="1"   placeholder="เริ่มตอนที่" value="1">
        <input id="qb-limit" type="number" min="1"   placeholder="จำนวน"       value="100">
        <input id="qb-delay" type="number" min="200" placeholder="หน่วง ms"    value="500">
      </div>
      <div class="qb-row">
        <button id="qb-run">▶ เริ่มเก็บเร็ว</button>
        <button id="qb-stop" disabled>■ หยุด</button>
      </div>
      <progress id="qb-prog" max="100" value="0"></progress>
      <div id="qb-status">พร้อม • Fast Fetch + iframe Fallback</div>
      <div class="qb-row">
        <button id="qb-copy" disabled>Copy ทั้งหมด</button>
        <button id="qb-dl"   disabled>ดาวน์โหลด TXT</button>
      </div>
      <div id="qb-log"></div>
    </div>`;
  document.body.append(panel);

  const css = document.createElement('style');
  css.id = APP + '-css';
  css.textContent = `
    #${APP}{position:fixed;z-index:2147483647;right:10px;bottom:10px;width:min(370px,calc(100vw - 20px));background:#1a1a2e;color:#e0e0f0;border:2px solid #f5a623;border-radius:16px;box-shadow:0 12px 40px #000a;font:14px/1.5 system-ui,sans-serif;overflow:hidden}
    #${APP} *{box-sizing:border-box}
    #${APP} .qb-head{display:flex;justify-content:space-between;align-items:center;background:#f5a623;color:#1a1a2e;padding:10px 14px;font-weight:800;font-size:15px}
    #${APP} #qb-body{padding:12px;display:flex;flex-direction:column;gap:7px}
    #${APP} #qb-info{font-size:12px;color:#aaa;text-align:center;background:#0f0f1e;border-radius:8px;padding:6px 10px;word-break:break-all}
    #${APP} .qb-label{font-size:11px;color:#888;margin-bottom:-4px}
    #${APP} .qb-label small{color:#666}
    #${APP} .qb-row{display:flex;gap:6px;flex-wrap:wrap}
    #${APP} button{flex:1;border:0;border-radius:10px;padding:9px 8px;background:#f5a623;color:#1a1a2e;font-weight:700;cursor:pointer;font-size:13px}
    #${APP} button:disabled{opacity:.35;cursor:default}
    #${APP} button.qb-cnt{background:#2d2d50;color:#f5a623;border:1px solid #f5a62366}
    #${APP} button.qb-cnt.active{background:#f5a623;color:#1a1a2e}
    #${APP} #qb-min{flex:none;width:32px;padding:2px;background:#fff3;font-size:18px;border-radius:8px}
    #${APP} input{flex:1;min-width:60px;padding:8px;border:1px solid #444;border-radius:9px;background:#0f0f1e;color:#e0e0f0;font-size:12px;text-align:center}
    #${APP} #qb-firsturl{text-align:left;font-size:11px;color:#ccc}
    #${APP} progress{width:100%;height:10px;border-radius:5px;accent-color:#f5a623}
    #${APP} #qb-status{font-size:12px;color:#f5a623;font-weight:600;text-align:center}
    #${APP} #qb-copy{background:#2d2d50;color:#e0e0f0;border:1px solid #555}
    #${APP} #qb-dl{background:#27ae60;color:#fff}
    #${APP} #qb-log{max-height:75px;overflow-y:auto;font-size:11px;color:#888;background:#0a0a18;border-radius:8px;padding:6px 8px;white-space:pre-wrap;word-break:break-all}`;
  document.head.append(css);

  const $ = s => panel.querySelector(s);
  const ui = {
    body: $('#qb-body'), info: $('#qb-info'),
    firstUrl: $('#qb-firsturl'),
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
  function setRunning(v) { running = v; ui.run.disabled = v; ui.stop.disabled = !v; }
  function finishRun() {
    const ok   = results.filter(r => r.method !== 'fail').length;
    const fail = results.length - ok;
    setStatus(`เสร็จ ${ok} ตอน${fail ? ` (ล้มเหลว ${fail})` : ''} — พร้อมดาวน์โหลด`);
    ui.copy.disabled = ui.dl.disabled = !results.length;
    setRunning(false);
  }

  ui.cnts.forEach(btn => {
    btn.onclick = () => {
      ui.cnts.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      ui.limit.value = btn.dataset.n;
    };
  });
  panel.querySelector('[data-n="100"]').classList.add('active');

  // ── init: สแกนสารบัญ + auto-fill URL ────────────────────────────────────────
  async function init() {
    S = getUrlState();

    // ถ้าอยู่บน chapter page → auto-fill firstUrl + ย่อ panel ไว้ก่อน
    if (!S.isIndexPage) {
      if (!ui.firstUrl.value) {
        ui.firstUrl.value = location.href;
        if (S.chapterNum) ui.from.value = S.chapterNum;
      }
      // Minimize by default on chapter pages so it doesn't block reading
      if (ui.body.style.display !== 'none') {
        ui.body.style.display = 'none';
        ui.min.textContent = '+';
      }
    } else {
      ui.body.style.display = '';
      ui.min.textContent = '−';
    }

    try {
      setStatus('กำลังสแกนสารบัญ…');
      catalog = await fetchCatalog();
      const last = catalog.at(-1)?.number || '?';
      ui.info.textContent = `📚 ${novelTitle()} — พบ ${catalog.length} ตอน (1–${last})`;
      setStatus(`พร้อม • ${catalog.length} ตอน • Fast Fetch + iframe Fallback`);
    } catch (e) {
      ui.info.textContent = `⚠️ สแกนสารบัญไม่ได้ — ลิงก์ตอนแรกถูก auto-fill แล้ว กด ▶ ได้เลย`;
      setStatus('กด ▶ เพื่อเริ่มจากลิงก์ตอนแรกด้านบน');
      addLog('สแกนสารบัญล้มเหลว: ' + e.message);
    }
  }

  // ── Mode A: โหลดจาก catalog ─────────────────────────────────────────────────
  async function runFromCatalog(selected) {
    ui.prog.max = selected.length; ui.prog.value = 0;
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
      if (i < selected.length - 1 && !stopped) await sleep(Number(ui.delay.value) || 500);
    }
  }

  // ── Mode B: โหลดจากลิงก์ตอนแรก ตาม "下一章" ────────────────────────────────
  async function runFromUrl(startUrl) {
    const limit = Math.max(1, Number(ui.limit.value) || 100);
    const delay = Math.max(200, Number(ui.delay.value) || 500);
    ui.prog.max = limit; ui.prog.value = 0;

    let currentUrl = startUrl;
    let chNum = Math.max(1, Number(ui.from.value) || 1);

    for (let i = 0; i < limit && !stopped && currentUrl; i++) {
      setStatus(`โหลดตอน ${chNum} (${i + 1}/${limit})`);
      try {
        const data = await fetchChapter(currentUrl);
        results.push({ number: chNum, title: data.title || `第${chNum}章`, content: data.paras.join('\n\n'), method: data.method });
        addLog(`✓ ตอน ${chNum} [${data.method}] ${data.paras.length} ย่อหน้า — ถัดไป: ${data.nextUrl ? '✓' : '✗'}`);
        currentUrl = data.nextUrl || null;
      } catch (e) {
        results.push({ number: chNum, title: `第${chNum}章`, content: '[โหลดไม่สำเร็จ: ' + e.message + ']', method: 'fail' });
        addLog(`✗ ตอน ${chNum}: ${e.message}`);
        currentUrl = null;
      }
      chNum++;
      ui.prog.value = i + 1;
      if (i < limit - 1 && !stopped && currentUrl) await sleep(delay);
    }
    if (!currentUrl && !stopped) addLog('ถึงตอนสุดท้ายที่มีแล้ว');
  }

  // ── main run ────────────────────────────────────────────────────────────────
  async function run() {
    if (running) return;
    stopped = false; results = []; setRunning(true);
    ui.copy.disabled = ui.dl.disabled = true;

    const manualUrl = ui.firstUrl.value.trim();

    if (manualUrl) {
      addLog('โหมด: ลิงก์ตอนแรก → ตาม 下一章 อัตโนมัติ');
      await runFromUrl(manualUrl);
    } else {
      const fromN  = Math.max(1, Number(ui.from.value) || 1);
      const limit  = Math.max(1, Number(ui.limit.value) || 100);
      const selected = catalog.filter(x => x.number >= fromN).slice(0, limit);

      if (!selected.length) {
        setStatus('ไม่พบตอนใน catalog — กรุณาใส่ลิงก์ตอนแรก'); setRunning(false); return;
      }
      addLog(`โหมด: catalog (${selected.length} ตอน)`);
      await runFromCatalog(selected);
    }
    finishRun();
  }

  // ── Build TXT ────────────────────────────────────────────────────────────────
  function buildTxt() {
    const title = novelTitle();
    const parts = [`${title}\n${'═'.repeat(30)}\n`];
    for (const r of results)
      parts.push(`\n${r.title}\n${'─'.repeat(20)}\n\n${r.content}\n`);
    const failed = results.filter(r => r.method === 'fail').map(r => r.number);
    if (failed.length) parts.push(`\n[ตอนที่โหลดไม่สำเร็จ: ${failed.join(', ')}]`);
    return parts.join('');
  }

  // ── Events ──────────────────────────────────────────────────────────────────
  ui.run.onclick = run;
  ui.stop.onclick = () => { stopped = true; setStatus('กำลังหยุด…'); };
  ui.min.onclick = () => {
    const show = ui.body.style.display === 'none';
    ui.body.style.display = show ? '' : 'none';
    ui.min.textContent = show ? '−' : '+';
  };
  ui.copy.onclick = () => {
    const txt = buildTxt();
    navigator.clipboard?.writeText(txt).then(() => setStatus('Copy สำเร็จ!')).catch(() => {
      const ta = Object.assign(document.createElement('textarea'), { value: txt });
      document.body.append(ta); ta.select(); document.execCommand('copy'); ta.remove();
      setStatus('Copy สำเร็จ!');
    });
  };
  ui.dl.onclick = () => {
    const txt  = buildTxt();
    const name = `${safeTitle(novelTitle())}_${results[0]?.number || 1}-${results.at(-1)?.number || ''}.txt`;
    const blob = new Blob(['﻿' + txt], { type: 'text/plain;charset=utf-8' });
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: name });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 3000);
  };

  // ── SPA navigation: keep panel alive + re-init on URL change ────────────────
  let lastHref = location.href;

  // Poll every 1.5s: re-add panel/styles if SPA removed them, detect URL change
  setInterval(() => {
    const body = document.body;
    if (body && !body.contains(panel)) body.append(panel);
    if (document.head && !document.head.contains(css)) document.head.append(css);
    if (document.head && !document.head.contains(adCss)) document.head.append(adCss);

    if (location.href !== lastHref) {
      lastHref = location.href;
      if (!running) {
        catalog = []; results = [];
        ui.firstUrl.value = '';
        ui.prog.value = 0;
        ui.copy.disabled = ui.dl.disabled = true;
        ui.log.textContent = '';
        init();
      }
    }
  }, 1500);

  init();
})();
