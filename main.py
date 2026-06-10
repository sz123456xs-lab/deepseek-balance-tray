"""
DeepSeek 余额查询 - Windows 工具栏 (DeskBand 风格)
通过 ctypes 调用 Win32 API 嵌入任务栏
效果和视频中一样：任务栏上直接显示"余额 xx.xx"
"""
import os
import sys
import json
import time
import threading
import atexit
import socket
import ctypes
import ctypes.wintypes

import requests
import tkinter as tk
from tkinter import messagebox

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ── 单实例锁 ──
LOCK_PORT = 29002
_lock_sock = None
def _cleanup():
    global _lock_sock
    if _lock_sock:
        try: _lock_sock.close()
        except: pass
def acquire_lock() -> bool:
    global _lock_sock
    try:
        _lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _lock_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _lock_sock.bind(("127.0.0.1", LOCK_PORT))
        _lock_sock.listen(1)
        atexit.register(_cleanup)
        return True
    except: return False

# ── 配置 ──
CONFIG_DIR = os.path.expanduser("~/.deepseek_tray")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
def load_config():
    if not os.path.exists(CONFIG_FILE): return {"api_key": ""}
    try:
        with open(CONFIG_FILE, "r") as f: return json.load(f)
    except: return {"api_key": ""}
def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f: json.dump(cfg, f, ensure_ascii=False, indent=2)

# ── DeepSeek API ──
class DeepSeekAPI:
    BASE = "https://api.deepseek.com"
    def __init__(self, api_key: str):
        self.sess = requests.Session()
        self.sess.headers.update({"Accept":"application/json","Authorization":f"Bearer {api_key}"})
    def get_balance(self):
        try:
            r = self.sess.get(f"{self.BASE}/user/balance", timeout=10)
            if r.status_code == 200:
                d = r.json()
                infos = d.get("balance_infos",[])
                if infos:
                    i = infos[0]
                    return {"ok":True,"total":float(i.get("total_balance",0)),"granted":float(i.get("granted_balance",0)),"topped_up":float(i.get("topped_up_balance",0)),"currency":i.get("currency","CNY")}
                return {"ok":False,"err":"无余额信息"}
            elif r.status_code == 401: return {"ok":False,"err":"API Key 无效"}
            else: return {"ok":False,"err":f"HTTP {r.status_code}"}
        except requests.Timeout: return {"ok":False,"err":"请求超时"}
        except requests.ConnectionError: return {"ok":False,"err":"无法连接"}
        except Exception as e: return {"ok":False,"err":str(e)}

# ── Win32 API ──
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# 查找任务栏窗口
def find_taskbar():
    """返回任务栏窗口句柄和矩形"""
    hwnd = user32.FindWindowW("Shell_TrayWnd", None)
    if not hwnd:
        hwnd = user32.FindWindowW("ReBarWindow32", None)
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return hwnd, rect

def find_tray_notify():
    """返回通知区域窗口"""
    # 尝试查找 DeskBand 宿主
    hwnd = user32.FindWindowExW(0, 0, "WorkerW", None)
    if hwnd:
        hwnd2 = user32.FindWindowExW(hwnd, 0, "ReBarWindow32", None)
        if hwnd2:
            return hwnd2
    return None

# ── 悬浮窗应用 ──
class BalanceOverlay:
    """一个始终置顶、吸附在任务栏上方的小窗口"""
    WIDTH = 200
    HEIGHT = 32
    
    def __init__(self):
        self.cfg = load_config()
        self.api_key = self.cfg.get("api_key", "")
        self.api = DeepSeekAPI(self.api_key) if self.api_key else None
        self.balance = None
        self.last_display = ""
        
        # 创建主窗口
        self.root = tk.Tk()
        self.root.title("")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#202020")
        self.root.geometry(f"{self.WIDTH}x{self.HEIGHT}")
        
        # 窗口内容
        self.frame = tk.Frame(self.root, bg="#202020", cursor="hand2")
        self.frame.pack(fill=tk.BOTH, expand=True)
        
        # 状态圆点
        self.dot = tk.Canvas(self.frame, width=10, height=10, bg="#202020",
                             highlightthickness=0, cursor="hand2")
        self.dot.pack(side=tk.LEFT, padx=(6, 2), pady=11)
        self.dot_id = self.dot.create_oval(1, 1, 9, 9, fill="#FACC15", outline="")
        
        # 余额文字
        self.display_text = tk.StringVar(value="加载中...")
        self.label = tk.Label(self.frame, textvariable=self.display_text,
                              bg="#202020", fg="#F0F0F0",
                              font=("Segoe UI", 10), anchor=tk.W, cursor="hand2")
        self.label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))
        
        # 关闭 ×
        self.close_btn = tk.Label(self.frame, text="×", bg="#202020", fg="#666666",
                                  font=("Segoe UI", 11), cursor="hand2")
        self.close_btn.pack(side=tk.RIGHT, padx=(0, 6))
        self.close_btn.bind("<Button-1>", lambda e: self.quit())
        self.close_btn.bind("<Enter>", lambda e: self.close_btn.configure(fg="white"))
        self.close_btn.bind("<Leave>", lambda e: self.close_btn.configure(fg="#666666"))
        
        # 事件绑定
        for w in [self.frame, self.label, self.dot]:
            w.bind("<Button-1>", self._start_move)
            w.bind("<B1-Motion>", self._on_move)
            w.bind("<Button-3>", self._show_menu)
            w.bind("<Double-Button-1>", lambda e: self._show_detail())
        self.root.bind("<Button-3>", self._show_menu)
        
        # 定位
        self._position()
        
        # 自动刷新
        self._alive = True
        self._schedule_refresh()
    
    def _position(self):
        """定位到任务栏上方右下角"""
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        _, tb = find_taskbar()
        # 放在右下角通知区域旁
        x = sw - self.WIDTH - 10
        y = sh - self.HEIGHT - 45  # 任务栏上方约 5px
        self.root.geometry(f"+{x}+{y}")
    
    def _start_move(self, event):
        self._drag_x, self._drag_y = event.x, event.y
    
    def _on_move(self, event):
        x = self.root.winfo_x() + event.x - self._drag_x
        y = self.root.winfo_y() + event.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")
    
    def _show_menu(self, event=None):
        menu = tk.Menu(self.root, tearoff=0, bg="#2d2d2d", fg="#e0e0e0",
                       activebackground="#4F6EF7", activeforeground="white",
                       font=("Segoe UI", 10))
        menu.add_command(label="📊 余额详情", command=self._show_detail)
        menu.add_separator()
        menu.add_command(label="🔄 刷新", command=self.refresh)
        menu.add_command(label="⚙ 设置 API Key", command=self._show_settings)
        menu.add_separator()
        menu.add_command(label="❌ 退出", command=self.quit)
        try:
            menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            menu.grab_release()
    
    def refresh(self):
        if not self.api:
            self.balance = {"ok": False, "err": "未设置 API Key"}
        else:
            self.balance = self.api.get_balance()
        self._update()
    
    def _update(self):
        bal = self.balance
        if bal is None:
            self.dot.itemconfig(self.dot_id, fill="#FACC15")
            self.display_text.set("查询中...")
        elif not bal.get("ok"):
            self.dot.itemconfig(self.dot_id, fill="#F87171")
            self.display_text.set(bal.get("err", "错误")[:12])
        else:
            self.dot.itemconfig(self.dot_id, fill="#10B981")
            cur = bal.get("currency", "CNY")
            total = bal.get("total", 0)
            prefix = "¥" if cur == "CNY" else "$"
            self.display_text.set(f"余额 {prefix}{total:.2f}")
    
    def _show_detail(self):
        self.refresh()
        win = tk.Toplevel(self.root)
        win.title("DeepSeek 余额详情")
        win.geometry("360x260")
        win.resizable(False, False)
        win.configure(bg="#1a1a2e")
        win.attributes("-topmost", True)
        
        bal = self.balance
        items = []
        if bal is None:
            items.append(("状态","查询中...","#FACC15"))
        elif not bal.get("ok"):
            items.append(("错误",bal.get("err","未知"),"#F87171"))
        else:
            cur = bal.get("currency","CNY")
            prefix = "¥" if cur == "CNY" else "$"
            items.append(("💰 总余额", f"{prefix}{bal['total']:.2f}", "#4F6EF7"))
            items.append(("充值余额", f"{prefix}{bal['topped_up']:.2f}", "#4CAF50"))
            items.append(("赠送余额", f"{prefix}{bal['granted']:.2f}", "#FF9800"))
        
        frame = tk.Frame(win, bg="#1a1a2e", padx=20, pady=15)
        frame.pack(fill=tk.BOTH, expand=True)
        for label, value, color in items:
            row = tk.Frame(frame, bg="#1a1a2e")
            row.pack(fill=tk.X, pady=5)
            tk.Label(row, text=label, bg="#1a1a2e", fg="#a0a0a0",
                     font=("Segoe UI", 11), anchor=tk.W, width=10).pack(side=tk.LEFT)
            tk.Label(row, text=value, bg="#1a1a2e", fg=color,
                     font=("Segoe UI", 13, "bold"), anchor=tk.E).pack(side=tk.RIGHT)
        tk.Button(frame, text="关闭", bg="#333333", fg="#e0e0e0",
                  font=("Segoe UI", 10), relief=tk.FLAT, command=win.destroy
                  ).pack(pady=(10, 0))
    
    def _show_settings(self):
        win = tk.Toplevel(self.root)
        win.title("设置 API Key")
        win.geometry("460x200")
        win.resizable(False, False)
        win.configure(bg="#1a1a2e")
        
        frame = tk.Frame(win, bg="#1a1a2e", padx=25, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)
        tk.Label(frame, text="🔑 DeepSeek API Key", bg="#1a1a2e", fg="#ffffff",
                 font=("Segoe UI", 13, "bold")).pack(anchor=tk.W)
        tk.Label(frame, text="在 platform.deepseek.com → API Keys 获取",
                 bg="#1a1a2e", fg="#888888", font=("Segoe UI", 9)).pack(anchor=tk.W, pady=(0, 8))
        
        var = tk.StringVar(value=self.api_key)
        entry = tk.Entry(frame, textvariable=var, bg="#16213e", fg="#e0e0e0",
                         font=("Consolas", 11), relief=tk.FLAT, bd=8, show="*")
        entry.pack(fill=tk.X)
        
        btn_frame = tk.Frame(frame, bg="#1a1a2e")
        btn_frame.pack(fill=tk.X, pady=(15, 0))
        def save():
            key = var.get().strip()
            if not key:
                messagebox.showwarning("提示", "请输入 API Key")
                return
            self.api_key = key
            self.cfg["api_key"] = key
            save_config(self.cfg)
            self.api = DeepSeekAPI(key)
            self.refresh()
            messagebox.showinfo("完成", "API Key 已保存")
            win.destroy()
        tk.Button(btn_frame, text="保存", bg="#4F6EF7", fg="white",
                  font=("Segoe UI", 11, "bold"), relief=tk.FLAT, bd=0,
                  padx=25, pady=8, cursor="hand2", command=save
                  ).pack(side=tk.RIGHT, padx=(10, 0))
        tk.Button(btn_frame, text="取消", bg="#333333", fg="#e0e0e0",
                  font=("Segoe UI", 11), relief=tk.FLAT, bd=0,
                  padx=25, pady=8, cursor="hand2",
                  command=win.destroy).pack(side=tk.RIGHT)
    
    def _schedule_refresh(self):
        if not self._alive: return
        self.refresh()
        self.root.after(30000, self._schedule_refresh)
    
    def quit(self):
        self._alive = False
        self.root.quit()
        self.root.destroy()
    
    def run(self):
        self.root.mainloop()


def main():
    if not acquire_lock():
        print("程序已在运行中")
        sys.exit(0)
    app = BalanceOverlay()
    try:
        app.run()
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        _cleanup()
    sys.exit(0)

if __name__ == "__main__":
    main()
