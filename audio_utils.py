# -*- coding: utf-8 -*-
"""Windows 音频 API 封装: COM 初始化 / 音频会话枚举 / 音量控制 / 麦克风枚举。

依赖: pycaw (基于 comtypes 的 WASAPI 封装) + sounddevice。
"""
import os
import threading

import comtypes
from pycaw.pycaw import AudioUtilities, IAudioMeterInformation

# 每个线程缓存默认输出设备的音量 COM 对象:
# 反复创建 COM 设备枚举器非常慢 (约 30ms/次), 引擎循环高频调用会拖垮 CPU。
_tls = threading.local()


class SessionInfo:
    """一个音频会话的摘要信息。"""
    __slots__ = ("pid", "name", "volume", "meter")

    def __init__(self, pid, name, volume, meter):
        self.pid = pid          # 进程 ID (系统声音为 0)
        self.name = name        # 进程名, 如 CloudMusic.exe
        self.volume = volume    # ISimpleAudioVolume
        self.meter = meter      # IAudioMeterInformation


def init_com():
    """初始化当前线程的 COM (幂等)。"""
    try:
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
    except Exception:
        try:
            comtypes.CoInitialize()
        except Exception:
            pass


def _endpoint():
    """默认输出设备的 IAudioEndpointVolume (线程内缓存, 避免反复创建 COM 对象)。

    兼容新旧 pycaw: 新版 GetSpeakers() 返回 AudioDevice 包装对象,
    其 .EndpointVolume 属性为 IAudioEndpointVolume; 旧版直接返回接口。
    """
    ep = getattr(_tls, "_endpoint", None)
    if ep is None:
        dev = AudioUtilities.GetSpeakers()
        ep = getattr(dev, "EndpointVolume", None) or dev
        _tls._endpoint = ep
    return ep


def get_sessions():
    """枚举当前活跃的音频会话, 返回 SessionInfo 列表 (异常时返回空列表)。"""
    out = []
    try:
        for s in AudioUtilities.GetAllSessions():
            try:
                pid = s.ProcessId
                name = None
                try:
                    if s.Process is not None:
                        name = s.Process.name()
                except Exception:
                    name = None
                if not name:
                    name = "System Sounds" if pid == 0 else "PID %d" % pid
                if pid == os.getpid():  # 跳过本工具自身
                    continue
                meter = s._ctl.QueryInterface(IAudioMeterInformation)
                out.append(SessionInfo(pid, name, s.SimpleAudioVolume, meter))
            except Exception:
                continue
    except Exception:
        pass
    return out


def get_master_volume():
    """读取主音量 (0.0 ~ 1.0), 失败返回 None。"""
    try:
        return float(_endpoint().GetMasterVolumeLevelScalar())
    except Exception:
        return None


def set_master_volume(value):
    """设置主音量 (0.0 ~ 1.0)。"""
    try:
        _endpoint().SetMasterVolumeLevelScalar(max(0.0, min(1.0, float(value))), None)
    except Exception:
        pass


def list_mic_devices():
    """列出可用输入(麦克风)设备, 返回 [(索引, 名称), ...]。"""
    import sounddevice as sd
    out = []
    try:
        for i, d in enumerate(sd.query_devices()):
            try:
                if int(d.get("max_input_channels", 0)) > 0:
                    out.append((i, d.get("name", "Device %d" % i)))
            except Exception:
                continue
    except Exception:
        pass
    return out
