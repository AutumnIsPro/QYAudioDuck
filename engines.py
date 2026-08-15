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


def _find_session(sessions, name):
    """按进程名查找会话: 先精确匹配, 再子串匹配。"""
    if not name:
        return None
    needle = name.strip().lower()
    for s in sessions:
        if s.name and s.name.lower() == needle:
            return s
    for s in sessions:
        if s.name and needle in s.name.lower():
            return s
    return None


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
                audio_utils.set_master_volume(_approach(cur, self.last_base, 0.05))


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
        self.last_base = None         # 闪避前音乐音量(用于停止时恢复)

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
        base = None
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

            voice_sess = _find_session(cache, voice_app)
            music_sess = _find_session(cache, music_app)

            peak = 0.0
            if voice_sess is not None:
                try:
                    peak = float(voice_sess.meter.GetPeakValue() or 0.0)
                except Exception:
                    peak = 0.0
            self.voice_peak = peak
            active = peak >= threshold
            if active:
                silent_since = now

            if music_sess is None:
                base = None
                self.state = "no_music"
                time.sleep(0.1)
                continue

            try:
                cur = float(music_sess.volume.GetMasterVolume())
            except Exception:
                time.sleep(0.05)
                continue
            self.music_volume_now = cur

            if voice_sess is None:
                # 语音应用尚未出现(未开麦/未检测到会话) -> 若之前闪避过则恢复
                if base is not None:
                    nv = _approach(cur, base, 0.04)
                    try:
                        music_sess.volume.SetMasterVolume(nv, None)
                    except Exception:
                        pass
                    if abs(nv - base) < 0.005:
                        base = None
                    self.state = "restoring"
                else:
                    self.state = "no_voice"
            elif active:
                if base is None:
                    base = cur
                    self.last_base = base
                target = base * duck_level
                if cur - target > 0.005:
                    try:
                        music_sess.volume.SetMasterVolume(_approach(cur, target, 0.04), None)
                    except Exception:
                        pass
                self.state = "ducked"
            else:
                if base is not None:
                    if (now - silent_since) >= release_delay:
                        nv = _approach(cur, base, 0.04)
                        try:
                            music_sess.volume.SetMasterVolume(nv, None)
                        except Exception:
                            pass
                        if abs(nv - base) < 0.005:
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
        if restore:
            audio_utils.init_com()
            base = self.last_base
            if base is not None:
                try:
                    sess = _find_session(audio_utils.get_sessions(), self.music_app)
                    if sess is not None:
                        cur = float(sess.volume.GetMasterVolume())
                        sess.volume.SetMasterVolume(_approach(cur, base, 0.05), None)
                except Exception:
                    pass
