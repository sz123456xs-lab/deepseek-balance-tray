"""
DeepSeek 余额查询小工具 - 启动入口
"""

import os
import sys

# 确保在正确的工作目录
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from tray_ui import DeepSeekTrayApp


def main():
    """主入口"""
    # 检查是否已有实例在运行 (简单防止多开)
    import socket

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 28999))
        sock.listen(1)
    except OSError:
        print("程序已在运行中")
        return

    app = DeepSeekTrayApp()
    app.run()


if __name__ == "__main__":
    main()
