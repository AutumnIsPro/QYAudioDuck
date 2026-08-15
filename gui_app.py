# -*- coding: utf-8 -*-
"""图形界面: customtkinter 淡粉半透明玻璃主题窗口 (9:16 竖屏, 随机背景图)。"""
import os
import random
import sys
import threading
import time
import tkinter as tk
from datetime import datetime

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

import audio_utils
import config as cfg_mod
import engines
import single_instance
import updater

# ---------- 配色 (深色图片背景 + 亮色文字, 卡片无填充只留轮廓) ----------
BG = "#1a1a26"           # 窗口底色兜底 (正常被背景图覆盖)
CARD = "transparent"     # 卡片: 不填充, 只保留轮廓
CARD_BORDER = "#ffc9dc"  # 卡片描边: 浅粉细线
ACCENT = "#ff8fb3"       # 主色: 亮粉
ACCENT2 = "#c9a0f0"      # 辅色: 亮紫
GREEN = "#7ddb87"        # 开启态
ORANGE = "#f2b05c"
RED = "#f2707f"
TEXT = "#fff5f9"         # 亮白文字 (浮在暗化图片上)
MUTED = "#d9bfcd"        # 浅粉灰次要文字

# 控件配色
SLIDER_TRACK = "#f3c9d9"
INPUT_BG = "#fff5f9"
BTN = "#f7a8c8"
BTN_HOVER = "#f48bb0"
LOG_BG = "#fff8fb"

MIC_MAX_DISPLAY = 0.5   # 麦克风电平条满格对应的 RMS 值


def _patch_transparent_redraw():
    """让 fg_color='transparent' 的 customtkinter 控件在重绘时不再绘制不透明内部填充。

    customtkinter 用"父级颜色"模拟透明, 会把 inner_parts 填成窗口底色 (不透明),
    盖住我们铺的背景图。此补丁在每次重绘后自动删除这些填充, 实现真正的透明。
    """
    for cls_name in ("CTkLabel", "CTkFrame", "CTkTextbox"):
        cls = getattr(ctk, cls_name, None)
        if cls is None or not hasattr(cls, "_draw"):
            continue
        orig = cls._draw

        def make(orig_draw):
            def _draw(self, no_color_updates=False):
                res = orig_draw(self, no_color_updates)
                if getattr(self, "_fg_color", None) == "transparent":
                    try:
                        self._canvas.delete("inner_parts")
                    except Exception:
                        pass
                return res
            return _draw

        cls._draw = make(orig)


_patch_transparent_redraw()


class GlassLabel(tk.Canvas):
    """透明文字标签: 文字直接绘制在画布上, 没有任何背景块 (替代 CTkLabel 内嵌的 tk.Label)。

    直接继承 tk.Canvas (不再包一层 Frame): 每个标签只占一个 Tk 控件,
    显著减少窗口缩放/拖动时布局重排与重绘的开销。
    """

    def __init__(self, master=None, text="", font=None, text_color="#ffffff",
                 wraplength=0, justify="left", anchor="w", **kw):
        super().__init__(master, highlightthickness=0, bd=0, bg=BG,
                         width=10, height=10, **kw)
        self._canvas = self
        self._text = text
        self._font = font
        self._fg = text_color
        self._wraplength = wraplength
        self._justify = justify
        self._anchor = anchor
        self._text_id = None
        self._last_drawn = None
        self.bind("<Configure>", self._on_resize)
        self._redraw()

    def _on_resize(self, _event=None):
        # 画布尺寸未变则跳过重绘, 减少窗口缩放/拖动时的重复绘制开销
        try:
            if (self._canvas.winfo_width(), self._canvas.winfo_height()) == self._last_drawn:
                return
        except Exception:
            pass
        self._redraw()

    def _redraw(self):
        c = self._canvas
        c.delete("gl_text")
        # 描边: 偏移 1px 的深色副本 (凸显文字)
        offs = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1))
        for dx, dy in offs:
            c.create_text(dx, dy, text=self._text, font=self._font,
                          fill="#221a26", anchor="nw", justify=self._justify,
                          width=self._wraplength or 0, tags=("gl_text",))
        self._text_id = c.create_text(0, 0, text=self._text, font=self._font,
                                      fill=self._fg, anchor="nw", justify=self._justify,
                                      width=self._wraplength or 0, tags=("gl_text",))
        self._resize_to_text()
        try:
            self._last_drawn = (c.winfo_width(), c.winfo_height())
        except Exception:
            self._last_drawn = None

    def _resize_to_text(self):
        """按文字 bbox 调整画布尺寸, 让网格布局为文字分配空间。"""
        c = self._canvas
        try:
            if self._text_id is not None:
                x0, y0, x1, y1 = c.bbox(self._text_id)
                nw = max(1, int(x1 - x0))
                nh = max(1, int(y1 - y0))
                if nw != c.cget("width") or nh != c.cget("height"):
                    c.configure(width=nw, height=nh)
        except Exception:
            pass

    def set_text(self, text):
        self._text = text
        if self._text_id is not None:
            try:
                self._canvas.itemconfigure(self._text_id, text=text)
            except Exception:
                pass
        self._resize_to_text()

    def set_color(self, color):
        self._fg = color
        if self._text_id is not None:
            try:
                self._canvas.itemconfigure(self._text_id, fill=color)
            except Exception:
                pass

    def configure(self, **kw):
        for ignore in ("fg_color", "corner_radius", "border_width", "border_color"):
            kw.pop(ignore, None)
        if "text" in kw:
            self.set_text(kw.pop("text"))
        if "text_color" in kw:
            self.set_color(kw.pop("text_color"))
        super().configure(**kw)

    def cget(self, key):
        if key == "text":
            return self._text
        if key == "text_color":
            return self._fg
        return super().cget(key)


class GlassFrame(tk.Canvas):
    """透明布局容器: 轻量画布容器 (替代仅用于布局的透明 CTkFrame)。

    CTkFrame 每次缩放都要重绘圆角矩形并处理自身 Configure, 开销大;
    纯布局容器改用 tk.Canvas, 每个容器只占一个廉价 Tk 控件, 背景图
    由 _paint_node 铺上, 面板额外绘制细圆角描边。
    """

    def __init__(self, master=None, is_panel=False, **kw):
        kw.pop("fg_color", None)
        kw.pop("corner_radius", None)
        kw.pop("border_width", None)
        kw.pop("border_color", None)
        super().__init__(master, highlightthickness=0, bd=0, bg=BG, **kw)
        self._canvas = self
        self._is_panel = is_panel

    def configure(self, **kw):
        for ignore in ("fg_color", "corner_radius", "border_width", "border_color"):
            kw.pop(ignore, None)
        super().configure(**kw)

    def cget(self, key):
        if key == "fg_color":
            return "transparent"
        return super().cget(key)


def _now_tag():
    return datetime.now().strftime("%H:%M:%S")


class App(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        super().__init__()

        self.cfg = cfg_mod.load_config()
        self.mic_engine = engines.MicDuckEngine()
        self.app_engine = engines.AppDuckEngine()

        self._mic_map = {}            # 下拉显示名 -> 设备索引
        self._last_mic_state = None
        self._last_app_state = None
        self._last_err = None
        self._save_job = None
        self._resize_job = None
        self._painted_size = None      # 已绘制背景的窗口尺寸 (拖动窗口时不重绘)
        self._bg_cache = {}            # (w,h) -> (PIL图, PhotoImage) 背景缓存, 避免重复缩放
        self._ghost = False            # 缩放幽灵模式: 拖动期间冻结界面
        self._ghost_photo = None       # 幽灵模式快照
        self._last_resize_t = None     # 上次尺寸变化时刻 (检测连续缩放)
        self._start_t = time.monotonic()   # 启动时刻 (启动初期不触发幽灵模式)
        self._bg_img = None           # 背景 PIL 图 (随机挑选)
        self._bg_pil = None           # 合成后的最终背景图
        self._bg_photo = None         # 背景 PhotoImage 引用
        self._bg = None               # 背景画布
        self._bg_ratio = 16 / 9       # 背景图宽高比 (无图时默认 16:9)
        self._ratio_fixed = False     # 启动时是否已按图片比例校正过窗口
        self._show_event = single_instance.create_show_event()  # 单实例"显示窗口"事件

        self.title("音频自动闪避助手")
        self.geometry("1080x608")     # 初始 16:9, 启动后按背景图比例精确调整
        self.minsize(800, 450)
        self.configure(fg_color=BG)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._set_aumid()
        self._apply_icon()

        # 背景画布: 图片 + 磨砂玻璃 + 反光 (先创建, 位于所有控件之下)
        self._bg = tk.Canvas(self, highlightthickness=0, bd=0, bg=BG)
        self._bg.place(x=0, y=0, relwidth=1, relheight=1)
        self._load_bg_image()
        self.bind("<Configure>", self._on_bg_resize)

        audio_utils.init_com()
        self._build_ui()
        self._load_to_ui()
        # 设备/会话枚举较慢, 延后到窗口显示后再执行, 让界面尽快弹出
        self.after(50, self._refresh_mics)
        self.after(80, self._refresh_apps)
        self.after(150, self._poll)
        self.after(150, self._apply_taskbar_icon)
        self.after(120, self._redraw_all)
        # 自动更新检查 (延后启动, 后台线程, 不阻塞界面)
        self.after(4000, self._start_update_check)

    @staticmethod
    def _icon_path():
        """定位 icon.ico: 打包版优先 exe 旁, 其次 exe 内置 (_MEIPASS), 源码版在脚本旁。"""
        cands = []
        if getattr(sys, "frozen", False):
            cands.append(os.path.join(os.path.dirname(sys.executable), "icon.ico"))
            cands.append(os.path.join(getattr(sys, "_MEIPASS", ""), "icon.ico"))
        cands.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico"))
        for p in cands:
            if p and os.path.exists(p):
                return p
        return None

    @staticmethod
    def _set_aumid():
        """设置 AppUserModelID: 让任务栏显示窗口自定义图标, 而非 pythonw 的 Python 图标。

        Windows 任务栏按钮默认使用进程 exe 的图标; 显式设置一个自定义 AUMID 后,
        任务栏会改用它关联的图标(此处无注册, 回落到窗口 WM_SETICON 设置的图标)。
        """
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "AudioDuck.AudioDuckingAssistant.1")
        except Exception:
            pass

    def _apply_icon(self):
        """设置标题栏图标 (tkinter 方式)。"""
        ico = self._icon_path()
        if ico:
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

    def _apply_taskbar_icon(self):
        """通过 Win32 API 直接设置窗口图标, 确保任务栏 / Alt-Tab 显示自定义图标。"""
        ico = self._icon_path()
        if not ico:
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            self.update_idletasks()
            hwnd = self.winfo_id()
            # GA_ROOT=2: 取真正的顶层窗口(带标题栏的那个), winfo_id 返回的是客户区子窗口
            root = user32.GetAncestor(hwnd, 2) or hwnd
            hicon = user32.LoadImageW(None, ico, 1, 0, 0, 0x10)  # IMAGE_ICON=1, LR_LOADFROMFILE=0x10
            if hicon:
                WM_SETICON = 0x0080
                user32.SendMessageW(root, WM_SETICON, 0, hicon)  # ICON_SMALL: 标题栏/任务栏
                user32.SendMessageW(root, WM_SETICON, 1, hicon)  # ICON_BIG: Alt-Tab
        except Exception:
            pass

    # ================= 背景 (随机图片 + 玻璃质感) =================

    def _find_bg_files(self):
        """定位背景图文件夹: 优先 exe/脚本旁的自定义 114514, 其次打包进 exe 内的。"""
        if getattr(sys, "frozen", False):
            exe_folder = os.path.join(os.path.dirname(sys.executable), "114514")
            bundle_folder = os.path.join(getattr(sys, "_MEIPASS", ""), "114514")
        else:
            exe_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "114514")
            bundle_folder = None
        for fld in (exe_folder, bundle_folder):
            if fld and os.path.isdir(fld):
                files = [os.path.join(fld, f) for f in os.listdir(fld)
                         if f.lower().endswith((".png", ".jpg", ".jpeg"))]
                if files:
                    return files
        return []

    def _load_bg_image(self):
        """随机挑选一张背景图片 (优先 exe 旁自定义, 其次打包内置)。"""
        files = self._find_bg_files()
        self._bg_files = files
        if files:
            self._bg_index = random.randrange(len(files))
            self._apply_bg_file(files[self._bg_index])
        else:
            self._bg_img = None
            self._bg_ratio = 16 / 9

    def _apply_bg_file(self, path):
        """加载指定背景图片。"""
        try:
            img = Image.open(path).convert("RGB")
            img.thumbnail((1920, 1920), Image.LANCZOS)   # 足够 1080p~2K 窗口, 减小每次缩放开销
            self._bg_img = img
            self._bg_ratio = img.width / img.height
            return True
        except Exception:
            self._bg_img = None
            return False

    def _change_bg(self):
        """切换到下一张背景图片 (平滑交叉淡入淡出)。"""
        files = self._bg_files
        if not files:
            self.log("未找到背景图片 (114514 文件夹为空)")
            return
        self._bg_index = (self._bg_index + 1) % len(files)
        path = files[self._bg_index]
        old_img = self._bg_img
        if self._apply_bg_file(path):
            try:
                self._crossfade_bg(old_img, self._bg_img,
                                   self.winfo_width(), self.winfo_height())
            except Exception:
                # 动画异常时直接切换
                self._draw_background(self.winfo_width(), self.winfo_height())
            self.log("🎨 已更换背景: %s" % os.path.basename(path))

    def _cover_resize(self, img, w, h):
        """把图片 cover 缩放后居中裁剪到精确的窗口尺寸 (w, h)。

        必须返回完全一致的尺寸, 否则新旧帧无法用 Image.blend 混合
        (不同宽高比的图片 cover 后会得到不同尺寸)。
        """
        scale = max(w / img.width, h / img.height)
        nw = max(1, int(round(img.width * scale)))
        nh = max(1, int(round(img.height * scale)))
        img2 = img.resize((nw, nh), Image.LANCZOS)
        if nw != w or nh != h:
            left = (nw - w) // 2
            top = (nh - h) // 2
            img2 = img2.crop((left, top, left + w, top + h))
        return img2

    def _crossfade_bg(self, old_img, new_img, w, h):
        """背景平滑过渡: 新旧图按比例混合, 逐帧动画 (同时同步所有控件的背景)。"""
        if w < 50 or h < 50 or new_img is None:
            self._draw_background(w, h)
            return
        old_r = self._cover_resize(old_img, w, h) if old_img is not None else None
        new_r = self._cover_resize(new_img, w, h)
        steps = 24
        frames = []
        for i in range(steps):
            t = (i + 1) / steps
            frames.append(Image.blend(old_r, new_r, t) if old_r is not None else new_r)
        frames.append(new_r)
        self._fade_frames = frames
        self._fade_step = 0
        self._fade_w, self._fade_h = w, h
        self.after(20, self._animate_bg_step)

    def _animate_bg_step(self):
        """交叉淡入淡出的一帧。"""
        frames = getattr(self, "_fade_frames", None)
        if not frames:
            return
        i = self._fade_step
        w, h = self._fade_w, self._fade_h
        frame = frames[i]
        self._bg_photo = ImageTk.PhotoImage(frame)
        self._bg.delete("all")
        self._bg.create_image(w // 2, h // 2, image=self._bg_photo)
        self._paint_transparent_widgets()   # 同步所有控件背景, 整体一起过渡
        self._fade_step += 1
        if i + 1 < len(frames):
            self.after(28, self._animate_bg_step)
        else:
            # 完成: 固定最终背景
            self._bg_pil = frame
            self._bg_photo = ImageTk.PhotoImage(frame)
            self._bg.delete("all")
            self._bg.create_image(w // 2, h // 2, image=self._bg_photo)
            self._paint_transparent_widgets()
            self._fade_frames = None

    def _on_bg_resize(self, event):
        """窗口位置/尺寸变化时 (防抖) 重绘背景。

        Windows 上拖动窗口 (仅位置变化) 也会触发 <Configure>; 只要窗口尺寸没变
        就不重绘, 彻底消除拖拽时的卡顿。连续缩放 (拖动边角) 时进入"幽灵模式":
        界面冻结为快照、子控件隐藏, 拖动过程只剩背景画布重绘 (~几 ms/事件),
        松手后恢复控件并重新绘制。
        """
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2 or h < 2:
            return
        if (w, h) == self._painted_size:
            return   # 位置变了但尺寸没变 (拖动窗口): 无需重绘
        now = time.monotonic()
        # 两次尺寸变化间隔 < 400ms 且已过启动期 (比例校正/初始布局结束) -> 连续缩放 (拖动边角), 进入幽灵模式
        # 最大化 (zoomed) 不进入: 单次跳变, 正常重绘即可
        if (not self._ghost and self._last_resize_t is not None
                and (now - self._last_resize_t) < 0.4
                and (now - self._start_t) > 2.0
                and self.state() != "zoomed"):
            self._enter_ghost()
        self._last_resize_t = now
        delay = 300 if self._ghost else 150
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(delay, self._redraw_all)

    def _enter_ghost(self):
        """进入缩放幽灵模式: 把当前界面冻结为一张快照, 隐藏所有子控件。

        拖动边角缩放时, 每次鼠标移动都会触发一次全窗口重排 (~150-200ms 卡顿);
        幽灵模式下子控件被隐藏, 只有背景画布需要重绘, 拖动过程流畅,
        松手后由 _redraw_all 恢复控件并重新绘制。
        """
        if self._ghost:
            return
        try:
            w, h = self.winfo_width(), self.winfo_height()
            if w < 60 or h < 60:
                return
            x, y = self.winfo_rootx(), self.winfo_rooty()
            from PIL import ImageGrab
            snap = ImageGrab.grab(bbox=(x, y, x + w, y + h))   # 快照失败则保持普通模式
        except Exception:
            return
        try:
            for child in self.winfo_children():
                if child is self._bg:
                    continue
                try:
                    child.grid_remove()
                except Exception:
                    try:
                        child.pack_forget()
                    except Exception:
                        pass
            self._bg.delete("all")
            self._ghost_photo = ImageTk.PhotoImage(snap)
            self._bg.create_image(w // 2, h // 2, image=self._ghost_photo)
            self._ghost = True
        except Exception:
            self._ghost = False
            self._ghost_photo = None
            for child in self.winfo_children():
                if child is self._bg:
                    continue
                try:
                    child.grid()
                except Exception:
                    pass
            self._bg.delete("all")

    def _exit_ghost(self):
        """退出幽灵模式: 恢复子控件, 重新绘制背景。"""
        if not self._ghost:
            return
        self._ghost = False
        self._ghost_photo = None
        try:
            for child in self.winfo_children():
                if child is self._bg:
                    continue
                try:
                    child.grid()
                except Exception:
                    try:
                        child.pack()
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            self.update_idletasks()   # 强制几何布局就绪, 避免用刚恢复的过期控件位置绘制背景
        except Exception:
            pass
        self._painted_size = None   # 强制重绘 (尺寸可能已变)
        self._redraw_all()

    def _redraw_all(self):
        if self._ghost:
            self._exit_ghost()   # 缩放结束: 恢复控件并重绘
            return
        if not self._ratio_fixed:
            self._fix_ratio()
            self._ratio_fixed = True
        # 缩放时用更快的 BILINEAR (背景照片上几乎看不出与 LANCZOS 的差别)
        self._draw_background(self.winfo_width(), self.winfo_height(), Image.BILINEAR)
        # 布局稳定后再同步一次透明控件的背景 (几何更新可能滞后于重绘, 避免图片错位)
        self.after(80, self._paint_transparent_widgets)

    def _fix_ratio(self):
        """启动时把窗口客户区比例调整为与背景图一致, 使整张图完整显示不裁剪。

        注意: 不能用 self.geometry() —— customtkinter 会再次做 DPI 缩放;
        直接调用 tk 底层 wm geometry 设置真实像素尺寸。
        """
        try:
            self.update_idletasks()
            w = self.winfo_width()
            h = self.winfo_height()
            if w < 50 or h < 50:
                return
            target = int(round(w / self._bg_ratio))
            if abs(target - h) >= 2:
                self.tk.call("wm", "geometry", self._w, "%dx%d" % (w, target))
        except Exception:
            pass

    def _draw_background(self, w, h, resample=Image.LANCZOS):
        """绘制背景: 直接缩放填满整窗的图片 (无暗化/暗角/反光等玻璃效果)。

        缩放结果与 PhotoImage 按 (w, h) 缓存: 相同尺寸直接复用, 避免反复
        重采样与 Tk 图像转换 (窗口来回缩放、反复最大化时几乎零开销)。
        """
        if not self._bg or w < 2 or h < 2:
            return
        self._painted_size = (w, h)
        c = self._bg
        c.delete("all")
        hit = self._bg_cache.get((w, h))
        if hit is not None:
            img, photo = hit
        else:
            if self._bg_img is not None:
                img = self._bg_img
                scale = max(w / img.width, h / img.height)   # cover 填满
                nw = max(1, int(round(img.width * scale)))
                nh = max(1, int(round(img.height * scale)))
                try:
                    img = img.resize((nw, nh), resample)
                except Exception:
                    pass
                if nw < w or nh < h:
                    img = img.resize((w, h), resample)   # 兜底填满
            else:
                img = Image.new("RGB", (w, h))
                d0 = ImageDraw.Draw(img)
                top, bottom = (36, 26, 38), (26, 20, 32)
                for y in range(0, h, 2):
                    t = y / max(1, h)
                    d0.rectangle([0, y, w, y + 2], fill=tuple(
                        int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
            photo = ImageTk.PhotoImage(img)
            self._bg_cache[(w, h)] = (img, photo)
            if len(self._bg_cache) > 3:
                self._bg_cache.pop(next(iter(self._bg_cache)))   # 淘汰最旧尺寸, 控制内存
        self._bg_pil = img
        self._bg_photo = photo
        c.create_image(w // 2, h // 2, image=photo)
        self._paint_transparent_widgets()

    # ================= 透明控件: 背景同步绘制 =================

    def _paint_transparent_widgets(self):
        """把所有 fg_color 为 transparent 的控件内部画布铺上背景图, 实现真正透明。"""
        if self._bg_photo is None:
            return
        try:
            rx, ry = self.winfo_rootx(), self.winfo_rooty()
            pw, ph = self._bg_photo.width(), self._bg_photo.height()
            wx = (self.winfo_width() - pw) // 2
            wy = (self.winfo_height() - ph) // 2
        except Exception:
            return
        try:
            from customtkinter.windows.widgets.core_widget_classes import CTkBaseClass
        except Exception:
            CTkBaseClass = ctk.CTkFrame  # 兜底
        for child in self.winfo_children():
            self._paint_node(child, rx, ry, wx, wy, CTkBaseClass)
        # 缓存透明控件画布, 供轮询时定期清理被重建的内部填充
        self._transparent_canvases = []

        def collect(w):
            if isinstance(w, CTkBaseClass) and getattr(w, "_fg_color", None) == "transparent":
                try:
                    self._transparent_canvases.append(w._canvas)
                except Exception:
                    pass
            for c in w.winfo_children():
                collect(c)
        collect(self)

    def _cleanup_inner_fills(self):
        """定期删除被 customtkinter 重建的不透明内部填充, 保持面板透明。"""
        for c in getattr(self, "_transparent_canvases", ()):
            try:
                c.delete("inner_parts")
            except Exception:
                pass

    def _paint_node(self, widget, rx, ry, wx, wy, base_cls):
        """检查节点自身 (含顶层透明框架), 并递归其子树。"""
        try:
            if isinstance(widget, base_cls):
                self._paint_widget_bg(widget, rx, ry, wx, wy)
            elif isinstance(widget, GlassFrame):
                self._paint_glass_frame(widget, rx, ry, wx, wy)
            elif isinstance(widget, GlassLabel):
                self._paint_glass_label(widget, rx, ry, wx, wy)
        except Exception:
            pass
        for child in widget.winfo_children():
            try:
                self._paint_node(child, rx, ry, wx, wy, base_cls)
            except Exception:
                pass

    def _paint_widget_bg(self, w, rx, ry, wx, wy):
        """把所有 CTk 控件的内部画布铺上对齐的背景图, 盖住深色画布底。

        透明控件 (fg_color='transparent') 额外删除 customtkinter 的填充/边框项
        (它们是"全卡矩形+内部遮罩"结构, 删遮罩会暴露全卡粉色矩形), 面板改用
        自己绘制的细圆角描边; 标签用采样色芯片融入图片。
        """
        try:
            # 主画布
            c = w._canvas
            ox = w.winfo_rootx() - rx
            oy = w.winfo_rooty() - ry
            c.delete("bgimg")
            c.create_image(wx - ox, wy - oy, image=self._bg_photo,
                           anchor="nw", tags=("bgimg",))
            c.tag_lower("bgimg")
            # 部分控件 (如开关) 还有全尺寸的 _bg_canvas, 同样铺上背景图
            if hasattr(w, "_bg_canvas"):
                bc = w._bg_canvas
                bc.delete("bgimg")
                bc.create_image(wx - ox, wy - oy, image=self._bg_photo,
                                anchor="nw", tags=("bgimg",))
                bc.tag_lower("bgimg")
        except Exception:
            return
        # 控件内部文字标签处理: 消除文字底部的色块
        try:
            for child in w.winfo_children():
                if isinstance(child, tk.Label):
                    if isinstance(w, ctk.CTkButton):
                        # 按钮: 文字底色 = 按钮填充色, 融入按钮
                        fill = getattr(w, "_fg_color", None)
                        if isinstance(fill, (tuple, list)):
                            fill = fill[0]
                        if fill and fill != "transparent":
                            child.configure(bg=fill)
                    elif isinstance(w, ctk.CTkSwitch):
                        # 开关: 隐藏文字标签, 改用画布文字 (直接浮在背景上, 无色块)
                        try:
                            child.place_forget()
                        except Exception:
                            pass
                        try:
                            child.grid_remove()
                        except Exception:
                            pass
                        c = getattr(w, "_bg_canvas", None) or getattr(w, "_canvas", None)
                        if c is not None:
                            c.delete("ctrl_text")
                            c.create_text(child.winfo_x() + child.winfo_width() // 2,
                                          child.winfo_y() + child.winfo_height() // 2,
                                          text=child.cget("text"), font=child.cget("font"),
                                          fill=child.cget("fg"), tags=("ctrl_text",))
        except Exception:
            pass
        if getattr(w, "_fg_color", None) != "transparent":
            return   # 非透明控件 (滑块/按钮/下拉等): 保留自身填充
        # 删除 customtkinter 的填充与边框项
        try:
            c = w._canvas
            for tag in ("inner_parts", "inner_oval_1_a", "inner_oval_1_b",
                        "inner_oval_2_a", "inner_oval_2_b", "inner_oval_3_a", "inner_oval_3_b",
                        "inner_oval_4_a", "inner_oval_4_b", "inner_corner_part",
                        "inner_rectangle_1", "inner_rectangle_2", "inner_rectangle_part",
                        "border_parts", "border_oval_1_a", "border_oval_1_b",
                        "border_oval_2_a", "border_oval_2_b", "border_oval_3_a", "border_oval_3_b",
                        "border_oval_4_a", "border_oval_4_b", "border_corner_part",
                        "border_rectangle_1", "border_rectangle_2", "border_rectangle_part"):
                c.delete(tag)
        except Exception:
            pass
        if isinstance(w, ctk.CTkTextbox):
            try:  # tk.Text 无法透明, 用深色近似 rgba(0,0,0,0.35) 毛玻璃
                w._textbox.configure(bg="#1c1824")
            except Exception:
                pass
        # 面板: 绘制细圆角描边 (1px 半透明白)
        if getattr(w, "_is_panel", False):
            self._draw_panel_outline(w)

    def _paint_glass_label(self, w, rx, ry, wx, wy):
        """GlassLabel: 画布铺背景图, 文字 (画布项) 浮于其上, 无任何背景块。"""
        try:
            c = w._canvas
            ox = w.winfo_rootx() - rx
            oy = w.winfo_rooty() - ry
            c.delete("bgimg")
            c.create_image(wx - ox, wy - oy, image=self._bg_photo,
                           anchor="nw", tags=("bgimg",))
            c.tag_lower("bgimg")
        except Exception:
            pass

    def _paint_glass_frame(self, w, rx, ry, wx, wy):
        """GlassFrame: 铺背景图 (同 GlassLabel), 面板额外画细圆角描边。"""
        try:
            c = w._canvas
            ox = w.winfo_rootx() - rx
            oy = w.winfo_rooty() - ry
            c.delete("bgimg")
            c.create_image(wx - ox, wy - oy, image=self._bg_photo,
                           anchor="nw", tags=("bgimg",))
            c.tag_lower("bgimg")
        except Exception:
            pass
        if getattr(w, "_is_panel", False):
            self._draw_panel_outline(w)

    def _draw_panel_outline(self, w):
        """面板细圆角描边: 深色描边 + 浅色粗线 (2px) + 8px 圆角。"""
        try:
            c = w._canvas
            c.delete("panel_outline")
            ww, wh = w.winfo_width(), w.winfo_height()
            if ww < 12 or wh < 12:
                return
            r = 8
            pts = [r, 0, ww - r, 0, ww, 0, ww, r, ww, wh - r, ww, wh,
                   ww - r, wh, r, wh, 0, wh, 0, wh - r, 0, r]
            # 深色描边 (4px, 打底) + 浅色主线 (2px)
            c.create_polygon(pts, smooth=True, outline="#2a1f2e",
                             width=4, fill="", tags=("panel_outline",))
            c.create_polygon(pts, smooth=True, outline="#fff0f6",
                             width=2, fill="", tags=("panel_outline",))
            c.tag_raise("panel_outline")
        except Exception:
            pass

    # ================= UI 构建 =================

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # --- 头部: 标题 + 个性签名 (无头像) ---
        header = GlassFrame(self)
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(10, 4))
        header.grid_columnconfigure(0, weight=1)
        title_row = GlassFrame(header)
        title_row.grid(row=0, column=0, sticky="ew")
        GlassLabel(title_row, text="🎧 音频自动闪避助手", font=("Microsoft YaHei UI", 21, "bold"),
                     text_color=ACCENT).pack(side="left")
        self.bg_btn = ctk.CTkButton(title_row, text="🎨 换背景", width=80, height=28,
                                    font=("Microsoft YaHei UI", 13, "bold"),
                                    fg_color=BTN, hover_color=BTN_HOVER, text_color="#5c3a4a",
                                    command=self._change_bg)
        self.bg_btn.pack(side="right", padx=(0, 10))
        GlassLabel(title_row, text="糗鸭 QiuuuuuYa", font=("Microsoft YaHei UI", 14, "italic", "bold"),
                     text_color=ACCENT2).pack(side="right")
        GlassLabel(header, text="直播 / 语音聊天时，自动压低背景声音，突出人声 ✿",
                     font=("Microsoft YaHei UI", 12, "bold"), text_color=MUTED).grid(row=1, column=0, sticky="w", pady=(2, 0))

        # --- 主体: 两功能卡片 (横向并排) ---
        body = GlassFrame(self)
        body.grid(row=1, column=0, sticky="nsew", padx=16, pady=6)
        body.grid_columnconfigure(0, weight=1, uniform="cards")
        body.grid_columnconfigure(1, weight=1, uniform="cards")
        body.grid_rowconfigure(0, weight=1)

        self._build_mic_card(body)
        self._build_app_card(body)

        # --- 日志 (可开/关, 默认收起) ---
        log_frame = GlassFrame(self, is_panel=True)
        log_frame.grid(row=2, column=0, sticky="ew", padx=16, pady=(6, 4))
        log_frame.grid_columnconfigure(0, weight=1)
        log_head = GlassFrame(log_frame)
        log_head.grid(row=0, column=0, sticky="ew", padx=14, pady=(8, 2))
        GlassLabel(log_head, text="📋 运行日志", font=("Microsoft YaHei UI", 13, "bold"),
                     text_color=TEXT).pack(side="left")
        self.log_toggle_btn = ctk.CTkButton(log_head, text="展开 ▾", width=58, height=24,
                                            font=("Microsoft YaHei UI", 12, "bold"),
                                            fg_color=BTN, hover_color=BTN_HOVER, text_color="#5c3a4a",
                                            command=self._toggle_log)
        self.log_toggle_btn.pack(side="right")
        self.log_box = ctk.CTkTextbox(log_frame, height=100, fg_color="transparent", text_color=TEXT,
                                      font=("Consolas", 11), corner_radius=8,
                                      border_width=1, border_color=CARD_BORDER)
        self.log_box.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))
        self.log_box.configure(state="disabled")
        self._log_visible = False
        self.log_box.grid_remove()  # 默认收起日志

        # --- 状态栏 ---
        status = GlassFrame(self)
        status.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 12))
        self.status_label = GlassLabel(status, text="● 未启用任何闪避功能",
                                         font=("Microsoft YaHei UI", 13, "bold"), text_color=MUTED)
        self.status_label.pack(side="left")
        # 关闭方式选择
        ctrl_bar = GlassFrame(status)
        ctrl_bar.pack(side="right")
        self.update_btn = ctk.CTkButton(ctrl_bar, text="检查更新", width=78, height=26,
                                        font=("Microsoft YaHei UI", 12, "bold"),
                                        fg_color=BTN, hover_color=BTN_HOVER, text_color="#5c3a4a",
                                        command=self._manual_update_check)
        self.update_btn.pack(side="left", padx=(0, 10))
        GlassLabel(ctrl_bar, text="关闭时:", font=("Microsoft YaHei UI", 12, "bold"),
                   text_color=MUTED).pack(side="left")
        self.close_combo = ctk.CTkComboBox(ctrl_bar, width=120, height=26,
                                           values=["直接关闭", "隐藏到托盘"],
                                           font=("Microsoft YaHei UI", 12, "bold"),
                                           fg_color=INPUT_BG, button_color=BTN,
                                           button_hover_color=BTN_HOVER, border_color=CARD_BORDER)
        self.close_combo.pack(side="left", padx=(8, 14))
        self.close_combo.configure(command=self._on_close_behavior)
        GlassLabel(status, text="应用需保持运行 · 关闭窗口时自动恢复音量",
                     font=("Microsoft YaHei UI", 12, "bold"), text_color=MUTED).pack(side="right")

    def _on_close_behavior(self, _value=None):
        """保存关闭方式设置。"""
        text = (self.close_combo.get() or "").strip()
        self.cfg["close_behavior"] = "tray" if text == "隐藏到托盘" else "exit"
        self._save_debounced()

    def _toggle_log(self):
        """展开 / 收起运行日志。"""
        self._log_visible = not self._log_visible
        if self._log_visible:
            self.log_box.grid()
            self.log_toggle_btn.configure(text="收起 ▴")
        else:
            self.log_box.grid_remove()
            self.log_toggle_btn.configure(text="展开 ▾")

    def _slider(self, parent, row, label_text):
        """一行: 左侧标题 + 右侧数值 + 下方滑条。返回 (row, slider, val_label)。"""
        frame = GlassFrame(parent)
        frame.grid(row=row, column=0, sticky="ew", padx=20, pady=(6, 0))
        row += 1
        frame.grid_columnconfigure(0, weight=1)
        GlassLabel(frame, text=label_text, font=("Microsoft YaHei UI", 13, "bold"),
                     text_color=TEXT).grid(row=0, column=0, sticky="w")
        val = GlassLabel(frame, text="", font=("Microsoft YaHei UI", 13, "bold"), text_color=ACCENT)
        val.grid(row=0, column=1, sticky="e")
        slider = ctk.CTkSlider(frame, from_=0, to=100, number_of_steps=100,
                               fg_color=SLIDER_TRACK, progress_color=ACCENT)
        slider.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        return row, slider, val

    def _build_mic_card(self, parent):
        card = GlassFrame(parent, is_panel=True)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        card.grid_columnconfigure(0, weight=1)
        row = 0

        head = GlassFrame(card)
        head.grid(row=row, column=0, sticky="ew", padx=20, pady=(16, 2)); row += 1
        GlassLabel(head, text="🎙️ 直播人声突显", font=("Microsoft YaHei UI", 18, "bold"),
                     text_color=ACCENT).pack(side="left")
        self.mic_switch = ctk.CTkSwitch(head, text="启用", font=("Microsoft YaHei UI", 14, "bold"),
                                        text_color=TEXT, fg_color=SLIDER_TRACK, button_color="#f8b6d0",
                                        progress_color=GREEN, command=self._sync_engines)
        self.mic_switch.pack(side="right")

        GlassLabel(card, text="检测到麦克风说话时，自动压低桌面输出音量，让直播 / 录制里的人声更突出。",
                     font=("Microsoft YaHei UI", 12, "bold"), text_color=MUTED,
                     wraplength=430, justify="left").grid(row=row, column=0, sticky="w", padx=20, pady=(0, 6)); row += 1

        # 麦克风设备
        devrow = GlassFrame(card)
        devrow.grid(row=row, column=0, sticky="ew", padx=20, pady=4); row += 1
        GlassLabel(devrow, text="麦克风设备", font=("Microsoft YaHei UI", 13, "bold"),
                     text_color=TEXT).pack(side="left")
        self.mic_combo = ctk.CTkComboBox(devrow, width=200, values=[""],
                                         font=("Microsoft YaHei UI", 13, "bold"),
                                         fg_color=INPUT_BG, button_color=BTN,
                                         button_hover_color=BTN_HOVER, border_color=CARD_BORDER)
        self.mic_combo.pack(side="left", padx=(10, 6))
        self.mic_combo.bind("<Return>", lambda e: self._on_mic_pick())
        self.mic_combo.bind("<FocusOut>", lambda e: self._on_mic_pick())
        ctk.CTkButton(devrow, text="刷新", width=60, height=28, font=("Microsoft YaHei UI", 13, "bold"),
                      fg_color=BTN, hover_color=BTN_HOVER, command=self._refresh_mics).pack(side="left")

        # 滑条
        row, self.mic_thr_slider, self.mic_thr_val = self._slider(card, row, "说话触发阈值（灵敏度）")
        self.mic_thr_slider.configure(command=self._on_mic_thr)
        row, self.mic_duck_slider, self.mic_duck_val = self._slider(card, row, "闪避后桌面音量")
        self.mic_duck_slider.configure(command=self._on_mic_duck)
        row, self.mic_delay_slider, self.mic_delay_val = self._slider(card, row, "停止说话后恢复延迟")
        self.mic_delay_slider.configure(command=self._on_mic_delay)

        # 电平表
        meter = GlassFrame(card)
        meter.grid(row=row, column=0, sticky="ew", padx=20, pady=(10, 0)); row += 1
        meter.grid_columnconfigure(1, weight=1)
        GlassLabel(meter, text="麦克风电平", font=("Microsoft YaHei UI", 13, "bold"),
                     text_color=TEXT).grid(row=0, column=0, sticky="w")
        self.mic_level_val = GlassLabel(meter, text="0%", font=("Microsoft YaHei UI", 13, "bold"),
                                          text_color=TEXT)
        self.mic_level_val.grid(row=0, column=2, sticky="e", padx=(10, 0))
        self.mic_meter = ctk.CTkProgressBar(meter, height=8, corner_radius=4,
                                            fg_color=SLIDER_TRACK, progress_color=ACCENT)
        self.mic_meter.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(2, 0))
        self.mic_meter.set(0)

        self.mic_status = GlassLabel(card, text="● 未启用", font=("Microsoft YaHei UI", 13, "bold"),
                                       text_color=MUTED)
        self.mic_status.grid(row=row, column=0, sticky="w", padx=20, pady=(8, 0)); row += 1
        self.mic_master = GlassLabel(card, text="桌面音量: --", font=("Microsoft YaHei UI", 13, "bold"),
                                       text_color=TEXT)
        self.mic_master.grid(row=row, column=0, sticky="w", padx=20, pady=(2, 16)); row += 1

    def _build_app_card(self, parent):
        card = GlassFrame(parent, is_panel=True)
        card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        card.grid_columnconfigure(0, weight=1)
        row = 0

        head = GlassFrame(card)
        head.grid(row=row, column=0, sticky="ew", padx=20, pady=(16, 2)); row += 1
        GlassLabel(head, text="💬 语音聊天闪避", font=("Microsoft YaHei UI", 18, "bold"),
                     text_color=ACCENT2).pack(side="left")
        self.app_switch = ctk.CTkSwitch(head, text="启用", font=("Microsoft YaHei UI", 14, "bold"),
                                        text_color=TEXT, fg_color=SLIDER_TRACK, button_color="#f8b6d0",
                                        progress_color=GREEN, command=self._sync_engines)
        self.app_switch.pack(side="right")

        GlassLabel(card, text="语音聊天应用一有声音输出，就自动压低音乐播放器的音量，凸显聊天人声。",
                     font=("Microsoft YaHei UI", 12, "bold"), text_color=MUTED,
                     wraplength=430, justify="left").grid(row=row, column=0, sticky="w", padx=20, pady=(0, 6)); row += 1

        # 语音应用
        row = self._app_row(card, row, "语音聊天应用", "voice")
        # 音乐应用
        row = self._app_row(card, row, "音乐播放应用", "music")

        # 滑条
        row, self.app_thr_slider, self.app_thr_val = self._slider(card, row, "语音输出触发阈值（灵敏度）")
        self.app_thr_slider.configure(command=self._on_app_thr)
        row, self.app_duck_slider, self.app_duck_val = self._slider(card, row, "闪避后音乐音量")
        self.app_duck_slider.configure(command=self._on_app_duck)
        row, self.app_delay_slider, self.app_delay_val = self._slider(card, row, "语音静默后恢复延迟")
        self.app_delay_slider.configure(command=self._on_app_delay)

        # 电平表
        meter = GlassFrame(card)
        meter.grid(row=row, column=0, sticky="ew", padx=20, pady=(10, 0)); row += 1
        meter.grid_columnconfigure(1, weight=1)
        GlassLabel(meter, text="语音输出电平", font=("Microsoft YaHei UI", 13, "bold"),
                     text_color=TEXT).grid(row=0, column=0, sticky="w")
        self.voice_level_val = GlassLabel(meter, text="0%", font=("Microsoft YaHei UI", 13, "bold"),
                                            text_color=TEXT)
        self.voice_level_val.grid(row=0, column=2, sticky="e", padx=(10, 0))
        self.voice_meter = ctk.CTkProgressBar(meter, height=8, corner_radius=4,
                                              fg_color=SLIDER_TRACK, progress_color=ACCENT2)
        self.voice_meter.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(2, 0))
        self.voice_meter.set(0)

        self.app_status = GlassLabel(card, text="● 未启用", font=("Microsoft YaHei UI", 13, "bold"),
                                       text_color=MUTED)
        self.app_status.grid(row=row, column=0, sticky="w", padx=20, pady=(8, 0)); row += 1
        self.music_vol_val = GlassLabel(card, text="音乐音量: --", font=("Microsoft YaHei UI", 13, "bold"),
                                          text_color=TEXT)
        self.music_vol_val.grid(row=row, column=0, sticky="w", padx=20, pady=(2, 16)); row += 1

    def _app_row(self, card, row, label_text, key):
        """一行应用选择: 标签 + 下拉框 + 刷新按钮。"""
        f = GlassFrame(card)
        f.grid(row=row, column=0, sticky="ew", padx=20, pady=4)
        row += 1
        GlassLabel(f, text=label_text, font=("Microsoft YaHei UI", 13, "bold"),
                     text_color=TEXT).pack(side="left")
        combo = ctk.CTkComboBox(f, width=200, values=[""], font=("Microsoft YaHei UI", 13, "bold"),
                                fg_color=INPUT_BG, button_color=BTN,
                                button_hover_color=BTN_HOVER, border_color=CARD_BORDER)
        combo.pack(side="left", padx=(10, 6))
        combo.configure(command=lambda _e, c=combo: self._on_app_pick())
        combo.bind("<Return>", lambda e: self._on_app_pick())
        combo.bind("<FocusOut>", lambda e: self._on_app_pick())
        ctk.CTkButton(f, text="刷新", width=60, height=28, font=("Microsoft YaHei UI", 13, "bold"),
                      fg_color=BTN, hover_color=BTN_HOVER,
                      command=self._refresh_apps).pack(side="left")
        if key == "voice":
            self.voice_combo = combo
        else:
            self.music_combo = combo
        return row

    # ================= 刷新与加载 =================

    def _refresh_mics(self):
        try:
            mics = audio_utils.list_mic_devices()
        except Exception as exc:
            mics = []
            self.log("麦克风枚举失败: %s" % exc)
        self._mic_map = {"%d: %s" % (i, name): i for i, name in mics}
        values = list(self._mic_map.keys())
        self.mic_combo.configure(values=values if values else [""])
        if values:
            cur = self.mic_combo.get()
            dev = self.cfg.get("mic_device")
            if cur and cur in self._mic_map:
                pass
            else:
                keep = next((k for k, v in self._mic_map.items() if v == dev), values[0])
                self.mic_combo.set(keep)
        else:
            self.mic_combo.set("")

    def _refresh_apps(self):
        sessions = audio_utils.get_sessions()
        names = sorted({s.name for s in sessions
                        if s.name and not s.name.startswith("PID ")
                        and s.name not in ("System Sounds", "AudioSrv")})
        for combo in (self.voice_combo, self.music_combo):
            cur = combo.get()
            combo.configure(values=names)
            if cur:
                combo.set(cur)      # 保留已选值(即使不在列表, 允许手动输入)

    def _load_to_ui(self):
        # 滑条 -> 控件
        self.mic_thr_slider.set(round(self.cfg["mic_threshold"] / 0.005))
        self.mic_duck_slider.set(round(self.cfg["mic_duck_level"] * 100))
        self.mic_delay_slider.set(round(self.cfg["mic_release_delay"] * 20))
        self.app_thr_slider.set(round(self.cfg["app_threshold"] * 100))
        self.app_duck_slider.set(round(self.cfg["app_duck_level"] * 100))
        self.app_delay_slider.set(round(self.cfg["app_release_delay"] * 20))
        # 数值标签
        self._refresh_slider_labels()
        # 应用选择
        self.voice_combo.set(self.cfg.get("voice_app") or "")
        self.music_combo.set(self.cfg.get("music_app") or "")
        # 关闭方式
        self.close_combo.set("隐藏到托盘" if self.cfg.get("close_behavior") == "tray" else "直接关闭")
        # 开关
        self.mic_switch.select() if self.cfg["mic_duck_enabled"] else self.mic_switch.deselect()
        self.app_switch.select() if self.cfg["app_duck_enabled"] else self.app_switch.deselect()
        # 按配置启动引擎
        self._sync_engines()

    def _refresh_slider_labels(self):
        self.mic_thr_val.configure(text=str(round(self.mic_thr_slider.get())))
        self.mic_duck_val.configure(text="%d%%" % round(self.mic_duck_slider.get()))
        self.mic_delay_val.configure(text="%.1f 秒" % (self.mic_delay_slider.get() * 0.05))
        self.app_thr_val.configure(text=str(round(self.app_thr_slider.get())))
        self.app_duck_val.configure(text="%d%%" % round(self.app_duck_slider.get()))
        self.app_delay_val.configure(text="%.1f 秒" % (self.app_delay_slider.get() * 0.05))

    # ================= 引擎启停 =================

    def _sync_engines(self):
        mic_on = bool(self.mic_switch.get())
        app_on = bool(self.app_switch.get())

        # --- 麦克风闪避 ---
        if mic_on and not self.mic_engine.running:
            dev = self.cfg.get("mic_device")
            if dev is None and self._mic_map:
                dev = next(iter(self._mic_map.values()))
                self.cfg["mic_device"] = dev
                self._on_mic_pick()
            self.mic_engine.start(dev, self.cfg["mic_threshold"], self.cfg["mic_duck_level"],
                                  self.cfg["mic_release_delay"])
            if self.mic_engine.error:
                self.log("⚠ " + self.mic_engine.error)
            else:
                self.log("🎙️ 麦克风闪避已启用（检测到说话将自动压低桌面音量）")
            self._last_mic_state = None
        elif not mic_on and self.mic_engine.running:
            self.mic_engine.stop(restore=True)
            self.log("🎙️ 麦克风闪避已停用，桌面音量已恢复")
            self._last_mic_state = None

        # --- 语音聊天闪避 ---
        voice = (self.voice_combo.get() or "").strip()
        music = (self.music_combo.get() or "").strip()
        if app_on and not self.app_engine.running:
            if not voice or not music:
                self.log("⚠ 语音闪避: 请先选择「语音聊天应用」与「音乐播放应用」"
                         "（可从下拉框选择，也可手动输入进程名）")
                self.app_switch.deselect()
                app_on = False  # 修正状态, 避免每次启动都重复告警
            elif voice.lower() == music.lower():
                self.log("⚠ 语音闪避: 两个应用不能相同")
                self.app_switch.deselect()
                app_on = False
            else:
                self.app_engine.start(voice, music, self.cfg["app_threshold"],
                                      self.cfg["app_duck_level"], self.cfg["app_release_delay"])
                self.log("💬 语音闪避已启用：语音=%s · 音乐=%s" % (voice, music))
                self._last_app_state = None
        elif not app_on and self.app_engine.running:
            self.app_engine.stop(restore=True)
            self.log("💬 语音闪避已停用，音乐音量已恢复")
            self._last_app_state = None

        self.cfg["mic_duck_enabled"] = mic_on
        self.cfg["app_duck_enabled"] = app_on
        self.cfg["voice_app"] = voice
        self.cfg["music_app"] = music
        self._save_debounced()

    # ================= 控件回调 =================

    def _on_mic_pick(self):
        text = self.mic_combo.get().strip()
        self.cfg["mic_device"] = self._mic_map.get(text)
        if self.mic_engine.running:
            self.mic_engine.update(device=self.cfg["mic_device"])
        self._save_debounced()

    def _on_app_pick(self):
        self.cfg["voice_app"] = (self.voice_combo.get() or "").strip()
        self.cfg["music_app"] = (self.music_combo.get() or "").strip()
        if self.app_engine.running:
            self.app_engine.update(voice_app=self.cfg["voice_app"], music_app=self.cfg["music_app"])
        self._save_debounced()

    def _on_mic_thr(self, v):
        val = round(v)
        self.cfg["mic_threshold"] = round(val * 0.005, 4)
        self.mic_thr_val.configure(text=str(val))
        if self.mic_engine.running:
            self.mic_engine.update(threshold=self.cfg["mic_threshold"])
        self._save_debounced()

    def _on_mic_duck(self, v):
        val = round(v)
        self.cfg["mic_duck_level"] = val / 100.0
        self.mic_duck_val.configure(text="%d%%" % val)
        if self.mic_engine.running:
            self.mic_engine.update(duck_level=self.cfg["mic_duck_level"])
        self._save_debounced()

    def _on_mic_delay(self, v):
        val = round(v)
        sec = val * 0.05
        self.cfg["mic_release_delay"] = round(sec, 2)
        self.mic_delay_val.configure(text="%.1f 秒" % sec)
        if self.mic_engine.running:
            self.mic_engine.update(release_delay=self.cfg["mic_release_delay"])
        self._save_debounced()

    def _on_app_thr(self, v):
        val = round(v)
        self.cfg["app_threshold"] = val / 100.0
        self.app_thr_val.configure(text=str(val))
        if self.app_engine.running:
            self.app_engine.update(threshold=self.cfg["app_threshold"])
        self._save_debounced()

    def _on_app_duck(self, v):
        val = round(v)
        self.cfg["app_duck_level"] = val / 100.0
        self.app_duck_val.configure(text="%d%%" % val)
        if self.app_engine.running:
            self.app_engine.update(duck_level=self.cfg["app_duck_level"])
        self._save_debounced()

    def _on_app_delay(self, v):
        val = round(v)
        sec = val * 0.05
        self.cfg["app_release_delay"] = round(sec, 2)
        self.app_delay_val.configure(text="%.1f 秒" % sec)
        if self.app_engine.running:
            self.app_engine.update(release_delay=self.cfg["app_release_delay"])
        self._save_debounced()

    # ================= 轮询刷新与日志 =================

    def _poll(self):
        # 单实例: 检测到"再次打开"请求 -> 显示窗口到前台
        if single_instance.is_show_requested(getattr(self, "_show_event", None)):
            self.deiconify()
            self.lift()
        # 处理托盘菜单命令 (托盘线程设置, 主线程安全消费)
        cmd = getattr(self, "_tray_cmd", None)
        if cmd:
            self._tray_cmd = None
            if cmd == "show":
                self.deiconify()
                self.lift()
            elif cmd == "exit":
                self._real_close()
                return
        # 处理自动更新检查结果
        self._consume_update()
        # --- 麦克风卡片 ---
        rms = self.mic_engine.mic_rms
        level = min(1.0, rms / MIC_MAX_DISPLAY)
        if abs(level - getattr(self, "_last_mic_level", -1.0)) >= 0.005:
            self.mic_meter.set(level)
            self._last_mic_level = level
        self.mic_level_val.configure(text="%d%%" % min(100, int(rms / MIC_MAX_DISPLAY * 100)))
        self.mic_master.configure(text="桌面音量: %d%%" % round(self.mic_engine.master_now * 100))
        if self.mic_engine.running:
            text, color = self._mic_state_text(self.mic_engine.state)
        else:
            text, color = "● 未启用", MUTED
        self.mic_status.configure(text=text, text_color=color)
        if self.mic_engine.running and self.mic_engine.state != self._last_mic_state:
            self._last_mic_state = self.mic_engine.state
            if self.mic_engine.state == "ducked":
                self.log("🎙️ 检测到说话，桌面音量正在压低…")
            elif self.mic_engine.state == "restoring":
                self.log("🎙️ 已停止说话，桌面音量恢复中…")

        # --- 语音闪避卡片 ---
        peak = self.app_engine.voice_peak
        if abs(peak - getattr(self, "_last_voice_level", -1.0)) >= 0.005:
            self.voice_meter.set(min(1.0, peak))
            self._last_voice_level = peak
        self.voice_level_val.configure(text="%d%%" % min(100, int(peak * 100)))
        self.music_vol_val.configure(text="音乐音量: %d%%" % round(self.app_engine.music_volume_now * 100))
        if self.app_engine.running:
            text, color = self._app_state_text(self.app_engine.state)
        else:
            text, color = "● 未启用", MUTED
        self.app_status.configure(text=text, text_color=color)
        if self.app_engine.running and self.app_engine.state != self._last_app_state:
            self._last_app_state = self.app_engine.state
            st = self.app_engine.state
            if st == "ducked":
                self.log("💬 语音聊天有输出，音乐音量正在压低…")
            elif st == "restoring":
                self.log("💬 语音已静默，音乐音量恢复中…")
            elif st == "no_voice":
                self.log("💬 等待语音应用输出（请确认已开麦）…")
            elif st == "no_music":
                self.log("💬 未找到音乐应用的音频会话（请确认音乐正在播放）")

        # --- 错误上报 ---
        if self.mic_engine.error != self._last_err:
            self._last_err = self.mic_engine.error
            if self.mic_engine.error:
                self.log("⚠ " + self.mic_engine.error)

        # --- 全局状态 ---
        n = int(self.mic_engine.running) + int(self.app_engine.running)
        if n:
            self.status_label.configure(text="● 运行中（%d 项闪避功能）" % n, text_color=GREEN)
        else:
            self.status_label.configure(text="● 未启用任何闪避功能", text_color=MUTED)

        self.after(150, self._poll)

    @staticmethod
    def _mic_state_text(state):
        if state == "ducked":
            return "🎤 说话中 · 桌面音量已闪避", ACCENT
        if state == "restoring":
            return "🔄 已停止说话 · 音量恢复中", ORANGE
        return "● 待机 · 等待说话", MUTED

    @staticmethod
    def _app_state_text(state):
        return {
            "ducked":   ("💬 语音中 · 音乐已闪避", ACCENT2),
            "restoring":("🔄 语音结束 · 音乐恢复中", ORANGE),
            "no_voice": ("○ 等待语音应用输出…", MUTED),
            "no_music": ("○ 未找到音乐应用会话", MUTED),
            "normal":   ("● 待机 · 等待语音输出", MUTED),
        }.get(state, ("● 待机", MUTED))

    def log(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", "[%s] %s\n" % (_now_tag(), msg))
        lines = int(self.log_box.index("end-1c").split(".")[0])
        if lines > 300:
            self.log_box.delete("1.0", "%d.0" % (lines - 200))
        if lines > 6:  # 内容超过可视区才滚动, 避免昂贵的 see() 阻塞启动
            self.log_box.see("end")
        self.log_box.configure(state="disabled")

    # ================= 配置保存与退出 =================

    def _save_debounced(self):
        if self._save_job:
            self.after_cancel(self._save_job)
        self._save_job = self.after(400, self._save_now)

    def _save_now(self):
        self._save_job = None
        cfg_mod.save_config(self.cfg)

    def on_close(self):
        """点击窗口关闭按钮: 按设置隐藏到托盘后台运行, 或直接退出。"""
        if self.cfg.get("close_behavior") == "tray" and self._ensure_tray():
            self.withdraw()          # 隐藏窗口, 应用继续后台运行
            try:
                self._tray_icon.notify("音频自动闪避助手正在后台运行")
            except Exception:
                pass
        else:
            self._real_close()

    def _ensure_tray(self):
        """创建系统托盘图标 (幂等)。成功返回 True, 失败返回 False。"""
        if getattr(self, "_tray_icon", None) is not None:
            return True
        try:
            import pystray
            from PIL import Image as _PILImage
        except Exception:
            self.log("⚠ 托盘组件不可用, 已改为直接关闭")
            return False
        try:
            ico = self._icon_path()
            image = _PILImage.open(ico) if ico else _PILImage.new("RGB", (32, 32), "#f06a9e")
            menu = pystray.Menu(
                pystray.MenuItem("显示主窗口", self._tray_show, default=True),
                pystray.MenuItem("退出", self._tray_exit),
            )
            self._tray_icon = pystray.Icon("AudioDuck", image, "音频自动闪避助手", menu)
            self._tray_icon.run_detached()
            return True
        except Exception as exc:
            self.log("⚠ 托盘图标创建失败: %s" % exc)
            return False

    def _tray_show(self, *_args):
        """托盘菜单: 显示主窗口 (经轮询线程安全地执行)。"""
        self._tray_cmd = "show"

    def _tray_exit(self, *_args):
        """托盘菜单: 完全退出。"""
        self._tray_cmd = "exit"

    def _real_close(self):
        """完全退出: 停止引擎, 保存配置, 移除托盘图标, 关闭窗口。"""
        self.mic_engine.stop(restore=True)
        self.app_engine.stop(restore=True)
        cfg_mod.save_config(self.cfg)
        icon = getattr(self, "_tray_icon", None)
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass
        self.destroy()

    # ================= 自动更新 =================

    def _update_url(self):
        url = (self.cfg.get("update_url") or "").strip()
        return url or updater.UPDATE_URL

    def _start_update_check(self, manual=False):
        """后台线程检查更新 (不阻塞 UI), 结果由 _poll 消费。"""
        def worker():
            try:
                has_new, info, err = updater.check_update(self._update_url())
            except Exception as exc:
                has_new, info, err = False, None, str(exc)
            self._update_result = (has_new, info, err, manual)
            self._update_cmd = "result"
        threading.Thread(target=worker, daemon=True).start()

    def _manual_update_check(self):
        if getattr(self, "_update_checking", False):
            return
        self._update_checking = True
        self.update_btn.configure(state="disabled", text="检查中...")
        self._start_update_check(manual=True)

    def _consume_update(self):
        """处理更新检查结果 (主线程)。"""
        cmd = getattr(self, "_update_cmd", None)
        if not cmd:
            return
        self._update_cmd = None
        if cmd != "result":
            return
        import tkinter.messagebox as mb
        self._update_checking = False
        self.update_btn.configure(state="normal", text="检查更新")
        has_new, info, err, manual = self._update_result
        if err:
            if manual:
                mb.showerror("检查更新", err, parent=self)
            else:
                self.log("⚠ 自动更新检查失败: %s" % err)
        elif not has_new:
            if manual:
                mb.showinfo("检查更新", "当前已是最新版本 (v%s)" % updater.APP_VERSION, parent=self)
        else:
            notes = (info.get("notes") or "无")
            if mb.askyesno("发现新版本",
                           "发现新版本 v%s (当前 v%s)\n\n更新说明:\n%s\n\n是否立即下载并更新?"
                           % (info["version"], updater.APP_VERSION, notes),
                           parent=self):
                self._apply_update(info)

    def _apply_update(self, info):
        import tkinter.messagebox as mb
        ok, msg = updater.apply_update(info)
        if not ok:
            mb.showerror("更新失败", msg, parent=self)
            return
        self.log("🔄 " + msg)
        mb.showinfo("自动更新", msg + "\n\n程序即将关闭, 片刻后将自动重启为最新版本。", parent=self)
        self._real_close()
