# -*- coding: utf-8 -*-
"""自动更新: 检查更新源版本清单, 下载新 exe, 通过临时批处理完成自我替换。

更新源格式 (version.json, 需 HTTPS):
    {"version": "1.1.0", "url": "https://.../AudioDuck.exe", "sha256": "可选", "notes": "更新说明"}

使用说明见 README 的「自动更新」章节。把 UPDATE_URL 改成你自己的更新源地址即可。
"""
import hashlib
import json
import os
import subprocess
import sys
import urllib.request

APP_VERSION = "1.0.0"
UPDATE_URL = "https://raw.githubusercontent.com/AutumnIsPro/QYAudioDuck/main/version.json"
# 备选加速源 (如直连 GitHub 慢, 可改用 jsDelivr): https://cdn.jsdelivr.net/gh/AutumnIsPro/QYAudioDuck@main/version.json
FETCH_TIMEOUT = 10


def _split_version(v):
    parts = []
    for p in str(v).strip().split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return parts


def is_newer(remote, local):
    """remote 版本号是否大于 local。"""
    return _split_version(remote) > _split_version(local)


def fetch_manifest(url):
    """拉取版本清单, 返回 dict。"""
    req = urllib.request.Request(url, headers={"User-Agent": "AudioDuck-Updater/1.0"})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_update(update_url):
    """检查更新: 返回 (有新版, 信息 dict 或 None, 错误信息或 None)。"""
    try:
        info = fetch_manifest(update_url)
        if not isinstance(info, dict) or "version" not in info:
            return False, None, "更新清单格式错误"
        if is_newer(info["version"], APP_VERSION):
            return True, info, None
        return False, None, None
    except Exception as exc:
        return False, None, "无法连接更新服务器: %s" % exc


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def download_exe(url, dest):
    """下载新版本 exe 到 dest, 返回字节数。"""
    req = urllib.request.Request(url, headers={"User-Agent": "AudioDuck-Updater/1.0"})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT * 3) as resp:
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
    return os.path.getsize(dest)


def apply_update(info, exe_name=None):
    """下载并安排自我替换 (仅打包版有效)。返回 (ok, 消息)。"""
    if not getattr(sys, "frozen", False):
        return False, "当前为源码版, 无法自动更新, 请手动替换 exe"
    exe_name = exe_name or os.path.basename(sys.executable)
    d = os.path.dirname(sys.executable)
    new_path = os.path.join(d, exe_name[:-4] + "_new.exe")
    try:
        download_exe(info["url"], new_path)
    except Exception as exc:
        return False, "下载更新失败: %s" % exc
    if os.path.getsize(new_path) < 100000:
        return False, "下载的文件异常 (可能不是有效的 exe)"
    if info.get("sha256"):
        got = _sha256(new_path)
        if got.lower() != str(info["sha256"]).lower():
            return False, "更新文件校验失败 (sha256 不匹配)"
    # 生成更新批处理 (纯 ASCII, 避免 cmd 编码问题)
    bat = os.path.join(d, "updater.bat")
    script = (
        "@echo off\r\n"
        ":wait\r\n"
        'tasklist /fi "IMAGENAME eq %s" 2>nul | find /i "%s" >nul\r\n'
        "if not errorlevel 1 (\r\n"
        "  timeout /t 1 /nobreak >nul\r\n"
        "  goto wait\r\n"
        ")\r\n"
        'copy /y "%%~dp0%s_new.exe" "%%~dp0%s" >nul\r\n'
        'del /q "%%~dp0%s_new.exe"\r\n'
        'del /q "%%~f0"\r\n'
        'start "" "%%~dp0%s"\r\n'
    ) % (exe_name, exe_name, exe_name[:-4], exe_name, exe_name[:-4], exe_name)
    with open(bat, "w", encoding="ascii") as f:
        f.write(script)
    subprocess.Popen(["cmd", "/c", bat], creationflags=subprocess.CREATE_NO_WINDOW)
    return True, "更新已下载完成, 程序即将重启以完成更新"
