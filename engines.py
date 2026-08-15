# -*- coding: utf-8 -*-
"""闪避引擎: 麦克风闪避 + 应用会话闪避, 各自运行在独立后台线程。"""
import threading
import time

import numpy as np
import sounddevice as sd

import audio_utils


def _approach(current, target, step):
    """向目标值平滑逼近一步, 返回新值。"""
    if abs(target - current) <= step:
        return target
    return current + step if target > current else current - step


def _find_sessions(sessions, name):
    """按进程名查找全部匹配会话: 先精确匹配, 再子串匹配。

    一个应用可能拥有多个同名会话 (如网易云音乐常有 2 个), 必须全部处理。
    """
    if not name:
        return []
    needle = name.strip().lower()
    exact = [s for s in sessions if s.name and s.name.lower() == needle]
    if exact:
        return exact
    return [s for s in sessions if s.name and needle in s.name.lower()]


def _session_keys(music_sessions):
    """为每个音乐会话生成稳定键 (pid, 同 pid 序号), 用于跨刷新保持原始音量。"""
    counts = {}
    for ms in music_sessions:
        n = counts.get(ms.pid, 0)
        counts[ms.pid] = n + 1
        yield (ms.pid, n), ms


class MicDuckEngine:
    """功能一: 麦克风闪避。

    监测麦克风输入电平, 检测到说话(电平超过阈值)时平滑压低桌面主音量,
    停止说话并经过释放延迟后平滑恢复 —— 用于直播/录制时凸显人声。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._stream = None

        # 状态 (GUI 轮询读取)
        self.mic_rms = 0.0        # 当前麦克风电平 (RMS)
        self.speaking = False     # 是否正在说话
        self.master_now = 1.0     # 当前桌面主音量
        self.state = "normal"     # normal | ducked | restoring
        self.error = None
        self.last_base = 1.0      # 闪避前的基准音量(用于停止时恢复)

        # 配置
        self.device = None        # 麦克风设备索引
        self.threshold = 0.05
        self.duck_level = 0.30
        self.release_delay = 1.0

    @property
    def running(self):
        return self._running

    def start(self, device, threshold, duck_level, release_delay):
        with self._lock:
            if self._running:
                return
            self.device = device
            self.threshold = threshold
            self.duck_level = duck_level
            self.release_delay = release_delay
            self.error = None
            self._running = True
            self._open_stream()
        threading.Thread(target=self._loop, daemon=True, name="mic-duck").start()

    def update(self, device=None, threshold=None, duck_level=None, release_delay=None):
        """运行中动态修改参数。"""
        with self._lock:
            if threshold is not None:
                self.threshold = threshold
            if duck_level is not None:
                self.duck_level = duck_level
            if release_delay is not None:
                self.release_delay = release_delay
            if device is not None and device != self.device:
                self.device = device
                self._open_stream()

    def _open_stream(self):
        self._close_stream()
        try:
            stream = sd.InputStream(device=self.device, channels=1, blocksize=1024,
                                    dtype="float32", callback=self._cb)
            stream.start()
            self._stream = stream
            self.error = None
        except Exception as exc:
            self._stream = None
            self.error = "无法打开麦克风: %s" % exc

    def _close_stream(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _cb(self, indata, frames, time_info, status):
        try:
            self.mic_rms = float(np.sqrt(np.mean(indata ** 2)))
        except Exception:
            pass

    def _loop(self):
        audio_utils.init_com()
        silent_since = time.time()
        base = None
        while True:
            with self._lock:
                if not self._running:
                    break
                threshold, duck_level, release_delay = self.threshold, self.duck_level, self.release_delay

            now = time.time()
            speaking = self.mic_rms >= threshold
            if speaking:
                silent_since = now
            self.speaking = speaking

            cur = audio_utils.get_master_volume()
            if cur is None:
                time.sleep(0.05)
                continue
            self.master_now = cur

            if speaking:
                if base is None:
                    base = cur
                    self.last_base = base
                target = base * duck_level
                if cur - target > 0.01:
                    audio_utils.set_master_volume(_approach(cur, target, 0.045))
                self.state = "ducked"
            else:
                if base is not None:
                    if (now - silent_since) >= release_delay:
                        nv = _approach(cur, base, 0.045)
                        audio_utils.set_master_volume(nv)
                        if abs(nv - base) < 0.01:
                            base = None
                        self.state = "restoring"
                    else:
                        self.state = "ducked"
                else:
                    self.state = "normal"
            time.sleep(0.05)

    def stop(self, restore=True):
        with self._lock:
            self._running = False
        self._close_stream()
        if restore:
            audio_utils.init_com()
            cur = audio_utils.get_master_volume()
            if cur is not None:
                audio_utils.set_master_volume(self.last_base)  # 直接恢复原始音量


class AppDuckEngine:
    """功能二: 语音聊天闪避。

    监测语音聊天应用的输出电平, 当语音输出超过阈值时平滑压低音乐播放应用的
    会话音量; 语音静默并经过释放延迟后平滑恢复 —— 用于语音聊天时凸显人声。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._running = False

        # 状态 (GUI 轮询读取)
        self.voice_peak = 0.0         # 语音应用输出峰值
        self.music_volume_now = 1.0   # 音乐应用当前音量
        self.state = "normal"         # normal | ducked | restoring | no_voice | no_music
        self.error = None
        self._bases = {}              # (pid,序号) -> 闪避前原始音量 (用于恢复)

        # 配置
        self.voice_app = ""
        self.music_app = ""
        self.threshold = 0.05
        self.duck_level = 0.30
        self.release_delay = 1.0

    @property
    def running(self):
        return self._running

    def start(self, voice_app, music_app, threshold, duck_level, release_delay):
        with self._lock:
            if self._running:
                return
            self.voice_app = (voice_app or "").strip()
            self.music_app = (music_app or "").strip()
            self.threshold = threshold
            self.duck_level = duck_level
            self.release_delay = release_delay
            self.error = None
            self._running = True
        threading.Thread(target=self._loop, daemon=True, name="app-duck").start()

    def update(self, voice_app=None, music_app=None, threshold=None, duck_level=None, release_delay=None):
        with self._lock:
            if voice_app is not None:
                self.voice_app = (voice_app or "").strip()
            if music_app is not None:
                self.music_app = (music_app or "").strip()
            if threshold is not None:
                self.threshold = threshold
            if duck_level is not None:
                self.duck_level = duck_level
            if release_delay is not None:
                self.release_delay = release_delay

    def _loop(self):
        audio_utils.init_com()
        cache = []
        last_refresh = 0.0
        silent_since = time.time()
        while True:
            with self._lock:
                if not self._running:
                    break
                voice_app, music_app = self.voice_app, self.music_app
                threshold, duck_level, release_delay = self.threshold, self.duck_level, self.release_delay

            now = time.time()
            if now - last_refresh > 2.0:          # 每 2 秒刷新一次会话列表
                cache = audio_utils.get_sessions()
                last_refresh = now

            voice_sessions = _find_sessions(cache, voice_app)
            music_sessions = _find_sessions(cache, music_app)

            # 语音峰值: 取所有语音会话的最大值 (一个应用可能有多个会话)
            peak = 0.0
            for vs in voice_sessions:
                try:
                    peak = max(peak, float(vs.meter.GetPeakValue() or 0.0))
                except Exception:
                    pass
            self.voice_peak = peak
            active = peak >= threshold
            if active:
                silent_since = now

            if not music_sessions:
                self._bases.clear()
                self.state = "no_music"
                time.sleep(0.1)
                continue

            self.music_volume_now = self._music_volume(music_sessions)

            if not voice_sessions:
                # 语音应用尚未出现(未开麦/未检测到会话) -> 直接恢复所有音乐会话
                for key, ms in _session_keys(music_sessions):
                    base = self._bases.get(key)
                    if base is not None:
                        try:
                            cur = float(ms.volume.GetMasterVolume())
                            nv = _approach(cur, base, 0.04)
                            ms.volume.SetMasterVolume(nv, None)
                            if abs(nv - base) < 0.005:
                                self._bases.pop(key, None)
                        except Exception:
                            pass
                self.state = "restoring" if self._bases else "no_voice"
            elif active:
                # 语音有输出 -> 压低该应用的全部音乐会话
                for key, ms in _session_keys(music_sessions):
                    try:
                        cur = float(ms.volume.GetMasterVolume())
                        if key not in self._bases:
                            self._bases[key] = cur
                        target = self._bases[key] * duck_level
                        if cur - target > 0.005:
                            ms.volume.SetMasterVolume(_approach(cur, target, 0.04), None)
                    except Exception:
                        pass
                self.state = "ducked"
            else:
                # 语音静默: 经过释放延迟后恢复所有音乐会话
                restoring = False
                for key, ms in _session_keys(music_sessions):
                    base = self._bases.get(key)
                    if base is not None:
                        if (now - silent_since) >= release_delay:
                            try:
                                cur = float(ms.volume.GetMasterVolume())
                                nv = _approach(cur, base, 0.04)
                                ms.volume.SetMasterVolume(nv, None)
                                if abs(nv - base) < 0.005:
                                    self._bases.pop(key, None)
                            except Exception:
                                pass
                        restoring = True
                self.state = "restoring" if restoring else "normal"
            time.sleep(0.05)

    @staticmethod
    def _music_volume(music_sessions):
        """音乐音量展示值: 取全部会话的最大值 (反映实际听到的响度)。"""
        vols = []
        for ms in music_sessions:
            try:
                vols.append(float(ms.volume.GetMasterVolume()))
            except Exception:
                pass
        return max(vols) if vols else 1.0

    def stop(self, restore=True):
        with self._lock:
            self._running = False
        if restore:
            audio_utils.init_com()
            try:
                sessions = audio_utils.get_sessions()
                for key, ms in _session_keys(_find_sessions(sessions, self.music_app)):
                    base = self._bases.get(key)
                    if base is not None:
                        try:
                            ms.volume.SetMasterVolume(base, None)  # 直接恢复原始音量
                        except Exception:
                            pass
            except Exception:
                pass
