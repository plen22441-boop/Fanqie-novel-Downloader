#!/usr/bin/env node
// สร้างไฟล์ติดตั้งไฟล์เดียว: dist/mynovel-insights.user.js = ส่วนหัว userscript + insights-core.js + ตัวสคริปต์
//   node mynovel_insights/build-userscript.js          เขียนไฟล์
//   node mynovel_insights/build-userscript.js --check  ตรวจว่าไฟล์ใน dist ตรงกับต้นฉบับ (ใช้ในเทสต์)
'use strict';
const fs = require('fs');
const path = require('path');
const dir = __dirname;
function build() {
  const src = fs.readFileSync(path.join(dir, 'mynovel-collector.user.js'), 'utf8');
  const core = fs.readFileSync(path.join(dir, 'insights-core.js'), 'utf8');
  const end = src.indexOf('// ==/UserScript==');
  if (end < 0) throw new Error('ไม่พบส่วนหัว userscript');
  const cut = end + '// ==/UserScript=='.length;
  return src.slice(0, cut) + '\n\n// ───── insights-core.js (ไฟล์นี้สร้างอัตโนมัติด้วย build-userscript.js — แก้ที่ต้นฉบับ) ─────\n'
    + core + '\n// ───── mynovel-collector.user.js ─────' + src.slice(cut);
}
const out = path.join(dir, 'dist', 'mynovel-insights.user.js');
const text = build();
if (process.argv.includes('--check')) {
  const cur = fs.existsSync(out) ? fs.readFileSync(out, 'utf8') : '';
  if (cur !== text) { console.error('dist/mynovel-insights.user.js ไม่ตรงกับต้นฉบับ — รัน node mynovel_insights/build-userscript.js'); process.exit(1); }
  console.log('dist ตรงกับต้นฉบับ');
} else {
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, text);
  console.log('เขียน', path.relative(process.cwd(), out), text.length, 'bytes');
}
module.exports = { build };
