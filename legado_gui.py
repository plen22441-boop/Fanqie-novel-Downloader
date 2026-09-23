"""
Legado (阅读) 书源管理与搜索下载界面
"""

import tkinter as tk
from tkinter import messagebox, filedialog
import customtkinter as ctk
import threading
import os
import json
from collections import OrderedDict

from config import CONFIG
from legado_source import (
    LegadoEngine, import_sources_from_json, import_sources_from_url
)
from library import add_to_library


class LegadoManagerWindow(ctk.CTkToplevel):
    """Legado 书源管理 + 搜索下载窗口"""

    def __init__(self, master, geometry=None):
        super().__init__(master)
        self.title("Legado 书源 - 多站搜索下载")
        self.geometry(geometry or "900x700")
        self.minsize(800, 600)

        self.engine = LegadoEngine()
        self.search_results = []
        self.is_downloading = False
        self.selected_result = None

        self.setup_ui()
        self.update_source_count()

        self.transient(master)
        self.grab_set()

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # --- 顶部: 书源管理 ---
        source_frame = ctk.CTkFrame(self)
        source_frame.grid(row=0, column=0, padx=15, pady=(15, 5), sticky="ew")
        source_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(source_frame, text="书源管理", font=("", 14, "bold")).grid(
            row=0, column=0, padx=10, pady=8, sticky="w"
        )

        self.source_count_label = ctk.CTkLabel(source_frame, text="已加载: 0 个书源")
        self.source_count_label.grid(row=0, column=1, padx=10, pady=8, sticky="w")

        btn_frame = ctk.CTkFrame(source_frame, fg_color="transparent")
        btn_frame.grid(row=0, column=2, padx=5, pady=8)

        ctk.CTkButton(btn_frame, text="网络导入", width=90,
                       command=self.import_from_url).pack(side="left", padx=3)
        ctk.CTkButton(btn_frame, text="文件导入", width=90,
                       command=self.import_from_file).pack(side="left", padx=3)
        ctk.CTkButton(btn_frame, text="查看书源", width=90,
                       command=self.view_sources).pack(side="left", padx=3)
        ctk.CTkButton(btn_frame, text="清空书源", width=90,
                       fg_color="#C0392B", hover_color="#E74C3C",
                       command=self.clear_sources).pack(side="left", padx=3)

        # --- 中部: 搜索区域 ---
        search_frame = ctk.CTkFrame(self)
        search_frame.grid(row=1, column=0, padx=15, pady=5, sticky="ew")
        search_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(search_frame, text="搜索小说:").grid(
            row=0, column=0, padx=10, pady=8, sticky="w"
        )

        self.search_entry = ctk.CTkEntry(search_frame, placeholder_text="输入小说名称或关键词")
        self.search_entry.grid(row=0, column=1, padx=5, pady=8, sticky="ew")
        self.search_entry.bind("<Return>", lambda e: self.do_search())

        self.search_btn = ctk.CTkButton(search_frame, text="搜索", width=80,
                                         command=self.do_search)
        self.search_btn.grid(row=0, column=2, padx=5, pady=8)

        # --- 结果区域 ---
        result_frame = ctk.CTkFrame(self)
        result_frame.grid(row=2, column=0, padx=15, pady=5, sticky="nsew")
        result_frame.grid_columnconfigure(0, weight=1)
        result_frame.grid_rowconfigure(0, weight=1)

        self.result_list = ctk.CTkTextbox(result_frame, wrap="word")
        self.result_list.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.result_list.configure(state="disabled")

        # --- 下载区域 ---
        download_frame = ctk.CTkFrame(self)
        download_frame.grid(row=3, column=0, padx=15, pady=5, sticky="ew")
        download_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(download_frame, text="选择序号:").grid(
            row=0, column=0, padx=10, pady=8, sticky="w"
        )

        self.select_entry = ctk.CTkEntry(download_frame, placeholder_text="输入搜索结果序号 (如: 1)", width=120)
        self.select_entry.grid(row=0, column=1, padx=5, pady=8, sticky="w")

        ctk.CTkLabel(download_frame, text="保存路径:").grid(
            row=0, column=2, padx=(15, 5), pady=8, sticky="w"
        )

        self.save_path_entry = ctk.CTkEntry(download_frame, width=200)
        self.save_path_entry.grid(row=0, column=3, padx=5, pady=8, sticky="ew")
        self.save_path_entry.insert(0, CONFIG["file"].get("default_save_path", "downloads"))

        ctk.CTkButton(download_frame, text="浏览", width=60,
                       command=self.browse_save).grid(row=0, column=4, padx=5, pady=8)

        self.download_btn = ctk.CTkButton(download_frame, text="下载小说", width=100,
                                            fg_color="#27AE60", hover_color="#2ECC71",
                                            command=self.do_download)
        self.download_btn.grid(row=0, column=5, padx=5, pady=8)

        # --- 进度区域 ---
        progress_frame = ctk.CTkFrame(self)
        progress_frame.grid(row=4, column=0, padx=15, pady=(5, 15), sticky="ew")
        progress_frame.grid_columnconfigure(0, weight=1)

        self.progress_bar = ctk.CTkProgressBar(progress_frame)
        self.progress_bar.grid(row=0, column=0, padx=10, pady=(8, 4), sticky="ew")
        self.progress_bar.set(0)

        self.status_label = ctk.CTkLabel(progress_frame, text="就绪", anchor="center")
        self.status_label.grid(row=1, column=0, padx=10, pady=(0, 8), sticky="ew")

    def update_source_count(self):
        count = len(self.engine.sources)
        enabled = len(self.engine.get_enabled_sources())
        self.source_count_label.configure(text=f"已加载: {count} 个书源 (启用: {enabled})")

    def log_result(self, text):
        self.result_list.configure(state="normal")
        self.result_list.insert("end", text + "\n")
        self.result_list.see("end")
        self.result_list.configure(state="disabled")
        self.update_idletasks()

    def clear_results(self):
        self.result_list.configure(state="normal")
        self.result_list.delete("1.0", "end")
        self.result_list.configure(state="disabled")

    def update_status(self, text):
        self.status_label.configure(text=text)
        self.update_idletasks()

    def update_progress(self, value):
        self.progress_bar.set(value / 100.0)
        self.update_idletasks()

    # --- 书源管理 ---

    def import_from_url(self):
        dialog = ctk.CTkInputDialog(
            text="输入书源 URL 地址:\n(如: http://dy.miaogongzi.cc/shuyuan)",
            title="网络导入书源"
        )
        url = dialog.get_input()
        if not url or not url.strip():
            return

        self.update_status("正在从网络导入书源...")
        threading.Thread(target=self._do_import_url, args=(url.strip(),), daemon=True).start()

    def _do_import_url(self, url):
        try:
            sources = import_sources_from_url(url)
            if sources:
                added = self.engine.add_sources(sources)
                self.after(0, lambda: self._import_done(len(sources), added))
            else:
                self.after(0, lambda: messagebox.showwarning("提示", "未从该 URL 解析到有效书源", parent=self))
                self.after(0, lambda: self.update_status("导入失败"))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("错误", f"导入失败: {str(e)}", parent=self))
            self.after(0, lambda: self.update_status("导入失败"))

    def import_from_file(self):
        path = filedialog.askopenfilename(
            title="选择书源 JSON 文件",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
            parent=self
        )
        if not path:
            return

        try:
            with open(path, 'r', encoding='utf-8') as f:
                text = f.read()
            sources = import_sources_from_json(text)
            if sources:
                added = self.engine.add_sources(sources)
                self._import_done(len(sources), added)
            else:
                messagebox.showwarning("提示", "文件中未找到有效书源", parent=self)
        except Exception as e:
            messagebox.showerror("错误", f"导入失败: {str(e)}", parent=self)

    def _import_done(self, total, added):
        self.update_source_count()
        self.update_status(f"导入完成: 发现 {total} 个书源，新增 {added} 个")
        messagebox.showinfo("导入完成", f"发现 {total} 个书源\n新增 {added} 个\n重复跳过 {total - added} 个", parent=self)

    def view_sources(self):
        if not self.engine.sources:
            messagebox.showinfo("书源列表", "暂无书源，请先导入", parent=self)
            return
        SourceListWindow(self, self.engine)

    def clear_sources(self):
        if not self.engine.sources:
            return
        if messagebox.askyesno("确认", f"确定要清空全部 {len(self.engine.sources)} 个书源吗？", parent=self):
            self.engine.clear_sources()
            self.update_source_count()
            self.update_status("已清空所有书源")

    # --- 搜索 ---

    def do_search(self):
        keyword = self.search_entry.get().strip()
        if not keyword:
            messagebox.showwarning("提示", "请输入搜索关键词", parent=self)
            return

        if not self.engine.get_enabled_sources():
            messagebox.showwarning("提示", "没有可用的书源，请先导入书源", parent=self)
            return

        self.search_btn.configure(state="disabled")
        self.clear_results()
        self.search_results = []
        self.update_status("正在搜索...")
        self.update_progress(0)

        threading.Thread(target=self._do_search, args=(keyword,), daemon=True).start()

    def _do_search(self, keyword):
        def callback(msg):
            self.after(0, lambda: self.update_status(msg))

        results = self.engine.search_parallel(keyword, max_sources=20, timeout=15, callback=callback)
        self.search_results = results
        self.after(0, lambda: self._show_results(results))

    def _show_results(self, results):
        self.clear_results()
        self.search_btn.configure(state="normal")

        if not results:
            self.log_result("未找到任何结果，请尝试其他关键词或导入更多书源")
            self.update_status("搜索完成 - 无结果")
            return

        seen = set()
        unique_results = []
        for r in results:
            key = (r["name"], r["author"])
            if key not in seen:
                seen.add(key)
                unique_results.append(r)
        self.search_results = unique_results

        self.log_result(f"找到 {len(unique_results)} 个结果:\n")
        self.log_result(f"{'序号':<5} {'书名':<25} {'作者':<15} {'来源':<20}")
        self.log_result("-" * 70)

        for i, r in enumerate(unique_results, 1):
            name = r["name"][:22] + "..." if len(r["name"]) > 25 else r["name"]
            author = r["author"][:12] + "..." if len(r["author"]) > 15 else r["author"]
            source = r["source"][:17] + "..." if len(r["source"]) > 20 else r["source"]
            self.log_result(f"  {i:<4} {name:<25} {author:<15} {source:<20}")
            if r.get("intro"):
                intro = r["intro"][:60] + "..." if len(r["intro"]) > 60 else r["intro"]
                self.log_result(f"       简介: {intro}")
            self.log_result("")

        self.update_status(f"搜索完成 - 找到 {len(unique_results)} 个结果")
        self.update_progress(100)

    # --- 下载 ---

    def browse_save(self):
        folder = filedialog.askdirectory(title="选择保存位置", parent=self)
        if folder:
            self.save_path_entry.delete(0, "end")
            self.save_path_entry.insert(0, folder)

    def do_download(self):
        if self.is_downloading:
            messagebox.showwarning("提示", "正在下载中", parent=self)
            return

        if not self.search_results:
            messagebox.showwarning("提示", "请先搜索小说", parent=self)
            return

        idx_str = self.select_entry.get().strip()
        if not idx_str:
            messagebox.showwarning("提示", "请输入要下载的序号", parent=self)
            return

        try:
            idx = int(idx_str) - 1
            if idx < 0 or idx >= len(self.search_results):
                raise ValueError()
        except ValueError:
            messagebox.showerror("错误", f"无效序号，请输入 1-{len(self.search_results)} 之间的数字", parent=self)
            return

        save_path = self.save_path_entry.get().strip()
        if not save_path:
            save_path = CONFIG["file"].get("default_save_path", "downloads")

        self.selected_result = self.search_results[idx]
        self.is_downloading = True
        self.download_btn.configure(state="disabled")
        self.update_progress(0)

        threading.Thread(
            target=self._do_download,
            args=(self.selected_result, save_path),
            daemon=True
        ).start()

    def _do_download(self, result, save_path):
        def log_cb(msg):
            self.after(0, lambda: self.log_result(msg))

        def progress_cb(value, text):
            self.after(0, lambda: self.update_progress(value))
            self.after(0, lambda: self.update_status(text))

        try:
            self.after(0, lambda: self.clear_results())
            log_cb(f"开始下载: 《{result['name']}》")
            log_cb(f"作者: {result['author']}")
            log_cb(f"来源: {result['source']}")
            log_cb(f"地址: {result['url']}")
            log_cb("")

            contents, chapters = self.engine.download_novel(
                result["source_url"],
                result["url"],
                save_path,
                progress_callback=progress_cb,
                log_callback=log_cb
            )

            output_file = os.path.join(save_path, f"{result['name']}.txt")
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(f"书名: 《{result['name']}》\n")
                f.write(f"作者: {result['author']}\n")
                f.write(f"来源: {result['source']}\n")
                if result.get("intro"):
                    f.write(f"\n简介:\n{result['intro']}\n")
                f.write("\n" + "=" * 50 + "\n\n")

                for idx in sorted(contents.keys()):
                    chapter, content = contents[idx]
                    f.write(f"\n{chapter['title']}\n\n")
                    f.write(content + "\n\n")

            success = len(contents)
            total = len(chapters)

            log_cb(f"\n下载完成! 成功: {success}章, 失败: {total - success}章")
            log_cb(f"文件保存在: {output_file}")

            book_info = {
                "name": result["name"],
                "author": result["author"],
                "description": result.get("intro", ""),
                "save_path": save_path,
                "source": result["source"]
            }
            book_id = f"legado_{result['source_url']}_{result['name']}"
            add_to_library(book_id, book_info, output_file)
            log_cb("已添加到书库")

            self.after(0, lambda: self.update_progress(100))
            self.after(0, lambda: self.update_status("下载完成!"))
            self.after(0, lambda: messagebox.showinfo(
                "完成",
                f"《{result['name']}》下载完成!\n"
                f"共 {success}/{total} 章\n"
                f"保存路径: {output_file}",
                parent=self
            ))

        except Exception as e:
            log_cb(f"\n错误: {str(e)}")
            self.after(0, lambda: self.update_status(f"下载失败: {str(e)}"))
            self.after(0, lambda: messagebox.showerror("错误", f"下载失败: {str(e)}", parent=self))

        finally:
            self.is_downloading = False
            self.after(0, lambda: self.download_btn.configure(state="normal"))


class SourceListWindow(ctk.CTkToplevel):
    """书源列表查看/管理窗口"""

    def __init__(self, master, engine):
        super().__init__(master)
        self.title("书源列表")
        self.geometry("600x500")
        self.engine = engine

        self.setup_ui()
        self.load_list()

        self.transient(master)
        self.grab_set()

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.source_list = ctk.CTkTextbox(self, wrap="word")
        self.source_list.grid(row=0, column=0, padx=15, pady=15, sticky="nsew")

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=1, column=0, padx=15, pady=(0, 15), sticky="ew")

        ctk.CTkButton(btn_frame, text="关闭", command=self.destroy, width=80).pack(side="right", padx=5)
        ctk.CTkButton(btn_frame, text="删除选中", width=100,
                       fg_color="#E74C3C", hover_color="#C0392B",
                       command=self.delete_source).pack(side="right", padx=5)

        self.delete_entry = ctk.CTkEntry(btn_frame, placeholder_text="输入序号删除", width=120)
        self.delete_entry.pack(side="right", padx=5)

    def load_list(self):
        self.source_list.configure(state="normal")
        self.source_list.delete("1.0", "end")

        self.source_list.insert("end", f"共 {len(self.engine.sources)} 个书源:\n\n")
        self.source_list.insert("end", f"{'序号':<5} {'书源名称':<25} {'状态':<8} {'网址'}\n")
        self.source_list.insert("end", "-" * 70 + "\n")

        for i, source in enumerate(self.engine.sources, 1):
            status = "启用" if source.enabled else "禁用"
            name = source.name[:22] + "..." if len(source.name) > 25 else source.name
            self.source_list.insert("end", f"  {i:<4} {name:<25} {status:<8} {source.url}\n")

        self.source_list.configure(state="disabled")

    def delete_source(self):
        idx_str = self.delete_entry.get().strip()
        if not idx_str:
            return
        try:
            idx = int(idx_str) - 1
            if idx < 0 or idx >= len(self.engine.sources):
                raise ValueError()
        except ValueError:
            messagebox.showerror("错误", "无效序号", parent=self)
            return

        source = self.engine.sources[idx]
        if messagebox.askyesno("确认", f"确定删除书源: {source.name}?", parent=self):
            self.engine.remove_source(source.url)
            self.load_list()
            if hasattr(self.master, "update_source_count"):
                self.master.update_source_count()
