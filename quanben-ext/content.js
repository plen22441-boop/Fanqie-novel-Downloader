(function () {
  'use strict';

  const APP = 'nd-universal';
  if (document.getElementById(APP)) return;

  const sleep = ms => new Promise(r => setTimeout(r, ms));

  // ── Site detection (for known sites with catalog support) ────────────────────
  const HOST = location.hostname.replace(/^www\./, '');
  const IS_QUANBEN  = /quanben-xiaoshuo\.(com|net)/.test(HOST);
  const IS_BOLUOMAO = HOST === 'boluomao1.com';

  function getUrlState() {
    const path = location.pathname;
    if (IS_QUANBEN) {
      const parts = path.replace(/^\//, '').split('/');
      const slug = parts[1] || '';
      return {
        slug,
        catalogUrl: `${location.origin}/n/${slug}/`,
        isIndexPage: parts.length <= 2 || !parts[2],
        chapterNum: (parts[2] && /^\d+$/.test(parts[2])) ? Number(parts[2]) : null
      };
    }
    if (IS_BOLUOMAO) {
      const bookM  = /\/book\/(\d+)\.html/.exec(path);
      const readM  = /\/read\/(\d+)\//.exec(path);
      const bookId = bookM ? bookM[1] : (readM ? readM[1] : null);
      const chM    = /\/chapter\/(\d+)/.exec(path) || /\/read\/\d+\/(\d+)/.exec(path);
      return {
        slug: bookId || '',
        catalogUrl: bookId ? `${location.origin}/book/${bookId}.html` : null,
        isIndexPage: !!bookM,
        chapterNum: chM ? Number(chM[1]) : null
      };
    }
    // Generic: unknown site — no catalog auto-scan
    return { slug: '', catalogUrl: null, isIndexPage: false, chapterNum: null };
  }
  let S = getUrlState();

  let stopped = false, running = false;
  let catalog = [];
  let results = [];

  const BLOCK_RE = /Just a moment|安全验证|人机验证|Verify you are human|Access Denied|Forbidden/i;
  // Match "next CHAPTER" only — not "next page" (避免跟着分页链接走)
  const NEXT_CH_RE = /下一[章节回篇]|next\s*chapter/i;
  // "next page" within same chapter (same chapter split into multiple pages)
  const NEXT_PG_RE = /下一页|next\s*page/i;
  const JUNK_RE  = /当前位置|上一章|下一章|回目录|©\s*20\d\d|document\.domain|this\.location|GoogleAnalytics|function\(i,s,o|ga\("create|ga\("send|\(function\(/i;
  // Filter out lines that are just novel recommendation titles 《...》 (with optional surrounding whitespace/tabs)
  const RECOMMEND_RE = /^\s*《[^》]{1,60}》\s*$/;

  // ── Text helpers ─────────────────────────────────────────────────────────────
  function clean(s) {
    return (s || '').replace(/ /g, ' ').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
  }

  function chNumFromText(t) {
    const m = /第\s*([零一二三四五六七八九十百千万\d]+)\s*[章节回]/u.exec(t)
           || /[Cc]hapter\s*(\d+)/i.exec(t)
           || /(\d+)/.exec(t);
    if (!m) return null;
    const d = m[1].replace(/[零一二三四五六七八九十百千万]/g, c => '零一二三四五六七八九十百千万'.indexOf(c));
    return parseInt(d, 10) || null;
  }

  function cleanDoc(doc) {
    doc.querySelectorAll('script,style,noscript,nav,header,footer,aside,.breadcrumb,#breadcrumb,.chapter-nav,.page-path,.nav-btn,.copyright,.ads,.ad,#ad,iframe').forEach(el => el.remove());
  }

  // ── Content selectors (tries many known patterns) ────────────────────────────
  const CONTENT_SELS = [
    '#content', '#chapter-content', '#chaptercontent', '#chapterContent',
    '.chapter-content', '.chaptercontent', '.content-chapter',
    '#article', '.article-content', '#articleBody',
    '#novelContent', '.novel-content', '#readcontent',
    '.readcontent', '#readContent', '.read-content',
    '#txt', '.txt', '#text', '.text-content',
    '#booktext', '.book-text', '#bookContent',
    '.entry-content', '.post-content', '.page-content',
    '#mainContent', '.main-content', 'article',
    '#chp_content', '.chp-content', '.chapter_content',
  ];

  // Score an element: higher = more likely real novel content.
  // Penalizes elements whose lines are mostly 《book recommendations》.
  function contentScore(el) {
    const raw = (el.textContent || '').trim();
    if (raw.length < 50) return 0;
    const lines = raw.split(/\n+/).map(s => s.trim()).filter(s => s.length > 1);
    if (!lines.length) return 0;
    const junkLines = lines.filter(s => RECOMMEND_RE.test(s) || isJunkLine(s)).length;
    const junkRatio = junkLines / lines.length;
    // Discount heavily if more than 30% junk
    const score = raw.length * (1 - junkRatio * 2);
    return score;
  }

  function findContentBox(doc) {
    // Try known selectors first — pick the one with best score
    let bestSel = null, bestSelScore = 0;
    for (const sel of CONTENT_SELS) {
      const el = doc.querySelector(sel);
      if (!el) continue;
      const sc = contentScore(el);
      if (sc > bestSelScore) { bestSelScore = sc; bestSel = el; }
    }
    if (bestSel && bestSelScore > 200) return bestSel;

    // Fallback: score all divs, pick the best
    let best = null, bestScore = 0;
    doc.querySelectorAll('div,section,article').forEach(el => {
      // Skip containers that are ancestors of a better candidate
      const sc = contentScore(el);
      if (sc > bestScore) { bestScore = sc; best = el; }
    });
    return best;
  }

  function isJunkLine(s) {
    return JUNK_RE.test(s) || RECOMMEND_RE.test(s);
  }

  function parseParagraphs(box) {
    const ps = [...box.querySelectorAll('p')]
      .map(p => clean(p.textContent || ''))
      .filter(s => s.length > 1 && !isJunkLine(s));
    if (ps.length >= 3) return ps;

    const tmpHtml = (box.innerHTML || '').replace(/<br\s*\/?>/gi, '\n');
    const tmp = box.ownerDocument.createElement('div');
    tmp.innerHTML = tmpHtml;
    const raw = tmp.textContent || box.textContent || '';
    let lines = clean(raw).split(/\n+/).map(s => s.trim()).filter(s => s.length > 2 && !isJunkLine(s));
    if (lines.length >= 3) return lines;

    return clean(raw).split(/　　/).map(s => s.trim()).filter(s => s.length > 2 && !isJunkLine(s));
  }

  // ── Find next-chapter and next-page links separately ─────────────────────────
  function findLinks(doc, baseUrl) {
    const all = [...doc.querySelectorAll('a')];
    let nextChapter = null, nextPage = null;
    for (const a of all) {
      const t = clean(a.textContent);
      const href = a.getAttribute('href');
      if (!href || href === '#') continue;
      const full = new URL(href, baseUrl).href;
      if (!nextChapter && NEXT_CH_RE.test(t)) nextChapter = full;
      if (!nextPage && NEXT_PG_RE.test(t)) nextPage = full;
    }
    return { nextChapter, nextPage };
  }

  // ── Title guess ───────────────────────────────────────────────────────────────
  function novelTitle() {
    if (IS_QUANBEN && S.slug) return S.slug;
    const t = document.title.replace(/[-_|–—].*$/, '').trim();
    return t || HOST;
  }

  // ── Fetch chapter via Fast Fetch ─────────────────────────────────────────────
  async function fastFetch(url) {
    const resp = await fetch(url, { credentials: 'include', cache: 'no-store' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const html = await resp.text();
    const doc = new DOMParser().parseFromString(html, 'text/html');
    // Fix relative URLs — set base
    const base = doc.createElement('base');
    base.href = url;
    doc.head.prepend(base);
    return doc;
  }

  // ── Fetch chapter via iframe ──────────────────────────────────────────────────
  async function iframeFetch(url, timeoutMs = 15000) {
    return new Promise((resolve, reject) => {
      const f = document.createElement('iframe');
      f.style.cssText = 'position:fixed;width:1px;height:1px;left:-9999px;top:-9999px;opacity:0;';
      f.sandbox = 'allow-same-origin allow-scripts';
      const timer = setTimeout(() => { f.remove(); reject(new Error('iframe timeout')); }, timeoutMs);
      f.onload = () => {
        clearTimeout(timer);
        try { resolve(f.contentDocument || f.contentWindow.document); }
        catch (e) { reject(e); }
        finally { setTimeout(() => f.remove(), 500); }
      };
      f.src = url;
      document.body.appendChild(f);
    });
  }

  // ── Fetch one doc ─────────────────────────────────────────────────────────────
  async function fetchDoc(url) {
    let doc;
    try { doc = await fastFetch(url); }
    catch (_) { doc = await iframeFetch(url); }
    if (BLOCK_RE.test(doc.title || '')) throw new Error('ถูก block — CAPTCHA/WAF');
    return doc;
  }

  // ── Extract chapter — collects all pages of the same chapter ─────────────────
  async function extractChapter(url) {
    const allParas = [];
    let title = '';
    let currentUrl = url;
    const visitedPages = new Set();

    for (let page = 0; page < 20; page++) {
      if (visitedPages.has(currentUrl)) break;
      visitedPages.add(currentUrl);

      const doc = await fetchDoc(currentUrl);
      cleanDoc(doc);

      if (!title) {
        title = clean(doc.querySelector('h1,h2,.chapter-title,.title')?.textContent || doc.title || '');
      }

      const box = findContentBox(doc);
      if (box) {
        const paras = parseParagraphs(box);
        allParas.push(...paras);
      }

      const { nextChapter, nextPage } = findLinks(doc, currentUrl);

      // If there's a "next page" link that stays on the same chapter, follow it
      // Stop if: no next-page link, or next-page is the same as next-chapter (i.e., no real pagination)
      if (nextPage && nextPage !== nextChapter && nextPage !== currentUrl) {
        currentUrl = nextPage;
        await sleep(80);
      } else {
        // No more pages — return with next chapter URL
        return { title, paras: allParas, nextUrl: nextChapter };
      }
    }

    return { title, paras: allParas, nextUrl: null };
  }

  // ── Catalog scan (known sites only) ──────────────────────────────────────────
  async function fetchCatalog() {
    if (IS_QUANBEN)  return fetchQuanbenCatalog();
    if (IS_BOLUOMAO) return fetchBoluomaoCatalog();
    return [];
  }

  async function fetchQuanbenCatalog() {
    const cu = S.catalogUrl;
    if (!cu) return [];
    const resp = await fetch(cu, { credentials: 'include', cache: 'no-store' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const doc = new DOMParser().parseFromString(await resp.text(), 'text/html');
    const links = [...doc.querySelectorAll('a[href]')].filter(a => {
      const h = a.getAttribute('href') || '';
      return /\/n\/[^/]+\/\d+/.test(h) || /\/\d+\.html$/.test(h);
    });
    const seen = new Set(); const entries = [];
    for (const a of links) {
      const href = new URL(a.getAttribute('href'), cu).href;
      if (seen.has(href)) continue; seen.add(href);
      const t = clean(a.textContent);
      const n = chNumFromText(t) || entries.length + 1;
      entries.push({ number: n, title: t || `第${n}章`, url: href });
    }
    return entries.sort((a, b) => a.number - b.number);
  }

  async function fetchBoluomaoCatalog() {
    if (!S.catalogUrl) return [];
    let doc;
    if (S.isIndexPage) { doc = document; }
    else {
      const resp = await fetch(S.catalogUrl, { credentials: 'include', cache: 'no-store' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      doc = new DOMParser().parseFromString(await resp.text(), 'text/html');
    }
    const sels = ['#chapter-list a','.chapter-list a','.chapter_list a','#chapterList a','.chapterList a','a[href*="/chapter/"]','a[href*="/read/"]'];
    let links = [];
    for (const sel of sels) {
      links = [...doc.querySelectorAll(sel)].filter(a => /\/(chapter|read)\//.test(a.getAttribute('href') || ''));
      if (links.length > 2) break;
    }
    const seen = new Set(); const entries = []; let idx = 0;
    for (const a of links) {
      const href = new URL(a.getAttribute('href') || '', S.catalogUrl || location.href).href;
      if (/-\d+\.html$/.test(href) || seen.has(href)) continue;
      seen.add(href);
      const t = clean(a.textContent);
      const n = chNumFromText(t) || ++idx;
      entries.push({ number: n, title: t || `第${n}章`, url: href });
    }
    return entries.sort((a, b) => a.number - b.number);
  }

  // ── Parallel fetch pool ───────────────────────────────────────────────────────
  // Fetches entries[] concurrently (CONCURRENCY at a time), preserving order.
  const CONCURRENCY = 8;

  async function fetchPool(entries, fromN) {
    const ordered = new Array(entries.length);
    let nextIdx = 0;
    let done = 0;

    async function worker() {
      while (!stopped) {
        const idx = nextIdx++;
        if (idx >= entries.length) return;
        const ch = entries[idx];
        setStatus(`กำลังโหลด ${done + 1}/${entries.length} (${CONCURRENCY} คู่ขนาน)…`);
        try {
          const { title, paras } = await extractChapter(ch.url);
          ordered[idx] = `\n\n第${ch.number}章 ${title || ch.title}\n\n` + paras.join('\n\n');
          addLog(`✓ ${ch.number}. ${title || ch.title}`);
        } catch (e) {
          ordered[idx] = `\n\n第${ch.number}章 ${ch.title}\n\n[โหลดไม่สำเร็จ: ${e.message}]`;
          addLog(`✗ ตอน ${ch.number}: ${e.message}`);
        }
        done++;
        ui.prog.value = done;
        await sleep(80);
      }
    }

    await Promise.all(Array.from({ length: CONCURRENCY }, worker));
    return ordered.filter(Boolean);
  }

  // ── Download runner ───────────────────────────────────────────────────────────
  async function runDownload() {
    if (running) return;
    running = true; stopped = false;
    results = [];
    ui.copy.disabled = ui.dl.disabled = true;

    const fromN     = parseInt(ui.from.value, 10) || 1;
    const count     = parseInt(ui.cnt.value,  10) || 50;
    const manualUrl = ui.firstUrl.value.trim();

    let entries = [];
    if (catalog.length) {
      entries = catalog.filter(c => c.number >= fromN).slice(0, count);
    }

    // Mode A: catalog known — parallel fetch
    if (entries.length) {
      ui.prog.max = entries.length;
      results = await fetchPool(entries, fromN);

    // Mode B: no catalog — follow next-chapter links (sequential, can't parallelize)
    } else if (manualUrl) {
      addLog('ไม่มีสารบัญ — ไล่ลิงก์ตอนต่อไป…');
      let url = manualUrl;
      for (let i = 0; i < count && url && !stopped; i++) {
        ui.prog.value = i;
        setStatus(`กำลังโหลด ${i + 1}/${count}…`);
        try {
          const { title, paras, nextUrl } = await extractChapter(url);
          const num = fromN + i;
          results.push(`\n\n第${num}章 ${title}\n\n` + paras.join('\n\n'));
          addLog(`✓ ${num}. ${title}`);
          ui.prog.value = i + 1;
          url = nextUrl || null;
          if (!url) { addLog('ไม่พบลิงก์ตอนต่อไปแล้ว'); break; }
          await sleep(200);
        } catch (e) {
          addLog(`✗ ตอน ${fromN + i}: ${e.message}`);
          await sleep(1500);
        }
      }
    } else {
      setStatus('ใส่ลิงก์ตอนแรกด้านบน แล้วกด ▶');
      running = false; return;
    }

    if (results.length) {
      ui.copy.disabled = false;
      ui.dl.disabled = false;
      setStatus(`เสร็จ ${results.length} ตอน — กด DL หรือ Copy`);
    } else {
      setStatus('ไม่ได้ข้อมูลเลย — ลองใส่ URL ตอนแรก');
    }
    running = false;
  }

  function buildText() {
    return '﻿' + novelTitle() + '\n\n' + results.join('\n');
  }

  function doDownload() {
    const blob = new Blob([buildText()], { type: 'text/plain;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${novelTitle()}.txt`;
    a.click();
  }

  // ── UI ────────────────────────────────────────────────────────────────────────
  const css = document.createElement('style');
  css.id = APP + '-css';
  css.textContent = `
/* ── Panel shell ── */
#${APP}{
  position:fixed;bottom:20px;right:14px;z-index:2147483647;
  width:272px;font:13px/1.5 'Segoe UI',sans-serif;
  filter:drop-shadow(0 4px 18px rgba(255,0,128,.35));
  user-select:none;
}
/* ── Header bar ── */
#${APP} .nd-head{
  background:linear-gradient(135deg,#1a1a1a 0%,#2d002d 100%);
  border-radius:14px 14px 0 0;
  padding:10px 14px;
  display:flex;justify-content:space-between;align-items:center;
  cursor:move;
  border-bottom:2px solid #FF0080;
}
#${APP} .nd-head-title{
  display:flex;align-items:center;gap:7px;
  color:#fff;font-weight:700;font-size:14px;letter-spacing:.5px;
}
#${APP} .nd-head-title span.nd-dot{
  width:8px;height:8px;border-radius:50%;
  background:#FF0080;box-shadow:0 0 6px #FF0080;
  display:inline-block;
}
#${APP} .nd-min-btn{
  background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);
  border-radius:6px;color:#fff;cursor:pointer;
  font-size:16px;line-height:1;padding:2px 8px;
  transition:background .2s;
}
#${APP} .nd-min-btn:hover{background:#FF0080;}

/* ── Body ── */
#${APP} .nd-body{
  background:linear-gradient(160deg,#FF0080 0%,#c4005e 100%);
  border:2px solid #FF0080;border-top:none;
  border-radius:0 0 14px 14px;
  padding:12px;
  display:flex;flex-direction:column;gap:9px;
}

/* ── Info / status ── */
#${APP} .nd-info{
  font-size:11.5px;color:#fff;
  background:rgba(0,0,0,.25);border:1px solid rgba(255,255,255,.2);
  border-radius:8px;padding:6px 9px;line-height:1.4;
}
#${APP} .nd-status{
  font-size:12px;font-weight:700;
  color:#fff;text-align:center;
  text-shadow:0 1px 4px rgba(0,0,0,.3);
}

/* ── Section label ── */
#${APP} .nd-label{
  font-size:10.5px;font-weight:700;color:rgba(255,255,255,.75);
  text-transform:uppercase;letter-spacing:.6px;
  margin-bottom:2px;
}

/* ── URL input row ── */
#${APP} .nd-url-wrap{
  display:flex;align-items:center;gap:6px;
}
#${APP} .nd-url-wrap input[type=text]{
  flex:1;min-width:0;
}
#${APP} input[type=text]{
  width:100%;box-sizing:border-box;
  padding:7px 10px;
  background:rgba(255,255,255,.9);
  border:1.5px solid rgba(255,255,255,.4);border-radius:8px;
  font-size:12px;color:#1a1a1a;
  transition:border-color .2s;
  outline:none;
}
#${APP} input[type=text]:focus{border-color:#fff;background:#fff;}

/* ── Chapter range row ── */
#${APP} .nd-range{
  display:flex;align-items:center;gap:6px;
}
#${APP} .nd-range label{
  font-size:11px;color:rgba(255,255,255,.85);white-space:nowrap;
}
#${APP} .nd-range input[type=number]{
  width:52px;padding:5px 6px;
  background:rgba(255,255,255,.9);
  border:1.5px solid rgba(255,255,255,.4);border-radius:7px;
  font-size:12px;text-align:center;outline:none;color:#1a1a1a;
  transition:border-color .2s;
}
#${APP} .nd-range input[type=number]:focus{border-color:#fff;}

/* ── Quick-count pills ── */
#${APP} .nd-pills{display:flex;gap:5px;}
#${APP} .nd-pill{
  flex:1;padding:5px 0;
  background:rgba(255,255,255,.15);border:1.5px solid rgba(255,255,255,.35);
  border-radius:20px;font-size:12px;font-weight:700;
  color:#fff;cursor:pointer;text-align:center;
  transition:all .15s;
}
#${APP} .nd-pill:hover,#${APP} .nd-pill.active{
  background:#fff;border-color:#fff;color:#FF0080;
}

/* ── Action buttons ── */
#${APP} .nd-actions{display:flex;gap:6px;}
#${APP} .nd-btn-run{
  flex:1;padding:9px 0;
  background:#1a1a1a;
  border:none;border-radius:10px;
  color:#fff;font-size:13px;font-weight:700;letter-spacing:.3px;
  cursor:pointer;transition:opacity .2s;
  box-shadow:0 2px 8px rgba(0,0,0,.3);
}
#${APP} .nd-btn-run:hover{opacity:.82;}
#${APP} .nd-btn-stop{
  padding:9px 14px;
  background:rgba(0,0,0,.35);border:1.5px solid rgba(255,255,255,.3);
  border-radius:10px;
  color:#fff;font-size:13px;cursor:pointer;transition:opacity .2s;
}
#${APP} .nd-btn-stop:hover{background:rgba(0,0,0,.55);}

/* ── Save buttons ── */
#${APP} .nd-saves{display:flex;gap:6px;}
#${APP} .nd-btn-save{
  flex:1;padding:8px 0;
  background:rgba(255,255,255,.9);border:none;
  border-radius:10px;color:#c4005e;
  font-size:12px;font-weight:700;cursor:pointer;
  transition:all .15s;
  box-shadow:0 1px 4px rgba(0,0,0,.15);
}
#${APP} .nd-btn-save:hover:not(:disabled){background:#fff;color:#FF0080;}
#${APP} .nd-btn-save:disabled{
  background:rgba(255,255,255,.3);color:rgba(255,255,255,.5);cursor:not-allowed;
}

/* ── Progress bar ── */
#${APP} .nd-prog-wrap{
  background:rgba(0,0,0,.25);border-radius:99px;height:7px;overflow:hidden;
}
#${APP} .nd-prog-bar{
  height:100%;border-radius:99px;
  background:linear-gradient(90deg,#fff,rgba(255,255,255,.7));
  width:0%;transition:width .25s;
}

/* ── Log ── */
#${APP} .nd-log{
  max-height:68px;overflow-y:auto;
  font-size:11px;
  background:rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.15);
  border-radius:8px;padding:5px 8px;line-height:1.6;
}
#${APP} .nd-log .ok{color:#fff;}
#${APP} .nd-log .err{color:rgba(255,255,255,.55);}

/* ── Clear button ── */
#${APP} .nd-clear-btn{
  flex-shrink:0;width:32px;height:32px;
  background:rgba(0,0,0,.25);border:1.5px solid rgba(255,255,255,.3);
  border-radius:8px;color:#fff;font-size:14px;
  cursor:pointer;display:flex;align-items:center;justify-content:center;
  transition:all .15s;padding:0;line-height:1;
}
#${APP} .nd-clear-btn:hover{background:rgba(0,0,0,.5);}

/* ── Minimized state ── */
#${APP}.nd-minimized .nd-body{display:none;}
#${APP}.nd-minimized .nd-head{border-radius:14px;border-bottom:none;}
#${APP}.nd-minimized{filter:drop-shadow(0 2px 8px rgba(255,0,128,.25));}
`;

  const adCss = document.createElement('style');
  adCss.id = APP + '-adcss';
  adCss.textContent = `
[id*="ad" i]:not(body):not(html):not(#${APP}):not([id*="read"]):not([id*="content"]):not([id*="chapter"]),
[class*="ad-" i]:not(.${APP}), [class*="-ad" i]:not(.${APP}),
[class*="banner" i]:not(.${APP}), [class*="popup" i],
[class*="float-ad" i], [id*="float-ad" i],
ins.adsbygoogle { display:none!important; }
`;

  const panel = document.createElement('div');
  panel.id = APP;
  panel.innerHTML = `
<div class="nd-head" id="${APP}-head">
  <div class="nd-head-title">
    <span class="nd-dot"></span>
    📖 Novel Downloader
  </div>
  <button class="nd-min-btn" id="${APP}-min">−</button>
</div>
<div class="nd-body">
  <div class="nd-info" id="${APP}-info">กำลังสแกนสารบัญ…</div>

  <div>
    <div class="nd-label">🔗 URL ตอนแรก (สำหรับเว็บไม่มีสารบัญ)</div>
    <div class="nd-url-wrap">
      <input type="text" id="${APP}-firstUrl" placeholder="วาง URL ตอนที่ 1 ที่นี่" />
      <button class="nd-clear-btn" id="${APP}-clearUrl" title="ล้าง URL">✕</button>
    </div>
  </div>

  <div>
    <div class="nd-label">📚 ช่วงตอนที่ต้องการ</div>
    <div class="nd-range">
      <label>เริ่มตอน</label>
      <input type="number" id="${APP}-from" value="1" min="1" />
      <label>จำนวนตอน</label>
      <input type="number" id="${APP}-cnt" value="50" min="1" max="999" />
    </div>
  </div>

  <div>
    <div class="nd-label">⚡ เลือกจำนวนด่วน</div>
    <div class="nd-pills">
      <button class="nd-pill" id="${APP}-q50">50</button>
      <button class="nd-pill" id="${APP}-q100">100</button>
      <button class="nd-pill" id="${APP}-q200">200</button>
      <button class="nd-pill" id="${APP}-q300">300</button>
    </div>
  </div>

  <div class="nd-actions">
    <button class="nd-btn-run" id="${APP}-run">▶ เริ่มโหลด</button>
    <button class="nd-btn-stop" id="${APP}-stop">■</button>
  </div>

  <div class="nd-prog-wrap"><div class="nd-prog-bar" id="${APP}-progbar"></div></div>
  <div class="nd-status" id="${APP}-status">พร้อมใช้งาน</div>

  <div class="nd-saves">
    <button class="nd-btn-save" id="${APP}-dl" disabled>💾 บันทึก .txt</button>
    <button class="nd-btn-save" id="${APP}-copy" disabled>📋 คัดลอก</button>
  </div>

  <div class="nd-log" id="${APP}-log"></div>
</div>
`;

  const ui = {
    head:     panel.querySelector(`#${APP}-head`),
    min:      panel.querySelector(`#${APP}-min`),
    body:     panel.querySelector('.nd-body'),
    info:     panel.querySelector(`#${APP}-info`),
    firstUrl: panel.querySelector(`#${APP}-firstUrl`),
    from:     panel.querySelector(`#${APP}-from`),
    cnt:      panel.querySelector(`#${APP}-cnt`),
    run:      panel.querySelector(`#${APP}-run`),
    stop:     panel.querySelector(`#${APP}-stop`),
    copy:     panel.querySelector(`#${APP}-copy`),
    dl:       panel.querySelector(`#${APP}-dl`),
    progbar:  panel.querySelector(`#${APP}-progbar`),
    status:   panel.querySelector(`#${APP}-status`),
    log:      panel.querySelector(`#${APP}-log`),
    // prog shim — used as {value, max} by runDownload
    prog: { _v: 0, _m: 100,
      get value(){ return this._v; },
      set value(v){ this._v = v; const el = panel.querySelector(`#${APP}-progbar`); if(el) el.style.width = (this._m ? Math.round(v/this._m*100) : 0)+'%'; },
      get max(){ return this._m; },
      set max(v){ this._m = v; }
    },
  };

  function setStatus(t) { ui.status.textContent = t; }
  function addLog(t) {
    const d = document.createElement('div');
    d.className = t.startsWith('✓') ? 'ok' : (t.startsWith('✗') ? 'err' : '');
    d.textContent = t;
    ui.log.appendChild(d);
    ui.log.scrollTop = ui.log.scrollHeight;
  }

  // ── Minimize / expand ─────────────────────────────────────────────────────────
  let minimized = false;
  function setMinimized(v) {
    minimized = v;
    if (v) { panel.classList.add('nd-minimized'); ui.min.textContent = '+'; }
    else   { panel.classList.remove('nd-minimized'); ui.min.textContent = '−'; }
  }
  ui.min.addEventListener('click', () => setMinimized(!minimized));

  // ── Drag ─────────────────────────────────────────────────────────────────────
  let dx = 0, dy = 0, dragging = false;
  ui.head.addEventListener('pointerdown', e => {
    if (e.target === ui.min) return;
    dragging = true; dx = e.clientX - panel.getBoundingClientRect().left;
    dy = e.clientY - panel.getBoundingClientRect().top;
    e.preventDefault();
  });
  document.addEventListener('pointermove', e => {
    if (!dragging) return;
    panel.style.left = (e.clientX - dx) + 'px';
    panel.style.top  = (e.clientY - dy) + 'px';
    panel.style.right = 'auto'; panel.style.bottom = 'auto';
  });
  document.addEventListener('pointerup', () => { dragging = false; });

  // ── Quick count pills ─────────────────────────────────────────────────────────
  const pills = panel.querySelectorAll('.nd-pill');
  function setPill(val) {
    ui.cnt.value = val;
    pills.forEach(p => p.classList.toggle('active', p.textContent === String(val)));
  }
  panel.querySelector(`#${APP}-q50`).onclick  = () => setPill(50);
  panel.querySelector(`#${APP}-q100`).onclick = () => setPill(100);
  panel.querySelector(`#${APP}-q200`).onclick = () => setPill(200);
  panel.querySelector(`#${APP}-q300`).onclick = () => setPill(300);
  setPill(50); // default highlight

  panel.querySelector(`#${APP}-clearUrl`).onclick = () => {
    ui.firstUrl.value = '';
    ui.firstUrl.focus();
  };

  ui.run.onclick  = runDownload;
  ui.stop.onclick = () => { stopped = true; setStatus('⏹ หยุดแล้ว'); };
  ui.copy.onclick = () => { navigator.clipboard.writeText(buildText()).then(() => setStatus('✅ คัดลอกแล้ว!')); };
  ui.dl.onclick   = doDownload;

  // ── Mount ─────────────────────────────────────────────────────────────────────
  document.head.appendChild(css);
  document.head.appendChild(adCss);
  document.body.appendChild(panel);

  // ── Init: try catalog scan on known sites ────────────────────────────────────
  async function init() {
    S = getUrlState();

    // On chapter pages: fill first URL box and minimize
    if (!S.isIndexPage && S.chapterNum) {
      if (!ui.firstUrl.value) {
        ui.firstUrl.value = location.href;
        ui.from.value = S.chapterNum;
      }
      setMinimized(true);
    }

    if (!IS_QUANBEN && !IS_BOLUOMAO) {
      // Generic unknown site — just show panel, let user paste URL
      ui.info.textContent = `🌐 ${HOST} — ใส่ URL ตอนแรกแล้วกด ▶`;
      setStatus('พร้อม — ใส่ URL ตอนแรก');
      if (!ui.firstUrl.value) ui.firstUrl.value = location.href;
      return;
    }

    try {
      setStatus('กำลังสแกนสารบัญ…');
      catalog = await fetchCatalog();
      if (catalog.length) {
        const last = catalog.at(-1)?.number || '?';
        ui.info.textContent = `📚 ${novelTitle()} — ${catalog.length} ตอน (1–${last})`;
        setStatus(`พร้อม • ${catalog.length} ตอน`);
        if (!S.isIndexPage) setMinimized(false);
      } else {
        throw new Error('ไม่พบตอน');
      }
    } catch (e) {
      ui.info.textContent = `⚠️ สแกนสารบัญไม่ได้ — ใส่ URL ตอนแรก`;
      setStatus('ใส่ URL ตอนแรกแล้วกด ▶');
      addLog('catalog: ' + e.message);
    }
  }

  init();

  // ── SPA keep-alive + URL change detection ────────────────────────────────────
  let lastHref = location.href;
  setInterval(() => {
    if (document.body && !document.body.contains(panel)) {
      document.body.appendChild(panel);
    }
    if (document.head && !document.head.contains(css)) document.head.appendChild(css);
    if (document.head && !document.head.contains(adCss)) document.head.appendChild(adCss);

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

})();
