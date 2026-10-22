# -*- coding: utf-8 -*-
"""launcher.py —— 打包成 exe 后的唯一入口，按参数分派到面板或托盘

    VGN键盘电量.exe            打开简洁面板（等同双击）
    VGN键盘电量.exe --panel    打开简洁面板
    VGN键盘电量.exe --tray     启动托盘（开机自启用的就是这个）
    VGN键盘电量.exe --quit     让正在运行的托盘退出
    VGN键盘电量.exe --status   打印托盘/自启状态
    VGN键盘电量.exe --once     命令行读一次电量就退出

源码模式下不需要它：直接 python my_devices.py / python tray_app.py 即可。
"""

import sys

TRAY_FLAGS = ("--tray", "--quit", "--status", "--debug")


def _attach_console() -> None:
    """noconsole 的 exe 被 cmd 启动时，把输出接到父进程的控制台。

    不做这一步，--once / --status 在黑窗口里看不到任何结果。
    """
    if sys.stdout is not None:
        return
    try:
        import ctypes
        if not ctypes.windll.kernel32.AttachConsole(-1):
            return
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)      # UTF-8，中文不乱码
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace",
                          buffering=1)
        sys.stderr = sys.stdout
    except Exception:
        pass


def main() -> int:
    argv = sys.argv[1:]
    if any(a in ("--once", "--status", "--quit", "--diag") for a in argv):
        _attach_console()

    if any(a in TRAY_FLAGS for a in argv):
        # --tray 只是"启动托盘"的标记，tray_app 自己的 argparse 不认识它
        sys.argv = [sys.argv[0]] + [a for a in argv if a != "--tray"]
        import tray_app
        return tray_app.main()

    sys.argv = [sys.argv[0]] + [a for a in argv if a != "--panel"]
    import my_devices
    my_devices.main()
    return 0


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main())
