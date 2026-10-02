"""
โมดูลตรวจทานสำนวนภาษาไทยสำหรับนิยายแปล
ใช้ Claude AI เป็นบรรณาธิการตรวจสอบ:
- สำนวนภาษาไทย
- ความสม่ำเสมอของคำศัพท์/terminology
- สรรพนามตัวละคร (ชาย/หญิง)
"""

import tkinter as tk
from tkinter import messagebox, scrolledtext
import customtkinter as ctk
import threading
import json
import os
import re

PROOFREADER_CONFIG_FILE = "proofreader_config.json"

DEFAULT_CONFIG = {
    "api_key": "",
    "model": "claude-opus-4-5",
    "characters": {},
    "glossary": {},
    "custom_rules": ""
}


def load_proofreader_config():
    if os.path.exists(PROOFREADER_CONFIG_FILE):
        try:
            with open(PROOFREADER_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                cfg = DEFAULT_CONFIG.copy()
                cfg.update(data)
                return cfg
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_proofreader_config(cfg):
    try:
        with open(PROOFREADER_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"บันทึก config ล้มเหลว: {e}")


def build_system_prompt(cfg):
    characters = cfg.get("characters", {})
    glossary = cfg.get("glossary", {})
    custom_rules = cfg.get("custom_rules", "").strip()

    char_lines = ""
    if characters:
        char_lines = "\n## รายชื่อตัวละครและสรรพนาม\n"
        for name, info in characters.items():
            pronoun = info.get("pronoun", "")
            gender = info.get("gender", "")
            notes = info.get("notes", "")
            char_lines += f"- **{name}**: เพศ={gender}, สรรพนาม={pronoun}"
            if notes:
                char_lines += f", หมายเหตุ={notes}"
            char_lines += "\n"

    glossary_lines = ""
    if glossary:
        glossary_lines = "\n## คำศัพท์/Terminology ที่กำหนด\n"
        for zh, th in glossary.items():
            glossary_lines += f"- {zh} → {th}\n"

    custom_section = ""
    if custom_rules:
        custom_section = f"\n## กฎเพิ่มเติมจากบรรณาธิการ\n{custom_rules}\n"

    return f"""คุณคือบรรณาธิการนิยายไทยผู้เชี่ยวชาญ ทำหน้าที่ตรวจทานต้นฉบับแปลจากภาษาจีนเป็นภาษาไทย

## หน้าที่ของคุณ
ตรวจสอบและชี้ปัญหาในด้านต่อไปนี้:
1. **สำนวนภาษา**: ประโยคที่ฟังดูเป็น "ภาษาจีนแปลตรงๆ" ไม่เป็นธรรมชาติ, คำที่ไม่เหมาะสม
2. **สรรพนาม**: สรรพนามตัวละครหลุด/ผิดเพศ เช่น ตัวละครชายใช้ "หล่อน/เธอ" แทนที่จะเป็น "เขา/เขา"
3. **Terminology**: คำศัพท์เฉพาะที่ใช้ไม่สม่ำเสมอกับ glossary ที่กำหนด
4. **ความสอดคล้อง**: ชื่อตัวละคร, สถานที่, ของวิเศษที่สะกดไม่ตรงกัน
{char_lines}{glossary_lines}{custom_section}
## รูปแบบการตอบ
ตอบเป็น JSON ในรูปแบบนี้เท่านั้น:
{{
  "summary": "สรุปภาพรวมคุณภาพการแปล",
  "score": 85,
  "issues": [
    {{
      "type": "สรรพนาม|สำนวน|terminology|สะกด|อื่นๆ",
      "severity": "high|medium|low",
      "original": "ข้อความต้นฉบับที่มีปัญหา",
      "suggestion": "ข้อเสนอแนะการแก้ไข",
      "reason": "เหตุผล"
    }}
  ],
  "good_points": ["จุดที่แปลได้ดี"]
}}

ถ้าไม่พบปัญหา ให้ issues เป็น array ว่าง []
"""


class ProofreadWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("ตรวจทานสำนวนภาษา (AI Editor)")
        self.geometry("1000x750")
        self.resizable(True, True)
        self.cfg = load_proofreader_config()
        self._setup_ui()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Top bar
        top = ctk.CTkFrame(self)
        top.grid(row=0, column=0, padx=10, pady=(10, 0), sticky="ew")
        top.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(top, text="ตรวจทานสำนวน", font=("Arial", 16, "bold")).grid(
            row=0, column=0, padx=10, pady=8, sticky="w"
        )

        btn_frame = ctk.CTkFrame(top, fg_color="transparent")
        btn_frame.grid(row=0, column=2, padx=10, pady=8, sticky="e")

        ctk.CTkButton(
            btn_frame, text="⚙ ตั้งค่า", width=100,
            command=self._open_settings, fg_color="gray40"
        ).pack(side="left", padx=4)

        self.run_btn = ctk.CTkButton(
            btn_frame, text="▶ ตรวจทาน", width=120,
            command=self._run_proofread
        )
        self.run_btn.pack(side="left", padx=4)

        # Main pane split
        pane = ctk.CTkFrame(self)
        pane.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        pane.grid_columnconfigure(0, weight=1)
        pane.grid_columnconfigure(1, weight=1)
        pane.grid_rowconfigure(0, weight=1)

        # Left: input
        left = ctk.CTkFrame(pane)
        left.grid(row=0, column=0, padx=(0, 5), pady=0, sticky="nsew")
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(left, text="เนื้อหาที่ต้องการตรวจ (วางข้อความที่แปลแล้ว)").grid(
            row=0, column=0, padx=8, pady=(8, 2), sticky="w"
        )
        self.input_text = ctk.CTkTextbox(left, wrap="word")
        self.input_text.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="nsew")

        # Right: result
        right = ctk.CTkFrame(pane)
        right.grid(row=0, column=1, padx=(5, 0), pady=0, sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="ผลการตรวจทาน").grid(
            row=0, column=0, padx=8, pady=(8, 2), sticky="w"
        )
        self.result_text = ctk.CTkTextbox(right, wrap="word", state="disabled")
        self.result_text.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="nsew")

        # Status bar
        self.status_var = tk.StringVar(value="พร้อมใช้งาน")
        status_bar = ctk.CTkLabel(self, textvariable=self.status_var, anchor="w", text_color="gray70")
        status_bar.grid(row=2, column=0, padx=12, pady=(0, 6), sticky="ew")

    def _set_result(self, text):
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", text)
        self.result_text.configure(state="disabled")

    def _run_proofread(self):
        api_key = self.cfg.get("api_key", "").strip()
        if not api_key:
            messagebox.showerror(
                "ยังไม่ได้ตั้งค่า API Key",
                "กรุณาตั้งค่า Claude API Key ก่อนใช้งาน\nไปที่ ⚙ ตั้งค่า",
                parent=self
            )
            return

        content = self.input_text.get("1.0", "end").strip()
        if not content:
            messagebox.showwarning("ไม่มีข้อความ", "กรุณาวางข้อความที่ต้องการตรวจทาน", parent=self)
            return

        self.run_btn.configure(state="disabled", text="⏳ กำลังตรวจ...")
        self.status_var.set("กำลังส่งให้ Claude ตรวจสอบ...")
        self._set_result("กำลังประมวลผล...")

        thread = threading.Thread(target=self._do_proofread, args=(content,), daemon=True)
        thread.start()

    def _do_proofread(self, content):
        try:
            import anthropic
        except ImportError:
            self.after(0, self._on_error, "ไม่พบ library anthropic\nกรุณารัน: pip install anthropic")
            return

        try:
            client = anthropic.Anthropic(api_key=self.cfg["api_key"])
            system_prompt = build_system_prompt(self.cfg)
            model = self.cfg.get("model", "claude-opus-4-5")

            message = client.messages.create(
                model=model,
                max_tokens=4096,
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": f"กรุณาตรวจทานข้อความต่อไปนี้:\n\n---\n{content}\n---"
                    }
                ]
            )

            raw = message.content[0].text
            self.after(0, self._on_result, raw)

        except Exception as e:
            self.after(0, self._on_error, str(e))

    def _on_result(self, raw_text):
        self.run_btn.configure(state="normal", text="▶ ตรวจทาน")
        try:
            # หา JSON ใน response
            match = re.search(r'\{[\s\S]*\}', raw_text)
            if match:
                data = json.loads(match.group())
                display = self._format_result(data)
            else:
                display = raw_text
        except Exception:
            display = raw_text

        self._set_result(display)
        self.status_var.set("ตรวจสอบเสร็จสิ้น")

    def _format_result(self, data):
        lines = []
        score = data.get("score", "N/A")
        summary = data.get("summary", "")

        lines.append(f"═══════════════════════════════════")
        lines.append(f"  คะแนนคุณภาพ: {score}/100")
        lines.append(f"═══════════════════════════════════")
        if summary:
            lines.append(f"\n📋 สรุป: {summary}\n")

        issues = data.get("issues", [])
        if issues:
            lines.append(f"⚠️  พบปัญหา {len(issues)} จุด\n")
            for i, issue in enumerate(issues, 1):
                sev = issue.get("severity", "")
                sev_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(sev, "⚪")
                itype = issue.get("type", "")
                lines.append(f"{'─'*40}")
                lines.append(f"{sev_icon} [{i}] ประเภท: {itype} | ระดับ: {sev}")
                orig = issue.get("original", "")
                if orig:
                    lines.append(f"  ต้นฉบับ : {orig}")
                sugg = issue.get("suggestion", "")
                if sugg:
                    lines.append(f"  แนะนำ   : {sugg}")
                reason = issue.get("reason", "")
                if reason:
                    lines.append(f"  เหตุผล  : {reason}")
        else:
            lines.append("✅ ไม่พบปัญหา การแปลอยู่ในเกณฑ์ดี\n")

        good = data.get("good_points", [])
        if good:
            lines.append(f"\n✨ จุดที่แปลได้ดี:")
            for g in good:
                lines.append(f"  • {g}")

        return "\n".join(lines)

    def _on_error(self, msg):
        self.run_btn.configure(state="normal", text="▶ ตรวจทาน")
        self._set_result(f"❌ เกิดข้อผิดพลาด:\n\n{msg}")
        self.status_var.set("เกิดข้อผิดพลาด")

    def _open_settings(self):
        ProofreadSettingsWindow(self, self.cfg, self._on_settings_saved)

    def _on_settings_saved(self, new_cfg):
        self.cfg = new_cfg
        save_proofreader_config(new_cfg)


class ProofreadSettingsWindow(ctk.CTkToplevel):
    def __init__(self, master, cfg, on_save_callback):
        super().__init__(master)
        self.title("ตั้งค่าการตรวจทาน")
        self.geometry("700x600")
        self.resizable(True, True)
        self.cfg = json.loads(json.dumps(cfg))  # deep copy
        self.on_save = on_save_callback
        self._setup_ui()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.grab_set()

    def _setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        tabview = ctk.CTkTabview(self)
        tabview.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        tabview.add("API")
        tabview.add("ตัวละคร")
        tabview.add("คำศัพท์")
        tabview.add("กฎเพิ่มเติม")

        self._build_api_tab(tabview.tab("API"))
        self._build_chars_tab(tabview.tab("ตัวละคร"))
        self._build_glossary_tab(tabview.tab("คำศัพท์"))
        self._build_rules_tab(tabview.tab("กฎเพิ่มเติม"))

        save_btn = ctk.CTkButton(self, text="บันทึกการตั้งค่า", command=self._save)
        save_btn.grid(row=1, column=0, padx=10, pady=(0, 10))

    def _build_api_tab(self, tab):
        tab.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(tab, text="Claude API Key:", anchor="w").grid(
            row=0, column=0, padx=10, pady=10, sticky="w"
        )
        self.api_key_var = tk.StringVar(value=self.cfg.get("api_key", ""))
        api_entry = ctk.CTkEntry(tab, textvariable=self.api_key_var, show="*", width=300)
        api_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")

        ctk.CTkLabel(tab, text="Model:", anchor="w").grid(
            row=1, column=0, padx=10, pady=10, sticky="w"
        )
        self.model_var = tk.StringVar(value=self.cfg.get("model", "claude-opus-4-5"))
        model_menu = ctk.CTkOptionMenu(
            tab, variable=self.model_var,
            values=["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5-20251001"]
        )
        model_menu.grid(row=1, column=1, padx=10, pady=10, sticky="w")

        hint = ctk.CTkLabel(
            tab,
            text="รับ API Key ได้ที่ https://console.anthropic.com/",
            text_color="gray60", anchor="w"
        )
        hint.grid(row=2, column=0, columnspan=2, padx=10, pady=5, sticky="w")

    def _build_chars_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            tab,
            text="กรอกข้อมูลตัวละคร: ชื่อ | เพศ (ชาย/หญิง/ไม่ระบุ) | สรรพนาม | หมายเหตุ\nแต่ละตัวละครหนึ่งบรรทัด เช่น: หลินเฟิง | ชาย | เขา | พระเอก",
            justify="left", anchor="w"
        ).grid(row=0, column=0, padx=10, pady=(10, 4), sticky="w")

        self.chars_text = ctk.CTkTextbox(tab, wrap="word")
        self.chars_text.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")

        chars = self.cfg.get("characters", {})
        lines = []
        for name, info in chars.items():
            g = info.get("gender", "")
            p = info.get("pronoun", "")
            n = info.get("notes", "")
            lines.append(f"{name} | {g} | {p} | {n}")
        self.chars_text.insert("1.0", "\n".join(lines))

    def _build_glossary_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            tab,
            text="คำศัพท์ที่ต้องใช้ให้ตรงตาม: คำจีน/อังกฤษ | คำไทยที่กำหนด\nแต่ละคำหนึ่งบรรทัด เช่น: 灵力 | พลังจิตวิญญาณ",
            justify="left", anchor="w"
        ).grid(row=0, column=0, padx=10, pady=(10, 4), sticky="w")

        self.glossary_text = ctk.CTkTextbox(tab, wrap="word")
        self.glossary_text.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")

        glossary = self.cfg.get("glossary", {})
        lines = [f"{k} | {v}" for k, v in glossary.items()]
        self.glossary_text.insert("1.0", "\n".join(lines))

    def _build_rules_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            tab,
            text="กฎพิเศษเพิ่มเติม (พิมพ์เป็นประโยคหรือรายการ):",
            anchor="w"
        ).grid(row=0, column=0, padx=10, pady=(10, 4), sticky="w")

        self.rules_text = ctk.CTkTextbox(tab, wrap="word")
        self.rules_text.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.rules_text.insert("1.0", self.cfg.get("custom_rules", ""))

    def _save(self):
        self.cfg["api_key"] = self.api_key_var.get().strip()
        self.cfg["model"] = self.model_var.get()

        # parse characters
        chars = {}
        for line in self.chars_text.get("1.0", "end").strip().splitlines():
            parts = [p.strip() for p in line.split("|")]
            if parts and parts[0]:
                name = parts[0]
                chars[name] = {
                    "gender": parts[1] if len(parts) > 1 else "",
                    "pronoun": parts[2] if len(parts) > 2 else "",
                    "notes": parts[3] if len(parts) > 3 else ""
                }
        self.cfg["characters"] = chars

        # parse glossary
        glossary = {}
        for line in self.glossary_text.get("1.0", "end").strip().splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2 and parts[0]:
                glossary[parts[0]] = parts[1]
        self.cfg["glossary"] = glossary

        self.cfg["custom_rules"] = self.rules_text.get("1.0", "end").strip()

        self.on_save(self.cfg)
        messagebox.showinfo("สำเร็จ", "บันทึกการตั้งค่าแล้ว", parent=self)
        self.destroy()
