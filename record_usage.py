"""
DeepSeek 调用记录工具 - 用于记录每次 API 调用的 Token 用量
可集成到任何调用 DeepSeek API 的 Python 项目中

使用方法:
    from record_usage import record_deepseek_call

    # 在你的 API 调用代码中
    response = ...  # 你的 DeepSeek API 响应
    record_deepseek_call(response)

或者手动记录:
    record_deepseek_call(
        model="deepseek-v4-flash",
        input_tokens=150,
        output_tokens=50,
        cache_hit_tokens=100,
    )
"""

import json
import os

USAGE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usage_history.json")


def record_deepseek_call(response_or_model, input_tokens=None, output_tokens=None,
                         cache_hit_tokens=0, cost_usd=None):
    """
    记录一次 DeepSeek API 调用

    用法 1 - 传入 API 响应对象 (支持 OpenAI 格式):
        record_deepseek_call(response)

    用法 2 - 手动指定参数:
        record_deepseek_call("deepseek-v4-flash", input_tokens=150, output_tokens=50)

    参数:
        response_or_model: OpenAI 格式的 API 响应，或模型名字符串
        input_tokens: 手动指定输入 tokens
        output_tokens: 手动指定输出 tokens
        cache_hit_tokens: 缓存命中的 tokens (用于费用计算)
        cost_usd: 手动指定费用 (USD)，如果不传则根据定价自动计算
    """
    if isinstance(response_or_model, str):
        # 手动记录模式
        model = response_or_model
        inp = input_tokens or 0
        out = output_tokens or 0
        cache = cache_hit_tokens or 0
        cost = cost_usd
    else:
        # 从 API 响应中提取 (OpenAI 兼容格式)
        resp = response_or_model
        model = resp.get("model", "unknown")
        usage = resp.get("usage", {}) or {}
        inp = usage.get("prompt_tokens", 0) or 0
        out = usage.get("completion_tokens", 0) or 0
        # DeepSeek 在 usage 中有 prompt_cache_hit_tokens
        cache = usage.get("prompt_cache_hit_tokens", 0) or 0
        cost = None  # 从响应中不直接获取费用

    if cost is None:
        # 尝试自动计算费用
        from deepseek_api import calculate_cost
        cost = calculate_cost(model, inp, out, cache)

    from deepseek_api import UsageTracker
    tracker = UsageTracker()
    tracker.record_call(model, inp, out, cache, cost)
