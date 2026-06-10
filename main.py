"""
DeepSeek 余额查询 - 纯 tkinter 托盘版
不使用 pystray，使用 Windows 原生 API 实现系统托盘
"""
import os
import sys
import json
import time
import threading
import atexit
import socket
import struct
from datetime import datetime, timedelta

import requests
import tkinter as tk
from tkinter import ttk, messagebox

os.chdir(os.path.dirname(os.path.abspath(__file__)))

###############################################################################
# 单实例锁
###############################################################################
LOCK_PORT = 29000
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
    except:
        return False

###############################################################################
# 配置
###############################################################################
CONFIG_DIR = os.path.expanduser("~/.deepseek_tray")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {"api_key": ""}
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except:
        return {"api_key": ""}

def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

###############################################################################
# DeepSeek API
###############################################################################
class DeepSeekAPI:
    BASE = "https://api.deepseek.com"

    def __init__(self, api_key: str):
        self.sess = requests.Session()
        self.sess.headers.update({
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        })

    def get_balance(self):
        try:
            r = self.sess.get(f"{self.BASE}/user/balance", timeout=10)
            if r.status_code == 200:
                d = r.json()
                infos = d.get("balance_infos", [])
                if infos:
                    i = infos[0]
                    return {
                        "ok": True,
                        "total": float(i.get("total_balance", 0)),
                        "granted": float(i.get("granted_balance", 0)),
                        "topped_up": float(i.get("topped_up_balance", 0)),
                        "currency": i.get("currency", "CNY"),
                    }
                return {"ok": False, "err": "无余额信息"}
            elif r.status_code == 401:
                return {"ok": False, "err": "API Key 无效或已过期"}
            else:
                return {"ok": False, "err": f"HTTP {r.status_code}"}
        except requests.Timeout:
            return {"ok": False, "err": "请求超时"}
        except requests.ConnectionError:
            return {"ok": False, "err": "无法连接服务器"}
        except Exception as e:
            return {"ok": False, "err": str(e)}

###############################################################################
# Windows 系统托盘实现（使用 ctypes 调用 Win32 API）
###############################################################################
import ctypes
import ctypes.wintypes

# Windows API 常量
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_USER = 0x0400
NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010
NIS_HIDDEN = 0x00000001
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_LBUTTONDBLCLK = 0x0203

# 加载 user32
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("hWnd", ctypes.wintypes.HWND),
        ("uID", ctypes.wintypes.UINT),
        ("uFlags", ctypes.wintypes.UINT),
        ("uCallbackMessage", ctypes.wintypes.UINT),
        ("hIcon", ctypes.wintypes.HANDLE),
        ("szTip", ctypes.wintypes.WCHAR * 128),
        ("dwState", ctypes.wintypes.DWORD),
        ("dwStateMask", ctypes.wintypes.DWORD),
        ("szInfo", ctypes.wintypes.WCHAR * 256),
        ("uVersion", ctypes.wintypes.UINT),
        ("szInfoTitle", ctypes.wintypes.WCHAR * 64),
        ("dwInfoFlags", ctypes.wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", ctypes.wintypes.HANDLE),
    ]

def create_tray_icon(hwnd, uid, icon_handle, tip_text):
    """创建系统托盘图标"""
    nid = NOTIFYICONDATAW()
    nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    nid.hWnd = hwnd
    nid.uID = uid
    nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
    nid.uCallbackMessage = WM_USER + 1
    nid.hIcon = icon_handle
    nid.szTip = tip_text[:127]
    user32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
    return nid

def modify_tray_tip(nid, tip_text):
    """修改托盘图标的提示文字"""
    nid.uFlags = NIF_TIP
    nid.szTip = tip_text[:127]
    user32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

def modify_tray_icon(nid, icon_handle):
    """修改托盘图标的图标"""
    nid.uFlags = NIF_ICON
    nid.hIcon = icon_handle
    user32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

def delete_tray_icon(nid):
    """删除托盘图标"""
    user32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))

###############################################################################
# 托盘应用
###############################################################################
from PIL import Image, ImageDraw, ImageFont

class TrayApp:
    WINDOW_CLASS = "DeepSeekTrayWindow"
    ICON_ID = 1

    def __init__(self):
        self.cfg = load_config()
        self.api_key = self.cfg.get("api_key", "")
        self.api = DeepSeekAPI(self.api_key) if self.api_key else None
        self.balance = None
        self.running = True
        self.nid = None
        self.hwnd = None
        self.hwnd_popup = None
        self.settings_win = None

    def make_icon(self, text="DS", color="#4F6EF7"):
        """生成 icon 的 HICON 句柄"""
        size = 32
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # 解析颜色
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        draw.rounded_rectangle([1, 1, size-2, size-2], radius=6, fill=(r, g, b, 255))
        try:
            fnt = ImageFont.truetype("arial.ttf", 16)
        except:
            fnt = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=fnt)
        x = (size - (bbox[2] - bbox[0])) / 2
        y = (size - (bbox[3] - bbox[1])) / 2 - 1
        draw.text((x, y), text, fill="white", font=fnt)
        # 转为 HICON
        from PIL import ImageWin
        return ImageWin.Handle(img, None)

    def create_window(self):
        """创建隐藏窗口用于接收消息"""
        hinstance = kernel32.GetModuleHandleW(None)
        # 注册窗口类
        wc = ctypes.wintypes.WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(wc)
        wc.lpfnWndProc = self._wnd_proc
        wc.hInstance = hinstance
        wc.lpszClassName = self.WINDOW_CLASS
        class_atom = user32.RegisterClassExW(ctypes.byref(wc))
        # 创建窗口
        self.hwnd = user32.CreateWindowExW(
            0, self.WINDOW_CLASS, "DeepSeek", 0,
            0, 0, 0, 0, 0, 0, hinstance, 0
        )
        # 创建托盘图标
        icon_handle = self.make_icon()
        self.nid = create_tray_icon(self.hwnd, self.ICON_ID, icon_handle, "DeepSeek 余额")
        # 设置版本
        user32.Shell_NotifyIconW.c_void_p = 0

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        """窗口消息处理"""
        if msg == WM_USER + 1:
            # 托盘图标回调消息
            lomessage = lparam & 0xFFFF
            if lomessage == WM_RBUTTONUP:
                # 右键弹出菜单
                self._show_context_menu()
            elif lomessage == WM_LBUTTONUP:
                # 左键显示详情
                self.refresh()
                self._show_detail_popup()
            elif lomessage == WM_LBUTTONDBLCLK:
                self.refresh()
                self._show_detail_popup()
        elif msg == WM_DESTROY:
            self.running = False
            user32.PostQuitMessage(0)
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # 窗口过程回调必须定义为类方法并用 WINFUNCTYPE
    _wnd_proc = ctypes.WINFUNCTYPE(
        ctypes.c_int64,
        ctypes.c_int64, ctypes.c_uint, ctypes.c_int64, ctypes.c_int64
    )(_wnd_proc.__func__ if hasattr(_wnd_proc, '__func__') else lambda h,m,w,l: user32.DefWindowProcW(h,m,w,l))

    def refresh(self):
        if not self.api:
            self.balance = {"ok": False, "err": "未设置 API Key"}
        else:
            self.balance = self.api.get_balance()
        self._update_tray()

    def _update_tray(self):
        """更新托盘图标提示和颜色"""
        if not self.nid:
            return
        bal = self.balance
        if bal is None:
            tip = "查询中..."
            color = "#FACC15"
        elif not bal.get("ok"):
            tip = f"⚠ {bal.get('err', '错误')}"
            color = "#F87171"
        else:
            cur = bal.get("currency", "CNY")
            total = bal.get("total", 0)
            prefix = "¥" if cur == "CNY" else "$"
            tip = f"DeepSeek 余额: {prefix}{total:.2f}"
            color = "#10B981"
        try:
            icon_handle = self.make_icon("DS", color)
            modify_tray_icon(self.nid, icon_handle)
            modify_tray_tip(self.nid, tip)
        except:
            pass

    def _show_context_menu(self):
        """显示右键菜单 - 使用 tkinter 弹出菜单"""
        menu = tk.Menu(None, tearoff=0, bg="#2d2d2d", fg="#e0e0e0",
                       activebackground="#4F6EF7", activeforeground="white",
                       font=("Segoe UI", 10))
        menu.add_command(label="📊 余额详情", command=lambda: (self.refresh(), self._show_detail_popup()))
        menu.add_separator()
        menu.add_command(label="🔄 刷新", command=self.refresh)
        menu.add_command(label="⚙ 设置 API Key", command=self._show_settings)
        menu.add_separator()
        menu.add_command(label="❌ 退出", command=self._quit)
        # 显示在鼠标位置
        try:
            x, y = self._get_cursor_pos()
            menu.tk_popup(x, y)
        except:
            pass
        finally:
            menu.grab_release()

    def _get_cursor_pos(self):
        """获取鼠标位置"""
        point = ctypes.wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        return point.x, point.y

    def _show_detail_popup(self):
        """显示余额详情弹窗 - 纯 tkinter"""
        if self.hwnd_popup and self.hwnd_popup.winfo_exists():
            try:
                self.hwnd_popup.lift()
                return
            except:
                pass

        win = tk.Toplevel()
        win.title("DeepSeek 余额详情")
        win.geometry("360x260")
        win.resizable(False, False)
        win.configure(bg="#1a1a2e")
        win.attributes("-topmost", True)
        self.hwnd_popup = win

        bal = self.balance
        items = []
        if bal is None:
            items.append(("状态", "查询中...", "#FACC15"))
        elif not bal.get("ok"):
            items.append(("错误", bal.get("err", "未知错误"), "#F87171"))
        else:
            cur = bal.get("currency", "CNY")
            prefix = "¥" if cur == "CNY" else "$"
            items.append(("💰 总余额", f"{prefix}{bal['total']:.2f}", "#4F6EF7"))
            items.append(("充值余额", f"{prefix}{bal['topped_up']:.2f}", "#4CAF50"))
            items.append(("赠送余额", f"{prefix}{bal['granted']:.2f}", "#FF9800"))
            items.append(("货币", cur, "#a0a0a0"))

        frame = tk.Frame(win, bg="#1a1a2e", padx=20, pady=15)
        frame.pack(fill=tk.BOTH, expand=True)

        for label, value, color in items:
            row = tk.Frame(frame, bg="#1a1a2e")
            row.pack(fill=tk.X, pady=5)
            tk.Label(row, text=label, bg="#1a1a2e", fg="#a0a0a0",
                     font=("Segoe UI", 11), anchor=tk.W, width=10
                     ).pack(side=tk.LEFT)
            tk.Label(row, text=value, bg="#1a1a2e", fg=color,
                     font=("Segoe UI", 13, "bold"), anchor=tk.E
                     ).pack(side=tk.RIGHT)

        btn_frame = tk.Frame(frame, bg="#1a1a2e")
        btn_frame.pack(fill=tk.X, pady=(10, 0))
        tk.Button(btn_frame, text="刷新", bg="#4F6EF7", fg="white",
                  font=("Segoe UI", 10), relief=tk.FLAT, bd=0,
                  padx=20, pady=5, cursor="hand2",
                  command=lambda: (self.refresh(), self._show_detail_popup())
                  ).pack(side=tk.LEFT)
        tk.Button(btn_frame, text="关闭", bg="#333333", fg="#e0e0e0",
                  font=("Segoe UI", 10), relief=tk.FLAT, bd=0,
                  padx=20, pady=5, cursor="hand2",
                  command=self._close_popup
                  ).pack(side=tk.RIGHT)

    def _close_popup(self):
        if self.hwnd_popup:
            try:
                self.hwnd_popup.destroy()
            except:
                pass
            self.hwnd_popup = None

    def _show_settings(self):
        """设置 API Key 窗口"""
        if self.settings_win:
            try:
                self.settings_win.lift()
                return
            except:
                pass

        win = tk.Toplevel()
        win.title("设置 API Key")
        win.geometry("460x200")
        win.resizable(False, False)
        win.configure(bg="#1a1a2e")
        self.settings_win = win

        frame = tk.Frame(win, bg="#1a1a2e", padx=25, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame, text="🔑 DeepSeek API Key",
                 bg="#1a1a2e", fg="#ffffff",
                 font=("Segoe UI", 13, "bold")).pack(anchor=tk.W)
        tk.Label(frame, text="在 platform.deepseek.com → API Keys 获取",
                 bg="#1a1a2e", fg="#888888",
                 font=("Segoe UI", 9)).pack(anchor=tk.W, pady=(0, 8))

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
            self.settings_win = None

        def cancel():
            win.destroy()
            self.settings_win = None

        tk.Button(btn_frame, text="保存", bg="#4F6EF7", fg="white",
                  font=("Segoe UI", 11, "bold"), relief=tk.FLAT, bd=0,
                  padx=25, pady=8, cursor="hand2",
                  command=save).pack(side=tk.RIGHT, padx=(10, 0))
        tk.Button(btn_frame, text="取消", bg="#333333", fg="#e0e0e0",
                  font=("Segoe UI", 11), relief=tk.FLAT, bd=0,
                  padx=25, pady=8, cursor="hand2",
                  command=cancel).pack(side=tk.RIGHT)

        win.protocol("WM_DELETE_WINDOW", cancel)

    def _quit(self):
        self.running = False
        self._close_popup()
        try:
            if self.settings_win:
                self.settings_win.destroy()
        except:
            pass
        if self.nid:
            try:
                delete_tray_icon(self.nid)
            except:
                pass
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)

    def run(self):
        """主消息循环"""
        # 创建窗口 + 托盘图标
        self.create_window()
        # 首次刷新
        self.refresh()
        # 自动刷新线程 (30秒)
        def auto_refresh():
            while self.running:
                time.sleep(30)
                if self.running:
                    self.refresh()
        threading.Thread(target=auto_refresh, daemon=True).start()
        # Windows 消息循环
        msg = ctypes.wintypes.MSG()
        while self.running:
            ret = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
            if ret <= 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


###############################################################################
# 启动
###############################################################################
def main():
    if not acquire_lock():
        print("程序已在运行中")
        sys.exit(0)

    app = TrayApp()
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
