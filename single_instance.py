# -*- coding: utf-8 -*-
"""单实例控制: 应用已运行时再次打开, 只把已有窗口显示到前台, 不启动新实例。

原理 (Windows):
- 命名互斥体 (Mutex): 判断是否已有实例在运行
- 命名事件 (Event): 第二个实例用它通知第一个实例"显示窗口"
"""
import ctypes

MUTEX_NAME = "Local\\AudioDuck_SingleInstance"
EVENT_NAME = "Local\\AudioDuck_ShowEvent"

_kernel32 = ctypes.windll.kernel32


def try_acquire():
    """尝试成为唯一实例。

    返回 (mutex_handle, is_first):
      is_first=True  -> 本进程是第一个实例, 应继续正常启动
      is_first=False -> 已有实例在运行
    """
    handle = _kernel32.CreateMutexW(None, False, MUTEX_NAME)
    already = _kernel32.GetLastError() == 183   # ERROR_ALREADY_EXISTS
    return handle, not already


def create_show_event():
    """第一个实例: 创建"显示窗口"事件, 返回事件句柄 (轮询用)。"""
    return _kernel32.CreateEventW(None, False, False, EVENT_NAME)


def signal_show():
    """第二个实例: 通知已运行的实例显示窗口。"""
    ev = _kernel32.OpenEventW(0x0002, False, EVENT_NAME)   # EVENT_MODIFY_STATE
    if ev:
        _kernel32.SetEvent(ev)
        _kernel32.CloseHandle(ev)
        return True
    return False


def is_show_requested(event_handle):
    """轮询: 事件是否被置位 (自动复位事件, 检测后自动清除)。"""
    if not event_handle:
        return False
    return _kernel32.WaitForSingleObject(event_handle, 0) == 0   # WAIT_OBJECT_0
