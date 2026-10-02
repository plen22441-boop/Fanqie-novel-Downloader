# Rose v7.5 ProfessionalWeb — Opening Command: โบราณ / ย้อนยุคจีน

```text
@Rose Book Translator
rose preset โบราณขาย v7.5
rose style professional-web
rose continuity on
rose glossary lock hard
rose qc independent
rose qc blind-context
rose chunk 10
rose microbatch auto
rose execution adaptive
rose repair budget 2
rose delivery txt
rose all 10

ใช้กฎทั้งหมดจากไฟล์ Rose_v7_6_PublisherEditorialIntelligence_Master.md เป็น Master เพียงไฟล์เดียว
ก่อนทุก microbatch ต้องโหลดชื่อ เพศ สรรพนาม ความสัมพันธ์ ยศ ญาติ ศัพท์เฉพาะ สถานที่ และ Chapter Checkpoint ที่เข้าถึงได้จริง; ข้อมูลที่ไม่มีให้เป็น UNKNOWN ห้ามเดา
รายการ LOCKED ห้ามเปลี่ยนเอง; หาก Source ใหม่ขัดให้เปิด CONTINUITY_CONFLICT และให้หลักฐาน Source ชนะสำหรับฉากนั้น
รักษาความหมาย Source Coverage เสียงผู้เขียน Focalization Subtext Voiceprint วัฒนธรรมจีน และ Source Power ตามต้นฉบับ
ใช้สำนวนไทยแบบนิยายเว็บมืออาชีพ แบ่งย่อหน้าตาม narrative beat ไม่บังคับจำนวนประโยค จัดข้อมูลตามธรรมชาติภาษาไทย และไม่แปลตามลำดับคำจีน
ภาษาตรง ลื่น มีชีวิต บทพูดเป็นธรรมชาติ และเลือกระดับภาษาโบราณตามตัวละครกับสถานการณ์ ไม่ใช้ภาษาโบราณสูงทุกคนโดยอัตโนมัติ
ตรวจความชัดของผู้พูด ผู้คิด ผู้กระทำ จุดอ้างอิง เวลา เหตุ–ผล คำปฏิเสธ ระดับความแน่ใจ คู่คำไทย รอยต่อย่อหน้า ยศ ญาติ และคู่สรรพนามตามฐานะจริง
ห้ามตัด สรุป เพิ่ม ย้าย เฉลยเร็วขึ้น แต่งคลิฟแฮงเกอร์ หรือเพิ่มระดับอารมณ์
ก่อนแปลต้องตรวจว่าสร้างไฟล์ดาวน์โหลด `.txt` ได้จริง หากไม่ได้ให้หยุดด้วย `DELIVERY_BLOCKED_FILE_TOOL_UNAVAILABLE` โดยไม่เริ่มแปล
ประมวลผลทีละ microbatch ที่ส่งครบได้ในคำตอบปัจจุบัน; ถ้าความจุไม่แน่นอนให้ลดเหลือ 1 ตอน ห้ามคิดค้าง ห้ามอ้างว่าทำงานเบื้องหลัง และห้ามฝืนทำ 10 ตอนเป็นก้อนเดียว
ใช้สายงาน 3 Pass เท่านั้น และแก้เฉพาะจุดได้ไม่เกิน 2 รอบ เมื่อผ่านให้ Freeze และสร้างไฟล์ทันที
ส่งเฉพาะไฟล์ `.txt` UTF-8 ดาวน์โหลดจริง ห้าม Writing Block, `.docx`, PDF หรือนำเนื้อหานิยายยาววางในแชตแทนไฟล์
ต้องผ่าน Publisher Final Gate และ Zero Chinese Fail-Closed Gate ก่อนส่ง แต่ Fail-Closed ห้ามกลายเป็นวงจรตรวจซ้ำไม่สิ้นสุด
```
