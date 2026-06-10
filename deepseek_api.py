"""
DeepSeek API 后端模块
- 查询余额 (GET /user/balance)
- 根据 token 用量和价格计算消费
- 由于 DeepSeek 没有提供官方的历史用量 API，我们通过 balance 变化 + 本地记录来估算
"""

import json
import os
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

# 价格配置 (per 1M tokens, USD)
# 来源: https://api-docs.deepseek.com/quick_start/pricing
PRICING = {
    "deepseek-v4-flash": {
        "input_cache_hit": 0.0028,
        "input_cache_miss": 0.14,
        "output": 0.28,
        "name_cn": "DeepSeek V4 Flash",
    },
    "deepseek-v4-pro": {
        "input_cache_hit": 0.003625,
        "input_cache_miss": 0.435,
        "output": 0.87,
        "name_cn": "DeepSeek V4 Pro",
    },
}

# 汇率 (USD -> CNY, 粗略估算)
USD_TO_CNY = 7.25


class DeepSeekAPI:
    """DeepSeek 官方 API 封装"""

    BASE_URL = "https://api.deepseek.com"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        })

    def get_balance(self) -> dict:
        """查询余额
        返回格式:
        {
            "is_available": bool,
            "balance_infos": [{
                "currency": "CNY" | "USD",
                "total_balance": str,
                "granted_balance": str,
                "topped_up_balance": str,
            }]
        }
        """
        resp = self.session.get(f"{self.BASE_URL}/user/balance", timeout=15)
        resp.raise_for_status()
        return resp.json()

    def list_models(self) -> list:
        """列出可用模型"""
        resp = self.session.get(f"{self.BASE_URL}/models", timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])

    def simple_balance_report(self) -> dict:
        """获取简洁的余额报告"""
        balance_data = self.get_balance()
        is_available = balance_data.get("is_available", False)

        infos = balance_data.get("balance_infos", [])
        if not infos:
            return {"error": "无余额信息", "is_available": is_available}

        info = infos[0]
        currency = info.get("currency", "CNY")
        total = float(info.get("total_balance", "0"))
        granted = float(info.get("granted_balance", "0"))
        topped_up = float(info.get("topped_up_balance", "0"))

        return {
            "currency": currency,
            "total_balance": total,
            "granted_balance": granted,
            "topped_up_balance": topped_up,
            "is_available": is_available,
        }


class UsageTracker:
    """用量跟踪 - 通过本地记录 API 调用历史来统计各模型用量"""

    DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usage_history.json")

    def __init__(self):
        self.history = self._load()

    def _load(self) -> list:
        if os.path.exists(self.DATA_FILE):
            try:
                with open(self.DATA_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return []
        return []

    def _save(self):
        os.makedirs(os.path.dirname(self.DATA_FILE), exist_ok=True)
        with open(self.DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)

    def record_call(self, model: str, input_tokens: int, output_tokens: int,
                    cache_hit_tokens: int = 0, cost_usd: float = 0):
        """记录一次 API 调用"""
        now = datetime.now()
        record = {
            "timestamp": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_hit_tokens": cache_hit_tokens,
            "cost_usd": round(cost_usd, 6),
        }
        self.history.append(record)
        # 只保留最近 90 天的记录
        cutoff = (now - timedelta(days=90)).isoformat()
        self.history = [r for r in self.history if r["timestamp"] >= cutoff]
        self._save()

    def get_today_summary(self) -> dict:
        """获取今日用量汇总"""
        today = datetime.now().strftime("%Y-%m-%d")
        today_calls = [r for r in self.history if r["date"] == today]

        by_model = {}
        total_cost = 0.0
        total_input = 0
        total_output = 0

        for r in today_calls:
            model = r["model"]
            if model not in by_model:
                by_model[model] = {
                    "input_tokens": 0, "output_tokens": 0,
                    "cache_hit_tokens": 0, "cost_usd": 0.0, "calls": 0,
                }
            by_model[model]["input_tokens"] += r["input_tokens"]
            by_model[model]["output_tokens"] += r["output_tokens"]
            by_model[model]["cache_hit_tokens"] += r.get("cache_hit_tokens", 0)
            by_model[model]["cost_usd"] += r["cost_usd"]
            by_model[model]["calls"] += 1
            total_cost += r["cost_usd"]
            total_input += r["input_tokens"]
            total_output += r["output_tokens"]

        return {
            "date": today,
            "total_cost_usd": round(total_cost, 4),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_calls": len(today_calls),
            "by_model": by_model,
        }

    def get_month_summary(self) -> dict:
        """获取本月用量汇总"""
        this_month = datetime.now().strftime("%Y-%m")
        month_calls = [r for r in self.history if r["date"].startswith(this_month)]

        by_model = {}
        total_cost = 0.0

        for r in month_calls:
            model = r["model"]
            if model not in by_model:
                by_model[model] = {
                    "input_tokens": 0, "output_tokens": 0,
                    "cache_hit_tokens": 0, "cost_usd": 0.0, "calls": 0,
                }
            by_model[model]["input_tokens"] += r["input_tokens"]
            by_model[model]["output_tokens"] += r["output_tokens"]
            by_model[model]["cost_usd"] += r["cost_usd"]
            by_model[model]["calls"] += 1
            total_cost += r["cost_usd"]

        return {
            "month": this_month,
            "total_cost_usd": round(total_cost, 4),
            "total_calls": len(month_calls),
            "by_model": by_model,
        }

    def get_weekly_trend(self) -> list:
        """获取最近 7 天的 Token 消耗趋势"""
        today = datetime.now()
        trend = []
        for i in range(6, -1, -1):
            day = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            day_calls = [r for r in self.history if r["date"] == day]

            total_input = sum(r["input_tokens"] for r in day_calls)
            total_output = sum(r["output_tokens"] for r in day_calls)
            total_cost = sum(r["cost_usd"] for r in day_calls)

            trend.append({
                "date": day,
                "input_tokens": total_input,
                "output_tokens": total_output,
                "total_tokens": total_input + total_output,
                "cost_usd": round(total_cost, 4),
                "calls": len(day_calls),
            })
        return trend

    def get_models_summary(self) -> dict:
        """获取 V4 Flash / V4 Pro 的用量统计"""
        today = self.get_today_summary()
        month = self.get_month_summary()

        models_data = {}
        all_model_names = set()
        for r in today.get("by_model", {}):
            all_model_names.add(r)
        for r in month.get("by_model", {}):
            all_model_names.add(r)

        for model in all_model_names:
            today_m = today.get("by_model", {}).get(model, {})
            month_m = month.get("by_model", {}).get(model, {})
            models_data[model] = {
                "today_tokens": (today_m.get("input_tokens", 0) +
                                 today_m.get("output_tokens", 0)),
                "today_cost_usd": today_m.get("cost_usd", 0),
                "today_calls": today_m.get("calls", 0),
                "month_tokens": (month_m.get("input_tokens", 0) +
                                 month_m.get("output_tokens", 0)),
                "month_cost_usd": month_m.get("cost_usd", 0),
                "month_calls": month_m.get("calls", 0),
            }

        return models_data


def format_currency(amount: float, currency: str = "CNY") -> str:
    """格式化货币显示"""
    if currency == "CNY":
        return f"¥{amount:.2f}"
    else:
        return f"${amount:.2f}"


def format_tokens(n: int) -> str:
    """格式化 Token 数量显示"""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    elif n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def calculate_cost(model: str, input_tokens: int, output_tokens: int,
                   cache_hit_tokens: int = 0) -> float:
    """根据模型和用量计算费用 (USD)"""
    pricing = PRICING.get(model)
    if not pricing:
        return 0.0

    cache_miss_input = input_tokens - cache_hit_tokens
    if cache_miss_input < 0:
        cache_miss_input = 0

    cost = (
        cache_hit_tokens / 1_000_000 * pricing["input_cache_hit"]
        + cache_miss_input / 1_000_000 * pricing["input_cache_miss"]
        + output_tokens / 1_000_000 * pricing["output"]
    )
    return cost
