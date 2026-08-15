# -*- coding: utf-8 -*-
"""生成应用图标 icon.ico (纯标准库实现, 无需 Pillow)。

绘制: 圆角方形渐变底 + 白色麦克风图形, 输出多尺寸 ICO。
"""
import struct
import zlib


# ---------------- PNG 编码 ----------------

def _png_chunk(tag, data):
    chunk = tag + data
    return struct.pack(">I", len(data)) + chunk + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)


def encode_png(width, height, rgba_rows):
    raw = b"".join(b"\x00" + row for row in rgba_rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8bit RGBA
    return (b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(raw, 9))
            + _png_chunk(b"IEND", b""))


# ---------------- 几何判定 (坐标基于 256x256) ----------------

def _seg_inside(x, y, x1, y1, x2, y2, r):
    dx = x2 - x1
    dy = y2 - y1
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else ((x - x1) * dx + (y - y1) * dy) / l2
    t = max(0.0, min(1.0, t))
    px = x1 + t * dx
    py = y1 + t * dy
    return (x - px) ** 2 + (y - py) ** 2 <= r * r


def _rounded_rect_inside(x, y, x0, y0, x1, y1, r):
    if x0 <= x <= x1 and y0 <= y <= y1:
        dx = max(x0 + r - x, 0.0, x - (x1 - r))
        dy = max(y0 + r - y, 0.0, y - (y1 - r))
        return dx * dx + dy * dy <= r * r
    return False


def _mic_inside(x, y):
    """白色麦克风: 胶囊体 + 弧形支架 + 立杆。"""
    if _seg_inside(x, y, 128, 80, 128, 130, 20):      # 胶囊体
        return True
    if y >= 150:                                       # 弧形支架(下半圆环)
        d2 = (x - 128) ** 2 + (y - 150) ** 2
        if 22 * 22 <= d2 <= 32 * 32:
            return True
    if _seg_inside(x, y, 128, 182, 128, 208, 6):      # 立杆
        return True
    return False


# ---------------- 渲染 ----------------

SS = 4  # 每像素 4x4 超采样抗锯齿
TOP = (122, 162, 247)    # #7aa2f7
BOTTOM = (157, 123, 245)  # #9d7bf5


def render(size):
    scale = 256.0 / size
    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            cov_bg = 0.0
            cov_fg = 0.0
            for sy in range(SS):
                for sx in range(SS):
                    x = (px + (sx + 0.5) / SS) * scale
                    y = (py + (sy + 0.5) / SS) * scale
                    if _rounded_rect_inside(x, y, 14, 14, 242, 242, 58):
                        cov_bg += 1.0
                    if _mic_inside(x, y):
                        cov_fg += 1.0
            cov_bg /= SS * SS
            cov_fg /= SS * SS
            if cov_bg <= 0.0:
                row += b"\x00\x00\x00\x00"
                continue
            t = (py + 0.5) / size
            bg_r = TOP[0] + (BOTTOM[0] - TOP[0]) * t
            bg_g = TOP[1] + (BOTTOM[1] - TOP[1]) * t
            bg_b = TOP[2] + (BOTTOM[2] - TOP[2]) * t
            a = cov_fg
            r = int(bg_r * (1 - a) + 255 * a)
            g = int(bg_g * (1 - a) + 255 * a)
            b = int(bg_b * (1 - a) + 255 * a)
            row += bytes((r, g, b, int(cov_bg * 255)))
        rows.append(bytes(row))
    return rows


def pack_ico(images):
    """images: [(size, png_bytes), ...]"""
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)
    entries = b""
    body = b""
    offset = 6 + 16 * count
    for size, png in images:
        w = size if size < 256 else 0
        h = size if size < 256 else 0
        entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(png), offset)
        body += png
        offset += len(png)
    return header + entries + body


def main():
    images = []
    for size in (256, 128, 64, 48, 32, 16):
        rows = render(size)
        images.append((size, encode_png(size, size, rows)))
        print("rendered %dx%d" % (size, size))
    with open("icon.ico", "wb") as f:
        f.write(pack_ico(images))
    print("icon.ico written")


if __name__ == "__main__":
    main()
