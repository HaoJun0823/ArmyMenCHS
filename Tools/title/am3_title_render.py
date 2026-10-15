# -*- coding: utf-8 -*-
"""Army3 title 贴图汉化：抹字 + 用官方 13x13 点阵写字。

对每一处文字行：
    1. 在该行盒内按亮度判定"非背景"像素（含文字与 1px 描边），
       用同行左右最近背景像素做线性插值填补 —— 保留横向渐变与底纹过渡
    2. 用 Hzk16（官方中文版字库，与游戏实机同一套字形）渲染译文
    3. 竖向居中于原行、横向默认居中（同一列出现 ≥3 个左对齐块时自动改左对齐）
    4. 按原文样式补 1px 描边（描边色从原图采样）
"""
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from am3_hzk16 import Hzk16

SRC = r"G:\Projects\ArmyMenCHS\Army3_Object_CHS\title\png_ai"
WORK = r"I:\LocalGames\Army Men\_am3_title_work"
PALETTE = r"G:\Projects\ArmyMenCHS\Army3_Object_CHS\title\palette.bin"
FONT = Hzk16()

# ── 调色板吸附 ──────────────────────────────────────────────────────
# 本作贴图是 256 色索引图；线性插值产生的过渡色不在调色板里，打包时会就近
# 匹配（最大距离 5），会在纯色背景上留下肉眼可见的噪点。这里直接吸附。
_PAL_RGB = None
_PAL_LUT = None          # (r,g,b) -> 索引


def _palette():
    global _PAL_RGB, _PAL_LUT
    if _PAL_RGB is None:
        pal = open(PALETTE, "rb").read()
        cols = []
        for i in range(256):
            b, g, r, _ = pal[i * 4:i * 4 + 4]
            cols.append((r, g, b))
        _PAL_RGB = cols
        _PAL_LUT = {}
        for i, c in enumerate(cols):
            _PAL_LUT.setdefault(c, i)
    return _PAL_RGB, _PAL_LUT


def snap_to_palette(arr):
    """把整图吸附到最近的调色板色（精确命中则原样）。"""
    pal, lut = _palette()
    flat = arr.reshape(-1, 3)
    out = np.empty_like(flat)
    cache = {}
    uniq, inv = np.unique(flat, axis=0, return_inverse=True)
    res = np.empty_like(uniq)
    pal_a = np.array(pal, dtype=np.int32)
    for i, c in enumerate(uniq):
        t = (int(c[0]), int(c[1]), int(c[2]))
        if t in lut:
            res[i] = c
            continue
        d = np.abs(pal_a - c.astype(np.int32)).sum(axis=1)
        res[i] = pal_a[int(d.argmin())]
    out = res[inv].reshape(arr.shape)
    return out

_LATIN = None


def latin_bitmaps():
    """ASCII 32..126 的二值位图（SimSun 12px 内嵌点阵二值化）。"""
    global _LATIN
    if _LATIN is not None:
        return _LATIN
    from PIL import ImageDraw, ImageFont
    f = ImageFont.truetype(r"C:\Windows\Fonts\simsun.ttc", 12)
    out = {}
    for code in range(32, 127):
        ch = chr(code)
        im = Image.new("L", (18, 18), 0)
        ImageDraw.Draw(im).text((3, 2), ch, font=f, fill=255)
        a = np.asarray(im)
        ys, xs = np.nonzero(a > 110)
        if len(ys) == 0:
            out[ch] = (len(ch) and 5 or 5, 1, [0])
            continue
        y1, y2, x1, x2 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
        rows = []
        for y in range(y1, y2 + 1):
            v = 0
            for x in range(x1, x2 + 1):
                v = (v << 1) | (1 if a[y, x] > 110 else 0)
            rows.append(v)
        out[ch] = (x2 - x1 + 1, y2 - y1 + 1, rows)
    _LATIN = out
    return out


def glyph(ch):
    """返回 (宽, 高, 行位掩码, 基线偏移)。汉字为 13x13 全格；ASCII 为紧凑位图。"""
    if ch == " ":
        return (7, 1, [0], 0)
    gb = None
    try:
        gb = ch.encode("gbk")
    except UnicodeEncodeError:
        gb = None
    if gb and len(gb) == 2 and gb[0] >= 0x81:
        rows = FONT.bits(ch)
        if rows:
            return (FONT.width, FONT.height, rows, 0)
    lat = latin_bitmaps().get(ch)
    if lat and lat[2]:
        # ASCII 基线对齐：字面底边落在 13 格的第 12 行（汉字基线附近）
        y_off = 12 - (lat[1] - 1)
        return (lat[0], lat[1], lat[2], y_off)
    return (13, 13, [0b1111111111111] + [0b1000000000001] * 11 + [0b1111111111111], 0)


def layout(text, tracking=1):
    items = [glyph(c) for c in text]
    w = sum(g[0] for g in items) + tracking * max(0, len(items) - 1)
    rows = [0] * FONT.height
    x = 0
    for gw, gh, grows, yoff in items:
        for i, v in enumerate(grows):
            rows[yoff + i] |= v << (w - x - gw)
        x += gw + tracking
    return w, FONT.height, rows


def render_mask(text, tracking=1):
    w, h, rows = layout(text, tracking)
    # 去掉整行全空的首尾（保持 13 格网格，避免上下跳动）
    return w, h, rows


def detect_style(arr, L):
    """原文的文字样式。

    实测结论：原英文是"纯白/黄/绿字形 + 1px 灰色抗锯齿环"（调色板里恰好是
    ABABAB/C6C6C6/8E8E8E 这几个灰）——那是 **抗锯齿**，不是描边。
    汉字点阵（Hzk16）本身是 1bit 无抗锯齿，再套一圈描边只会糊，所以默认不加。
    需要时用译文表的 outline=RRGGBB 显式指定。
    """
    return False, None


def inpaint(arr, L, tol=14, grow=2):
    """抹掉行盒内的文字与描边。

    掩码 = 精确前景色匹配（lines.json 已给出实测穷举的 4 个文字色）
           ∪ 与"盒外背景亮度"差 > tol 的像素（吃掉抗锯齿过渡与彩色描边），
    再膨胀 grow 像素。填充：同行左右最近的非掩码像素线性插值
    （背景在这些面板上沿水平方向基本是常量，插值可保住横向渐变与底纹）。

    注意：**不能**用盒内逐行众数估计背景 —— 标题行的文字宽度可占该行 80%，
    众数会变成文字色，导致掩码整个翻转、抹字失效。
    """
    x1, y1, x2, y2 = L["x1"], L["y1"], L["x2"], L["y2"]
    h, w = arr.shape[:2]
    # ★ 左右各留 10px 边距：x1/x2 是"精确色"首末列，而抗锯齿灰晕还会往外
    #   延伸约 2~3px；边距不够时晕会被当成背景锚点，插值出一条灰带。
    MARGIN = 10
    bx1, bx2 = max(0, x1 - MARGIN), min(w, x2 + 1 + MARGIN)
    by1, by2 = max(0, y1 - 2), min(h, y2 + 3)
    reg = arr[by1:by2, bx1:bx2].astype(np.int16)
    H, W = reg.shape[:2]
    lu = 0.299 * reg[:, :, 0] + 0.587 * reg[:, :, 1] + 0.114 * reg[:, :, 2]

    fg = np.array(L["fg"], dtype=np.int16)
    mask = np.all(reg == fg, axis=2)

    # 盒外背景亮度：取盒左右各 2 列的均值（无文字）
    ref = []
    if x1 - 4 >= 0:
        seg = arr[y1:y2 + 1, max(0, x1 - 5):max(1, x1 - 2)].astype(np.int16)
        ref.append(0.299 * seg[:, :, 0] + 0.587 * seg[:, :, 1] + 0.114 * seg[:, :, 2])
    if x2 + 5 <= w:
        seg = arr[y1:y2 + 1, x2 + 3:x2 + 6].astype(np.int16)
        ref.append(0.299 * seg[:, :, 0] + 0.587 * seg[:, :, 1] + 0.114 * seg[:, :, 2])
    if ref:
        bl = np.concatenate(ref, axis=1).mean(axis=1)          # 每行一个背景亮度
        yb1 = y1 - by1
        for y in range(H):
            ry = min(max(y - yb1, 0), len(bl) - 1)
            mask[y] |= np.abs(lu[y] - bl[ry]) > tol

    # 膨胀 grow 次
    for _ in range(grow):
        d = mask.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                sh = np.zeros_like(mask)
                ys0, ys1 = max(0, dy), H + min(0, dy)
                xs0, xs1 = max(0, dx), W + min(0, dx)
                sh[ys0:ys1, xs0:xs1] = mask[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
                d |= sh
        mask = d
    # ★ 两端各留 3 列强制作为背景锚点：
    #   否则标题行（文字占该行 80%+）膨胀后整行被掩，插值左右都取不到值，抹字静默失效。
    ANCHOR = 3
    mask[:, :ANCHOR] = False
    mask[:, W - ANCHOR:] = False

    out = reg.astype(np.float32)
    for y in range(H):
        row = mask[y]
        if not row.any():
            continue
        i = 0
        while i < W:
            if not row[i]:
                i += 1
                continue
            j = i
            while j + 1 < W and row[j + 1]:
                j += 1
            li = i - 1
            while li >= 0 and row[li]:
                li -= 1
            ri = j + 1
            while ri < W and row[ri]:
                ri += 1
            left = out[y, li] if li >= 0 else None
            right = out[y, ri] if ri < W else None
            for k in range(i, j + 1):
                if left is not None and right is not None:
                    t = (k - li) / float(ri - li)
                    out[y, k] = left * (1 - t) + right * t
                elif left is not None:
                    out[y, k] = left
                elif right is not None:
                    out[y, k] = right
            i = j + 1
    arr[by1:by2, bx1:bx2] = np.clip(out + 0.5, 0, 255).astype(np.uint8)
    return arr, mask


def blit(arr, text, x, y, w, h, rows, color, outline=None, tracking=1):
    H, W = arr.shape[:2]

    def put(xx, yy, c):
        if 0 <= xx < W and 0 <= yy < H:
            arr[yy, xx] = c

    if outline is not None:
        for yy, r in enumerate(rows):
            for xx in range(w):
                if (r >> (w - 1 - xx)) & 1:
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            if dx or dy:
                                put(x + xx + dx, y + yy + dy, outline)
    for yy, r in enumerate(rows):
        for xx in range(w):
            if (r >> (w - 1 - xx)) & 1:
                put(x + xx, y + yy, color)


def process(path, plan, lines_rec, out_path):
    im = Image.open(path).convert("RGB")
    arr = np.asarray(im).copy()

    # 自动对齐判定：同一列(±3px)出现 >=3 个文字块 -> 该列左对齐
    left_cols = {}
    for L in lines_rec["lines"]:
        left_cols.setdefault(round(L["x1"] / 4), []).append(L["x1"])
    col_members = {}
    for k, v in left_cols.items():
        for a in v:
            col_members[a] = len(v)

    applied = []
    residues = []
    for idx in sorted(plan.keys()):
        spec = plan[idx]
        L = lines_rec["lines"][idx - 1]
        # span：跨多个行盒的一条文本（原文被切成两段，如 "MAP / OBJECTIVE"）。
        # 一并擦除所有行盒，几何取并集，只画一次。
        span = spec.get("span") or []
        regions = [L] + [lines_rec["lines"][k - 1] for k in span]
        for R_ in regions:
            arr, _ = inpaint(arr, R_)
        ux1 = min(r["x1"] for r in regions)
        ux2 = max(r["x2"] for r in regions)
        uy1 = min(r["y1"] for r in regions)
        uy2 = max(r["y2"] for r in regions)
        fg = np.array(L["fg"], dtype=np.int16)
        left = sum(int(np.all(arr[r["y1"]:r["y2"] + 1, r["x1"]:r["x2"] + 1] == fg, axis=2).sum())
                   for r in regions)
        if left > 2:
            residues.append((idx, left))
        if not spec.get("text"):
            applied.append((idx, "", None))
            continue
        text = spec["text"]
        tracking = spec.get("tracking", 1)
        w, h, rows = render_mask(text, tracking)
        cy = (uy1 + uy2 + 1) / 2.0
        y = int(round(cy - h / 2.0))
        if spec.get("align") == "left":
            x = ux1
        elif spec.get("align") == "right":
            x = ux2 + 1 - w
        elif spec.get("align") == "center":
            x = int(round((ux1 + ux2 + 1) / 2.0 - w / 2.0))
        elif col_members.get(ux1, 0) >= 3:
            x = ux1
        else:
            x = int(round((ux1 + ux2 + 1) / 2.0 - w / 2.0))
        if spec.get("dx"):
            x += spec["dx"]
        if spec.get("dy"):
            y += spec["dy"]
        color = spec.get("color") or tuple(L["fg"])
        outline = spec.get("outline")
        blit(arr, text, x, y, w, h, rows, tuple(color), outline, tracking)
        applied.append((idx, text, (x, y, w, h)))
    # 全图吸附到调色板，保证回包时零色差
    arr = snap_to_palette(arr)
    Image.fromarray(arr).save(out_path)
    return applied, residues
