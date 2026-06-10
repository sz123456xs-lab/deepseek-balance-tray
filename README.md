# DeepSeek 余额查询小工具

> Windows 任务栏系统托盘工具 - 便捷查看 DeepSeek API 用量与花费

## ✨ 功能

| 功能 | 说明 |
|------|------|
| 💰 余额查询 | 直接显示总余额、充值余额、赠送余额 |
| 📊 今日/本月消费 | 自动汇总当天和当月的 API 消费金额 |
| 🤖 分模型统计 | 分别统计 DeepSeek V4 Flash、V4 Pro 的调用量和费用 |
| 📈 7天 Token 趋势 | 显示最近 7 天的 Token 消耗变化趋势 |
| 🖥️ 任务栏图标 | 右键菜单即可查看，无需打开浏览器 |
| 🔄 自动刷新 | 支持 1分钟 / 5分钟 / 30分钟 自动更新数据 |
| 🔒 本地存储 | API Key 仅保存在本地，不经过第三方 |

## 🚀 快速开始

### 1. 获取 API Key

1. 登录 [platform.deepseek.com](https://platform.deepseek.com)
2. 左侧菜单 → **API Keys** → **Create new API key**
3. 复制生成的 `sk-xxx...` 密钥

### 2. 启动工具

双击 `run.bat` 启动，或：

```bash
cd deepseek-tray
venv\Scripts\activate
python main.py
```

### 3. 配置 API Key

1. 右键任务栏图标 → **设置**
2. 粘贴你的 DeepSeek API Key
3. 选择自动刷新间隔（1分钟/5分钟/30分钟）
4. 点击 **保存**

### 4. 查看数据

- 右键图标 → **查看详情** → 弹出详细窗口
- 任务栏图标文字会轮播显示余额和用量信息
- 鼠标悬停图标显示完整 tooltip

## 📁 项目结构

```
deepseek-tray/
├── main.py              # 启动入口
├── deepseek_api.py      # DeepSeek API 封装 (余额查询 + 定价计算)
├── tray_ui.py           # 状态栏图标 + 弹窗UI + 设置窗口
├── config.py            # 配置文件管理
├── record_usage.py      # API 调用记录工具 (可集成到其他项目)
├── usage_history.json   # 用量历史数据 (自动生成)
├── run.bat              # Windows 启动脚本
└── venv/                # Python 虚拟环境
```

## 📡 API 调用记录

工具默认只显示通过 **本地记录** 的 API 调用。如果你想自动记录你的 DeepSeek API 调用，可以集成 `record_usage.py`：

```python
# 在你的项目中使用 DeepSeek API 的地方
from record_usage import record_deepseek_call

# 方式1: 直接传入 API 响应对象 (OpenAI 兼容格式)
response = client.chat.completions.create(...)
record_deepseek_call(response)

# 方式2: 手动指定参数
record_deepseek_call(
    model="deepseek-v4-flash",
    input_tokens=150,
    output_tokens=50,
    cache_hit_tokens=100,
)
```

## 🔧 定价参考

基于 [DeepSeek 官方定价](https://api-docs.deepseek.com/quick_start/pricing) (2026):

| 模型 | 输入 (缓存命中) | 输入 (缓存未命中) | 输出 | 上下文 |
|------|:-:|:-:|:-:|:-:|
| DeepSeek V4 Flash | $0.0028/1M | $0.14/1M | $0.28/1M | 1M |
| DeepSeek V4 Pro | $0.003625/1M | $0.435/1M | $0.87/1M | 1M |

## ⚠️ 注意事项

- 首次启动时余额会正常显示，但消费数据需要先有 API 调用记录
- 建议使用专用于查询的 **只读 API Key**（在平台设置权限）
- API Key 存储位置: `~/.deepseek_tray/config.json`
