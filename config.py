"""
配置模块 - 管理 DeepSeek API Key 和刷新间隔
配置文件存储在用户目录下: ~/.deepseek_tray/config.json
"""

import json
import os
from typing import Optional


CONFIG_DIR = os.path.expanduser("~/.deepseek_tray")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


DEFAULT_CONFIG = {
    "api_key": "",
    "refresh_interval": 5 * 60,  # 默认5分钟 (单位: 秒)
    "refresh_intervals": {
        "1分钟": 60,
        "5分钟": 300,
        "30分钟": 1800,
    },
    "usd_to_cny_rate": 7.25,
    "theme": "dark",
    "show_in_status_bar": True,
    "status_bar_scroll_speed": 3,  # 轮播切换间隔 (秒)
}


def validate_api_key(key: str) -> bool:
    """简单校验 API key 格式"""
    return bool(key) and len(key) >= 10 and key.startswith(("sk-", "deepseek-"))


def load_config() -> dict:
    """加载配置文件"""
    if not os.path.exists(CONFIG_FILE):
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        # 填充缺失的默认值
        for k, v in DEFAULT_CONFIG.items():
            config.setdefault(k, v)
        return config
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_CONFIG)


def save_config(config: dict):
    """保存配置文件"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_api_key() -> str:
    """获取 API Key"""
    config = load_config()
    return config.get("api_key", "")


def set_api_key(key: str):
    """设置 API Key"""
    config = load_config()
    config["api_key"] = key
    save_config(config)


def get_refresh_interval() -> int:
    """获取刷新间隔 (秒)"""
    config = load_config()
    return config.get("refresh_interval", 300)


def set_refresh_interval(seconds: int):
    """设置刷新间隔 (秒)"""
    config = load_config()
    config["refresh_interval"] = seconds
    save_config(config)


def get_refresh_intervals() -> dict:
    """获取所有可选的刷新间隔"""
    config = load_config()
    return config.get("refresh_intervals", DEFAULT_CONFIG["refresh_intervals"])
