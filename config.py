# -*- coding: utf-8 -*-
"""配置读写: 以 JSON 形式保存到 %APPDATA%/AudioDuck/config.json。"""
import json
import os

CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "AudioDuck")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULTS = {
    # 功能 1: 麦克风闪避(直播人声突显)
    "mic_duck_enabled": False,
    "mic_device": None,          # 麦克风设备索引 (sounddevice index)
    "mic_threshold": 0.05,       # 说话触发阈值 (RMS 0~0.5)
    "mic_duck_level": 0.30,      # 闪避后桌面音量 (原音量 × 该系数)
    "mic_release_delay": 1.0,    # 停止说话后多久恢复 (秒)
    # 功能 2: 语音聊天闪避(音乐闪避)
    "app_duck_enabled": False,
    "voice_app": "",             # 语音聊天应用进程名, 如 oopz.exe
    "music_app": "",             # 音乐应用进程名, 如 CloudMusic.exe
    "app_threshold": 0.05,       # 语音输出触发阈值 (峰值 0~1)
    "app_duck_level": 0.30,      # 闪避后音乐音量系数
    "app_release_delay": 1.0,    # 语音静默多久后恢复 (秒)
    # 关闭方式
    "close_behavior": "exit",    # exit=直接关闭 | tray=隐藏到托盘后台运行
    # 自动更新
    "update_url": "",            # 更新源地址 (留空用 updater.UPDATE_URL)
}


def load_config():
    """读取配置, 缺失项使用默认值。"""
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for key in DEFAULTS:
                if key in data:
                    cfg[key] = data[key]
    except Exception:
        pass
    return cfg


def save_config(cfg):
    """保存配置(静默失败, 不打断用户操作)。"""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
