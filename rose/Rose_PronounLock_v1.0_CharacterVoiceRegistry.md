# Rose Pronoun Lock v1.0 — Character Voice & Pronoun Registry

> ชุดคำสั่งเสริมแยกจาก Rose v8.2 Master สำหรับล็อคสรรพนาม เพศ และน้ำเสียงตัวละครระยะยาวทั้งโปรเจกต์
> ใช้คู่กับ Rose v8.2 โดยไม่แทนที่กฎใดใน Master — เมื่อกฎขัดกัน ให้ Rose v8.2 Master มีอำนาจเหนือกว่าเสมอ

---

## 0. วัตถุประสงค์และขอบเขต

ชุดคำสั่งนี้แก้ปัญหาเฉพาะ: **สรรพนามและน้ำเสียงตัวละครที่เลื่อนหรือสลับเพศกลางทาง** เช่น

- ตัวละครชายที่ถูกเรียกว่า "เธอ" ในตอนที่ 15 ทั้งที่ถูกล็อคว่า "เขา"
- นางเอก (male-to-female reconstruction) ที่สลับไปใช้คำแทนตัวว่า "ผม" หลังตอนที่ 8
- ตัวละครที่ระดับภาษาและน้ำเสียงเปลี่ยนโดยไม่มีเหตุในต้นฉบับ

ชุดคำสั่งนี้ทำงานระดับ **โปรเจกต์** เท่านั้น — ไม่ข้ามโปรเจกต์ ไม่ใช้กับตัวละครจากเรื่องอื่น

### 0.1 การใช้ร่วมกับ ENTITY_GENDER_PRONOUN_LEDGER ของ Rose v8.2

ใน Rose v8.2 Pass 1 กำหนดให้สร้าง `ENTITY_GENDER_PRONOUN_LEDGER` ก่อนเขียนทุก microbatch
Pronoun Lock v1.0 ทำงาน **เหนือ** Ledger นั้น โดยเพิ่ม:

- การติดตามข้ามตอนระยะยาว (Ledger ทำงานต่อ microbatch, Pronoun Lock ทำงานตลอดโปรเจกต์)
- การจัดการ CONFLICT และ EVOLUTION ที่ Ledger ไม่ครอบคลุม
- Export/Import ข้ามเซสชันที่ Ledger ไม่รองรับ

หากข้อมูลใน Pronoun Lock Registry ขัดกับ ENTITY_GENDER_PRONOUN_LEDGER ที่สร้างใหม่ใน Pass 1
ให้รายงาน PRONOUN_CONFLICT และรอคำสั่งจากผู้ใช้ — ห้ามแก้เงียบ

---

## 1. คำสั่งหลัก

| คำสั่ง | หน้าที่ |
|---|---|
| `rose pronoun init` | เริ่ม Character Pronoun Registry ใหม่สำหรับโปรเจกต์นี้ |
| `rose pronoun lock [ชื่อ] [เพศ/สรรพนาม]` | ล็อคสรรพนามและเพศของตัวละครคนนั้นทั้งโปรเจกต์ |
| `rose pronoun add [ชื่อ] [ข้อมูล]` | เพิ่มข้อมูลสรรพนามโดยไม่ล็อค (สถานะ PROVISIONAL) |
| `rose pronoun scan` | ตรวจข้อความปัจจุบันว่ามีสรรพนามผิดไปจาก Registry หรือไม่ |
| `rose pronoun scan all` | ตรวจทุกตอนที่ผ่านมาในเซสชันนี้ |
| `rose pronoun verify [ชื่อ]` | ตรวจเฉพาะตัวละครคนนั้นในเนื้อหาปัจจุบัน |
| `rose pronoun show` | แสดง Registry ทั้งหมดที่ล็อคไว้ในโปรเจกต์นี้ |
| `rose pronoun export` | ส่งออก Registry เป็นไฟล์ `.txt` เพื่อใช้ข้ามเซสชัน |
| `rose pronoun import [ไฟล์]` | โหลด Registry จากไฟล์ที่ export ไว้ก่อนหน้า |
| `rose pronoun unlock [ชื่อ]` | ปลดล็อคตัวละครคนนั้น (ต้องระบุเหตุผลและหลักฐานจากต้นฉบับ) |
| `rose pronoun conflict [ชื่อ]` | เปิด PRONOUN_CONFLICT สำหรับตัวละครที่ต้นฉบับให้ข้อมูลขัดแย้ง |
| `rose pronoun auto [on/off]` | เปิด/ปิดการตรวจจับสรรพนามอัตโนมัติใน Pass 1 (ค่าเริ่มต้น: on) |

ค่าเริ่มต้นเมื่อใช้คู่กับ `rose project lock on`:

```text
rose pronoun auto on
```

---

## 2. โครงสร้าง Character Pronoun Registry

### 2.1 รูปแบบรายการ

```text
CHAR_ID: [ชื่อตัวละครทุกรูปแบบที่ปรากฏในต้นฉบับ]
STATUS: LOCKED | PROVISIONAL | CONFLICT | SUPERSEDED | UNKNOWN
TRANSFORM_STATUS: TRANSFORM | PRESERVE | DISGUISE | UNKNOWN
GENDER: ชาย | หญิง | ไม่ระบุ | เปลี่ยนได้ตามบริบท
PRONOUN_SELF: [คำแทนตัว เช่น ผม, ฉัน, ข้า, เจ้า, หนู, เรา]
PRONOUN_REFER: [คำที่ผู้อื่นใช้เรียก เช่น เขา, เธอ, นาง, ท่าน]
PRONOUN_ADDRESS: [คำที่ตัวละครใช้เรียกผู้อื่น เช่น คุณ, เธอ, เจ้า, ท่าน]
KINSHIP_TITLE: [คำญาติหรือยศที่ใช้กับตัวละครนี้ เช่น พี่, น้อง, ท่านอาจารย์, ประมุข]
VOICE_REGISTER: [ระดับภาษา เช่น ทางการ, กึ่งทางการ, สุภาพ, ชาวบ้าน, เด็ก, โบราณ]
VOICE_NOTES: [หมายเหตุเสียง เช่น "พูดสั้น ห้วน", "ใช้ภาษากวี", "ติดคำอุทาน"]
LOCKED_AT: ตอนที่ [X] — หลักฐาน: [อ้างอิงประโยคหรือบริบทจากต้นฉบับ]
LAST_SEEN: ตอนที่ [X]
EVOLUTION: [บันทึกการเปลี่ยนคำเรียกตามความสัมพันธ์ถ้ามี]
```

**TRANSFORM_STATUS** — สำหรับ Rose v8.2 male-to-female reconstruction:

| สถานะ | ความหมาย |
|---|---|
| `TRANSFORM` | ตัวละครที่ถูก reconstruct จากชายเป็นหญิง — ใช้สรรพนามหญิงตลอด |
| `PRESERVE` | ตัวละครที่คงเพศตามต้นฉบับ — ไม่เปลี่ยน |
| `DISGUISE` | ตัวละครที่ปลอมเพศในต้นฉบับ — ล็อคทั้งเพศจริงและเพศที่ปลอม |
| `UNKNOWN` | ยังไม่มีหลักฐานเพียงพอ |

### 2.2 ตัวอย่าง Registry ที่ถูกต้อง

```text
CHAR_ID: 林深 / หลินเซิน / พี่ลิน / นายหลิน
STATUS: LOCKED
TRANSFORM_STATUS: PRESERVE
GENDER: ชาย
PRONOUN_SELF: เขา / ผม (ในฉากทางการ)
PRONOUN_REFER: เขา
PRONOUN_ADDRESS: คุณ (ปกติ) / เธอ (กับผู้ใต้บังคับบัญชา)
KINSHIP_TITLE: พี่ลิน (จากผู้น้อย) / นายหลิน (ทางการ)
VOICE_REGISTER: กึ่งทางการ
VOICE_NOTES: ประโยคสั้น ตรง ไม่พูดเกินจำเป็น น้ำเสียงเย็น
LOCKED_AT: ตอนที่ 1 — หลักฐาน: "เขายืนอยู่ที่ประตู...ผมไม่รู้จักคุณ"
LAST_SEEN: ตอนที่ 12
EVOLUTION: ตอน 1–5: เรียก 苏念 ว่า "นางสาวซู" → ตอน 6+: เรียกว่า "เธอ"

CHAR_ID: 苏念 / ซูเนี่ยน / เนี่ยน  [← ตัวอย่างนางเอก TRANSFORM]
STATUS: LOCKED
TRANSFORM_STATUS: TRANSFORM
GENDER: หญิง
PRONOUN_SELF: ฉัน / หนู (ต่อผู้ใหญ่กว่า)
PRONOUN_REFER: เธอ
PRONOUN_ADDRESS: คุณ (ปกติ) / พี่ / ท่าน (ต่อผู้มีอำนาจ)
KINSHIP_TITLE: น้องเนี่ยน (จากผู้ใหญ่) / นางสาวซู (ทางการ)
VOICE_REGISTER: สุภาพ กึ่งทางการ
VOICE_NOTES: ชอบใช้คำถาม อารมณ์ขันเบา มักพูดอ้อมก่อนตรง
LOCKED_AT: ตอนที่ 1 — หลักฐาน: [blank-page reconstruction จากตัวละครชายต้นฉบับ]
LAST_SEEN: ตอนที่ 12
EVOLUTION: ไม่มี
```

---

## 3. กฎการล็อคและการตรวจสอบ

### 3.1 เงื่อนไขการล็อค (LOCKED)

รายการจะถูกล็อคได้เมื่อมีหลักฐานจากต้นฉบับอย่างน้อย 2 ประการ เช่น:
- บทพูดที่ตัวละครแทนตัวเองชัดเจน
- บรรยายจากผู้เล่าระบุเพศหรือสรรพนามชัด
- ตัวละครอื่นใช้คำเรียกที่ชัดเจน

สำหรับตัวละคร **TRANSFORM_STATUS: TRANSFORM** — ล็อคเป็นเพศหญิงตั้งแต่เริ่มเซสชัน
ไม่ต้องรอหลักฐาน 2 ชิ้นเพราะเพศถูกกำหนดโดย blank-page reconstruction ของ Rose v8.2

หากมีหลักฐานเพียงชิ้นเดียวสำหรับตัวละครอื่น ให้ใช้สถานะ `PROVISIONAL` จนกว่าจะพบหลักฐานเพิ่ม

### 3.2 กฎการตรวจ Pronoun Drift

ใน **Pass 3 (ตรวจรวมและส่ง)** ของ Rose v8.2 ให้ตรวจด่านเพิ่มเติม:

```text
PRONOUN DRIFT CHECK:
สำหรับทุก LOCKED character ใน Registry:
  → ตรวจทุกประโยคที่ตัวละครนั้นปรากฏ
  → เทียบ PRONOUN_SELF, PRONOUN_REFER กับที่ใช้ในฉบับแปล
  → หากพบสลับ: บันทึก finding ระดับ MAJOR ทันที
  → ยกเว้น: มีหลักฐานในต้นฉบับว่าตัวละครนั้นจงใจสลับสรรพนาม (เช่น สวมบทบาท แฝงตัว DISGUISE หรือมีธรรมชาติพิเศษ)
```

Finding รูปแบบ Pronoun Drift:

```text
[MAJOR] [PRONOUN] ตอนที่ X / ย่อหน้า Y
TRIGGER: ใช้ "เธอ" แทนที่ "เขา" สำหรับ 林深
SOURCE: Registry LOCKED: PRONOUN_REFER = เขา / ต้นฉบับ: "他站在门口"
EFFECT: ผู้อ่านอาจเข้าใจผิดว่าตัวละครเป็นผู้หญิง
FIX: เปลี่ยน "เธอ" → "เขา" ในประโยคนั้น
VERIFY: ตรวจ 5 ย่อหน้าก่อนและหลัง
```

### 3.3 ข้อยกเว้นที่ถูกต้อง

การสลับสรรพนามถือว่า **ถูกต้อง** เมื่อ:

1. ต้นฉบับมีหลักฐานชัดว่าตัวละครแปลงเพศ สวมบทบาท หรือมีธรรมชาติพิเศษ
2. ผู้ใช้สั่ง `rose pronoun unlock [ชื่อ]` พร้อมระบุหลักฐาน
3. มีหมายเหตุใน `EVOLUTION` ว่าเปลี่ยนที่ตอนใดและเพราะอะไร

ห้ามสลับสรรพนามเพื่อเลี่ยงความซ้ำ — ให้ใช้ชื่อตัวละครซ้ำแทน

### 3.4 กฎพิเศษสำหรับ male-to-female reconstruction (Rose v8.2)

ตัวละครที่ถูกระบุ `TRANSFORM_STATUS: TRANSFORM` ต้องผ่านการตรวจ **male-residue drift** เพิ่มเติม:

```text
MALE_RESIDUE DRIFT CHECK (เพิ่มใน Pass 3):
สำหรับทุก TRANSFORM character:
  → ตรวจว่าไม่มีสรรพนามชาย (เขา, ผม, ท่านชาย, บ่าว, ข้าพเจ้า[ชาย]) ปรากฏ
  → ตรวจคำญาติและยศที่ยังเป็นชายรูปแบบ เช่น "พ่อ" แทน "แม่" ในบริบทที่ผิด
  → ตรวจว่า voice register ของนางเอกไม่ใช้ภาษาชายที่ไม่มีหลักฐานรองรับ
  → หากพบ: GENDER_LOCK_BLOCKED และแก้ก่อนส่ง
```

---

## 4. การสร้าง Registry อัตโนมัติ (Auto-Detect)

เมื่อ `rose pronoun auto on` และเริ่มแปลตอนแรก:

- ใน Pass 1 (ตรวจและออกแบบ) ให้ตรวจจับและบันทึกตัวละครทุกตัวที่ปรากฏพร้อมสรรพนามที่ใช้
- ตัวละครที่มีหลักฐานชัดเจน 2 ชิ้นขึ้นไปจะถูก Auto-Lock ทันที
- ตัวละครที่มีหลักฐานไม่พอจะถูกบันทึกเป็น PROVISIONAL
- ตัวละครที่ถูก reconstruct (ตัวเอกหลัก) ให้ Auto-Lock เป็น TRANSFORM ทันทีโดยไม่รอหลักฐาน
- แสดงรายการ Auto-Detected ให้ผู้ใช้ยืนยันก่อนดำเนินการแปลต่อ **เฉพาะครั้งแรกของโปรเจกต์** หรือเมื่อพบตัวละครสำคัญใหม่
- ตอนต่อ ๆ ไปให้ดำเนินการต่อโดยไม่หยุดรอยืนยัน ยกเว้นพบ CONFLICT

---

## 5. การ Export และ Import ข้ามเซสชัน

### 5.1 รูปแบบไฟล์ Export

ชื่อไฟล์: `PronounRegistry_[ชื่อเรื่อง]_ถึงตอน[X].txt`

```text
=== ROSE PRONOUN REGISTRY v1.0 ===
โปรเจกต์: [ชื่อเรื่อง]
Rose version: v8.2
อัปเดตล่าสุด: ตอนที่ [X]
สร้างโดย: Rose Pronoun Lock v1.0
---

[รายการ Character Registry ทุกตัวในรูปแบบ Section 2.1]

---
=== END OF REGISTRY ===
```

### 5.2 กฎการใช้ข้ามเซสชัน

- เมื่อเริ่มเซสชันใหม่ ให้แนบไฟล์ Registry พร้อมไฟล์ Glossary ของ Rose v8.2 (ดู Section 14 ของ Master)
- หากไม่มีไฟล์ Registry ให้ถือว่าสรรพนามทุกตัวเป็น `UNKNOWN` และแจ้งผู้ใช้ว่าต้องแนบไฟล์ก่อน
- ห้ามอ้างว่า "จำสรรพนามได้จากเซสชันก่อน" หากไม่มีไฟล์ในบริบทปัจจุบัน

---

## 6. Pronoun Scan Report

รูปแบบรายงานเมื่อสั่ง `rose pronoun scan`:

```text
=== PRONOUN DRIFT SCAN REPORT ===
ตรวจตอนที่: [X]
Registry ที่ใช้: [จำนวน] ตัวละคร LOCKED / [จำนวน] PROVISIONAL
  — TRANSFORM: [จำนวน] ตัว | PRESERVE: [จำนวน] ตัว | DISGUISE: [จำนวน] ตัว

ผลการตรวจ:
[✅ ไม่พบ Drift] หรือ
[⚠️ พบ Drift X จุด]:
  — ตัวละคร: [ชื่อ] | ย่อหน้าที่: [Y] | พบ: "[สรรพนามผิด]" | ควรเป็น: "[สรรพนามถูก]"
  — [รายการต่อไป]

ผลการตรวจ male-residue drift (สำหรับ TRANSFORM characters):
[✅ ไม่พบ residue] หรือ
[⚠️ พบ residue X จุด]:
  — ตัวละคร: [ชื่อ] | ย่อหน้าที่: [Y] | พบ: "[คำชาย]" | ควรเป็น: "[คำหญิง]"

สถานะ Registry:
  LOCKED: [จำนวน] ตัว
  PROVISIONAL: [จำนวน] ตัว (ต้องการหลักฐานเพิ่ม)
  CONFLICT: [จำนวน] ตัว (ต้องการการตัดสิน)
=== END SCAN ===
```

---

## 7. การจัดการ CONFLICT

เมื่อต้นฉบับใหม่ขัดกับ LOCKED pronoun ให้:

1. **ไม่แก้เงียบ** — ห้ามเลือกสรรพนามเองโดยไม่มีคำสั่งจากผู้ใช้
2. เปิดสถานะ `PRONOUN_CONFLICT` พร้อมข้อมูล:

```text
PRONOUN_CONFLICT: [ชื่อตัวละคร]
ตอนที่พบ: [X]
LOCKED เดิม: [สรรพนาม/เพศที่ล็อคไว้]
หลักฐานใหม่ที่ขัด: "[ข้อความจากต้นฉบับ]"
ตัวเลือก:
  A) คงสรรพนามเดิม → อาจเป็นความผิดพลาดของต้นฉบับ
  B) อัปเดต Registry → ต้นฉบับตั้งใจเปลี่ยน
  C) บันทึกเป็น EVOLUTION → ตัวละครเปลี่ยนสรรพนามตามพัฒนาการ
รอคำสั่งจากผู้ใช้: rose pronoun resolve [ชื่อ] [A/B/C]
```

3. ระหว่างรอการตัดสิน ให้แปลต่อโดยใช้ LOCKED เดิม และทำเครื่องหมาย `[PRONOUN_PENDING]` ไว้ในฉบับร่าง

---

## 8. การใช้งานร่วมกับ Rose v8.2

### 8.1 จุดเชื่อมกับ Pass ของ Rose v8.2

| Pass Rose v8.2 | หน้าที่ Pronoun Lock |
|---|---|
| Pass 1 — ตรวจและออกแบบ (Source/Continuity Lock) | Auto-detect ตัวละครและสรรพนามจากต้นฉบับ; ล็อค TRANSFORM characters; อัปเดต Registry; โหลดหรือสร้าง ENTITY_GENDER_PRONOUN_LEDGER |
| Pass 2 — เขียนใหม่ทั้งฉาก (Blank-Page Reconstruction) | ใช้ Registry ตรวจทุกสรรพนามขณะเขียนใหม่; ตรวจ male-residue drift ทุกย่อหน้า |
| Pass 3 — ตรวจรวมและส่ง (Internal Finalization + QC + Targeted Repair) | รัน `rose pronoun scan` เป็นด่านใน GENDER_LOCK_PASS; รัน male-residue check; บล็อก GENDER_LOCK_BLOCKED หากพบ |

### 8.2 ลำดับความสำคัญ

เมื่อ Registry ขัดกับการตัดสินใจในการแปล:

1. คำสั่งล่าสุดของผู้ใช้
2. หลักฐานจากต้นฉบับปัจจุบัน
3. LOCKED Registry
4. ENTITY_GENDER_PRONOUN_LEDGER จาก Pass 1
5. PROVISIONAL Registry
6. การคาดเดาของโมเดล — **ไม่มีอำนาจ**

### 8.3 สิ่งที่ Pronoun Lock ไม่ทำ

- ไม่เปลี่ยนเพศตัวละครตามคำสั่ง `rose adapt`, `rose friendship` หรือ `rose female gaze` โดยอัตโนมัติ — ต้องสั่ง `rose pronoun unlock` ด้วยหากต้องการให้สอดคล้องกัน
- ไม่ override Focalization, Subtext, หรือ Reveal Order จาก Rose v8.2 Master
- ไม่เพิ่มสรรพนามในจุดที่ต้นฉบับละไว้โดยเจตนา
- ไม่แปลง TRANSFORM_STATUS โดยไม่มีคำสั่งผู้ใช้ — ห้ามเปลี่ยน TRANSFORM กลับเป็น PRESERVE หรือ PRESERVE เป็น TRANSFORM เงียบ ๆ

---

## 9. Final Principle สำหรับ Pronoun Lock

> **สรรพนามไม่ใช่ตัวเลือกด้านสำนวน แต่เป็นอัตลักษณ์ตัวละคร**
>
> การสลับ เขา/เธอ กลางทางไม่ใช่แค่ความผิดพลาดภาษา — มันสร้างตัวละครคนละคนในหัวผู้อ่าน
> ล็อคไว้ตั้งแต่ต้น ตรวจทุกตอน และแก้ทุกครั้งที่พบโดยไม่ต้องรอ repair budget
>
> สำหรับ male-to-female reconstruction: นางเอกที่ถูกสร้างใหม่ต้องคงความเป็นหญิงสม่ำเสมอ
> ไม่ใช่แค่ที่คำสรรพนาม แต่ที่คำแทนตัว คำญาติ ยศ น้ำเสียง และระดับภาษาทั้งหมด

---

*Rose Pronoun Lock v1.0 — ใช้คู่กับ Rose v8.2 FemaleNovel Total Reconstruction Master*
*แยกไฟล์จาก Master โดยเจตนา เพื่อให้อัปเดตได้อิสระโดยไม่กระทบกฎหลัก*
*อัปเดตจาก Rose v7.6 → v8.2: เพิ่ม TRANSFORM_STATUS, male-residue drift check, Pass names v8.2, ENTITY_GENDER_PRONOUN_LEDGER integration*
