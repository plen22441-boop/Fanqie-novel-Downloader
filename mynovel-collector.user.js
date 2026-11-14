// ==UserScript==
// @name         MyNovel ตัวเก็บข้อมูลเรื่อง/แท็ก
// @namespace    mynovel-collector
// @version      1.0
// @description  เก็บชื่อเรื่อง แท็ก คำโปรย ยอดวิว จากหน้าโปรไฟล์และหน้าเรื่องใน MyNovel แล้วคัดลอกไปวิเคราะห์
// @match        https://mynovel.co/*
// @match        https://www.mynovel.co/*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  var KEY = 'mnc_data_v1';
  var MAX_AUTO = 40;      // จำนวนเรื่องสูงสุดที่เก็บอัตโนมัติ
  var WAIT_MS = 5000;     // รอให้หน้าเรื่องโหลด (มิลลิวินาที)

  function load() {
    try { return JSON.parse(localStorage.getItem(KEY)) || { list: [], pages: {} }; }
    catch (e) { return { list: [], pages: {} }; }
  }
  function save(d) {
    try { localStorage.setItem(KEY, JSON.stringify(d)); } catch (e) { alert('บันทึกไม่ได้: ' + e); }
  }
  function clean(s, n) {
    s = (s || '').replace(/[ \t]+/g, ' ').replace(/\n\s*\n+/g, '\n').trim();
    return n && s.length > n ? s.slice(0, n) + '…' : s;
  }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  // ---------- เก็บข้อมูลจากหน้าเรื่อง ----------
  function grabPage(doc, url) {
    var meta = function (sel) { var m = doc.querySelector(sel); return m ? m.getAttribute('content') : ''; };
    var h1 = doc.querySelector('h1');
    var tagSel = 'a[href*="tag"], a[href*="search"], a[href*="category"], a[href*="genre"],' +
      '[class*="tag" i], [class*="chip" i], [class*="badge" i], [class*="genre" i], [class*="category" i]';
    var tags = [];
    doc.querySelectorAll(tagSel).forEach(function (el) {
      var t = clean(el.innerText || el.textContent);
      if (t && t.length <= 30 && t.indexOf('\n') < 0 && tags.indexOf(t) < 0) tags.push(t);
    });
    var nd = '';
    var ndEl = doc.getElementById('__NEXT_DATA__');
    if (ndEl) nd = clean(ndEl.textContent, 6000);
    var main = doc.querySelector('main') || doc.body;
    return {
      url: url,
      docTitle: clean(doc.title),
      h1: h1 ? clean(h1.innerText) : '',
      ogTitle: meta('meta[property="og:title"]'),
      desc: meta('meta[name="description"]') || meta('meta[property="og:description"]'),
      tags: tags.slice(0, 40),
      text: clean(main ? main.innerText : '', 3500),
      nextData: nd,
      at: new Date().toISOString()
    };
  }

  // ---------- เก็บรายชื่อเรื่องจากหน้าโปรไฟล์ ----------
  function grabList() {
    var seen = {}, out = [];
    document.querySelectorAll('a[href*="/book/"]').forEach(function (a) {
      var u;
      try { u = new URL(a.href, location.href); } catch (e) { return; }
      if (/\/chapter\//.test(u.pathname)) return;
      var path = u.pathname.replace(/\/+$/, '');
      if (seen[path]) return;
      seen[path] = 1;
      var card = a, i = 0;
      // ขยายขึ้นไปหากรอบการ์ด แต่หยุดก่อนจะกินเรื่องอื่นเข้ามาด้วย
      while (card.parentElement && i < 5) {
        var p = card.parentElement, other = false;
        p.querySelectorAll('a[href*="/book/"]').forEach(function (x) {
          try { var xp = new URL(x.href, location.href).pathname; if (xp.indexOf(path) !== 0) other = true; } catch (e) {}
        });
        if (other) break;
        card = p; i++;
      }
      out.push({ url: u.origin + path, card: clean(card.innerText, 400) });
    });
    return out;
  }

  async function autoScroll() {
    var last = -1;
    for (var i = 0; i < 15; i++) {
      window.scrollTo(0, document.body.scrollHeight);
      await sleep(1500);
      var h = document.body.scrollHeight;
      if (h === last) break;
      last = h;
    }
    window.scrollTo(0, 0);
  }

  function loadInFrame(url) {
    return new Promise(function (resolve) {
      var f = document.createElement('iframe');
      f.style.cssText = 'position:fixed;left:-9999px;top:0;width:400px;height:800px;';
      f.src = url;
      var done = false;
      var finish = function () {
        if (done) return; done = true;
        var r = null;
        try { r = grabPage(f.contentDocument, url); } catch (e) { r = { url: url, error: String(e) }; }
        f.remove();
        resolve(r);
      };
      f.onload = function () { setTimeout(finish, WAIT_MS); };
      setTimeout(finish, WAIT_MS * 3);
      document.body.appendChild(f);
    });
  }

  // ---------- ส่งออก ----------
  function exportText() {
    var d = load(), lines = [];
    lines.push('=== MyNovel export ' + new Date().toISOString() + ' ===');
    lines.push('--- รายชื่อเรื่อง (' + d.list.length + ') ---');
    d.list.forEach(function (b, i) { lines.push((i + 1) + '. ' + b.url + '\n' + b.card); });
    var ps = Object.keys(d.pages).map(function (k) { return d.pages[k]; });
    lines.push('\n--- รายละเอียดเรื่อง (' + ps.length + ') ---');
    ps.forEach(function (p, i) {
      lines.push('\n##### ' + (i + 1) + ' ' + p.url);
      if (p.error) { lines.push('ERROR: ' + p.error); return; }
      lines.push('title: ' + (p.h1 || p.ogTitle || p.docTitle));
      if (p.desc) lines.push('desc: ' + p.desc);
      if (p.tags && p.tags.length) lines.push('tags: ' + p.tags.join(' | '));
      lines.push('text:\n' + p.text);
      if (p.nextData) lines.push('nextData:\n' + p.nextData);
    });
    return lines.join('\n');
  }

  function showText(t) {
    var w = document.createElement('div');
    w.style.cssText = 'position:fixed;inset:0;z-index:2147483647;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;';
    var box = document.createElement('div');
    box.style.cssText = 'background:#fff;color:#000;width:92vw;max-height:85vh;padding:10px;border-radius:10px;display:flex;flex-direction:column;gap:8px;font:14px sans-serif;';
    var ta = document.createElement('textarea');
    ta.value = t;
    ta.style.cssText = 'width:100%;height:55vh;font:12px monospace;';
    var row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:8px;';
    row.appendChild(btn('คัดลอก', function () {
      ta.select();
      (navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject())
        .then(function () { toast('คัดลอกแล้ว ✓ ไปวางในแชทได้เลย'); })
        .catch(function () { try { document.execCommand('copy'); toast('คัดลอกแล้ว ✓'); } catch (e) { toast('กดค้างในกล่องแล้วเลือกคัดลอกเอง'); } });
    }));
    row.appendChild(btn('ปิด', function () { w.remove(); }));
    box.appendChild(document.createTextNode('ข้อมูลทั้งหมด (' + t.length + ' ตัวอักษร)'));
    box.appendChild(ta); box.appendChild(row); w.appendChild(box);
    document.body.appendChild(w);
  }

  // ---------- UI ----------
  function btn(label, fn) {
    var b = document.createElement('button');
    b.textContent = label;
    b.style.cssText = 'padding:9px 10px;border:0;border-radius:8px;background:#e85d2a;color:#fff;font:14px sans-serif;';
    b.onclick = fn;
    return b;
  }
  var toastEl;
  function toast(m) {
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.style.cssText = 'position:fixed;left:50%;top:12px;transform:translateX(-50%);z-index:2147483647;background:#222;color:#fff;padding:8px 12px;border-radius:8px;font:14px sans-serif;max-width:90vw;';
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = m; toastEl.style.display = 'block';
    clearTimeout(toastEl._t); toastEl._t = setTimeout(function () { toastEl.style.display = 'none'; }, 3500);
  }
  function status() {
    var d = load();
    return 'รายชื่อ ' + d.list.length + ' · รายละเอียด ' + Object.keys(d.pages).length;
  }

  var panel = document.createElement('div');
  panel.style.cssText = 'position:fixed;right:8px;bottom:8px;z-index:2147483646;background:#fff;border:1px solid #ccc;border-radius:10px;padding:8px;display:flex;flex-direction:column;gap:6px;box-shadow:0 2px 8px rgba(0,0,0,.25);max-width:62vw;';
  var info = document.createElement('div');
  info.style.cssText = 'font:12px sans-serif;color:#333;';
  var body = document.createElement('div');
  body.style.cssText = 'display:none;flex-direction:column;gap:6px;';
  var refresh = function () { info.textContent = '📚 ' + status(); };

  body.appendChild(btn('1) เลื่อน+เก็บรายชื่อเรื่อง', async function () {
    toast('กำลังเลื่อนหน้าเพื่อโหลดเรื่องทั้งหมด…');
    await autoScroll();
    var d = load(); d.list = grabList(); save(d); refresh();
    toast('เจอ ' + d.list.length + ' เรื่อง');
  }));
  body.appendChild(btn('2) เก็บรายละเอียดทุกเรื่อง (อัตโนมัติ)', async function () {
    var d = load();
    if (!d.list.length) { toast('กดข้อ 1 ในหน้าโปรไฟล์ก่อน'); return; }
    var todo = d.list.slice(0, MAX_AUTO);
    for (var i = 0; i < todo.length; i++) {
      toast('กำลังเก็บเรื่อง ' + (i + 1) + '/' + todo.length + ' อย่าปิดหน้านี้');
      var r = await loadInFrame(todo[i].url);
      d = load(); d.pages[todo[i].url] = r; save(d); refresh();
    }
    toast('เสร็จแล้ว ✓ กด "ดู/คัดลอกข้อมูล"');
  }));
  body.appendChild(btn('เก็บเฉพาะหน้านี้', function () {
    var d = load(); var u = location.origin + location.pathname.replace(/\/+$/, '');
    d.pages[u] = grabPage(document, u); save(d); refresh();
    toast('เก็บหน้านี้แล้ว ✓');
  }));
  body.appendChild(btn('ดู/คัดลอกข้อมูล', function () { showText(exportText()); }));
  body.appendChild(btn('ล้างข้อมูล', function () {
    if (confirm('ล้างข้อมูลที่เก็บไว้ทั้งหมด?')) { save({ list: [], pages: {} }); refresh(); }
  }));

  var toggle = btn('📚 เก็บข้อมูล', function () {
    var open = body.style.display === 'none';
    body.style.display = open ? 'flex' : 'none';
  });
  panel.appendChild(toggle); panel.appendChild(info); panel.appendChild(body);
  document.body.appendChild(panel);
  refresh();
})();
