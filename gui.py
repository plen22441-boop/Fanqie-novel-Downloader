
import tkinter as tk
from tkinter import messagebox, filedialog
import customtkinter as ctk
import threading
import os
import re
import time
import json
import random
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import OrderedDict
import sys

# 导入项目中的其他模块
from config import CONFIG, save_user_config
from request_handler import RequestHandler
from library import LibraryWindow, add_to_library

# 设置 CustomTkinter 外观
ctk.set_appearance_mode("dark")  # 默认使用暗色主题
ctk.set_default_color_theme("blue")  # 默认使用蓝色主题

class NovelDownloaderGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # 基本窗口设置
        self.title("番茄小说下载器")
        self.geometry(CONFIG.get("default_window_geometry", "800x600"))
        
        # 状态变量
        self.is_downloading = False
        self.downloaded_chapters = set()
        self.content_cache = OrderedDict()
        self.request_handler = RequestHandler()

        # 加载图标 (移到 setup_ui 之前)
        self.load_icons()

        # 设置UI
        self.setup_ui()

        # 绑定关闭事件
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def load_icons(self):
        """加载应用图标"""
        self.icons = {}
        icon_size = (20, 20)
        # 使用 resource_path 获取 assets 文件夹的绝对路径
        assets_path = resource_path("assets")
        
        # 尝试加载图标
        try:
            from PIL import Image
            icon_files = {
                "download": "download.png",
                "folder": "folder.png",
                "library": "library.png",
                "settings": "settings.png"
            }
            
            for name, file in icon_files.items():
                icon_path = os.path.join(assets_path, file)
                if os.path.exists(icon_path):
                    try:
                        img = Image.open(icon_path).resize(icon_size)
                        self.icons[name] = ctk.CTkImage(light_image=img, dark_image=img)
                    except Exception as e:
                        print(f"无法加载图标 {file}: {e}")
        except ImportError:
            print("PIL 模块未安装，无法加载图标")
    
    def setup_ui(self):
        """设置用户界面"""
        # 配置网格布局
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        
        # 创建主框架
        main_frame = ctk.CTkFrame(self)
        main_frame.grid(row=0, column=0, padx=20, pady=20, sticky="ew")
        main_frame.grid_columnconfigure(1, weight=1)
        
        # 小说ID输入区域
        id_label = ctk.CTkLabel(main_frame, text="小说ID:", anchor="w")
        id_label.grid(row=0, column=0, padx=(0, 10), pady=10, sticky="w")
        
        self.novel_id = ctk.CTkEntry(main_frame, placeholder_text="输入番茄小说ID")
        self.novel_id.grid(row=0, column=1, padx=5, pady=10, sticky="ew")
        
        # 保存路径区域
        path_label = ctk.CTkLabel(main_frame, text="保存路径:", anchor="w")
        path_label.grid(row=1, column=0, padx=(0, 10), pady=10, sticky="w")
        
        self.save_path = ctk.CTkEntry(main_frame, placeholder_text="选择保存位置")
        self.save_path.grid(row=1, column=1, padx=5, pady=10, sticky="ew")
        self.save_path.insert(0, CONFIG["file"].get("default_save_path", "downloads"))
        
        # 浏览按钮
        browse_button = ctk.CTkButton(
            main_frame, 
            text="浏览",
            command=self.browse_folder,
            width=80,
            image=self.icons.get("folder"),
            compound="left" if "folder" in self.icons else "none"
        )
        browse_button.grid(row=1, column=2, padx=5, pady=10)
        
        # 下载按钮
        self.download_button = ctk.CTkButton(
            main_frame, 
            text="开始下载",
            command=self.start_download,
            width=120,
            image=self.icons.get("download"),
            compound="left" if "download" in self.icons else "none"
        )
        self.download_button.grid(row=1, column=3, padx=5, pady=10)
        
        # 书库按钮
        library_button = ctk.CTkButton(
            main_frame, 
            text="我的书库",
            command=self.open_library,
            width=120,
            image=self.icons.get("library"),
            compound="left" if "library" in self.icons else "none"
        )
        library_button.grid(row=0, column=3, padx=5, pady=10)
        
        # 进度区域
        progress_frame = ctk.CTkFrame(self)
        progress_frame.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="ew")
        progress_frame.grid_columnconfigure(0, weight=1)
        
        # 进度条
        self.progress_var = ctk.DoubleVar(value=0)
        self.progress_bar = ctk.CTkProgressBar(progress_frame)
        self.progress_bar.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.progress_bar.set(0)
        
        # 状态标签
        self.status_label = ctk.CTkLabel(progress_frame, text="准备就绪", anchor="center")
        self.status_label.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="ew")
        
        # 日志区域
        log_frame = ctk.CTkFrame(self)
        log_frame.grid(row=2, column=0, padx=20, pady=(0, 20), sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(0, weight=1)
        
        # 日志文本框
        self.log_text = ctk.CTkTextbox(log_frame, wrap="word")
        self.log_text.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.log_text.configure(state="disabled")
        
        # 底部按钮区域
        bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        bottom_frame.grid(row=3, column=0, padx=20, pady=(0, 20), sticky="ew")
        
        # 设置按钮
        settings_button = ctk.CTkButton(
            bottom_frame, 
            text="设置",
            command=self.open_settings,
            width=100,
            image=self.icons.get("settings"),
            compound="left" if "settings" in self.icons else "none"
        )
        settings_button.pack(side="left", padx=5)
        
        # 修复缺失章节按钮
        repair_button = ctk.CTkButton(
            bottom_frame,
            text="修复缺失章节",
            command=self.open_repair_dialog,
            width=130,
            fg_color="#d97706",
            hover_color="#b45309",
        )
        repair_button.pack(side="left", padx=5)

        # 清空日志按钮
        clear_log_button = ctk.CTkButton(
            bottom_frame,
            text="清空日志",
            command=self.clear_log,
            width=100
        )
        clear_log_button.pack(side="right", padx=5)
    
    def log(self, message):
        """添加日志"""
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self.update_idletasks()
    
    def update_progress(self, value, status_text):
        """更新进度和状态"""
        self.progress_var.set(value)
        self.progress_bar.set(value / 100)  # 进度条值范围是0-1
        self.status_label.configure(text=status_text)
        self.update_idletasks()
    
    def browse_folder(self):
        """打开文件夹选择对话框"""
        folder_path = filedialog.askdirectory(title="选择保存位置")
        if folder_path:
            self.save_path.delete(0, "end")
            self.save_path.insert(0, folder_path)
    
    def start_download(self):
        """开始下载"""
        if self.is_downloading:
            messagebox.showwarning("提示", "下载正在进行中")
            return
        
        novel_id = self.novel_id.get().strip()
        if not novel_id:
            messagebox.showerror("错误", "请输入小说ID")
            return
        
        save_path = self.save_path.get().strip()
        if not save_path:
            save_path = CONFIG["file"].get("default_save_path", "downloads")
        
        # 检查cookie是否可用
        try:
            # 尝试获取cookie，如果失败会抛出异常
            self.request_handler.get_cookie()
        except Exception as e:
            self.log(f"Cookie错误: {str(e)}")
            messagebox.showerror(
                "Cookie错误",
                f"无法获取有效Cookie，请检查网络连接或手动清除cookie.json文件\n\n错误详情:\n{str(e)}"
            )
            return
        
        self.download_button.configure(state="disabled")
        self.is_downloading = True
        self.downloaded_chapters.clear()
        self.content_cache.clear()
        
        threading.Thread(target=self.download_novel,
                       args=(novel_id, save_path),
                       daemon=True).start()
    
    def download_novel(self, book_id, save_path):
        """下载小说的具体实现"""
        try:
            self.log("正在获取书籍信息...")
            
            # 获取书籍信息
            name, author_name, description = self.request_handler.get_book_info(book_id)
            if not name:
                raise Exception("无法获取书籍信息，请检查小说ID或网络连接")
            
            self.log(f"书名：《{name}》")
            self.log(f"作者：{author_name}")
            self.log(f"简介：{description}")
            
            # 获取章节列表
            self.log("正在获取章节列表...")
            chapters = self.request_handler.extract_chapters(book_id)
            if not chapters:
                raise Exception("未找到任何章节")
            
            self.log(f"\n开始下载，共 {len(chapters)} 章")
            os.makedirs(save_path, exist_ok=True)
            
            # 创建文件并写入信息
            output_file = os.path.join(save_path, f"{name}.txt")
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(f"书名：《{name}》\n作者：{author_name}\n\n简介：\n{description}\n\n")
            
            # 下载章节
            total_chapters = len(chapters)
            success_count = 0
            
            # 先顺序下载前5章
            for chapter in chapters[:5]:
                content = self.request_handler.down_text(chapter["id"])
                if content:
                    self.content_cache[chapter["index"]] = (chapter, content)
                    self.downloaded_chapters.add(chapter["id"])
                    success_count += 1
                    progress = (success_count / total_chapters) * 100
                    self.update_progress(progress, f"正在下载: {success_count}/{total_chapters}")
                    self.log(f"已下载：{chapter['title']}")
            
            # 多线程下载剩余章节
            remaining_chapters = chapters[5:]
            with ThreadPoolExecutor(max_workers=CONFIG["request"].get("max_workers", 5)) as executor:
                future_to_chapter = {
                    executor.submit(self.request_handler.down_text, chapter["id"]): chapter
                    for chapter in remaining_chapters
                }
                
                for future in as_completed(future_to_chapter):
                    chapter = future_to_chapter[future]
                    try:
                        content = future.result()
                        if content:
                            self.content_cache[chapter["index"]] = (chapter, content)
                            self.downloaded_chapters.add(chapter["id"])
                            success_count += 1
                            self.log(f"已下载：{chapter['title']}")
                    except Exception as e:
                        self.log(f"下载失败：{chapter['title']} - {str(e)}")
                    finally:
                        progress = (success_count / total_chapters) * 100
                        self.update_progress(progress, f"正在下载: {success_count}/{total_chapters}")
            
            # 按顺序写入文件
            self.log("\n正在保存文件...")
            
            # 检查重复章节内容
            processed_contents = set()
            with open(output_file, 'a', encoding='utf-8') as f:
                for index in sorted(self.content_cache.keys()):
                    chapter, content = self.content_cache[index]
                    
                    # 检查内容是否重复
                    content_hash = hash(content)
                    if content_hash in processed_contents:
                        self.log(f"跳过重复章节：{chapter['title']}")
                        continue
                    
                    processed_contents.add(content_hash)
                    f.write(f"\n{chapter['title']}\n\n")
                    f.write(content + "\n\n")
            
            self.update_progress(100, "下载完成！")
            self.log(f"\n下载完成！成功：{success_count}章，失败：{total_chapters - success_count}章")
            self.log(f"文件保存在：{output_file}")
            
            # 添加到书库
            book_info = {
                "name": name,
                "author": author_name,
                "description": description,
                "save_path": save_path
            }
            add_to_library(book_id, book_info, output_file)
            self.log("已添加到书库")
            
            failed_count = total_chapters - success_count
            if failed_count > 0:
                self.log(f"\n⚠️  มี {failed_count} ตอนที่โหลดไม่สำเร็จ")
                self.log(f"   คุณสามารถใช้ปุ่ม '修复缺失章节' เพื่อโหลดตอนที่ขาดได้")
                messagebox.showwarning(
                    "下载不完整",
                    f"小说《{name}》下载完成，但有 {failed_count} 章下载失败。\n"
                    f"文件保存在：{output_file}\n\n"
                    f"请使用【修复缺失章节】功能补全缺失内容。"
                )
            else:
                messagebox.showinfo("完成", f"小说《{name}》下载完成！\n保存路径：{output_file}")

        except Exception as e:
            self.log(f"\n错误：{str(e)}")
            self.update_progress(0, f"下载失败: {str(e)}")
            messagebox.showerror("错误", f"下载失败: {str(e)}")

        finally:
            self.download_button.configure(state="normal")
            self.is_downloading = False

    def open_repair_dialog(self):
        """Open dialog to repair/patch missing chapters in an existing novel file."""
        if self.is_downloading:
            messagebox.showwarning("提示", "下载正在进行中，请等待完成后再修复")
            return
        RepairDialog(self)

    def open_library(self):
        """打开书库窗口"""
        try:
            # 获取当前窗口几何信息
            current_geometry = self.geometry()
            library_window = LibraryWindow(self, geometry=current_geometry)
            library_window.focus()
        except Exception as e:
            messagebox.showerror("错误", f"无法打开书库: {str(e)}")
    
    def open_settings(self):
        """打开设置窗口"""
        # 创建设置窗口
        settings_window = SettingsWindow(self)
        settings_window.focus()
    
    def clear_log(self):
        """清空日志"""
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
    
    def on_closing(self):
        """窗口关闭处理"""
        if self.is_downloading:
            if messagebox.askyesno("确认", "下载正在进行中，确定要退出吗？"):
                self.destroy()
        else:
            self.destroy()


_REPAIR_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]


def _repair_headers():
    return {
        "User-Agent": random.choice(_REPAIR_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


def _repair_fanqie_chapters(session, book_id):
    endpoints = [
        f"https://api5-normal-lf.fqnovel.com/reading/bookapi/search/{book_id}/v",
        f"https://api5-normal-lf.fqnovel.com/reading/bookapi/detail/v/?book_id={book_id}",
        f"https://api.cengui.cn/api/tomato/book.php?book_id={book_id}",
    ]
    for url in endpoints:
        try:
            r = session.get(url, headers=_repair_headers(), timeout=15)
            data = r.json()
            raw_list = (
                data.get("data", {}).get("chapter_list")
                or data.get("data", {}).get("chapters")
                or data.get("chapters")
                or (data.get("data") if isinstance(data.get("data"), list) else None)
            )
            if raw_list:
                chapters = []
                for idx, item in enumerate(raw_list):
                    cid = str(item.get("chapter_id") or item.get("id") or item.get("item_id", ""))
                    raw_title = item.get("chapter_title") or item.get("title") or f"第{idx+1}章"
                    if re.match(r"^(番外|特别篇|if线)\s*", raw_title):
                        title = raw_title
                    else:
                        clean = re.sub(r"^第[一二三四五六七八九十百千\d]+章\s*", "", raw_title).strip()
                        title = f"第{idx+1}章 {clean}" if clean else raw_title
                    if cid:
                        chapters.append({"index": idx, "id": cid, "title": title})
                if chapters:
                    return chapters
        except Exception:
            continue
    return []


def _repair_clean_content(raw, title=""):
    c = re.sub(r"<header>.*?</header>", "", raw, flags=re.DOTALL)
    c = re.sub(r"<footer>.*?</footer>", "", c, flags=re.DOTALL)
    c = re.sub(r"</?article>", "", c)
    c = re.sub(r'<p idx="\d+">', "\n", c)
    c = re.sub(r"</p>", "\n", c)
    c = re.sub(r"<[^>]+>", "", c)
    if title and c.startswith(title):
        c = c[len(title):].lstrip()
    c = re.sub(r"\n{2,}", "\n", c).strip()
    return "\n".join("    " + ln if ln.strip() else ln for ln in c.split("\n"))


def _repair_download_chapter(session, chapter, max_retries=5):
    for attempt in range(max_retries):
        try:
            url = f"https://api.cengui.cn/api/tomato/content.php?item_id={chapter['id']}"
            r = session.get(url, headers=_repair_headers(), timeout=15)
            data = r.json()
            if data.get("code") == 200:
                content = data.get("data", {}).get("content", "")
                api_title = data.get("data", {}).get("title", "")
                return chapter["index"], chapter["title"], _repair_clean_content(content, api_title)
        except Exception:
            pass
        time.sleep(1.5 * (attempt + 1))
    return chapter["index"], chapter["title"], ""


def _repair_parse_file(filepath):
    with open(filepath, encoding="utf-8") as f:
        text = f.read()
    lines = text.split("\n")
    header = "\n".join(lines[:2])
    blocks = re.split(r"─{30,}", text)
    chapters = {}
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        bl = block.split("\n")
        first_line = bl[0].strip() if bl else ""
        m = re.match(r"^第(\d+)章", first_line)
        if m:
            idx = int(m.group(1))
            content = "\n".join(bl[2:]).strip() if len(bl) > 2 else ""
            chapters[idx] = (first_line, content)
    return header, chapters


SEPARATOR = "─" * 40


class RepairDialog(ctk.CTkToplevel):
    """Dialog to patch/repair missing chapters in an existing novel .txt file."""

    def __init__(self, master):
        super().__init__(master)
        self.title("修复缺失章节")
        self.geometry("520x400")
        self.resizable(False, False)
        self.grab_set()
        self._running = False
        self._setup_ui()

    def _setup_ui(self):
        self.grid_columnconfigure(0, weight=1)

        info = ctk.CTkLabel(
            self,
            text="选择已下载的小说 .txt 文件并输入 Book ID，即可自动补全缺失章节。",
            wraplength=480,
            justify="left",
        )
        info.grid(row=0, column=0, padx=20, pady=(18, 6), sticky="w")

        # File picker
        file_frame = ctk.CTkFrame(self, fg_color="transparent")
        file_frame.grid(row=1, column=0, padx=20, pady=4, sticky="ew")
        file_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(file_frame, text="小说文件:").grid(row=0, column=0, sticky="w")
        self._file_var = tk.StringVar()
        file_entry = ctk.CTkEntry(file_frame, textvariable=self._file_var, placeholder_text="选择 .txt 文件")
        file_entry.grid(row=1, column=0, padx=(0, 8), sticky="ew")
        ctk.CTkButton(file_frame, text="浏览", width=70, command=self._browse_file).grid(row=1, column=1)

        # Book ID
        id_frame = ctk.CTkFrame(self, fg_color="transparent")
        id_frame.grid(row=2, column=0, padx=20, pady=4, sticky="ew")
        id_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(id_frame, text="Book ID (番茄小说编号):").grid(row=0, column=0, sticky="w")
        self._bookid_var = tk.StringVar()
        ctk.CTkEntry(id_frame, textvariable=self._bookid_var, placeholder_text="例: 7115595052725832716").grid(
            row=1, column=0, sticky="ew"
        )

        # Workers
        wk_frame = ctk.CTkFrame(self, fg_color="transparent")
        wk_frame.grid(row=3, column=0, padx=20, pady=4, sticky="ew")
        ctk.CTkLabel(wk_frame, text="并发数:").pack(side="left", padx=(0, 8))
        self._workers_var = tk.IntVar(value=10)
        ctk.CTkEntry(wk_frame, textvariable=self._workers_var, width=60).pack(side="left")

        # Progress
        self._progress = ctk.CTkProgressBar(self)
        self._progress.grid(row=4, column=0, padx=20, pady=(12, 0), sticky="ew")
        self._progress.set(0)
        self._status_label = ctk.CTkLabel(self, text="", anchor="w")
        self._status_label.grid(row=5, column=0, padx=20, pady=(2, 8), sticky="ew")

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=6, column=0, padx=20, pady=(0, 18), sticky="ew")
        self._run_btn = ctk.CTkButton(btn_frame, text="开始修复", command=self._start, fg_color="#d97706", hover_color="#b45309")
        self._run_btn.pack(side="left", padx=(0, 10))
        ctk.CTkButton(btn_frame, text="关闭", command=self.destroy, fg_color="gray40", hover_color="gray30").pack(side="left")

    def _browse_file(self):
        path = filedialog.askopenfilename(
            title="选择小说文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if path:
            self._file_var.set(path)

    def _set_status(self, text, progress=None):
        self._status_label.configure(text=text)
        if progress is not None:
            self._progress.set(progress)
        self.update_idletasks()

    def _start(self):
        filepath = self._file_var.get().strip()
        book_id = self._bookid_var.get().strip()
        if not filepath or not os.path.exists(filepath):
            messagebox.showerror("错误", "请选择有效的小说文件", parent=self)
            return
        if not book_id:
            messagebox.showerror("错误", "请输入 Book ID", parent=self)
            return
        if self._running:
            return
        self._running = True
        self._run_btn.configure(state="disabled")
        threading.Thread(target=self._run, args=(filepath, book_id), daemon=True).start()

    def _run(self, filepath, book_id):
        try:
            self._set_status("读取文件中...", 0)
            header, existing = _repair_parse_file(filepath)
            self._set_status(f"文件中已有 {len(existing)} 章，正在获取章节列表...")

            session = requests.Session()
            session.headers.update({"Accept-Language": "zh-CN,zh;q=0.9"})
            all_chapters = _repair_fanqie_chapters(session, book_id)
            total = len(all_chapters)
            if not all_chapters:
                self.after(0, lambda: messagebox.showerror("错误", "无法从 API 获取章节列表，请检查 Book ID", parent=self))
                return

            chapter_by_index = {ch["index"] + 1: ch for ch in all_chapters}
            missing = [i for i in range(1, total + 1)
                       if i not in existing or not existing[i][1].strip()]

            if not missing:
                self._set_status(f"✅ 文件已完整，共 {total} 章，无需修复", 1.0)
                self.after(0, lambda: messagebox.showinfo("完成", "文件已完整，无缺失章节！", parent=self))
                return

            self._set_status(f"发现 {len(missing)} 个缺失章节，开始下载...", 0)
            to_download = [chapter_by_index[i] for i in missing if i in chapter_by_index]
            new_chapters = {}
            workers = max(1, min(self._workers_var.get(), 20))
            done_count = 0

            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(_repair_download_chapter, session, ch): ch for ch in to_download}
                for f in as_completed(futs):
                    idx_0, title, content = f.result()
                    new_chapters[idx_0 + 1] = (title, content)
                    done_count += 1
                    pct = done_count / len(to_download)
                    self._set_status(f"下载中: {done_count}/{len(to_download)} — {title[:20]}", pct)

            merged = dict(existing)
            merged.update(new_chapters)

            base, ext = os.path.splitext(filepath)
            out_path = base + "_patched" + ext
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(header + "\n\n")
                for i in range(1, total + 1):
                    if i not in merged:
                        continue
                    title, content = merged[i]
                    f.write(f"{title}\n\n{content}\n\n{SEPARATOR}\n\n")

            still_missing = [i for i in range(1, total + 1)
                             if i not in merged or not merged[i][1].strip()]
            self._set_status(f"✅ 完成！修复了 {len(new_chapters)} 章，已保存: {os.path.basename(out_path)}", 1.0)

            msg = (
                f"修复完成！\n"
                f"补全章节: {len(new_chapters)}\n"
                f"仍缺失: {len(still_missing)}\n"
                f"文件: {out_path}"
            )
            self.after(0, lambda: messagebox.showinfo("修复完成", msg, parent=self))

        except Exception as e:
            self.after(0, lambda: messagebox.showerror("错误", f"修复失败: {e}", parent=self))
            self._set_status(f"错误: {e}", 0)
        finally:
            self._running = False
            self.after(0, lambda: self._run_btn.configure(state="normal"))


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("设置")
        self.geometry("500x400")
        
        # 加载当前配置
        self.config = CONFIG.copy()
        
        # 设置UI
        self.setup_ui()
        
        # 使窗口模态
        self.transient(master)
        self.grab_set()
        
        # 绑定关闭事件
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def setup_ui(self):
        """设置UI"""
        # 创建选项卡
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=20)
        
        # 添加选项卡
        self.tabview.add("下载设置")
        self.tabview.add("阅读器设置")
        self.tabview.add("文件设置")
        
        # 下载设置选项卡
        download_tab = self.tabview.tab("下载设置")
        download_tab.grid_columnconfigure(1, weight=1)
        
        # 线程数设置
        ctk.CTkLabel(download_tab, text="下载线程数:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.max_workers_var = ctk.StringVar(value=str(self.config["request"].get("max_workers", 5)))
        max_workers_entry = ctk.CTkEntry(download_tab, textvariable=self.max_workers_var, width=100)
        max_workers_entry.grid(row=0, column=1, padx=10, pady=10, sticky="w")
        
        # 重试次数设置
        ctk.CTkLabel(download_tab, text="重试次数:").grid(row=1, column=0, padx=10, pady=10, sticky="w")
        self.max_retries_var = ctk.StringVar(value=str(self.config["request"].get("max_retries", 3)))
        max_retries_entry = ctk.CTkEntry(download_tab, textvariable=self.max_retries_var, width=100)
        max_retries_entry.grid(row=1, column=1, padx=10, pady=10, sticky="w")
        
        # 请求超时设置
        ctk.CTkLabel(download_tab, text="请求超时(秒):").grid(row=2, column=0, padx=10, pady=10, sticky="w")
        self.request_timeout_var = ctk.StringVar(value=str(self.config["request"].get("request_timeout", 15)))
        request_timeout_entry = ctk.CTkEntry(download_tab, textvariable=self.request_timeout_var, width=100)
        request_timeout_entry.grid(row=2, column=1, padx=10, pady=10, sticky="w")
        
        # 阅读器设置选项卡
        reader_tab = self.tabview.tab("阅读器设置")
        reader_tab.grid_columnconfigure(1, weight=1)
        
        # 默认字体设置
        ctk.CTkLabel(reader_tab, text="默认字体:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.default_font_var = ctk.StringVar(value=self.config["reader"].get("default_font", "Arial"))
        default_font_entry = ctk.CTkEntry(reader_tab, textvariable=self.default_font_var, width=150)
        default_font_entry.grid(row=0, column=1, padx=10, pady=10, sticky="w")
        
        # 默认字体大小设置
        ctk.CTkLabel(reader_tab, text="默认字体大小:").grid(row=1, column=0, padx=10, pady=10, sticky="w")
        self.default_size_var = ctk.StringVar(value=str(self.config["reader"].get("default_size", 12)))
        default_size_entry = ctk.CTkEntry(reader_tab, textvariable=self.default_size_var, width=100)
        default_size_entry.grid(row=1, column=1, padx=10, pady=10, sticky="w")
        
        # 暗色模式设置
        ctk.CTkLabel(reader_tab, text="默认使用暗色模式:").grid(row=2, column=0, padx=10, pady=10, sticky="w")
        self.dark_mode_var = ctk.BooleanVar(value=self.config["reader"].get("dark_mode", True))
        dark_mode_switch = ctk.CTkSwitch(reader_tab, text="", variable=self.dark_mode_var)
        dark_mode_switch.grid(row=2, column=1, padx=10, pady=10, sticky="w")
        
        # 文件设置选项卡
        file_tab = self.tabview.tab("文件设置")
        file_tab.grid_columnconfigure(1, weight=1)

        # 默认保存路径设置
        ctk.CTkLabel(file_tab, text="默认保存路径:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.default_save_path_var = ctk.StringVar(value=self.config["file"].get("default_save_path", "downloads"))
        default_save_path_entry = ctk.CTkEntry(file_tab, textvariable=self.default_save_path_var, width=250)
        default_save_path_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")

        # 浏览按钮
        browse_button = ctk.CTkButton(file_tab, text="浏览", command=self.browse_save_path, width=80)
        browse_button.grid(row=0, column=2, padx=10, pady=10)

        # 清除 Cookie 按钮
        clear_cookie_button = ctk.CTkButton(file_tab, text="清除 Cookie", command=self.clear_cookie_file, width=120, fg_color="red", hover_color="#C40000")
        clear_cookie_button.grid(row=1, column=0, columnspan=3, padx=10, pady=(20, 10), sticky="w")


        # --- 添加阅读器颜色设置 ---
        # 默认文字颜色
        ctk.CTkLabel(reader_tab, text="默认文字颜色:").grid(row=3, column=0, padx=10, pady=10, sticky="w")
        self.default_fg_var = ctk.StringVar(value=self.config["reader"].get("default_fg", "#000000"))
        fg_color_entry = ctk.CTkEntry(reader_tab, textvariable=self.default_fg_var, width=100)
        fg_color_entry.grid(row=3, column=1, padx=10, pady=10, sticky="w")
        fg_color_button = ctk.CTkButton(reader_tab, text="选择", command=self.choose_fg_color, width=60)
        fg_color_button.grid(row=3, column=2, padx=5, pady=10)

        # 默认背景颜色
        ctk.CTkLabel(reader_tab, text="默认背景颜色:").grid(row=4, column=0, padx=10, pady=10, sticky="w")
        self.default_bg_var = ctk.StringVar(value=self.config["reader"].get("default_bg", "#FFFFFF"))
        bg_color_entry = ctk.CTkEntry(reader_tab, textvariable=self.default_bg_var, width=100)
        bg_color_entry.grid(row=4, column=1, padx=10, pady=10, sticky="w")
        bg_color_button = ctk.CTkButton(reader_tab, text="选择", command=self.choose_bg_color, width=60)
        bg_color_button.grid(row=4, column=2, padx=5, pady=10)
        # --- 结束添加阅读器颜色设置 ---

        # 底部按钮
        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.pack(fill="x", padx=20, pady=(0, 20))
        
        # 保存按钮
        save_button = ctk.CTkButton(button_frame, text="保存设置", command=self.save_settings, width=120)
        save_button.pack(side="right", padx=10)
        
        # 取消按钮
        cancel_button = ctk.CTkButton(button_frame, text="取消", command=self.on_closing, width=120)
        cancel_button.pack(side="right", padx=10)
    
    def browse_save_path(self):
        """浏览保存路径"""
        folder_path = filedialog.askdirectory(title="选择默认保存位置")
        if folder_path:
            self.default_save_path_var.set(folder_path)

    def clear_cookie_file(self):
        """清除 Cookie 文件"""
        cookie_path = CONFIG["file"]["cookie_file"]
        if os.path.exists(cookie_path):
            if messagebox.askyesno("确认", f"确定要清除 Cookie 文件 ({cookie_path}) 吗？\n这将需要重新生成 Cookie。", parent=self):
                try:
                    os.remove(cookie_path)
                    messagebox.showinfo("成功", "Cookie 文件已清除。", parent=self)
                except Exception as e:
                    messagebox.showerror("错误", f"清除 Cookie 文件失败: {str(e)}", parent=self)
        else:
            messagebox.showinfo("提示", "Cookie 文件不存在。", parent=self)

    def choose_fg_color(self):
        """选择默认文字颜色"""
        from tkinter import colorchooser
        color = colorchooser.askcolor(title="选择默认文字颜色", initialcolor=self.default_fg_var.get())[1]
        if color:
            self.default_fg_var.set(color)

    def choose_bg_color(self):
        """选择默认背景颜色"""
        from tkinter import colorchooser
        color = colorchooser.askcolor(title="选择默认背景颜色", initialcolor=self.default_bg_var.get())[1]
        if color:
            self.default_bg_var.set(color)

    def save_settings(self):
        """保存设置"""
        try:
            # 更新下载设置
            self.config["request"]["max_workers"] = int(self.max_workers_var.get())
            self.config["request"]["max_retries"] = int(self.max_retries_var.get())
            self.config["request"]["request_timeout"] = int(self.request_timeout_var.get())

            # 更新阅读器设置
            self.config["reader"]["default_font"] = self.default_font_var.get()
            self.config["reader"]["default_size"] = int(self.default_size_var.get())
            self.config["reader"]["dark_mode"] = self.dark_mode_var.get()
            self.config["reader"]["default_fg"] = self.default_fg_var.get() # 保存文字颜色
            self.config["reader"]["default_bg"] = self.default_bg_var.get() # 保存背景颜色

            # 更新文件设置
            self.config["file"]["default_save_path"] = self.default_save_path_var.get()

            # 保存配置
            save_user_config(self.config)

            messagebox.showinfo("成功", "设置已保存")
            self.destroy()
        except ValueError as e:
            messagebox.showerror("错误", f"输入值无效: {str(e)}")
        except Exception as e:
            messagebox.showerror("错误", f"保存设置失败: {str(e)}")

    def on_closing(self):
        """关闭窗口"""
        self.destroy()


if __name__ == "__main__":
    # 检查是否已安装 customtkinter
    try:
        import customtkinter
    except ImportError:
        print("未安装 customtkinter 模块，将使用传统 tkinter 界面")
        from tkinter import Tk
        root = Tk()
        root.withdraw()
        messagebox.showerror("错误", "未安装 customtkinter 模块，请安装后再运行程序")
        sys.exit(1)
# 解决打包后的资源路径问题
def resource_path(relative_path):
    """获取打包后的资源绝对路径"""
    try:
        # PyInstaller创建临时文件夹存储资源
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# 导入并显示启动画面
try:
    from splash import SplashScreen # 导入 SplashScreen 类

    # 1. 创建主应用实例
    app = NovelDownloaderGUI()
    # 2. 隐藏主应用窗口
    app.withdraw()

    # 3. 创建并显示启动画面，主应用实例作为父窗口
    # SplashScreen 内部会使用 after 调用 app.deiconify() 来显示主窗口
    # 使用 resource_path 获取 logo 路径
    logo_path = resource_path("assets/app_icon.png")
    splash = SplashScreen(app, logo_path=logo_path, duration=2.0)
    # splash.mainloop() # 不需要单独的 mainloop for splash

    # 4. 启动主应用的 mainloop
    app.mainloop()

except ImportError:
    print("无法导入 splash 模块，跳过启动画面。")
    # 如果无法导入启动画面，直接启动主应用
    app = NovelDownloaderGUI()
    app.mainloop()
except Exception as e:
    print(f"显示启动画面时出错: {e}")
    # 即使启动画面出错，也尝试启动主应用
    app = NovelDownloaderGUI()
    app.mainloop()