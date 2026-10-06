/* === DEBUG: วางใน Console บนหน้า dingdianzww.org/52507/ ===
   แค่เก็บข้อมูลโครงสร้างเว็บ ไม่โหลดอะไร
   ========================================================== */
(function(){
  var out = [];
  out.push('=== PAGE INFO ===');
  out.push('URL: ' + location.href);
  out.push('Title: ' + document.title);

  // 1. ดู <a> ทั้งหมดที่มีคำว่า "章" หรือ chapter-like
  var allA = Array.from(document.querySelectorAll('a'));
  var chapterA = allA.filter(function(a){
    var t = a.textContent.trim();
    return /第.*章|chapter/i.test(t) || /^\d+\s/.test(t);
  });
  out.push('\n=== A TAGS ที่น่าจะเป็นตอน: ' + chapterA.length + ' ===');
  chapterA.slice(0, 10).forEach(function(a, i){
    out.push(i + '. href="' + (a.getAttribute('href')||'NONE') + '" text="' + a.textContent.trim().substring(0,40) + '" onclick="' + (a.getAttribute('onclick')||'NONE') + '"');
  });

  // 2. ดู onclick elements ทั้งหมด
  var onclicks = Array.from(document.querySelectorAll('[onclick]'));
  out.push('\n=== ONCLICK ELEMENTS: ' + onclicks.length + ' ===');
  onclicks.slice(0, 15).forEach(function(el, i){
    out.push(i + '. <' + el.tagName + '> onclick="' + el.getAttribute('onclick').substring(0,100) + '" text="' + el.textContent.trim().substring(0,30) + '"');
  });

  // 3. ดู li ที่อาจเป็นรายการตอน
  var lis = Array.from(document.querySelectorAll('li'));
  var chLis = lis.filter(function(li){ return /第.*章|chapter/i.test(li.textContent); });
  out.push('\n=== LI ที่มีคำว่า 章: ' + chLis.length + ' ===');
  chLis.slice(0, 10).forEach(function(li, i){
    out.push(i + '. innerHTML: ' + li.innerHTML.substring(0,150));
  });

  // 4. ดู dd elements (บางเว็บนิยายจีนใช้ <dd>)
  var dds = Array.from(document.querySelectorAll('dd'));
  out.push('\n=== DD ELEMENTS: ' + dds.length + ' ===');
  dds.slice(0, 10).forEach(function(dd, i){
    out.push(i + '. innerHTML: ' + dd.innerHTML.substring(0,150));
  });

  // 5. ดู pagination links
  var pageLinks = allA.filter(function(a){
    var h = a.getAttribute('href') || '';
    return /[-_](\d+)\.html/.test(h) || /page/i.test(h) || /下一页|上一页/.test(a.textContent);
  });
  out.push('\n=== PAGINATION LINKS: ' + pageLinks.length + ' ===');
  pageLinks.forEach(function(a, i){
    out.push(i + '. href="' + a.getAttribute('href') + '" text="' + a.textContent.trim().substring(0,20) + '"');
  });

  // 6. ดู div/section ที่มี chapter links จำนวนมาก
  var containers = Array.from(document.querySelectorAll('div,section,ul,dl'));
  var bestContainer = null, bestCount = 0;
  containers.forEach(function(c){
    var links = c.querySelectorAll('a').length;
    if (links > bestCount && links < 200) { bestCount = links; bestContainer = c; }
  });
  if (bestContainer) {
    out.push('\n=== CONTAINER ที่มี links มากสุด (' + bestCount + ' links) ===');
    out.push('TAG: <' + bestContainer.tagName + '> id="' + (bestContainer.id||'') + '" class="' + (bestContainer.className||'').substring(0,60) + '"');
    var firstLinks = Array.from(bestContainer.querySelectorAll('a')).slice(0, 8);
    firstLinks.forEach(function(a, i){
      out.push('  ' + i + '. href="' + (a.getAttribute('href')||'NONE') + '" text="' + a.textContent.trim().substring(0,40) + '"');
    });
  }

  // 7. ดู body HTML ส่วนที่น่าจะเป็น chapter list
  var bodyHtml = document.body.innerHTML;
  var chIdx = bodyHtml.indexOf('第1章');
  if (chIdx === -1) chIdx = bodyHtml.indexOf('第一章');
  if (chIdx === -1) chIdx = bodyHtml.indexOf('章');
  if (chIdx > -1) {
    out.push('\n=== RAW HTML รอบ "章" (position ' + chIdx + ') ===');
    out.push(bodyHtml.substring(Math.max(0, chIdx - 200), chIdx + 500));
  }

  // print ทั้งหมด
  var result = out.join('\n');
  console.log(result);

  // copy ไว้ด้วย
  try { navigator.clipboard.writeText(result).then(function(){ console.log('\n📋 คัดลอกไว้แล้ว — วางส่งมาให้ Claude ได้เลย'); }); } catch(e){}
})();
