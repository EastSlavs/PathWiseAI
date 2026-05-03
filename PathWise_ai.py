import os
import json
import shutil
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from openai import OpenAI

DEFAULT_API_KEY = "sk-your_default_key_here"

APP_DATA_DIR = os.path.abspath(os.path.join(os.getenv('APPDATA'), 'PathWiseAI'))
CONFIG_FILE = os.path.join(APP_DATA_DIR, 'config.json')

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {"custom_api_key": ""}

def save_config(config_data):
    os.makedirs(APP_DATA_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f)

def get_ai_advice(path, active_key):
    if not active_key or active_key.startswith("sk-your_default_key"):
        return "未配置有效的 API Key。"

    try:
        client = OpenAI(api_key=active_key, base_url="https://api.deepseek.com")
        messages = [
            {
                "role": "system",
                "content": "你是Windows系统专家。直接分析提供的路径。\n"
                           "格式：\n"
                           "1.[用途]：简述所属软件或数据类型。\n"
                           "2.[后果]：简明指出删除后的具体影响。\n"
                           "3.[建议]：给出明确指示（可安全删除/存在风险/严禁删除）。\n"
                           "限制：60字以内。绝对禁止任何寒暄与多余解释。"
            },
            {"role": "user", "content": path}
        ]
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            stream=False
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"API 调用失败: {str(e)}"

def format_size(size_bytes):
    if size_bytes >= 1073741824:
        return f"{size_bytes / 1073741824:.2f} GB"
    if size_bytes >= 1048576:
        return f"{size_bytes / 1048576:.2f} MB"
    return f"{size_bytes / 1024:.2f} KB"

def find_cleanup_endpoints(target_directory, threshold_mb=100):
    threshold_bytes = threshold_mb * 1048576
    unallocated_sizes = {}
    endpoints = []

    for root, dirs, files in os.walk(target_directory, topdown=False):
        current_size = 0
        for f in files:
            filepath = os.path.join(root, f)
            try:
                if not os.path.islink(filepath):
                    current_size += os.path.getsize(filepath)
            except OSError:
                pass

        for d in dirs:
            child_path = os.path.join(root, d)
            current_size += unallocated_sizes.get(child_path, 0)

        if current_size >= threshold_bytes:
            endpoints.append({"path": root, "size": current_size})
            unallocated_sizes[root] = 0
        else:
            unallocated_sizes[root] = current_size

    endpoints.sort(key=lambda x: x["size"], reverse=True)
    return endpoints

class DiskAnalyzerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("PathWise AI - 存储分析节点")
        self.root.geometry("900x600")
        self.config = load_config()
        self.ai_cache = {}
        self.setup_ui()

    def get_active_key(self):
        custom_key = self.config.get("custom_api_key", "").strip()
        return custom_key if custom_key else DEFAULT_API_KEY

    def setup_ui(self):
        frame_top = tk.Frame(self.root, padx=10, pady=10)
        frame_top.pack(fill=tk.X)

        tk.Label(frame_top, text="目标目录:").grid(row=0, column=0, sticky=tk.W)
        self.entry_path = tk.Entry(frame_top, width=60)
        self.entry_path.grid(row=0, column=1, padx=5)
        tk.Button(frame_top, text="浏览", command=self.browse_dir).grid(row=0, column=2)

        tk.Label(frame_top, text="节点阈值(MB):").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.entry_threshold = tk.Entry(frame_top, width=10)
        self.entry_threshold.insert(0, "100")
        self.entry_threshold.grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)

        self.btn_scan = tk.Button(frame_top, text="开始扫描", command=self.start_scan, width=15)
        self.btn_scan.grid(row=1, column=2, pady=5)

        self.btn_setting = tk.Button(frame_top, text="设置 API", command=self.open_settings)
        self.btn_setting.grid(row=0, column=3, rowspan=2, padx=15)

        frame_mid = tk.Frame(self.root, padx=10)
        frame_mid.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(frame_mid, columns=("size", "path"), show="headings")
        self.tree.heading("size", text="占用空间")
        self.tree.heading("path", text="目录路径")
        self.tree.column("size", width=100, anchor=tk.E)
        self.tree.column("path", width=750, anchor=tk.W)

        scrollbar = ttk.Scrollbar(frame_mid, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        frame_bottom = tk.Frame(self.root, padx=10, pady=10)
        frame_bottom.pack(fill=tk.X)

        self.lbl_status = tk.Label(frame_bottom, text="就绪", fg="gray")
        self.lbl_status.pack(side=tk.LEFT)

        self.btn_del = tk.Button(frame_bottom, text="删除", command=self.delete_selected, width=8)
        self.btn_del.pack(side=tk.RIGHT, padx=2)

        self.btn_ai = tk.Button(frame_bottom, text="AI 分析", command=self.analyze_selected, width=8)
        self.btn_ai.pack(side=tk.RIGHT, padx=2)

        self.btn_rescan = tk.Button(frame_bottom, text="深度扫描", command=self.rescan_selected, width=10)
        self.btn_rescan.pack(side=tk.RIGHT, padx=2)

        self.btn_open = tk.Button(frame_bottom, text="打开", command=self.open_in_explorer, width=8)
        self.btn_open.pack(side=tk.RIGHT, padx=2)

        self.btn_copy = tk.Button(frame_bottom, text="复制", command=self.copy_path, width=8)
        self.btn_copy.pack(side=tk.RIGHT, padx=2)

        self.buttons = [self.btn_scan, self.btn_setting, self.btn_del, self.btn_ai, self.btn_rescan, self.btn_open, self.btn_copy]

    def open_settings(self):
        current_key = self.config.get("custom_api_key", "")
        new_key = simpledialog.askstring(
            "设置",
            "请输入自定义 API Key:\n(留空使用默认)",
            initialvalue=current_key
        )
        if new_key is not None:
            self.config["custom_api_key"] = new_key.strip()
            save_config(self.config)
            self.lbl_status.config(text="配置已保存", fg="green")

    def browse_dir(self):
        path = filedialog.askdirectory()
        if path:
            self.entry_path.delete(0, tk.END)
            self.entry_path.insert(0, os.path.normpath(path))

    def start_scan(self):
        target_dir = self.entry_path.get().strip()
        if not os.path.exists(target_dir):
            messagebox.showwarning("提示", "路径无效")
            return

        try:
            threshold = int(self.entry_threshold.get().strip())
        except ValueError:
            messagebox.showwarning("提示", "阈值错误")
            return

        self._toggle_buttons(tk.DISABLED)
        self.lbl_status.config(text="扫描中...", fg="blue")
        for item in self.tree.get_children():
            self.tree.delete(item)

        thread = threading.Thread(target=self._scan_process, args=(target_dir, threshold))
        thread.daemon = True
        thread.start()

    def _scan_process(self, target_dir, threshold):
        results = find_cleanup_endpoints(target_dir, threshold)
        self.root.after(0, self._update_treeview, results)

    def _update_treeview(self, results):
        for item in results:
            self.tree.insert("", tk.END, values=(format_size(item['size']), item['path']))
        self.lbl_status.config(text=f"完成，提取 {len(results)} 个节点", fg="green")
        self._toggle_buttons(tk.NORMAL)

    def _toggle_buttons(self, state):
        for btn in self.buttons:
            btn.config(state=state)

    def rescan_selected(self):
        selected = self.tree.selection()
        if not selected: return
        path = self.tree.item(selected[0])['values'][1]
        self.entry_path.delete(0, tk.END)
        self.entry_path.insert(0, path)
        self.start_scan()

    def open_in_explorer(self):
        selected = self.tree.selection()
        if not selected: return
        path = self.tree.item(selected[0])['values'][1]
        if os.path.exists(path):
            os.startfile(path)

    def copy_path(self):
        selected = self.tree.selection()
        if not selected: return
        path = self.tree.item(selected[0])['values'][1]
        self.root.clipboard_clear()
        self.root.clipboard_append(path)
        self.lbl_status.config(text="已复制", fg="green")

    def analyze_selected(self):
        selected = self.tree.selection()
        if not selected: return
        path = self.tree.item(selected[0])['values'][1]

        if path in self.ai_cache:
            messagebox.showinfo("分析结果", self.ai_cache[path])
            return

        active_key = self.get_active_key()

        self._toggle_buttons(tk.DISABLED)
        self.lbl_status.config(text="请求中...", fg="blue")

        thread = threading.Thread(target=self._ai_process, args=(path, active_key))
        thread.daemon = True
        thread.start()

    def _ai_process(self, path, key):
        result = get_ai_advice(path, key)
        if "失败" not in result and "未配置" not in result:
            self.ai_cache[path] = result
        self.root.after(0, self._show_ai_result, result)

    def _show_ai_result(self, result):
        self.lbl_status.config(text="就绪", fg="gray")
        self._toggle_buttons(tk.NORMAL)
        messagebox.showinfo("分析结果", result)

    def delete_selected(self):
        selected = self.tree.selection()
        if not selected: return
        path = self.tree.item(selected[0])['values'][1]

        if not messagebox.askyesno("确认", f"永久删除此目录？\n\n{path}"):
            return

        self._toggle_buttons(tk.DISABLED)
        self.lbl_status.config(text="清理中...", fg="red")

        thread = threading.Thread(target=self._delete_process, args=(path, selected[0]))
        thread.daemon = True
        thread.start()

    def _delete_process(self, path, item_id):
        shutil.rmtree(path, ignore_errors=True)
        success = not os.path.exists(path)
        msg = "已清理" if success else "部分文件锁定，已跳过"
        self.root.after(0, self._delete_done, item_id, msg, success)

    def _delete_done(self, item_id, msg, success):
        self._toggle_buttons(tk.NORMAL)
        self.lbl_status.config(text=msg, fg="green" if success else "orange")
        if success:
            self.tree.delete(item_id)

if __name__ == "__main__":
    root = tk.Tk()
    app = DiskAnalyzerGUI(root)
    root.mainloop()