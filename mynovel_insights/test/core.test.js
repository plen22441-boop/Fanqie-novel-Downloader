// รัน: node --test mynovel_insights/test/core.test.js
const test = require('node:test');
const assert = require('node:assert/strict');
const C = require('../insights-core.js');

const NOW = new Date('2026-11-16T05:00:00Z'); // = 12:00 เวลาไทย
const bkk = d => C.bkkParts(d);

test('ISO ไม่มี timezone ถือเป็นเวลาไทย', () => {
  const p = C.parseTime('2026-11-16 21:30');
  assert.equal(p.precise, true);
  assert.deepEqual(bkk(p.date), { dow: 1, hour: 21 });
});

test('ISO มี Z แปลงเป็นเวลาไทย (+7)', () => {
  const p = C.parseTime('2026-11-16T15:10:00Z');
  assert.equal(bkk(p.date).hour, 22);
});

test('วันที่ไทย พ.ศ. ย่อ + เวลา', () => {
  const p = C.parseTime('16 พ.ย. 2569 20:15');
  assert.equal(p.date.toISOString(), '2026-11-16T13:15:00.000Z');
  const q = C.parseTime('3 ม.ค. 69 เวลา 01.05 น.');
  assert.equal(q.date.toISOString(), '2026-01-02T18:05:00.000Z');
});

test('วันที่อย่างเดียว = ไม่ precise (ห้ามใช้รายชั่วโมง)', () => {
  assert.equal(C.parseTime('16 พ.ย. 2569').precise, false);
  assert.equal(C.parseTime('2026-11-16').precise, false);
});

test('เวลาสัมพัทธ์ภาษาไทย', () => {
  assert.equal(bkk(C.parseTime('2 ชั่วโมงที่แล้ว', NOW).date).hour, 10);
  assert.equal(C.parseTime('2 ชั่วโมงที่แล้ว', NOW).precise, true);
  assert.equal(C.parseTime('3 วันที่แล้ว', NOW).precise, false);
  assert.equal(bkk(C.parseTime('เมื่อวาน 23:40', NOW).date).hour, 23);
  assert.equal(C.parseTime('เมื่อวาน 23:40', NOW).date.toISOString(), '2026-11-15T16:40:00.000Z');
});

test('เวลาสัมพัทธ์อิง seenAt ของแต่ละรายการ', () => {
  const d = C.normalize({ events: [{ ts: '2 ชั่วโมงที่แล้ว', seenAt: '2026-11-10T15:00:00Z', kind: 'comment' }] }, NOW);
  assert.equal(d.events[0].ts.toISOString(), '2026-11-10T13:00:00.000Z');
});

test('epoch วินาที/มิลลิวินาที', () => {
  assert.equal(C.parseTime(1763300000).date.getTime(), 1763300000000);
  assert.equal(C.parseTime('1763300000000').date.getTime(), 1763300000000);
});

test('ข้อความเวลาขยะ -> null และถูกนับเป็น dropped', () => {
  assert.equal(C.parseTime('ไม่ใช่เวลา'), null);
  const d = C.normalize({ events: [{ ts: 'ไม่ใช่เวลา' }, { ts: '2026-11-16 10:00', kind: 'comment' }] });
  assert.equal(d.events.length, 1);
  assert.equal(d.dropped, 1);
});

test('แท็ก: ตัด #, รวมซ้ำ, แยกหลายรูปแบบ', () => {
  assert.deepEqual(C.splitTags('#ทะลุมิติ, #ย้อนยุค|วาย'), ['ทะลุมิติ', 'ย้อนยุค', 'วาย']);
  assert.deepEqual(C.splitTags('#ทะลุมิติ #ย้อนยุค'), ['ทะลุมิติ', 'ย้อนยุค']);
  assert.deepEqual(C.splitTags([{ name: '#BL' }, 'Fantasy']), ['bl', 'fantasy']);
});

test('ตัวเลขยอดวิว แบบ k / แสน / มีจุลภาค', () => {
  assert.equal(C.toNum('1.2k'), 1200);
  assert.equal(C.toNum('12,345'), 12345);
  assert.equal(C.toNum('3 แสน'), 300000);
  assert.equal(C.toNum('2.5M'), 2500000);
});

test('normalize: dedupe event ซ้ำ + merge หนังสือซ้ำ (เก็บอันดับดีสุด)', () => {
  const d = C.normalize({
    events: [{ id: 1, ts: '2026-11-16 10:00' }, { id: 1, ts: '2026-11-16 10:00' }],
    books: [{ id: 'a', title: 'A', tags: '#x', rank: 9 }, { id: 'a', title: 'A', tags: '#y', rank: 3 }],
  });
  assert.equal(d.events.length, 1);
  assert.equal(d.books.length, 1);
  assert.equal(d.books[0].rank, 3);
  assert.deepEqual(d.books[0].tags.sort(), ['x', 'y']);
});

test('CSV มี quote และ BOM', () => {
  const raw = C.importText('﻿ts,kind,bookId\n"2026-11-16 21:00",comment,"b,1"\n');
  assert.equal(raw.events.length, 1);
  assert.equal(raw.events[0].bookId, 'b,1');
});

test('timeMatrix นับเฉพาะ precise และเฉพาะ kind ที่เลือก', () => {
  const d = C.normalize({ events: [
    { ts: '2026-11-16 21:10', kind: 'comment' },
    { ts: '2026-11-16 21:50', kind: 'like' },
    { ts: '2026-11-16 21:20', kind: 'chapter' },
    { ts: '2026-11-16', kind: 'comment' },
  ] });
  const tm = C.timeMatrix(d.events);
  assert.equal(tm.n, 2);
  assert.equal(tm.byHour[21], 2);
  assert.equal(tm.matrix[1][21], 2); // จันทร์
});

test('equalizeBooks: เรื่องที่คอมเมนต์ถล่มไม่บิดภาพ', () => {
  const ev = [];
  for (let i = 0; i < 99; i++) ev.push({ id: 'h' + i, ts: '2026-11-16 03:00', kind: 'comment', bookId: 'hot' });
  ev.push({ ts: '2026-11-16 20:00', kind: 'comment', bookId: 'b1' });
  ev.push({ ts: '2026-11-16 20:30', kind: 'comment', bookId: 'b2' });
  const d = C.normalize({ events: ev });
  const raw = C.timeMatrix(d.events);
  const eq = C.timeMatrix(d.events, { equalizeBooks: true });
  assert.ok(raw.byHour[3] > raw.byHour[20]);
  assert.ok(eq.byHour[20] > eq.byHour[3]); // 2 เรื่อง vs 1 เรื่อง
});

test('bestWindow วนข้ามเที่ยงคืนได้', () => {
  const h = new Array(24).fill(0);
  h[23] = 5; h[0] = 5; h[1] = 5;
  const w = C.bestWindow(h, 3);
  assert.equal(w.start, 23);
  assert.equal(w.end, 2);
  assert.equal(w.share, 1);
});

test('expectationReport: หาชั่วโมงที่ "ไม่คาดถึง" และช่วงที่คาดแต่เงียบ', () => {
  const h = new Array(24).fill(1);
  h[12] = 6;  // พักเที่ยงพุ่ง (ไม่ได้คาดไว้)
  h[18] = 0.2; // คาดไว้แต่เงียบ
  const r = C.expectationReport(h, 18, 23);
  assert.equal(r.expected.width, 5);
  assert.equal(r.surprises[0].hour, 12);
  assert.equal(r.letdowns[0].hour, 18);
  assert.ok(r.capture <= 1);
});

test('supplyGap: ชั่วโมงที่คนอ่านมากแต่ลงตอนน้อย ได้ gap บวก', () => {
  const d = C.normalize({ events: [
    { ts: '2026-11-16 22:00', kind: 'comment' }, { ts: '2026-11-16 22:10', kind: 'comment' },
    { ts: '2026-11-16 18:00', kind: 'chapter' }, { ts: '2026-11-16 22:05', kind: 'chapter', id: 'c2' },
    { ts: '2026-11-16 18:30', kind: 'chapter' },
  ] });
  const g = C.supplyGap(d.events);
  assert.ok(g[22].gap > 0);
  assert.ok(g[18].gap < 0);
  assert.equal(C.supplyGap(C.normalize({ events: [{ ts: '2026-11-16 22:00', kind: 'comment' }] }).events), null);
});

test('tagStats: อันดับสูงได้ score มากกว่า, opportunity > 1 เมื่อติดอันดับเกินสัดส่วน', () => {
  const books = C.normalize({ books: [
    { id: 1, tags: '#niche', rank: 1 },
    { id: 2, tags: '#common', rank: 2 },
    { id: 3, tags: '#common' }, { id: 4, tags: '#common' }, { id: 5, tags: '#common' },
  ] }).books;
  const s = Object.fromEntries(C.tagStats(books).map(x => [x.tag, x]));
  assert.ok(s.niche.score > s.common.score);
  assert.ok(s.niche.opportunity > 1);
  assert.ok(s.common.opportunity < 1);
  assert.equal(s.niche.lowSample, true);
});

test('tagStats: แท็กที่อยู่ทุกเรื่อง = opportunity 1.0 พอดี (ไม่เอียงตามจำนวนแท็กต่อเรื่อง)', () => {
  const books = C.normalize({ books: [
    { id: 1, tags: '#all #a #b', rank: 1 }, { id: 2, tags: '#all #c #d', rank: 2 },
    { id: 3, tags: '#all #a' }, { id: 4, tags: '#all' },
  ] }).books;
  const s = Object.fromEntries(C.tagStats(books).map(x => [x.tag, x]));
  assert.ok(Math.abs(s.all.opportunity - 1) < 1e-9);
  assert.ok(Math.abs(s.all.rankShare - 1) < 1e-9);
});

test('tagPairs นับคู่แท็ก', () => {
  const books = C.normalize({ books: [
    { id: 1, tags: '#a #b', rank: 1 }, { id: 2, tags: '#b #a' },
  ] }).books;
  assert.deepEqual(C.tagPairs(books)[0], { pair: 'a + b', weight: 3 });
});

test('quality เตือนเมื่อข้อมูลน้อย / ไม่มีเวลาลงตอน', () => {
  const q = C.quality(C.normalize({ events: [{ ts: '2026-11-16 10:00', kind: 'comment' }] }));
  assert.ok(q.warnings.some(w => w.includes('300')));
  assert.ok(q.warnings.some(w => w.includes('chapter')));
});

test('demoData ผ่าน pipeline ได้ครบ', () => {
  const d = C.normalize(C.demoData(1));
  const q = C.quality(d);
  assert.ok(q.reader > 1000);
  assert.ok(C.supplyGap(d.events));
  assert.ok(C.tagStats(d.books).length > 5);
});
