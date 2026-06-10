"""
系统托盘图标 + 弹窗界面模块

核心设计：
1. 用 threading.Timer 做轮播，但用 daemon=True + 全局退出标记
2. 所有右键菜单回调用 lambda 闭包固定 self 引用
3. 窗口必须响应式可用，不能卡住 tkinter 事件循环
4. _on_exit 确保所有定时器取消 + icon.stop()
"""
import json
import os
import sys
import threading
import time
from datetime import datetime
from typing import Optional

import pystray
from PIL import Image, ImageDraw, ImageFont
import tkinter as tk
from tkinter import ttk, messagebox

from deepseek_api import (
    DeepSeekAPI,
    UsageTracker,
    PRICING,
    format_currency,
    format_tokens,
)
from config import (
    load_config,
    save_config,
    get_api_key,
    set_api_key,
    get_refresh_interval,
    set_refresh_interval,
    get_refresh_intervals,
)


class DeepSeekTrayApp:
    """DeepSeek 余额查询任务栏小工具"""

    ICON_SIZE = 64

    def __init__(self):
        self.config = load_config()
        self.api_key = get_api_key()
        self.refresh_interval = get_refresh_interval()
        self.usage_tracker = UsageTracker()

        # 数据缓存
        self.balance_data = {}
        self.today_data = {}
        self.month_data = {}
        self.weekly_trend = []
        self.models_data = {}
        self.last_refresh_time = None
        self.error_message = ""

        # 轮播 & 刷新控制
        self.status_bar_items = []
        self.status_index = 0
        self.scroll_speed = self.config.get("status_bar_scroll_speed", 3)
        self._alive = True          # 全局存活标记，True=运行中

        # 初始化 API 客户端
        self.api = None
        if self.api_key:
            self.api = DeepSeekAPI(self.api_key)

        # 创建图标
        self.icon = None
        self._create_icon()

        # 立即刷新数据
        self.refresh_data()

    def _create_icon(self):
        icon_image = self._generate_icon("余额")
        self.icon = pystray.Icon(
            "deepseek_tray",
            icon_image,
            "DeepSeek 余额 | 加载中...",
            menu=pystray.Menu(
                pystray.MenuItem(
                    "📊 查看详情",
                    lambda: self._show_detail_window(),
                    default=True,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("🔄 刷新数据", lambda: self._on_refresh()),
                pystray.MenuItem("⚙️ 设置", lambda: self._show_settings_window()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("🔁 切换刷新间隔", self._cycle_refresh_interval),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("❌ 退出", lambda: self._on_exit()),
            ),
        )
        # 注册 pystray 退出时的回调（用户从系统菜单关闭图标时）
        self.icon.on_stop = self._on_icon_stopped

    def _generate_icon(self, text: str, bg_color: str = "#4F6EF7") -> Image.Image:
        img = Image.new("RGBA", (self.ICON_SIZE, self.ICON_SIZE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        margin = 2
        draw.rounded_rectangle(
            [margin, margin, self.ICON_SIZE - margin, self.ICON_SIZE - margin],
            radius=12,
            fill=bg_color,
        )
        try:
            font_size = int(self.ICON_SIZE * 0.55)
            font = ImageFont.truetype("arial.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (self.ICON_SIZE - tw) / 2
        y = (self.ICON_SIZE - th) / 2 - 1
        draw.text((x, y), text, fill="white", font=font)
        return img

    def _get_interval_label(self) -> str:
        intervals = get_refresh_intervals()
        for label, sec in intervals.items():
            if sec == self.refresh_interval:
                return label
        return f"{self.refresh_interval // 60}分钟"

    def _cycle_refresh_interval(self):
        """切换到下一个刷新间隔"""
        intervals = list(get_refresh_intervals().values())
        try:
            idx = intervals.index(self.refresh_interval)
        except ValueError:
            idx = -1
        next_idx = (idx + 1) % len(intervals)
        self.refresh_interval = intervals[next_idx]
        set_refresh_interval(self.refresh_interval)
        self.refresh_data()
        # 更新菜单文字
        self.icon.menu = self._recreate_menu()
        self._update_tooltip()

    def _recreate_menu(self):
        return pystray.Menu(
            pystray.MenuItem(
                "📊 查看详情", lambda: self._show_detail_window(), default=True
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("🔄 刷新数据", lambda: self._on_refresh()),
            pystray.MenuItem("⚙️ 设置", lambda: self._show_settings_window()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("🔁 自动刷新: " + self._get_interval_label(), self._cycle_refresh_interval),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("❌ 退出", lambda: self._on_exit()),
        )

    # ── 刷新 ──

    def refresh_data(self):
        """刷新所有数据"""
        if not self._alive:
            return
        if not self.api:
            self.error_message = "请先配置 API Key"
            self._update_tooltip()
            return
        try:
            self.balance_data = self.api.simple_balance_report()
            self.today_data = self.usage_tracker.get_today_summary()
            self.month_data = self.usage_tracker.get_month_summary()
            self.weekly_trend = self.usage_tracker.get_weekly_trend()
            self.models_data = self.usage_tracker.get_models_summary()
            self.last_refresh_time = datetime.now()
            self.error_message = ""
            self._update_status_bar_items()
        except Exception as e:
            self.error_message = str(e)
        self._update_tooltip()

    def _update_status_bar_items(self):
        """构建轮播文本列表"""
        items = []
        if self.balance_data:
            cur = self.balance_data.get("currency", "CNY")
            total = self.balance_data.get("total_balance", 0)
            items.append(f"余额: {format_currency(total, cur)}")
        today_cost = self.today_data.get("total_cost_usd", 0)
        items.append(f"今日: ${today_cost:.4f}" if today_cost > 0 else "今日: $0")
        month_cost = self.month_data.get("total_cost_usd", 0)
        if month_cost > 0:
            items.append(f"本月: ${month_cost:.4f}")
        for model, data in self.models_data.items():
            short = model.replace("deepseek-", "DS ").replace("-", " ")
            tokens = data.get("today_tokens", 0)
            if tokens > 0:
                items.append(f"{short}: {format_tokens(tokens)}")
        if not items:
            items.append("DeepSeek 余额")
        self.status_bar_items = items
        self.status_index = 0

    def _update_tooltip(self):
        """更新托盘 tooltip"""
        lines = []
        if self.balance_data:
            cur = self.balance_data.get("currency", "CNY")
            total = self.balance_data.get("total_balance", 0)
            granted = self.balance_data.get("granted_balance", 0)
            topped_up = self.balance_data.get("topped_up_balance", 0)
            lines.append(f"💰 余额: {format_currency(total, cur)}")
            lines.append(f"   充值: {format_currency(topped_up, cur)}")
            lines.append(f"   赠送: {format_currency(granted, cur)}")
        else:
            lines.append("余额查询中...")
        today_cost = self.today_data.get("total_cost_usd", 0)
        month_cost = self.month_data.get("total_cost_usd", 0)
        lines.append(f"📊 今日: ${today_cost:.4f}" if today_cost > 0 else "📊 今日: $0")
        lines.append(f"📅 本月: ${month_cost:.4f}" if month_cost > 0 else "📅 本月: $0")
        if self.error_message:
            lines.append(f"⚠️ {self.error_message}")
        if self.last_refresh_time:
            lines.append(f"🔄 {self.last_refresh_time.strftime('%H:%M:%S')}")
        try:
            self.icon.title = "\n".join(lines)
        except Exception:
            pass

    # ── 轮播 ──

    def _start_scroll_loop(self):
        """启动轮播（在独立 daemon 线程中循环）"""
        def scroll_worker():
            while self._alive:
                if self.status_bar_items and self.icon:
                    try:
                        text = self.status_bar_items[self.status_index % len(self.status_bar_items)]
                        icon_char = text[:2] if len(text) >= 2 else text[:1]
                        self.icon.icon = self._generate_icon(icon_char)
                        self.status_index += 1
                    except Exception:
                        pass
                # 休眠轮播间隔
                for _ in range(int(self.scroll_speed * 10)):
                    if not self._alive:
                        return
                    time.sleep(0.1)
        t = threading.Thread(target=scroll_worker, daemon=True)
        t.start()

    def _start_refresh_loop(self):
        """启动自动刷新 daemon 线程"""
        def refresh_worker():
            while self._alive:
                # 休眠刷新间隔
                for _ in range(int(self.refresh_interval * 10)):
                    if not self._alive:
                        return
                    time.sleep(0.1)
                if self._alive:
                    self.refresh_data()
        t = threading.Thread(target=refresh_worker, daemon=True)
        t.start()

    def _on_refresh(self):
        self.refresh_data()

    def _show_detail_window(self):
        self.refresh_data()
        DetailWindow(self)

    def _show_settings_window(self):
        SettingsWindow(self)

    # ── 退出 ──

    def _on_icon_stopped(self):
        """pystray 图标被系统关闭时的回调"""
        self._alive = False

    def _on_exit(self):
        """主动退出"""
        self._alive = False
        try:
            self.icon.stop()
        except Exception:
            pass

    # ── 运行 ──

    def run(self):
        """运行应用（启动轮播、刷新、然后进入 pystray 消息循环）"""
        self._start_scroll_loop()
        self._start_refresh_loop()
        self.icon.run()


# ═══════════════════════════════════════════════════════════
# 详情窗口
# ═══════════════════════════════════════════════════════════

class DetailWindow:
    def __init__(self, app: DeepSeekTrayApp):
        self.app = app
        self.window = tk.Toplevel()
        self.window.title("DeepSeek 余额详情")
        self.window.geometry("520x580")
        self.window.resizable(False, False)
        self.window.configure(bg="#1a1a2e")
        # 允许用户用 Alt+F4 或窗口 X 关闭
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._center_window()
        self.window.grab_set()
        self.window.focus_set()

    def _on_close(self):
        try:
            self.window.grab_release()
        except Exception:
            pass
        self.window.destroy()

    def _center_window(self):
        self.window.update_idletasks()
        w = self.window.winfo_width()
        h = self.window.winfo_height()
        sw = self.window.winfo_screenwidth()
        sh = self.window.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.window.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        main_frame = tk.Frame(self.window, bg="#1a1a2e", padx=20, pady=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        bal = self.app.balance_data
        if bal:
            cur = bal.get("currency", "CNY")
            total = bal.get("total_balance", 0)
            granted = bal.get("granted_balance", 0)
            topped_up = bal.get("topped_up_balance", 0)
            avail = bal.get("is_available", False)

            tk.Label(main_frame, text="💰 账户余额",
                     bg="#1a1a2e", fg="#ffffff",
                     font=("Segoe UI", 14, "bold")).pack(anchor=tk.W)

            bf = tk.Frame(main_frame, bg="#16213e", padx=15, pady=12)
            bf.pack(fill=tk.X, pady=(5, 10))

            tk.Label(bf, text=format_currency(total, cur),
                     bg="#16213e", fg="#4F6EF7",
                     font=("Segoe UI", 26, "bold")).pack(anchor=tk.W)

            sf = tk.Frame(bf, bg="#16213e")
            sf.pack(fill=tk.X, pady=(3, 0))
            tk.Label(sf, text=f"充值: {format_currency(topped_up, cur)}",
                     bg="#16213e", fg="#4CAF50",
                     font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=(0, 15))
            tk.Label(sf, text=f"赠送: {format_currency(granted, cur)}",
                     bg="#16213e", fg="#FF9800",
                     font=("Segoe UI", 10)).pack(side=tk.LEFT)
            tk.Label(sf, text="● 可用" if avail else "● 不可用",
                     bg="#16213e",
                     fg="#4CAF50" if avail else "#ff4444",
                     font=("Segoe UI", 9, "bold")).pack(side=tk.RIGHT)

        # 消费
        tk.Label(main_frame, text="📊 消费概览",
                 bg="#1a1a2e", fg="#ffffff",
                 font=("Segoe UI", 14, "bold")).pack(anchor=tk.W, pady=(10, 5))

        cf = tk.Frame(main_frame, bg="#16213e", padx=15, pady=10)
        cf.pack(fill=tk.X)

        today_cost = self.app.today_data.get("total_cost_usd", 0)
        month_cost = self.app.month_data.get("total_cost_usd", 0)
        today_calls = self.app.today_data.get("total_calls", 0)
        month_calls = self.app.month_data.get("total_calls", 0)

        df = tk.Frame(cf, bg="#16213e")
        df.pack(fill=tk.X)
        tk.Label(df, text="今日消费", bg="#16213e", fg="#a0a0a0",
                 font=("Segoe UI", 10)).pack(side=tk.LEFT)
        tk.Label(df, text=f"${today_cost:.4f}" if today_cost > 0 else "$0.0000",
                 bg="#16213e", fg="#4F6EF7",
                 font=("Segoe UI", 14, "bold")).pack(side=tk.RIGHT)

        mf2 = tk.Frame(cf, bg="#16213e")
        mf2.pack(fill=tk.X, pady=(5, 0))
        tk.Label(mf2, text="本月消费", bg="#16213e", fg="#a0a0a0",
                 font=("Segoe UI", 10)).pack(side=tk.LEFT)
        tk.Label(mf2, text=f"${month_cost:.4f}" if month_cost > 0 else "$0.0000",
                 bg="#16213e", fg="#4F6EF7",
                 font=("Segoe UI", 14, "bold")).pack(side=tk.RIGHT)

        callf = tk.Frame(cf, bg="#16213e")
        callf.pack(fill=tk.X, pady=(5, 0))
        tk.Label(callf, text=f"今日调用 {today_calls} 次 | 本月 {month_calls} 次",
                 bg="#16213e", fg="#666666",
                 font=("Segoe UI", 9)).pack(anchor=tk.W)

        # 模型用量
        tk.Label(main_frame, text="🤖 各模型用量",
                 bg="#1a1a2e", fg="#ffffff",
                 font=("Segoe UI", 14, "bold")).pack(anchor=tk.W, pady=(10, 5))

        mf3 = tk.Frame(main_frame, bg="#16213e", padx=15, pady=10)
        mf3.pack(fill=tk.X)

        models_data = self.app.models_data
        if models_data:
            for model, data in models_data.items():
                row = tk.Frame(mf3, bg="#16213e")
                row.pack(fill=tk.X, pady=3)
                price_info = PRICING.get(model, {})
                display_name = price_info.get("name_cn", model)
                color = "#FF9800" if "flash" in model.lower() else "#E91E63"
                tk.Label(row, text=display_name, bg="#16213e", fg=color,
                         font=("Segoe UI", 11, "bold")).pack(side=tk.LEFT)
                tokens = data.get("today_tokens", 0)
                cost = data.get("today_cost_usd", 0)
                calls = data.get("today_calls", 0)
                tk.Label(row,
                         text=f"今日 {format_tokens(tokens)} · ${cost:.4f} · {calls}次",
                         bg="#16213e", fg="#a0a0a0",
                         font=("Segoe UI", 9)).pack(side=tk.RIGHT)
        else:
            tk.Label(mf3, text="暂无调用记录", bg="#16213e", fg="#666666",
                     font=("Segoe UI", 10)).pack()

        # 7天趋势
        tk.Label(main_frame, text="📈 近 7 天 Token 消耗趋势",
                 bg="#1a1a2e", fg="#ffffff",
                 font=("Segoe UI", 14, "bold")).pack(anchor=tk.W, pady=(10, 5))

        tf = tk.Frame(main_frame, bg="#16213e", padx=15, pady=10)
        tf.pack(fill=tk.X)

        trend = self.app.weekly_trend
        if trend:
            hf = tk.Frame(tf, bg="#16213e")
            hf.pack(fill=tk.X)
            for col, w in [("日期", 90), ("Tokens", 100), ("费用", 80), ("调用", 60)]:
                tk.Label(hf, text=col, bg="#16213e", fg="#888888",
                         font=("Segoe UI", 9, "bold"),
                         width=w//8).pack(side=tk.LEFT)
            for day in trend:
                df2 = tk.Frame(tf, bg="#16213e")
                df2.pack(fill=tk.X, pady=1)
                date_short = day["date"][5:]
                tk.Label(df2, text=date_short, bg="#16213e", fg="#cccccc",
                         font=("Segoe UI", 9), width=11,
                         anchor=tk.W).pack(side=tk.LEFT)
                tk.Label(df2, text=format_tokens(day["total_tokens"]),
                         bg="#16213e", fg="#4F6EF7",
                         font=("Segoe UI", 9), width=12,
                         anchor=tk.W).pack(side=tk.LEFT)
                tk.Label(df2,
                         text=f"${day['cost_usd']:.4f}" if day["cost_usd"] > 0 else "$0",
                         bg="#16213e", fg="#4CAF50",
                         font=("Segoe UI", 9), width=10,
                         anchor=tk.W).pack(side=tk.LEFT)
                tk.Label(df2, text=str(day["calls"]),
                         bg="#16213e", fg="#a0a0a0",
                         font=("Segoe UI", 9), width=7,
                         anchor=tk.W).pack(side=tk.LEFT)
        else:
            tk.Label(tf, text="暂无数据", bg="#16213e", fg="#666666",
                     font=("Segoe UI", 10)).pack()

        # 底部刷新信息
        if self.app.last_refresh_time:
            info_frame = tk.Frame(main_frame, bg="#1a1a2e")
            info_frame.pack(fill=tk.X, pady=(10, 0))
            tk.Label(info_frame,
                     text=f"数据来源: DeepSeek API  |  最后刷新: {self.app.last_refresh_time.strftime('%Y-%m-%d %H:%M:%S')}",
                     bg="#1a1a2e", fg="#555555",
                     font=("Segoe UI", 8)).pack()


# ═══════════════════════════════════════════════════════════
# 设置窗口
# ═══════════════════════════════════════════════════════════

class SettingsWindow:
    def __init__(self, app: DeepSeekTrayApp):
        self.app = app
        self.window = tk.Toplevel()
        self.window.title("DeepSeek 小工具 - 设置")
        self.window.geometry("480x360")
        self.window.resizable(False, False)
        self.window.configure(bg="#1a1a2e")
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._center_window()
        self.window.grab_set()
        self.window.focus_set()

    def _on_close(self):
        try:
            self.window.grab_release()
        except Exception:
            pass
        self.window.destroy()

    def _center_window(self):
        self.window.update_idletasks()
        w = self.window.winfo_width()
        h = self.window.winfo_height()
        sw = self.window.winfo_screenwidth()
        sh = self.window.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.window.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        main_frame = tk.Frame(self.window, bg="#1a1a2e", padx=25, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # API Key
        tk.Label(main_frame, text="🔑 DeepSeek API Key",
                 bg="#1a1a2e", fg="#ffffff",
                 font=("Segoe UI", 13, "bold")).pack(anchor=tk.W)
        tk.Label(main_frame,
                 text="在 platform.deepseek.com → API Keys 获取",
                 bg="#1a1a2e", fg="#888888",
                 font=("Segoe UI", 9)).pack(anchor=tk.W, pady=(0, 5))

        key_frame = tk.Frame(main_frame, bg="#1a1a2e")
        key_frame.pack(fill=tk.X)

        self.api_key_var = tk.StringVar(value=get_api_key())
        self.key_entry = tk.Entry(key_frame,
                                  textvariable=self.api_key_var,
                                  bg="#16213e", fg="#e0e0e0",
                                  font=("Consolas", 11),
                                  relief=tk.FLAT, bd=8,
                                  show="*", width=45)
        self.key_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.show_key_btn = tk.Button(key_frame, text="👁",
                                      bg="#16213e", fg="#888888",
                                      relief=tk.FLAT, bd=2, cursor="hand2",
                                      command=self._toggle_key_visibility,
                                      font=("Segoe UI", 10))
        self.show_key_btn.pack(side=tk.RIGHT, padx=(5, 0))
        self.key_hidden = True

        # 刷新间隔
        tk.Label(main_frame, text="\n⏱ 自动刷新间隔",
                 bg="#1a1a2e", fg="#ffffff",
                 font=("Segoe UI", 13, "bold")).pack(anchor=tk.W)

        interval_frame = tk.Frame(main_frame, bg="#1a1a2e")
        interval_frame.pack(fill=tk.X, pady=(5, 0))

        intervals = get_refresh_intervals()
        self.interval_var = tk.StringVar()
        current_interval = get_refresh_interval()

        for label, sec in intervals.items():
            rb = tk.Radiobutton(interval_frame, text=label,
                                variable=self.interval_var,
                                value=str(sec),
                                bg="#1a1a2e", fg="#e0e0e0",
                                selectcolor="#1a1a2e",
                                activebackground="#1a1a2e",
                                activeforeground="#4F6EF7",
                                font=("Segoe UI", 11),
                                indicatoron=False,
                                relief=tk.FLAT, bd=4, padx=12, pady=6)
            rb.pack(side=tk.LEFT, padx=(0, 8))
            if sec == current_interval:
                rb.select()

        # 底部按钮
        btn_frame = tk.Frame(main_frame, bg="#1a1a2e")
        btn_frame.pack(fill=tk.X, pady=(25, 0))

        tk.Button(btn_frame, text="💾 保存",
                  bg="#4F6EF7", fg="white",
                  font=("Segoe UI", 11, "bold"),
                  relief=tk.FLAT, bd=0, padx=25, pady=8,
                  cursor="hand2",
                  command=self._save).pack(side=tk.RIGHT, padx=(10, 0))

        tk.Button(btn_frame, text="取消",
                  bg="#333333", fg="#e0e0e0",
                  font=("Segoe UI", 11),
                  relief=tk.FLAT, bd=0, padx=25, pady=8,
                  cursor="hand2",
                  command=self._on_close).pack(side=tk.RIGHT)

        tk.Label(main_frame, text="\n💡 API Key 仅保存在本地，不会上传到任何第三方服务",
                 bg="#1a1a2e", fg="#555555",
                 font=("Segoe UI", 8)).pack(anchor=tk.W)

    def _toggle_key_visibility(self):
        if self.key_hidden:
            self.key_entry.config(show="")
            self.show_key_btn.config(text="🚫")
        else:
            self.key_entry.config(show="*")
            self.show_key_btn.config(text="👁")
        self.key_hidden = not self.key_hidden

    def _save(self):
        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showwarning("提示", "请输入 API Key")
            return
        set_api_key(api_key)
        self.app.api_key = api_key
        self.app.api = DeepSeekAPI(api_key)
        try:
            interval = int(self.interval_var.get())
            set_refresh_interval(interval)
            self.app.refresh_interval = interval
        except (ValueError, TypeError):
            pass
        self.app.refresh_data()
        self.app.icon.menu = self.app._recreate_menu()
        messagebox.showinfo("完成", "设置已保存！")
        self._on_close()
