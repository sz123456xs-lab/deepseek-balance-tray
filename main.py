"""
DeepSeek 余额查询 - 精简稳定版
"""
import os
import sys
import socket
import atexit
import threading
import time
import json
from datetime import datetime, timedelta
from typing import Optional

import pystray
from PIL import Image, ImageDraw, ImageFont
import requests
import tkinter as tk
from tkinter import messagebox

# ── 工作目录 ──
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ── 单实例锁 ──
LOCK_PORT = 28999
_lock_sock = None

def _cleanup():
    global _lock_sock
    if _lock_sock:
        try: _lock_sock.close()
        except: pass
        _lock_sock = None

def acquire_lock() -> bool:
    global _lock_sock
    try:
        _lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _lock_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _lock_sock.bind(("127.0.0.1", LOCK_PORT))
        _lock_sock.listen(1)
        atexit.register(_cleanup)
        return True
    except OSError:
        return False
    except:
        return False

# ── 配置管理 ──
CONFIG_DIR = os.path.expanduser("~/.deepseek_tray")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {"api_key": ""}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"api_key": ""}

def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

# ── DeepSeek API ──
class DeepSeekClient:
    BASE = "https://api.deepseek.com"

    def __init__(self, api_key: str):
        self.key = api_key
        self.sess = requests.Session()
        self.sess.headers.update({
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        })

    def get_balance(self) -> Optional[dict]:
        try:
            resp = self.sess.get(f"{self.BASE}/user/balance", timeout=10)
            if resp.status_code == 200:
                d = resp.json()
                infos = d.get("balance_infos", [])
                if infos:
                    i = infos[0]
                    return {
                        "total": float(i.get("total_balance", 0)),
                        "granted": float(i.get("granted_balance", 0)),
                        "topped_up": float(i.get("topped_up_balance", 0)),
                        "currency": i.get("currency", "CNY"),
                        "available": d.get("is_available", False),
                    }
            elif resp.status_code == 401:
                return {"error": "API Key 无效"}
            else:
                return {"error": f"HTTP {resp.status_code}"}
        except requests.Timeout:
            return {"error": "请求超时"}
        except requests.ConnectionError:
            return {"error": "网络错误"}
        except Exception as e:
            return {"error": str(e)}

# ── Tk root ──
_tk_root = None
def get_tk_root():
    global _tk_root
    if _tk_root is None:
        _tk_root = tk.Tk()
        _tk_root.withdraw()
    return _tk_root

# ── 主应用 ──
class DeepSeekTray:
    def __init__(self):
        self.cfg = load_config()
        self.api_key = self.cfg.get("api_key", "")
        self.client = DeepSeekClient(self.api_key) if self.api_key else None

        self.balance = None
        self.error = ""
        self._alive = True

        # 创建托盘图标
        self.icon = None
        self._create_icon()

    def _generate_icon(self, text: str, bg: str = "#4F6EF7"):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([2, 2, 62, 62], radius=12, fill=bg)
        try:
            font = ImageFont.truetype("arial.ttf", 32)
        except:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        x = (64 - (bbox[2] - bbox[0])) / 2
        y = (64 - (bbox[3] - bbox[1])) / 2 - 1
        draw.text((x, y), text, fill="white", font=font)
        return img

    def _create_icon(self):
        self.icon = pystray.Icon(
            "deepseek_tray",
            self._generate_icon("DS"),
            "DeepSeek 余额",
            menu=pystray.Menu(
                pystray.MenuItem("📊 余额详情", lambda: self.show_detail()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("🔄 刷新", lambda: self.refresh()),
                pystray.MenuItem("⚙️ 设置 API Key", lambda: self.show_settings()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("❌ 退出", lambda: self.quit()),
            ),
        )

    def refresh(self):
        """刷新余额"""
        if not self.client:
            self.balance = {"error": "未设置 API Key"}
            self._update_display()
            return
        result = self.client.get_balance()
        if result is None:
            self.balance = {"error": "无返回"}
        else:
            self.balance = result
        self._update_display()

    def _update_display(self):
        """更新图标 tooltip 和图标颜色"""
        if not self._alive:
            return
        bal = self.balance
        lines = []
        if bal is None:
            lines.append("查询中...")
            dot = "#FACC15"  # 黄
            icon_char = ".."
        elif "error" in bal:
            lines.append(f"⚠️ {bal['error']}")
            dot = "#F87171"  # 红
            icon_char = "!!"
        else:
            cur = bal.get("currency", "CNY")
            total = bal.get("total", 0)
            prefix = "¥" if cur == "CNY" else "$"
            lines.append(f"💰 余额: {prefix}{total:.2f}")
            lines.append(f"   充值: {prefix}{bal.get('topped_up', 0):.2f}")
            lines.append(f"   赠送: {prefix}{bal.get('granted', 0):.2f}")
            dot = "#10B981"  # 绿
            icon_char = f"{prefix}{total:.1f}"[:2]

        try:
            self.icon.title = "\n".join(lines)
            self.icon.icon = self._generate_icon(icon_char, dot)
        except:
            pass

    def show_detail(self):
        """弹出详情窗口"""
        self.refresh()
        root = get_tk_root()
        win = tk.Toplevel(root)
        win.title("DeepSeek 余额详情")
        win.geometry("380x200")
        win.resizable(False, False)
        win.configure(bg="#1a1a2e")
        win.grab_set()

        bal = self.balance
        lines = []
        if bal is None:
            lines.append(("", "查询中..."))
        elif "error" in bal:
            lines.append(("⚠️", bal['error']))
        else:
            cur = bal.get("currency", "CNY")
            prefix = "¥" if cur == "CNY" else "$"
            lines.append(("💰 总余额", f"{prefix}{bal['total']:.2f}"))
            lines.append(("充值余额", f"{prefix}{bal['topped_up']:.2f}"))
            lines.append(("赠送余额", f"{prefix}{bal['granted']:.2f}"))
            lines.append(("状态", "● 可用" if bal['available'] else "● 不可用"))

        frame = tk.Frame(win, bg="#1a1a2e", padx=20, pady=15)
        frame.pack(fill=tk.BOTH, expand=True)

        for label, value in lines:
            row = tk.Frame(frame, bg="#1a1a2e")
            row.pack(fill=tk.X, pady=4)
            tk.Label(row, text=label, bg="#1a1a2e", fg="#a0a0a0",
                     font=("Segoe UI", 11), anchor=tk.W, width=10
                     ).pack(side=tk.LEFT)
            color = "#4F6EF7" if "总余额" in label else "#e0e0e0"
            tk.Label(row, text=value, bg="#1a1a2e", fg=color,
                     font=("Segoe UI", 13, "bold"), anchor=tk.E
                     ).pack(side=tk.RIGHT)

        tk.Label(frame, text="", bg="#1a1a2e").pack()
        tk.Button(frame, text="关闭", bg="#333333", fg="#e0e0e0",
                  relief=tk.FLAT, padx=30, pady=6, cursor="hand2",
                  command=win.destroy).pack()

    def show_settings(self):
        """设置 API Key 对话框"""
        root = get_tk_root()
        win = tk.Toplevel(root)
        win.title("设置 API Key")
        win.geometry("480x200")
        win.resizable(False, False)
        win.configure(bg="#1a1a2e")
        win.grab_set()

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
                         font=("Consolas", 11), relief=tk.FLAT, bd=8,
                         show="*")
        entry.pack(fill=tk.X)

        btn_frame = tk.Frame(frame, bg="#1a1a2e")
        btn_frame.pack(fill=tk.X, pady=(15, 0))

        tk.Button(btn_frame, text="保存", bg="#4F6EF7", fg="white",
                  font=("Segoe UI", 11, "bold"), relief=tk.FLAT, bd=0,
                  padx=25, pady=8, cursor="hand2",
                  command=lambda: self._save_key(var.get().strip(), win)
                  ).pack(side=tk.RIGHT, padx=(10, 0))

        tk.Button(btn_frame, text="取消", bg="#333333", fg="#e0e0e0",
                  font=("Segoe UI", 11), relief=tk.FLAT, bd=0,
                  padx=25, pady=8, cursor="hand2",
                  command=win.destroy).pack(side=tk.RIGHT)

    def _save_key(self, key: str, win):
        if not key:
            messagebox.showwarning("提示", "请输入 API Key")
            return
        self.api_key = key
        self.cfg["api_key"] = key
        save_config(self.cfg)
        self.client = DeepSeekClient(key)
        self.refresh()
        messagebox.showinfo("完成", "API Key 已保存")
        win.destroy()

    def quit(self):
        self._alive = False
        try:
            self.icon.stop()
        except:
            pass

    def run(self):
        """启动应用"""
        # 首次刷新
        if self.client:
            self.refresh()
        else:
            self.balance = {"error": "未设置 API Key"}
            self._update_display()

        # 自动刷新线程 (30秒)
        def auto_refresh():
            while self._alive:
                time.sleep(30)
                if self._alive:
                    self.refresh()
        t = threading.Thread(target=auto_refresh, daemon=True)
        t.start()

        self.icon.run()


# ── 启动 ──
def main():
    if not acquire_lock():
        print("程序已在运行中")
        sys.exit(0)

    app = DeepSeekTray()
    try:
        app.run()
    except SystemExit:
        pass
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        _cleanup()
    sys.exit(0)


if __name__ == "__main__":
    main()
