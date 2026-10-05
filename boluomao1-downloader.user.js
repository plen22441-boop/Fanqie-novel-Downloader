// ==UserScript==
// @name         Boluomao1 Full Novel Downloader
// @namespace    fanfan-novel-downloader
// @version      1.1.0
// @description  ดาวน์โหลดทุกตอนจาก boluomao1.com รวมตอนหลายหน้า ตรวจตกหล่น และส่งออก TXT/ZIP UTF-8
// @author       Fanfan
// @match        https://www.boluomao1.com/book/*.html
// @match        https://boluomao1.com/book/*.html
// @match        https://www.boluomao1.com/chapter/*.html
// @match        https://boluomao1.com/chapter/*.html
// @match        https://www.boluomao1.com/read/*/*.html
// @match        https://boluomao1.com/read/*/*.html
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  const APP = 'blm1-downloader';
  const PUA = /[-]/;
  const HEAD = /第\s*([0-9０-９]+)\s*[章节回]/i;
  // รองรับ URL pattern: /chapter/12345.html หรือ /read/bookid/chapterid.html
  const URL_CHAPTER_SIMPLE = /\/chapter\/([0-9]+)(?:-([0-9]+))?\.html/i;
  const URL_CHAPTER_READ   = /\/read\/[^/]+\/([0-9]+)(?:-([0-9]+))?\.html/i;
  const BLOCK = /Just a moment|安全验证|人机验证|Verify Yourself|Access Denied|Forbidden/i;
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  let stopped = false, running = false, catalog = [], results = new Map();

  // ตรวจว่าอยู่หน้าไหน
  const isBookPage = /\/book\/[0-9]+\.html/.test(location.pathname);
  // ดึง book_id จาก /read/{book_id}/{chapter_id}.html
  const readMatch = /\/read\/([0-9]+)\//.exec(location.pathname);
  const bookIdFromRead = readMatch ? readMatch[1] : null;

  function asciiDigits(v) {
    return String(v || '').replace(/[０-９]/g, c => String(c.charCodeAt(0) - 0xFF10));
  }
  function clean(v) {
    return String(v || '').replace(/\r/g, '').replace(/ /g, ' ')
      .replace(/[ \t]+/g, ' ').split('\n').map(x => x.trim()).filter(Boolean).join('\n');
  }
  function urlPart(url) {
    const m = URL_CHAPTER_SIMPLE.exec(url) || URL_CHAPTER_READ.exec(url);
    return m ? { number: Number(m[1]), part: Number(m[2] || 1) } : { number: null, part: 1 };
  }
  function chapterNo(text, url = '') {
    const h = HEAD.exec(asciiDigits(text));
    if (h) return Number(h[1]);
    const p = urlPart(url);
    return p.number;
  }
  function title() { return (document.title.split(/[_｜|\-–]/)[0] || 'novel').trim(); }
  function safeName(v, fb = 'novel') {
    return (String(v || '').replace(/[\\/:*?"<>|]/g, '_').replace(/\s+/g, '_')
      .slice(0, 100).replace(/^[_.]+|[_.]+$/g, '') || fb);
  }

  // ─── UI ────────────────────────────────────────────────────────────────────
  const panel = document.createElement('section');
  panel.id = APP;
  panel.innerHTML = `
    <div class="bl-head"><strong>📚 โหลดนิยาย Boluomao1</strong><button id="bl-min">−</button></div>
    <div id="bl-body">
      <div class="bl-grid">
        <label>ตอนเริ่ม<input id="bl-start" inputmode="numeric" value="1"></label>
        <label>ตอนจบ<input id="bl-end" inputmode="numeric" placeholder="อัตโนมัติ"></label>
        <label>หน่วง(ms)<input id="bl-delay" inputmode="numeric" value="700"></label>
      </div>
      <div class="bl-act"><button id="bl-scan">1. สแกนสารบัญ</button><button id="bl-run" disabled>2. เริ่มโหลด</button><button id="bl-stop" disabled>หยุด</button></div>
      <progress id="bl-prog" max="1" value="0"></progress>
      <div id="bl-status">พร้อมใช้งาน${isBookPage ? ' (หน้าสารบัญ)' : ' (หน้าตอน)'}</div>
      <textarea id="bl-log" readonly></textarea>
      <div class="bl-act"><button id="bl-txt" disabled>TXT รวม</button><button id="bl-zip" disabled>ZIP + รายตอน</button><button id="bl-qc" disabled>รายงาน QC</button></div>
    </div>`;
  document.body.append(panel);

  const style = document.createElement('style');
  style.textContent = `
    #${APP}{position:fixed;z-index:2147483647;right:8px;bottom:8px;width:min(440px,calc(100vw - 16px));background:#f6fff9;color:#1a2b1a;border:2px solid #2e7d52;border-radius:15px;box-shadow:0 10px 35px #0005;font:14px/1.45 system-ui,sans-serif;overflow:hidden}
    #${APP} *{box-sizing:border-box}
    #${APP} .bl-head{display:flex;justify-content:space-between;align-items:center;background:#2e7d52;color:#fff;padding:10px 12px}
    #${APP} #bl-body{padding:10px}
    #${APP} button{border:0;border-radius:9px;padding:9px 11px;background:#2e7d52;color:#fff;font-weight:700;cursor:pointer}
    #${APP} button:disabled{opacity:.4;cursor:default}
    #${APP} #bl-min{padding:1px 10px;background:#ffffff22;font-size:20px}
    #${APP} .bl-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}
    #${APP} label{font-size:12px}
    #${APP} input{width:100%;margin-top:3px;padding:7px;border:1px solid #a8d5b5;border-radius:7px}
    #${APP} .bl-act{display:flex;gap:7px;flex-wrap:wrap;margin-top:9px}
    #${APP} progress{width:100%;height:14px;margin-top:10px}
    #${APP} #bl-status{margin:7px 0;font-weight:700}
    #${APP} textarea{width:100%;height:110px;resize:vertical;border:1px solid #c5e8d0;border-radius:8px;padding:7px;background:#fff;font:12px/1.4 monospace}
    @media(max-width:480px){#${APP} .bl-grid{grid-template-columns:1fr 1fr}#${APP} button{flex:1}}`;
  document.head.append(style);

  const $ = s => panel.querySelector(s);
  const ui = {
    body: $('#bl-body'), start: $('#bl-start'), end: $('#bl-end'), delay: $('#bl-delay'),
    scan: $('#bl-scan'), run: $('#bl-run'), stop: $('#bl-stop'),
    txt: $('#bl-txt'), zip: $('#bl-zip'), qc: $('#bl-qc'),
    prog: $('#bl-prog'), status: $('#bl-status'), log: $('#bl-log'), min: $('#bl-min')
  };

  function log(msg) { ui.log.value += `[${new Date().toLocaleTimeString('th-TH', { hour12: false })}] ${msg}\n`; ui.log.scrollTop = ui.log.scrollHeight; }
  function status(msg) { ui.status.textContent = msg; log(msg); }
  function setRunning(v) { running = v; ui.scan.disabled = v; ui.run.disabled = v || !catalog.length; ui.stop.disabled = !v; }
  function selectedCatalog() {
    const a = Math.max(1, Number(ui.start.value) || 1), b = Number(ui.end.value) || Infinity;
    return catalog.filter(x => x.number >= a && x.number <= b);
  }

  // ─── SCAN สารบัญ ────────────────────────────────────────────────────────────
  // รองรับทั้งหน้า book และหน้า chapter (เปิด book page ด้วย fetch)
  async function scan() {
    if (running) return;
    setRunning(true); stopped = false; results = new Map();
    ui.txt.disabled = ui.zip.disabled = ui.qc.disabled = true;
    try {
      let html = '';
      if (isBookPage) {
        html = document.documentElement.innerHTML;
      } else {
        // สร้าง URL สารบัญจาก book_id ที่ดึงจาก path หรือหา link ใน DOM
        let bookUrl = null;
        if (bookIdFromRead) {
          bookUrl = `${location.origin}/book/${bookIdFromRead}.html`;
        } else {
          const bookLink = document.querySelector('a[href*="/book/"]');
          if (bookLink) bookUrl = bookLink.href;
        }
        if (!bookUrl) throw new Error('ไม่พบ URL สารบัญ — กรุณาเปิดหน้าสารบัญ (boluomao1.com/book/XXXXX.html) แล้วลองใหม่');
        status('กำลังโหลดสารบัญจาก ' + bookUrl);
        const resp = await fetch(bookUrl, { credentials: 'include', cache: 'no-store' });
        if (!resp.ok) throw new Error(`โหลดสารบัญไม่สำเร็จ HTTP ${resp.status}`);
        html = await resp.text();
      }

      const parser = new DOMParser();
      const doc = parser.parseFromString(html, 'text/html');
      const found = new Map();

      // ลอง selector หลายแบบที่เว็บนิยายจีนใช้
      const chapterListSelectors = [
        '#chapter-list a', '.chapter-list a', '.chapter_list a',
        '#chapterList a', '.chapterList a', '.list-chapter a',
        '.catalog-list a', '#catalog a', '.volume-list a',
        '#book-detail-list a', '.book-chapter-list a', 'ul.list a',
        '.list a[href*="/chapter/"]', '.list a[href*="/read/"]',
        'a[href*="/chapter/"]', 'a[href*="/read/"]'
      ];

      let links = [];
      for (const sel of chapterListSelectors) {
        links = [...doc.querySelectorAll(sel)];
        if (links.length > 2) break;
      }
      if (!links.length) throw new Error('ไม่พบลิงก์ตอนในสารบัญ — อาจต้องปรับ selector สำหรับเว็บนี้');

      for (const a of links) {
        const p = urlPart(a.href), number = chapterNo(a.textContent, a.href);
        if (!number || p.part !== 1) continue;
        const candidate = { number, title: clean(a.textContent) || `第${number}章`, url: a.href };
        if (!found.has(number) || candidate.title.length > found.get(number).title.length)
          found.set(number, candidate);
      }

      catalog = [...found.values()].sort((a, b) => a.number - b.number);
      if (!catalog.length) throw new Error('ไม่พบตอนใดเลย — กรุณาตรวจสอบ URL หรือ selector');

      ui.start.value = catalog[0].number;
      ui.end.placeholder = String(catalog.at(-1).number);
      status(`พบ ${catalog.length} ตอน (${catalog[0].number}–${catalog.at(-1).number})`);
    } catch (e) { status('สแกนไม่สำเร็จ: ' + e.message); }
    finally { setRunning(false); }
  }

  // ─── โหลดหน้าตอน ────────────────────────────────────────────────────────────
  async function renderedPage(url, attempt = 1) {
    const rawPromise = fetch(url, { credentials: 'include', cache: 'no-store' }).then(r => r.ok ? r.text() : '').catch(() => '');
    try {
      return await new Promise((resolve, reject) => {
        const frame = document.createElement('iframe'); let done_called = false;
        frame.style.cssText = 'position:fixed;width:1px;height:1px;left:-9999px;top:-9999px;opacity:.01;pointer-events:none';
        const timer = setTimeout(() => finish(new Error('หมดเวลา')), 30000);
        async function finish(err) {
          if (done_called) return; done_called = true; clearTimeout(timer);
          const rawHtml = await rawPromise;
          try {
            if (err) throw err;
            const doc = frame.contentDocument, pageText = doc?.body?.innerText || '';
            if (!doc || BLOCK.test(pageText)) throw new Error('หน้าขอการยืนยัน');
            const titleNode = doc.querySelector('h1.title, .chapter-title h1, .chaptertitle, h1, .title');
            const chapterTitle = clean(titleNode?.innerText || '');
            // ลอง selector เนื้อหาหลายแบบ
            const contentSelectors = [
              '.chapter-content', '#chapter-content', '.read-content', '#read-content',
              '.content', '#content', '.article-content', '#article-content',
              '.text-content', '.novel-content', '.chapterBody', '#chapterBody'
            ];
            let paras = [];
            for (const sel of contentSelectors) {
              const box = doc.querySelector(sel);
              if (box) {
                paras = [...box.querySelectorAll('p')].map(p => clean(p.innerText)).filter(Boolean);
                if (!paras.length) paras = String(box.innerText).split(/\n+/).map(clean).filter(Boolean);
                if (paras.length > 0) break;
              }
            }
            if (!paras.length) {
              // fallback: ดึงจาก body ทั้งหมด กรองส่วน nav ออก
              paras = String(doc.body?.innerText || '').split(/\n+/).map(clean).filter(x => x.length > 10);
            }
            const links = [...doc.querySelectorAll('a[href]')].map(a => ({ text: clean(a.innerText), href: a.href, cls: a.className || '' }));
            resolve({ title: chapterTitle, paras, links, rawHtml });
          } catch (e) { reject(e); }
          finally { frame.remove(); }
        }
        frame.onload = () => setTimeout(() => finish(null), 700);
        frame.onerror = () => finish(new Error('เปิดหน้าไม่สำเร็จ'));
        frame.src = url; document.body.append(frame);
      });
    } catch (e) {
      if (attempt >= 4 || stopped) throw e;
      await sleep(attempt * 1400); return renderedPage(url, attempt + 1);
    }
  }

  function nextPage(links, number, visited) {
    return links.map(x => ({ ...x, ...urlPart(x.href) }))
      .filter(x => x.number === number && !visited.has(x.href))
      .sort((a, b) =>
        ((/下一页|หน้าถัดไป/.test(a.text) || /next/i.test(a.cls)) ? 0 : 1) -
        ((/下一页|หน้าถัดไป/.test(b.text) || /next/i.test(b.cls)) ? 0 : 1) ||
        a.part - b.part
      )[0]?.href || null;
  }

  async function scrape(item) {
    const out = { number: item.number, title: item.title, firstUrl: item.url, pages: [], paragraphs: [], status: 'ok', warnings: [], error: '' };
    let current = item.url; const visited = new Set();
    try {
      while (current && !visited.has(current)) {
        if (stopped) throw new Error('หยุดโดยผู้ใช้');
        visited.add(current);
        const page = await renderedPage(current);
        const observed = chapterNo(page.title, current);
        if (observed && observed !== item.number) throw new Error(`เลขตอนไม่ตรง: คาด ${item.number} พบ ${observed}`);
        if (!page.paras.length) throw new Error('ไม่พบเนื้อหา');
        out.title = page.title || out.title; out.pages.push(current); out.paragraphs.push(...page.paras);
        if (PUA.test(page.rawHtml) || PUA.test(page.paras.join(''))) { out.status = 'suspicious'; out.warnings.push('พบอักขระป้องกันคัดลอก'); }
        current = nextPage(page.links, item.number, visited);
        if (current) await sleep(Math.max(250, Number(ui.delay.value) || 700));
      }
      const body = out.paragraphs.join('\n\n'), count = body.replace(/\s/g, '').length;
      if (body.includes('')) { out.status = 'suspicious'; out.warnings.push('encoding เสีย'); }
      if (count < 200) { out.status = 'suspicious'; out.warnings.push(`สั้นผิดปกติ ${count} ตัวอักษร`); }
      if (out.pages.length > 1) out.warnings.push(`รวม ${out.pages.length} หน้า`);
    } catch (e) { out.status = 'failed'; out.error = e.message; }
    return out;
  }

  async function run() {
    const selected = selectedCatalog();
    if (running || !selected.length) return status('ช่วงตอนที่เลือกไม่พบในสารบัญ');
    stopped = false; results = new Map(); setRunning(true);
    ui.prog.max = selected.length; ui.prog.value = 0;
    try {
      for (let i = 0; i < selected.length && !stopped; i++) {
        const item = selected[i]; status(`โหลดตอน ${item.number} (${i + 1}/${selected.length})`);
        const result = await scrape(item); results.set(item.number, result); ui.prog.value = i + 1;
        log(`ตอน ${item.number}: ${result.status} — ${result.error || result.warnings.join('; ') || result.pages.length + ' หน้า'}`);
        await sleep(Math.max(250, Number(ui.delay.value) || 700));
      }
      const r = makeReport(selected);
      ui.txt.disabled = ui.zip.disabled = ui.qc.disabled = !results.size;
      status(r.complete ? `เสร็จ ${r.savedChapters} ตอน — ผ่าน QC` : 'เสร็จแล้ว — เปิด QC ก่อนใช้ไฟล์');
    } finally { setRunning(false); }
  }

  // ─── QC / Export ────────────────────────────────────────────────────────────
  function gaps(items) {
    if (!items.length) return [];
    const have = new Set(items.map(x => x.number)), out = [];
    for (let n = items[0].number; n <= items.at(-1).number; n++) if (!have.has(n)) out.push(n);
    return out;
  }
  function makeReport(selected = selectedCatalog()) {
    const all = [...results.values()].sort((a, b) => a.number - b.number);
    const failed = all.filter(x => x.status === 'failed').map(x => x.number);
    const suspicious = all.filter(x => x.status === 'suspicious').map(x => x.number);
    const notAttempted = selected.filter(x => !results.has(x.number)).map(x => x.number);
    return { bookTitle: title(), requestedRange: selected.length ? [selected[0].number, selected.at(-1).number] : [], discoveredChapters: selected.length, savedChapters: all.filter(x => x.status !== 'failed').length, catalogGaps: gaps(selected), failedChapters: failed, suspiciousChapters: suspicious, notAttempted, complete: !gaps(selected).length && !failed.length && !suspicious.length && !notAttempted.length, generatedAt: new Date().toISOString(), chapters: all.map(x => ({ ...x, characterCount: x.paragraphs.join('').length })) };
  }
  function reportText(r) {
    const list = a => a.length ? a.join(', ') : 'ไม่มี';
    const lines = ['รายงานตรวจความครบถ้วน', `เรื่อง: ${r.bookTitle}`, `ช่วงตอน: ${r.requestedRange.join('–')}`, `พบในสารบัญ: ${r.discoveredChapters} ตอน`, `บันทึกสำเร็จ: ${r.savedChapters} ตอน`, `ช่องว่าง: ${list(r.catalogGaps)}`, `โหลดไม่สำเร็จ: ${list(r.failedChapters)}`, `ต้องตรวจ: ${list(r.suspiciousChapters)}`, `ยังไม่โหลด: ${list(r.notAttempted)}`, `ผลรวม: ${r.complete ? 'ครบและผ่าน QC' : 'ยังไม่ผ่าน QC'}`, '', 'รายละเอียด:'];
    for (const x of r.chapters) lines.push(`ตอน ${x.number}: ${x.status} | ${x.pages.length} หน้า | ${x.characterCount} ตัวอักษร | ${x.warnings.join('; ') || x.error || 'ปกติ'}`);
    return lines.join('\n') + '\n';
  }
  function combined(r) {
    const missing = [...new Set([...r.catalogGaps, ...r.failedChapters, ...r.notAttempted])].sort((a, b) => a - b);
    const parts = [`เรื่อง: ${r.bookTitle} — ตอนที่ ${r.requestedRange.join('–')}`, `ตอนขาด: ${missing.length ? missing.join(', ') : 'ไม่มี'}`, `ต้องตรวจ: ${r.suspiciousChapters.length ? r.suspiciousChapters.join(', ') : 'ไม่มี'}`, ''];
    for (const x of r.chapters.filter(x => x.status !== 'failed')) parts.push(`${x.title}\n\n${x.paragraphs.join('\n\n')}\n`);
    return parts.join('\n');
  }

  function bytes(text, bom = false) { const b = new TextEncoder().encode(text); return bom ? new Uint8Array([239, 187, 191, ...b]) : b; }
  function u16(n) { return new Uint8Array([n & 255, n >>> 8 & 255]); }
  function u32(n) { return new Uint8Array([n & 255, n >>> 8 & 255, n >>> 16 & 255, n >>> 24 & 255]); }
  function join(chunks) { const out = new Uint8Array(chunks.reduce((n, x) => n + x.length, 0)); let at = 0; for (const x of chunks) { out.set(x, at); at += x.length; } return out; }
  function crc32(data) { let crc = -1; for (const v of data) { crc ^= v; for (let k = 0; k < 8; k++) crc = crc >>> 1 ^ (0xEDB88320 & -(crc & 1)); } return (crc ^ -1) >>> 0; }
  function zipBlob(files) {
    const local = [], central = []; let offset = 0;
    for (const f of files) {
      const name = bytes(f.name), data = f.data, crc = crc32(data);
      const h = join([u32(0x04034b50),u16(20),u16(0x0800),u16(0),u16(0),u16(0),u32(crc),u32(data.length),u32(data.length),u16(name.length),u16(0),name]);
      local.push(h, data); central.push(join([u32(0x02014b50),u16(20),u16(20),u16(0x0800),u16(0),u16(0),u16(0),u32(crc),u32(data.length),u32(data.length),u16(name.length),u16(0),u16(0),u16(0),u16(0),u32(0),u32(offset),name])); offset += h.length + data.length;
    }
    const c = join(central), end = join([u32(0x06054b50),u16(0),u16(0),u16(files.length),u16(files.length),u32(c.length),u32(offset),u16(0)]);
    return new Blob([...local, c, end], { type: 'application/zip' });
  }
  function download(name, blob) { const a = document.createElement('a'), url = URL.createObjectURL(blob); a.href = url; a.download = name; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 3000); }

  // ─── Events ─────────────────────────────────────────────────────────────────
  ui.scan.onclick = scan;
  ui.run.onclick = run;
  ui.stop.onclick = () => { stopped = true; status('กำลังหยุด…'); };
  ui.min.onclick = () => { const show = ui.body.style.display === 'none'; ui.body.style.display = show ? '' : 'none'; ui.min.textContent = show ? '−' : '+'; };
  ui.txt.onclick = () => { const r = makeReport(), name = `novel_${r.requestedRange.join('-')}`; download(`${name}.txt`, new Blob(['﻿', combined(r)], { type: 'text/plain;charset=utf-8' })); };
  ui.qc.onclick = () => { download('QC_REPORT.txt', new Blob(['﻿', reportText(makeReport())], { type: 'text/plain;charset=utf-8' })); };
  ui.zip.onclick = () => {
    const r = makeReport(), base = `novel_${r.requestedRange.join('-')}`;
    const files = [{ name: `${base}.txt`, data: bytes(combined(r), true) }, { name: 'QC_REPORT.txt', data: bytes(reportText(r), true) }, { name: 'QC_REPORT.json', data: bytes(JSON.stringify(r, null, 2)) }];
    for (const x of r.chapters.filter(x => x.status !== 'failed')) files.push({ name: `chapters/${String(x.number).padStart(4, '0')}_ch${x.number}.txt`, data: bytes(`${x.title}\n\n${x.paragraphs.join('\n\n')}\n`, true) });
    download(`${base}.zip`, zipBlob(files));
  };

  log(isBookPage
    ? 'อยู่หน้าสารบัญ กด "1. สแกนสารบัญ" เลย'
    : bookIdFromRead
      ? `ตรวจพบ book_id=${bookIdFromRead} — กด "1. สแกนสารบัญ" ได้เลย`
      : 'อยู่หน้าตอน — แนะนำให้เปิดหน้าสารบัญ (/book/XXXXX.html) ก่อน');
})();
