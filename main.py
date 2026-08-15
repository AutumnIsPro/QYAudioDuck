# -*- coding: utf-8 -*-
"""音频自动闪避助手 — 启动入口。"""
import importlib
import os
import sys
import traceback

REQUIRED = ("customtkinter", "pycaw", "comtypes", "psutil", "sounddevice", "numpy")

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "error.log")


def _setup_stdio():
    """避免控制台 GBK 编码打印中文报错时二次崩溃。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _report_error(exc):
    """把异常写入 error.log 并弹窗提示。"""
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 60 + "\n")
            f.write(traceback.format_exc())
            f.write("=" * 60 + "\n")
    except Exception:
        pass
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "音频自动闪避助手 - 启动失败",
            "程序启动时发生错误：\n\n%s\n\n详细信息已写入 error.log" % exc,
        )
        root.destroy()
    except Exception:
        pass


def check_deps():
    """检查必需依赖, 返回缺失列表。"""
    missing = []
    for mod in REQUIRED:
        try:
            importlib.import_module(mod)
        except Exception:
            missing.append(mod)
    return missing


def main():
    _setup_stdio()
    try:
        missing = check_deps()
        if missing:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "缺少依赖库",
                "首次运行需要安装以下 Python 库：\n\n"
                + "\n".join("• " + m for m in missing)
                + "\n\n请运行: pip install -r requirements.txt\n或直接双击 run.bat 自动安装。",
            )
            root.destroy()
            return 1

        import single_instance
        mutex_handle, is_first = single_instance.try_acquire()
        if not is_first:
            # 已有实例在运行: 通知它显示窗口, 本进程直接退出
            single_instance.signal_show()
            return 0

        import audio_utils
        audio_utils.init_com()

        import gui_app
        app = gui_app.App()
        app._instance_mutex = mutex_handle   # 保持互斥体句柄, 进程存活期间不释放
        app.mainloop()
        return 0
    except SystemExit:
        raise
    except Exception as exc:
        _report_error(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
