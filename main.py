"""
DeepSeek 余额查询小工具 - 启动入口

设计原则：
1. 单实例保护：socket 绑定（带 SO_REUSEADDR 防 TIME_WAIT）
2. atexit 注册清理，确保 pythonw.exe 彻底退出
3. 异常捕获 + 弹窗显示错误（避免静默失败）
"""
import os
import sys
import socket
import atexit

# 确保工作目录正确
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from tray_ui import DeepSeekTrayApp

# ── 全局 socket 锁 ──
LOCK_PORT = 28999
_lock_sock = None


def _cleanup():
    """退出时清理 socket 锁，确保进程死亡"""
    global _lock_sock
    if _lock_sock:
        try:
            _lock_sock.close()
        except Exception:
            pass
        _lock_sock = None


def acquire_lock() -> bool:
    """尝试获取单实例锁。成功返回 True，失败返回 False。"""
    global _lock_sock
    try:
        _lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _lock_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _lock_sock.bind(("127.0.0.1", LOCK_PORT))
        _lock_sock.listen(1)
        atexit.register(_cleanup)
        return True
    except OSError:
        print("程序已在运行中")
        return False
    except Exception as e:
        print(f"启动检查失败: {e}")
        return False


def main():
    if not acquire_lock():
        sys.exit(0)

    app = None
    exit_code = 0
    try:
        app = DeepSeekTrayApp()
        app.run()
    except SystemExit:
        # pystray.run() 正常退出
        pass
    except Exception as e:
        print(f"程序运行出错: {e}")
        import traceback
        traceback.print_exc()
        exit_code = 1
    finally:
        _cleanup()

    # 确保 pythonw.exe 进程死亡
    # 注意：不能用 os._exit(0)，否则 atexit 不执行
    # 但在 main() 末尾正常 return 即可，pystray 停止后主线程会结束
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
