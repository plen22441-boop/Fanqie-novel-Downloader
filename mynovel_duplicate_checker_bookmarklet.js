javascript:(async()=>{
/* ===== Duplicate Episode Checker — mynovel.co ===== */

const sleep = ms => new Promise(r => setTimeout(r, ms));

// --- 1. Scroll จนสุดหน้าเพื่อโหลด infinite-scroll ---
async function scrollAll() {
  let prev = -1;
  for (let i = 0; i < 300; i++) {
    window.scrollTo(0, document.body.scrollHeight);
    await sleep(900);
    const h = document.body.scrollHeight;
    if (h === prev) break;
    prev = h;
  }
}

// --- 2. กด "โหลดเพิ่ม" / "Load more" ถ้ามี ---
async function clickLoadMore() {
  let clicked = true;
  while (clicked) {
    clicked = false;
    const btns = [...document.querySelectorAll('button,a')];
    const btn = btns.find(b =>
      /load.?more|โหลดเพิ่ม|ดูเพิ่ม|see.?more|แสดงทั้งหมด/i.test(b.innerText)
    );
    if (btn) { btn.click(); await sleep(1500); clicked = true; }
    await scrollAll();
  }
}

// --- 3. ดึงชื่อตอนทั้งหมดจาก DOM ---
function getTitles() {
  const selectors = [
    "[class*='episode-title']","[class*='episodeTitle']",
    "[class*='chapter-title']","[class*='chapterTitle']",
    "div[class*='episode'] h3","div[class*='episode'] h4",
    "div[class*='chapter'] h3","div[class*='chapter'] h4",
    "table tbody tr td:first-child",
    "li[class*='episode']","ul[class*='episode'] li",
  ];

  let best = [], bestCount = 0;
  for (const sel of selectors) {
    const els = [...document.querySelectorAll(sel)];
    const titles = els.map(e => e.innerText.trim()).filter(t => t.length > 0);
    if (titles.length > bestCount) { bestCount = titles.length; best = titles; }
  }

  // Fallback: element ที่มีข้อความสั้นและดูเหมือนชื่อตอน
  if (best.length === 0) {
    best = [...document.querySelectorAll('*')]
      .filter(el =>
        el.children.length === 0 &&
        el.innerText?.trim().length > 0 &&
        el.innerText?.trim().length < 200 &&
        /ตอน|episode|chapter|ep\./i.test(el.innerText)
      )
      .map(el => el.innerText.trim());
  }

  return best;
}

// --- 4. เช็คซ้ำ ---
function findDuplicates(titles) {
  const map = {};
  titles.forEach((t, i) => {
    const key = t.toLowerCase().trim();
    if (!map[key]) map[key] = { title: t, positions: [] };
    map[key].positions.push(i + 1);
  });
  return Object.values(map).filter(v => v.positions.length > 1);
}

// --- 5. แสดงผล ---
function showResult(titles, dups) {
  // ลบ overlay เก่าถ้ามี
  document.getElementById('__dup_checker__')?.remove();

  const overlay = document.createElement('div');
  overlay.id = '__dup_checker__';
  overlay.style.cssText = `
    position:fixed;top:0;left:0;width:100%;height:100%;
    background:rgba(0,0,0,.6);z-index:999999;
    display:flex;align-items:center;justify-content:center;
    font-family:sans-serif;padding:12px;box-sizing:border-box;
  `;

  const box = document.createElement('div');
  box.style.cssText = `
    background:#fff;border-radius:12px;padding:20px;
    max-width:480px;width:100%;max-height:85vh;overflow-y:auto;
    box-shadow:0 8px 32px rgba(0,0,0,.3);
  `;

  const header = dups.length === 0
    ? `<h2 style="color:#16a34a;margin:0 0 8px">✅ ไม่พบชื่อตอนซ้ำ!</h2>`
    : `<h2 style="color:#dc2626;margin:0 0 8px">⚠️ พบชื่อซ้ำ ${dups.length} กลุ่ม</h2>`;

  const summary = `<p style="color:#555;margin:0 0 16px;font-size:14px">
    ตอนทั้งหมด: <b>${titles.length}</b> &nbsp;|&nbsp;
    ซ้ำ: <b>${dups.length}</b> กลุ่ม
  </p>`;

  let dupList = '';
  if (dups.length > 0) {
    dupList = `<div style="border-top:1px solid #eee;padding-top:12px">`;
    dups.forEach((d, i) => {
      dupList += `
        <div style="margin-bottom:12px;padding:10px;background:#fef2f2;border-radius:8px;font-size:13px">
          <b>${i+1}. "${d.title}"</b><br>
          <span style="color:#888">ซ้ำ ${d.positions.length} ครั้ง · ตำแหน่ง: ${d.positions.join(', ')}</span>
        </div>`;
    });
    dupList += `</div>`;
  }

  const copyBtn = `<button id="__dup_copy__" style="
    margin-top:12px;padding:10px 18px;background:#2563eb;color:#fff;
    border:none;border-radius:8px;font-size:14px;cursor:pointer;width:100%
  ">📋 คัดลอกผลลัพธ์</button>`;

  const closeBtn = `<button onclick="document.getElementById('__dup_checker__').remove()" style="
    margin-top:8px;padding:10px 18px;background:#e5e7eb;color:#333;
    border:none;border-radius:8px;font-size:14px;cursor:pointer;width:100%
  ">ปิด</button>`;

  box.innerHTML = header + summary + dupList + copyBtn + closeBtn;
  overlay.appendChild(box);
  document.body.appendChild(overlay);

  // คัดลอกผล
  document.getElementById('__dup_copy__').onclick = () => {
    const lines = [
      `ผลตรวจชื่อตอนซ้ำ — ${new Date().toLocaleString('th-TH')}`,
      `ตอนทั้งหมด: ${titles.length}  |  ซ้ำ: ${dups.length} กลุ่ม`,
      '',
    ];
    if (dups.length === 0) {
      lines.push('✅ ไม่พบชื่อตอนซ้ำ');
    } else {
      dups.forEach((d, i) => {
        lines.push(`${i+1}. "${d.title}"`);
        lines.push(`   ซ้ำ ${d.positions.length} ครั้ง ที่ตำแหน่ง: ${d.positions.join(', ')}`);
      });
    }
    navigator.clipboard.writeText(lines.join('\n'))
      .then(() => alert('คัดลอกแล้ว!'))
      .catch(() => {
        prompt('คัดลอกข้อความด้านล่าง:', lines.join('\n'));
      });
  };
}

// --- Main ---
const banner = document.createElement('div');
banner.id = '__dup_banner__';
banner.style.cssText = `
  position:fixed;top:0;left:0;width:100%;padding:12px;
  background:#2563eb;color:#fff;text-align:center;
  font-family:sans-serif;font-size:14px;z-index:999998;
`;
banner.innerText = '🔍 กำลังโหลดรายชื่อตอนทั้งหมด... (อาจใช้เวลา 10-30 วินาที)';
document.body.appendChild(banner);

try {
  await scrollAll();
  await clickLoadMore();
  const titles = getTitles();
  const dups = findDuplicates(titles);
  banner.remove();
  showResult(titles, dups);
} catch(e) {
  banner.innerText = '❌ เกิดข้อผิดพลาด: ' + e.message;
}
})();
