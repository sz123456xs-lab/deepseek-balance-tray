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
    import socket

    lock_port = 28999
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # 允许地址重用，避免强制关闭后端口 TIME_WAIT 导致无法启动
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", lock_port))
        sock.listen(1)
    except OSError:
        print("程序已在运行中")
        return
    except Exception as e:
        print(f"启动检查失败: {e}")
        return

    app = DeepSeekTrayApp()
    try:
        app.run()
    except Exception as e:
        print(f"程序运行出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            if sock:
                sock.close()
        except Exception:
            pass

    # 显式退出进程 (确保 pythonw.exe 不会残留)
    os._exit(0)


if __name__ == "__main__":
    main()
