"""
状态栏图标 + 弹窗界面模块
- 系统托盘图标 (pystray)
- 右键菜单
- 弹窗详情窗口 (tkinter)
- 状态栏余额轮播显示
"""

import json
import os
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

    # ---- 图标尺寸 ----
    ICON_SIZE = 64
    TOOLTIP_PREFIX = "DeepSeek 余额"

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

        # 状态栏轮播相关
        self.status_bar_items = []  # 轮播文本列表
        self.status_index = 0       # 当前轮播位置
        self.scroll_speed = self.config.get("status_bar_scroll_speed", 3)

        # 初始化 API 客户端
        self.api = None
        if self.api_key:
            self.api = DeepSeekAPI(self.api_key)

        # 自动刷新定时器
        self._refresh_timer = None

        # 创建图标
        self.icon = None
        self._create_icon()

        # 立即刷新数据
        self.refresh_data()

    def _create_icon(self):
        """创建托盘图标"""
        icon_image = self._generate_icon("D")
        # D 代表 DeepSeek
        self.icon = pystray.Icon(
            "deepseek_tray",
            icon_image,
            f"{self.TOOLTIP_PREFIX} | 加载中...",
            self._create_menu(),
        )

    def _generate_icon(self, text: str, bg_color: str = "#4F6EF7") -> Image.Image:
        """生成图标 (带文字的方块图标)"""
        img = Image.new("RGBA", (self.ICON_SIZE, self.ICON_SIZE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # 画圆角矩形背景
        margin = 2
        draw.rounded_rectangle(
            [margin, margin, self.ICON_SIZE - margin, self.ICON_SIZE - margin],
            radius=12,
            fill=bg_color,
        )

        # 尝试使用系统字体显示文字
        try:
            font_size = int(self.ICON_SIZE * 0.55)
            font = ImageFont.truetype("arial.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

        # 居中文字
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (self.ICON_SIZE - tw) / 2
        y = (self.ICON_SIZE - th) / 2 - 1
        draw.text((x, y), text, fill="white", font=font)

        return img

    def _create_menu(self):
        """创建右键菜单"""
        return pystray.Menu(
            pystray.MenuItem("📊 查看详情", self._show_detail_window, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("🔄 刷新数据", self._on_refresh),
            pystray.MenuItem("⚙️ 设置", self._show_settings_window),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "🔁 自动刷新: " + self._get_interval_label(),
                self._cycle_refresh_interval,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("❌ 退出", self._on_exit),
        )

    def _get_interval_label(self) -> str:
        """获取当前刷新间隔的文字标签"""
        intervals = get_refresh_intervals()
        for label, sec in intervals.items():
            if sec == self.refresh_interval:
                return label
        return f"{self.refresh_interval // 60}分钟"

    def _cycle_refresh_interval(self, icon, item):
        """循环切换刷新间隔"""
        intervals = list(get_refresh_intervals().values())
        current_index = intervals.index(self.refresh_interval) if self.refresh_interval in intervals else -1
        next_index = (current_index + 1) % len(intervals)
        self.refresh_interval = intervals[next_index]
        set_refresh_interval(self.refresh_interval)
        self._start_auto_refresh()
        self._update_tooltip()
        self.icon.menu = self._create_menu()

    def _start_auto_refresh(self):
        """启动自动刷新定时器"""
        if self._refresh_timer:
            self._refresh_timer.cancel()
        self._refresh_timer = threading.Timer(self.refresh_interval, self._auto_refresh)
        self._refresh_timer.daemon = True
        self._refresh_timer.start()

    def _auto_refresh(self):
        """自动刷新回调"""
        self.refresh_data()
        self._start_auto_refresh()

    def refresh_data(self):
        """刷新所有数据"""
        if not self.api:
            self.error_message = "请先配置 API Key"
            self._update_tooltip()
            return

        try:
            # 查询余额
            self.balance_data = self.api.simple_balance_report()

            # 获取今日/本月/模型用量
            self.today_data = self.usage_tracker.get_today_summary()
            self.month_data = self.usage_tracker.get_month_summary()
            self.weekly_trend = self.usage_tracker.get_weekly_trend()
            self.models_data = self.usage_tracker.get_models_summary()

            self.last_refresh_time = datetime.now()
            self.error_message = ""

            # 更新状态栏轮播项
            self._update_status_bar_items()

        except Exception as e:
            self.error_message = str(e)

        self._update_tooltip()

    def _update_status_bar_items(self):
        """构建状态栏轮播文本列表"""
        items = []
        balance = self.balance_data

        if balance:
            currency = balance.get("currency", "CNY")
            total = balance.get("total_balance", 0)
            items.append(f"余额: {format_currency(total, currency)}")

        # 今天消费
        today_cost = self.today_data.get("total_cost_usd", 0)
        if today_cost > 0:
            items.append(f"今日: ${today_cost:.4f}")
        else:
            items.append("今日: $0")

        # 本月消费
        month_cost = self.month_data.get("total_cost_usd", 0)
        if month_cost > 0:
            items.append(f"本月: ${month_cost:.4f}")

        # 各模型用量
        for model, data in self.models_data.items():
            short_name = model.replace("deepseek-", "DS ").replace("-", " ")
            tokens_today = data.get("today_tokens", 0)
            if tokens_today > 0:
                items.append(f"{short_name}: {format_tokens(tokens_today)}")

        if not items:
            items.append("DeepSeek 余额")

        self.status_bar_items = items
        self.status_index = 0

    def _update_tooltip(self):
        """更新托盘图标的工具提示"""
        lines = []

        balance = self.balance_data
        if balance:
            currency = balance.get("currency", "CNY")
            total = balance.get("total_balance", 0)
            granted = balance.get("granted_balance", 0)
            topped_up = balance.get("topped_up_balance", 0)
            lines.append(f"💰 余额: {format_currency(total, currency)}")
            lines.append(f"   充值: {format_currency(topped_up, currency)}")
            lines.append(f"   赠送: {format_currency(granted, currency)}")
        else:
            lines.append("余额查询中...")

        today_cost = self.today_data.get("total_cost_usd", 0)
        if today_cost > 0:
            lines.append(f"📊 今日消费: ${today_cost:.4f}")
        month_cost = self.month_data.get("total_cost_usd", 0)
        lines.append(f"📅 本月消费: ${month_cost:.4f}")

        if self.error_message:
            lines.append(f"⚠️ {self.error_message}")

        if self.last_refresh_time:
            lines.append(f"🔄 {self.last_refresh_time.strftime('%H:%M:%S')}")

        self.icon.title = "\n".join(lines)

        # 更新托盘图标为轮播文字
        self._update_icon_text()

    def _update_icon_text(self):
        """根据轮播更新图标文字"""
        if self.status_bar_items:
            text = self.status_bar_items[self.status_index % len(self.status_bar_items)]
            # 取前2个字符作为图标标识
            icon_char = text[:2] if len(text) >= 2 else text[:1]
            self.icon.icon = self._generate_icon(icon_char)
            self.status_index += 1

        # 定时轮播
        if self.scroll_speed > 0:
            threading.Timer(self.scroll_speed, self._update_icon_text).start()

    def _on_refresh(self, icon, item):
        """刷新按钮回调"""
        self.refresh_data()

    def _show_detail_window(self, icon, item):
        """显示详情窗口"""
        self.refresh_data()
        window = DetailWindow(self)

    def _show_settings_window(self, icon=None, item=None):
        """显示设置窗口"""
        window = SettingsWindow(self)

    def _on_exit(self, icon, item):
        """退出程序"""
        if self._refresh_timer:
            self._refresh_timer.cancel()
        self.icon.stop()

    def run(self):
        """运行应用"""
        # 启动自动刷新
        self._start_auto_refresh()
        self.icon.run()


class DetailWindow:
    """详情弹窗 - 显示余额、消费、用量详情"""

    def __init__(self, app: DeepSeekTrayApp):
        self.app = app
        self.window = tk.Toplevel()
        self.window.title("DeepSeek 余额详情")
        self.window.geometry("520x580")
        self.window.resizable(False, False)
        self.window.configure(bg="#1a1a2e")

        # 设置窗口样式
        self.style = ttk.Style()
        self.style.theme_use("clam")

        # 自定义样式
        self.style.configure("Dark.TFrame", background="#1a1a2e")
        self.style.configure("Dark.TLabel", background="#1a1a2e", foreground="#e0e0e0")
        self.style.configure("Header.TLabel", background="#1a1a2e", foreground="#ffffff",
                             font=("Segoe UI", 14, "bold"))
        self.style.configure("Value.TLabel", background="#1a1a2e", foreground="#4F6EF7",
                             font=("Segoe UI", 18, "bold"))
        self.style.configure("SubValue.TLabel", background="#1a1a2e", foreground="#a0a0a0",
                             font=("Segoe UI", 10))
        self.style.configure("Green.TLabel", background="#1a1a2e", foreground="#4CAF50",
                             font=("Segoe UI", 12, "bold"))
        self.style.configure("ModelFlash.TLabel", background="#1a1a2e", foreground="#FF9800",
                             font=("Segoe UI", 11, "bold"))
        self.style.configure("ModelPro.TLabel", background="#1a1a2e", foreground="#E91E63",
                             font=("Segoe UI", 11, "bold"))

        self._build_ui()
        self._center_window()
        self.window.grab_set()
        self.window.focus_set()

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
        """构建界面"""
        main_frame = tk.Frame(self.window, bg="#1a1a2e", padx=20, pady=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ===== 余额区域 =====
        balance = self.app.balance_data
        if balance:
            currency = balance.get("currency", "CNY")
            total = balance.get("total_balance", 0)
            granted = balance.get("granted_balance", 0)
            topped_up = balance.get("topped_up_balance", 0)
            is_avail = balance.get("is_available", False)

            header = tk.Label(main_frame, text="💰 账户余额",
                              bg="#1a1a2e", fg="#ffffff",
                              font=("Segoe UI", 14, "bold"))
            header.pack(anchor=tk.W)

            balance_frame = tk.Frame(main_frame, bg="#16213e", padx=15, pady=12)
            balance_frame.pack(fill=tk.X, pady=(5, 10))

            total_label = tk.Label(balance_frame,
                                   text=format_currency(total, currency),
                                   bg="#16213e", fg="#4F6EF7",
                                   font=("Segoe UI", 26, "bold"))
            total_label.pack(anchor=tk.W)

            sub_frame = tk.Frame(balance_frame, bg="#16213e")
            sub_frame.pack(fill=tk.X, pady=(3, 0))
            tk.Label(sub_frame, text=f"充值: {format_currency(topped_up, currency)}",
                     bg="#16213e", fg="#4CAF50", font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=(0, 15))
            tk.Label(sub_frame, text=f"赠送: {format_currency(granted, currency)}",
                     bg="#16213e", fg="#FF9800", font=("Segoe UI", 10)).pack(side=tk.LEFT)
            tk.Label(sub_frame, text="● 可用" if is_avail else "● 不可用",
                     bg="#16213e", fg=("#4CAF50" if is_avail else "#ff4444"),
                     font=("Segoe UI", 9, "bold")).pack(side=tk.RIGHT)

        # ===== 消费区域 =====
        tk.Label(main_frame, text="📊 消费概览",
                 bg="#1a1a2e", fg="#ffffff",
                 font=("Segoe UI", 14, "bold")).pack(anchor=tk.W, pady=(10, 5))

        today_cost = self.app.today_data.get("total_cost_usd", 0)
        month_cost = self.app.month_data.get("total_cost_usd", 0)

        cost_frame = tk.Frame(main_frame, bg="#16213e", padx=15, pady=10)
        cost_frame.pack(fill=tk.X)

        # 今日消费
        day_frame = tk.Frame(cost_frame, bg="#16213e")
        day_frame.pack(fill=tk.X)
        tk.Label(day_frame, text="今日消费",
                 bg="#16213e", fg="#a0a0a0", font=("Segoe UI", 10)).pack(side=tk.LEFT)
        tk.Label(day_frame, text=f"${today_cost:.4f}" if today_cost > 0 else "$0.0000",
                 bg="#16213e", fg="#4F6EF7", font=("Segoe UI", 14, "bold")).pack(side=tk.RIGHT)

        # 本月消费
        month_frame = tk.Frame(cost_frame, bg="#16213e")
        month_frame.pack(fill=tk.X, pady=(5, 0))
        tk.Label(month_frame, text="本月消费",
                 bg="#16213e", fg="#a0a0a0", font=("Segoe UI", 10)).pack(side=tk.LEFT)
        tk.Label(month_frame, text=f"${month_cost:.4f}" if month_cost > 0 else "$0.0000",
                 bg="#16213e", fg="#4F6EF7", font=("Segoe UI", 14, "bold")).pack(side=tk.RIGHT)

        today_calls = self.app.today_data.get("total_calls", 0)
        month_calls = self.app.month_data.get("total_calls", 0)
        calls_frame = tk.Frame(cost_frame, bg="#16213e")
        calls_frame.pack(fill=tk.X, pady=(5, 0))
        tk.Label(calls_frame, text=f"今日调用 {today_calls} 次 | 本月 {month_calls} 次",
                 bg="#16213e", fg="#666666", font=("Segoe UI", 9)).pack(anchor=tk.W)

        # ===== 模型用量区域 =====
        tk.Label(main_frame, text="🤖 各模型用量",
                 bg="#1a1a2e", fg="#ffffff",
                 font=("Segoe UI", 14, "bold")).pack(anchor=tk.W, pady=(10, 5))

        models_frame = tk.Frame(main_frame, bg="#16213e", padx=15, pady=10)
        models_frame.pack(fill=tk.X)

        models_data = self.app.models_data
        if models_data:
            for model, data in models_data.items():
                mf = tk.Frame(models_frame, bg="#16213e")
                mf.pack(fill=tk.X, pady=3)

                name = model
                price_info = PRICING.get(model, {})
                display_name = price_info.get("name_cn", model)

                # 模型名 + 颜色
                color = "#FF9800" if "flash" in model.lower() else "#E91E63"
                tk.Label(mf, text=display_name, bg="#16213e", fg=color,
                         font=("Segoe UI", 11, "bold")).pack(side=tk.LEFT)

                # 用量
                tokens = data.get("today_tokens", 0)
                cost = data.get("today_cost_usd", 0)
                calls = data.get("today_calls", 0)

                tk.Label(mf, text=f"今日 {format_tokens(tokens)} · ${cost:.4f} · {calls}次",
                         bg="#16213e", fg="#a0a0a0",
                         font=("Segoe UI", 9)).pack(side=tk.RIGHT)
        else:
            tk.Label(models_frame, text="暂无调用记录", bg="#16213e", fg="#666666",
                     font=("Segoe UI", 10)).pack()

        # ===== 7天趋势区域 =====
        tk.Label(main_frame, text="📈 近 7 天 Token 消耗趋势",
                 bg="#1a1a2e", fg="#ffffff",
                 font=("Segoe UI", 14, "bold")).pack(anchor=tk.W, pady=(10, 5))

        trend_frame = tk.Frame(main_frame, bg="#16213e", padx=15, pady=10)
        trend_frame.pack(fill=tk.X)

        trend = self.app.weekly_trend
        if trend:
            # 表头
            hf = tk.Frame(trend_frame, bg="#16213e")
            hf.pack(fill=tk.X)
            for col, w in [("日期", 90), ("Tokens", 100), ("费用", 80), ("调用", 60)]:
                tk.Label(hf, text=col, bg="#16213e", fg="#888888",
                         font=("Segoe UI", 9, "bold"), width=w//8).pack(side=tk.LEFT)

            for day in trend:
                df = tk.Frame(trend_frame, bg="#16213e")
                df.pack(fill=tk.X, pady=1)
                # 日期短格式
                date_short = day["date"][5:]  # MM-DD
                tk.Label(df, text=date_short, bg="#16213e", fg="#cccccc",
                         font=("Segoe UI", 9), width=11, anchor=tk.W).pack(side=tk.LEFT)
                tk.Label(df, text=format_tokens(day["total_tokens"]),
                         bg="#16213e", fg="#4F6EF7",
                         font=("Segoe UI", 9), width=12, anchor=tk.W).pack(side=tk.LEFT)
                tk.Label(df, text=f"${day['cost_usd']:.4f}" if day['cost_usd'] > 0 else "$0",
                         bg="#16213e", fg="#4CAF50",
                         font=("Segoe UI", 9), width=10, anchor=tk.W).pack(side=tk.LEFT)
                tk.Label(df, text=str(day["calls"]),
                         bg="#16213e", fg="#a0a0a0",
                         font=("Segoe UI", 9), width=7, anchor=tk.W).pack(side=tk.LEFT)

        else:
            tk.Label(trend_frame, text="暂无数据", bg="#16213e", fg="#666666",
                     font=("Segoe UI", 10)).pack()

        # 底部刷新信息
        if self.app.last_refresh_time:
            info_frame = tk.Frame(main_frame, bg="#1a1a2e")
            info_frame.pack(fill=tk.X, pady=(10, 0))
            tk.Label(info_frame,
                     text=f"数据来源: DeepSeek API   |   最后刷新: {self.app.last_refresh_time.strftime('%Y-%m-%d %H:%M:%S')}   |   自动刷新: {self._get_interval_label()}",
                     bg="#1a1a2e", fg="#555555",
                     font=("Segoe UI", 8)).pack()

            if self.app.error_message:
                tk.Label(info_frame, text=f"⚠️ {self.app.error_message}",
                         bg="#1a1a2e", fg="#ff4444",
                         font=("Segoe UI", 9)).pack()

    def _get_interval_label(self) -> str:
        intervals = get_refresh_intervals()
        for label, sec in intervals.items():
            if sec == self.app.refresh_interval:
                return label
        return f"{self.app.refresh_interval // 60}分钟"


class SettingsWindow:
    """设置窗口 - 配置 API Key 和刷新间隔"""

    def __init__(self, app: DeepSeekTrayApp):
        self.app = app
        self.window = tk.Toplevel()
        self.window.title("DeepSeek 小工具 - 设置")
        self.window.geometry("480x360")
        self.window.resizable(False, False)
        self.window.configure(bg="#1a1a2e")

        self._build_ui()
        self._center_window()
        self.window.grab_set()
        self.window.focus_set()

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

        # ===== API Key =====
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

        self.show_key_btn = tk.Button(key_frame, text="👁", bg="#16213e", fg="#888888",
                                       relief=tk.FLAT, bd=2, cursor="hand2",
                                       command=self._toggle_key_visibility,
                                       font=("Segoe UI", 10))
        self.show_key_btn.pack(side=tk.RIGHT, padx=(5, 0))
        self.key_hidden = True

        # ===== 刷新间隔 =====
        tk.Label(main_frame, text="\n⏱ 自动刷新间隔",
                 bg="#1a1a2e", fg="#ffffff",
                 font=("Segoe UI", 13, "bold")).pack(anchor=tk.W)

        interval_frame = tk.Frame(main_frame, bg="#1a1a2e")
        interval_frame.pack(fill=tk.X, pady=(5, 0))

        intervals = get_refresh_intervals()
        self.interval_var = tk.StringVar()
        current_interval = get_refresh_interval()

        for i, (label, sec) in enumerate(intervals.items()):
            rb = tk.Radiobutton(interval_frame, text=label,
                                 variable=self.interval_var,
                                 value=str(sec),
                                 bg="#1a1a2e", fg="#e0e0e0",
                                 selectcolor="#1a1a2e",
                                 activebackground="#1a1a2e",
                                 activeforeground="#4F6EF7",
                                 font=("Segoe UI", 11),
                                 indicatoron=False,
                                 relief=tk.FLAT,
                                 bd=4, padx=12, pady=6)
            rb.pack(side=tk.LEFT, padx=(0, 8))
            if sec == current_interval:
                rb.select()

        # ===== 底部按钮 =====
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
                   command=self.window.destroy).pack(side=tk.RIGHT)

        # 提示信息
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

        # 保存 API Key
        set_api_key(api_key)
        self.app.api_key = api_key
        self.app.api = DeepSeekAPI(api_key)

        # 保存间隔
        try:
            interval = int(self.interval_var.get())
            set_refresh_interval(interval)
            self.app.refresh_interval = interval
        except (ValueError, TypeError):
            pass

        # 刷新数据
        self.app.refresh_data()
        self.app.icon.menu = self.app._create_menu()

        messagebox.showinfo("完成", "设置已保存！")
        self.window.destroy()
