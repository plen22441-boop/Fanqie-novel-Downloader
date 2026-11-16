#!/usr/bin/env node
/*
 * เก็บข้อมูล MyNovel อัตโนมัติ (ใช้ใน GitHub Actions ทุกชั่วโมง)
 *
 *   node mynovel_insights/ci/collect.js            # ค่าเริ่มต้น: DATA_DIR=mynovel_insights/data
 *   DATA_DIR=_data node mynovel_insights/ci/collect.js
 *
 * วิธีทำงาน: เปิดหน้าตาม config.json ด้วย Chromium แล้วฝังสคริปต์ mynovel-collector.user.js ตัวเดียวกับที่
 * ใช้ในเบราว์เซอร์ จากนั้นรวมผลลงไฟล์ใน DATA_DIR:
 *   store.json                เวลาคอมเมนต์/ลงตอน (ตัดซ้ำ) + ข้อมูลหนังสือล่าสุด
 *   snapshots-YYYY-MM.jsonl   ยอดวิวของแต่ละเรื่อง ณ แต่ละรอบ -> คำนวณ "วิวที่เพิ่มต่อชั่วโมง"
 *   runs.json                 สถานะแต่ละรอบ (ไว้ดูว่าโดนบล็อก/ดึงไม่ได้หรือเปล่า)
 *   latest.json               ไฟล์สรุปที่แดชบอร์ดโหลด
 * ถ้ารอบนี้ไม่ได้ข้อมูลเลย จะจบด้วย exit 1 เพื่อให้ GitHub แจ้งเตือน
 */
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const C = require('../insights-core.js');

const ROOT = path.resolve(__dirname, '..');
const DATA = path.resolve(process.env.DATA_DIR || path.join(ROOT, 'data'));
const CONFIG = JSON.parse(fs.readFileSync(process.env.CONFIG || path.join(ROOT, 'config.json'), 'utf8'));
const US = fs.readFileSync(path.join(ROOT, 'mynovel-collector.user.js'), 'utf8');
const KEEP_MS = (CONFIG.keepDays || 180) * 8.64e7;

const readJSON = (f, d) => { try { return JSON.parse(fs.readFileSync(path.join(DATA, f), 'utf8')); } catch (e) { return d; } };
const writeJSON = (f, v) => fs.writeFileSync(path.join(DATA, f), JSON.stringify(v));
// ไม่เก็บ user id จริงของคนคอมเมนต์ลง repo สาธารณะ — ใช้แค่ hash ไว้ตัดรายการซ้ำ
const hashUser = u => (u == null ? undefined : crypto.createHash('sha256').update('mni:' + u).digest('hex').slice(0, 12));
const exactViews = v => (typeof v === 'number' ? v : (/^\s*\d[\d,]*\s*$/.test(String(v ?? '')) ? +String(v).replace(/[,\s]/g, '') : undefined));

async function visit(browser, page) {
  const t0 = Date.now();
  const st = { label: page.label || page.url, url: page.url, ok: false, events: 0, books: 0 };
  const ctx = await browser.newContext({ locale: 'th-TH', timezoneId: 'Asia/Bangkok', viewport: { width: 1280, height: 900 } });
  try {
    await ctx.addInitScript(`window.__MNI_FORCE_RANK = ${page.rank === true};`);
    await ctx.addInitScript(US);
    const p = await ctx.newPage();
    const res = await p.goto(page.url, { waitUntil: 'domcontentloaded', timeout: 45000 });
    st.http = res ? res.status() : null;
    await p.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    for (let i = 0; i < (page.scrolls ?? 3); i++) {
      await p.mouse.wheel(0, 2500);
      await p.waitForTimeout(1500);
    }
    await p.waitForTimeout(2500); // ให้ userscript สแกน DOM + บันทึก (debounce)
    st.title = (await p.title()).slice(0, 80);
    const raw = await p.evaluate(() => localStorage.getItem('mni_data_v1'));
    const store = raw ? JSON.parse(raw) : { events: {}, books: {} };
    st.events = Object.keys(store.events).length;
    st.books = Object.keys(store.books).length;
    st.ok = st.http != null && st.http < 400;
    if (st.ok && !st.events && !st.books) st.note = 'เปิดหน้าได้แต่ไม่พบข้อมูล (โครงสร้างเว็บอาจไม่ตรง หรือโดนหน้ากันบอท)';
    return { st, store, at: new Date().toISOString() };
  } catch (e) {
    st.error = String(e.message || e).slice(0, 200);
    return { st, store: { events: {}, books: {} }, at: new Date().toISOString() };
  } finally {
    st.ms = Date.now() - t0;
    await ctx.close();
  }
}

function merge(db, result, page) {
  const now = Date.now();
  for (const [k, e] of Object.entries(result.store.events)) {
    if (db.events[k]) continue;
    db.events[k] = { ts: e.ts, kind: e.kind, bookId: e.bookId, user: hashUser(e.user), seenAt: e.seenAt || result.at };
  }
  const snap = [];
  for (const b of Object.values(result.store.books)) {
    const prev = db.books[b.id] || {};
    db.books[b.id] = {
      id: b.id, title: b.title || prev.title,
      tags: [...new Set((prev.tags || []).concat(b.tags || []))],
      views: b.views ?? prev.views,
      rank: b.rank ?? prev.rank, rankAt: b.rank != null ? result.at : prev.rankAt,
      list: b.rank != null ? page.label : prev.list,
      seenAt: result.at,
    };
    const v = exactViews(b.views);
    if (v != null) snap.push([b.id, v]);
  }
  // ตัดรายการเก่าเกิน keepDays
  for (const [k, e] of Object.entries(db.events)) {
    const p = C.parseTime(e.ts, new Date(e.seenAt || now));
    if (p && now - p.date.getTime() > KEEP_MS) delete db.events[k];
  }
  return snap;
}

function readSnapshots(months) {
  const rows = [];
  for (const f of fs.readdirSync(DATA).filter(f => /^snapshots-\d{4}-\d{2}\.jsonl$/.test(f)).sort().slice(-months)) {
    for (const line of fs.readFileSync(path.join(DATA, f), 'utf8').split('\n')) {
      if (!line.trim()) continue;
      try {
        const s = JSON.parse(line);
        for (const [id, views] of s.b) rows.push({ ts: s.ts, id, views });
      } catch (e) { /* บรรทัดเสียข้ามไป */ }
    }
  }
  return rows;
}

function buildLatest(db, runs) {
  const now = Date.now();
  const vd = C.viewDeltas(readSnapshots(3), { maxGapHours: CONFIG.maxGapHours || 6 });
  const recent = 48 * 3.6e6; // อันดับที่เก่ากว่า 48 ชม. ไม่นับเป็น "อันดับปัจจุบัน"
  const books = Object.values(db.books).map(b => ({
    id: b.id, title: b.title, tags: b.tags, views: b.views, list: b.list,
    rank: b.rankAt && now - Date.parse(b.rankAt) < recent ? b.rank : undefined,
  }));
  return {
    generatedAt: new Date().toISOString(),
    source: 'github-actions',
    meta: {
      lastRun: runs[runs.length - 1],
      okRuns: runs.filter(r => r.items > 0).length, totalRuns: runs.length,
      firstRunAt: runs.length ? runs[0].at : null,
      viewStats: vd.stats, warnings: vd.warnings,
    },
    events: Object.entries(db.events).map(([id, e]) => Object.assign({ id }, e)).concat(vd.events),
    books,
  };
}

(async () => {
  fs.mkdirSync(DATA, { recursive: true });
  const { chromium } = require('playwright');
  const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
  const db = readJSON('store.json', { events: {}, books: {} });
  const runStart = new Date().toISOString();
  const pages = [];
  let items = 0;
  const month = runStart.slice(0, 7);
  for (const page of CONFIG.pages || []) {
    const r = await visit(browser, page);
    pages.push(r.st);
    console.log(JSON.stringify(r.st));
    const snap = merge(db, r, page);
    items += r.st.events + r.st.books;
    if (snap.length) fs.appendFileSync(path.join(DATA, `snapshots-${month}.jsonl`), JSON.stringify({ ts: r.at, list: page.label, b: snap }) + '\n');
  }
  await browser.close();

  const runs = readJSON('runs.json', []);
  runs.push({ at: runStart, items, pages });
  while (runs.length > 500) runs.shift();
  writeJSON('store.json', db);
  writeJSON('runs.json', runs);
  writeJSON('latest.json', buildLatest(db, runs));
  console.log(`items=${items} events(total)=${Object.keys(db.events).length} books(total)=${Object.keys(db.books).length}`);

  if (process.env.GITHUB_STEP_SUMMARY) {
    const rows = pages.map(p => `| ${p.label} | ${p.http ?? '-'} | ${p.events} | ${p.books} | ${p.error || p.note || ''} |`).join('\n');
    fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY,
      `### MyNovel Insights — ${runStart}\n\n| หน้า | HTTP | events | books | หมายเหตุ |\n|---|---|---|---|---|\n${rows}\n`);
  }
  if (!items) { console.error('ไม่ได้ข้อมูลเลยในรอบนี้'); process.exit(1); }
})().catch(e => { console.error(e); process.exit(1); });
