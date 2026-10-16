# -*- coding: utf-8 -*-
"""AM4 shared 面板贴图汉化（生产工具）。

沿用 3 代 Tools/title/am3_title_render.py 的算法思路（抹字插值 + Hzk16
13x13 点阵 + 调色板吸附），但**独立实现**。两代有四处实质差异：

  1. 调色板不同（256 条里 172 条不同）→ 用 4 代自己的 palette.bin
  2. 文字色不同（实测）：
         FFFFFF  白   —— 常态文字 / 选中态标签
         9CAA7B  暗绿 —— 未选中态标签（与 3 代白名单同名同值）
         113/142 灰   —— 抗锯齿环，非字形主体
     3 代的 FFFBF0 / FEE402 / 29DF29 在本批面板未出现。
  3. 面板布局不同：3 代 obj_0101 是 4 段，4 代是 3 段 → 3 代成品不可直接搬
  4. **标签页双态**：同一行里选中态是白、未选中态是暗绿，必须分块分色重绘
     （3 代没有这种一行多态的控件）

配置为显式行盒表（实测 + 目视核对），不用自动检测 —— 4 代面板底色是绿色
纹理，自动检测会把边框/箭头一起吃进来。

抹字插值两种模式：
    "h"  左右插值 —— 普通文字行（行内有充足背景）
    "v"  上下插值 —— 标签页（文字占满盒宽，左右无锚点；锚点行由 top/bot 显式给出，
                      必须落在盒**内部**，避开上下边框，否则会把边框色插进盒内成雾带）

★ 本脚本不修改 3 代任何文件；只 import 3 代的 Hzk16 读取器。
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, r"G:\Projects\ArmyMenCHS\Tools\title")
from am3_hzk16 import Hzk16  # noqa: E402

SHARED = r"G:\Projects\ArmyMenCHS\Army4_Object_CHS\shared"
SRC = os.path.join(SHARED, "png")
PALETTE = os.path.join(SHARED, "palette.bin")
FONT = Hzk16()

WHITE = (255, 255, 255)
GRAY = (113, 113, 113)
DARKGREEN = (156, 170, 123)      # 9CAA7B
COLORS = {"white": WHITE, "gray": GRAY, "dark": DARKGREEN}

# 标签页三盒（实测 y167 顶边框的非背景连续段）与盒内字形包围盒
TAB_BOXES = [(2, 52), (57, 101), (106, 141)]

TAB_ROWS = dict(y1=170, y2=178, top=[168, 169], bot=[179], mode="v", gh=9)

# ── 行盒表 ──────────────────────────────────────────────────────────────
LINES = {
    "obj_0101_k00580000.png": [
        dict(y1=139, y2=153, x1=40, x2=103, en="SELECTED UNITS", zh="选中的单位"),
        dict(y1=327, y2=341, x1=56, x2=87, en="SQUADS", zh="分队"),
        dict(y1=410, y2=424, x1=60, x2=82, en="MODE", zh="模式"),
    ],
    "obj_0102_k00580001.png": [
        dict(y1=145, y2=158, x1=25, x2=68, en="PLASTIC", zh="塑料"),
        dict(y1=164, y2=176, x1=59, x2=83, en="UNITS", zh="部队"),
        dict(y1=247, y2=259, x1=57, x2=85, en="ASSETS", zh="资产"),
        dict(y1=399, y2=411, x1=26, x2=55, en="FACING", zh="面向"),
        dict(y1=399, y2=411, x1=90, x2=116, en="SQUAD", zh="分队"),
    ],
    "obj_0103_k00580002.png": [
        dict(y1=145, y2=158, x1=25, x2=68, en="PLASTIC", zh="塑料"),
        dict(TAB_ROWS, x1=3, x2=51, en="TROOPERS", zh="部队", color="dark"),
        dict(TAB_ROWS, x1=58, x2=100, en="VEHICLES", zh="载具", color="white"),
        dict(TAB_ROWS, x1=107, x2=140, en="ASSETS", zh="资产", color="dark"),
        dict(y1=181, y2=194, x1=47, x2=96, en="ARMY MEN", zh="军队"),
        dict(y1=304, y2=316, x1=32, x2=111, en="GALACTIC ARMY", zh="银河军队"),
        dict(y1=386, y2=398, x1=59, x2=87, en="FACING", zh="面向"),
    ],
    "obj_0104_k00580003.png": [
        dict(y1=145, y2=158, x1=25, x2=68, en="PLASTIC", zh="塑料"),
        dict(TAB_ROWS, x1=3, x2=51, en="TROOPERS", zh="部队", color="dark"),
        dict(TAB_ROWS, x1=58, x2=100, en="VEHICLES", zh="载具", color="dark"),
        dict(TAB_ROWS, x1=107, x2=140, en="ASSETS", zh="资产", color="white"),
    ],
}


# ---------------------------------------------------------------- 调色板
_PAL_RGB = None
_PAL_LUT = None


def palette():
    global _PAL_RGB, _PAL_LUT
    if _PAL_RGB is None:
        raw = open(PALETTE, "rb").read()
        cols = []
        for i in range(256):
            b, g, r, _ = raw[i * 4:i * 4 + 4]
            cols.append((r, g, b))
        _PAL_RGB = cols
        _PAL_LUT = {}
        for i, c in enumerate(cols):
            _PAL_LUT.setdefault(c, i)
    return _PAL_RGB, _PAL_LUT


def snap_to_palette(arr):
    pal, lut = palette()
    pal_a = np.array(pal, dtype=np.int32)
    flat = arr.reshape(-1, 3)
    uniq, inv = np.unique(flat, axis=0, return_inverse=True)
    res = np.empty_like(uniq)
    for i, c in enumerate(uniq):
        t = (int(c[0]), int(c[1]), int(c[2]))
        if t in lut:
            res[i] = c
            continue
        d = np.abs(pal_a - c.astype(np.int32)).sum(axis=1)
        res[i] = pal_a[int(d.argmin())]
    return res[inv].reshape(arr.shape)


# ---------------------------------------------------------------- 字形
def glyph(ch):
    if ch == " ":
        return (7, 1, [0], 0)
    try:
        gb = ch.encode("gbk")
    except UnicodeEncodeError:
        gb = None
    if gb and len(gb) == 2 and gb[0] >= 0x81:
        rows = FONT.bits(ch)
        if rows:
            return (FONT.width, FONT.height, rows, 0)
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


def render_scaled(text, target_h, tracking=1):
    """按目标高度渲染译文位图。

    ★ 为什么需要：Hzk16 是 13x13 定点阵，而 4 代标签页盒内字形带只有 9 行，
      原英文标签仅 8px 高。直接写 13px 会**溢出标签盒**（实测）。
      这里按比例缩到目标高度（LANCZOS + 阈值二值化），保留字形结构且塞得进盒内。
    """
    w, h, rows = layout(text, tracking)
    if target_h >= h:
        return w, h, rows
    im = Image.new("L", (w, h), 0)
    px = im.load()
    for yy, r in enumerate(rows):
        for xx in range(w):
            if (r >> (w - 1 - xx)) & 1:
                px[xx, yy] = 255
    nw = max(1, int(round(w * target_h / float(h))))
    im2 = im.resize((nw, target_h), Image.LANCZOS)
    px2 = im2.load()
    out = []
    for yy in range(target_h):
        v = 0
        for xx in range(nw):
            v = (v << 1) | (1 if px2[xx, yy] >= 110 else 0)
        out.append(v)
    return nw, target_h, out


def blit(arr, x, y, w, rows, color):
    H, W = arr.shape[:2]
    for yy, r in enumerate(rows):
        py = y + yy
        if py < 0 or py >= H:
            continue
        for xx in range(w):
            if (r >> (w - 1 - xx)) & 1:
                px = x + xx
                if 0 <= px < W:
                    arr[py, px] = color


# ---------------------------------------------------------------- 抹字
def inpaint_h(arr, y1, y2, x1, x2):
    """左右插值抹字：锚点取行盒左右各 3 列。"""
    H, W = arr.shape[:2]
    out = arr.astype(np.float32)
    la = max(0, x1 - 3)
    ra = min(W - 1, x2 + 3)
    span = ra - la
    if span <= 0:
        return arr
    for y in range(max(0, y1), min(H, y2 + 1)):
        lc = arr[y, la].astype(np.float32)
        rc = arr[y, ra].astype(np.float32)
        for x in range(max(0, x1), min(W, x2 + 1)):
            t = (x - la) / float(span)
            out[y, x] = lc * (1 - t) + rc * t
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def inpaint_v(arr, y1, y2, x1, x2, top, bot):
    """上下插值抹字（标签页专用）。

    锚点行由 top/bot 显式给出，**必须落在标签盒内部**：
    实测字形带是 y170..y178，盒内可用作背景锚点的只有 y168/y169（上）与 y179（下）。
    早期版本按 y1-2/y2+2 自动取锚点，取到了 y167 —— 那是标签盒的**顶边框**，
    边框色被插值进盒内，渲染出整条雾带（已修）。
    """
    H, W = arr.shape[:2]
    out = arr.astype(np.float32)
    top = [y for y in top if 0 <= y < H] or [y1]
    bot = [y for y in bot if 0 <= y < H] or [y2]
    for x in range(max(0, x1 - 1), min(W, x2 + 2)):
        tc = arr[top, x].astype(np.float32).mean(axis=0)
        bc = arr[bot, x].astype(np.float32).mean(axis=0)
        ta, ba = float(np.mean(top)), float(np.mean(bot))
        span = ba - ta
        for y in range(max(0, y1), min(H, y2 + 1)):
            t = (y - ta) / span if span > 0 else 0.5
            out[y, x] = tc * (1 - t) + bc * t
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- 主流程
def process_file(name, spec, out_dir, check_dir=None):
    src = os.path.join(SRC, name)
    arr = np.asarray(Image.open(src).convert("RGB")).copy()
    H, W = arr.shape[:2]

    applied = []
    for it in spec:
        y1, y2 = it["y1"], it["y2"]
        x1, x2 = it["x1"], it["x2"]
        mode = it.get("mode", "h")
        colkey = it.get("color", "white")
        gh = it.get("gh", FONT.height)

        if mode == "v":
            arr = inpaint_v(arr, y1, y2, x1, x2,
                            it.get("top", [y1 - 1]), it.get("bot", [y2 + 1]))
        else:
            arr = inpaint_h(arr, y1 - 2, y2 + 2, max(0, x1 - 2), min(W - 1, x2 + 2))

        w, h, rows = render_scaled(it["zh"], gh)
        cy = (y1 + y2 + 1) / 2.0
        ty = int(round(cy - h / 2.0))
        tx = int(round((x1 + x2 + 1) / 2.0 - w / 2.0))
        blit(arr, tx, ty, w, rows, COLORS[colkey])
        applied.append({"en": it["en"], "zh": it["zh"],
                        "box": [x1, y1, x2, y2], "drawn": [tx, ty, w, h],
                        "color": colkey, "glyph_h": gh})

    arr = snap_to_palette(arr)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, name)
    Image.fromarray(arr).save(out)

    if check_dir:
        os.makedirs(check_dir, exist_ok=True)
        Z = 4
        a = Image.open(src).convert("RGB")
        b = Image.open(out).convert("RGB")
        sa = a.resize((W * Z, H * Z), Image.NEAREST)
        sb = b.resize((W * Z, H * Z), Image.NEAREST)
        c = Image.new("RGB", (sa.width * 2 + 20, sa.height + 22), (18, 18, 22))
        d = ImageDraw.Draw(c)
        d.text((4, 4), "EN   " + name, fill=(255, 220, 120))
        d.text((sa.width + 24, 4), "CHS", fill=(120, 255, 160))
        c.paste(sa, (0, 20))
        c.paste(sb, (sa.width + 20, 20))
        c.save(os.path.join(check_dir, "cmp_" + name))
    return applied


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(SHARED, "png_control_chs"))
    ap.add_argument("--check", default=None)
    ap.add_argument("--only", default=None)
    args = ap.parse_args()

    bad = FONT.selftest()
    if bad:
        print("!! Hzk16 字形自检未通过，中止：")
        for ch, msg in bad:
            print("   %s: %s" % (ch, msg))
        return 2
    print("Hzk16 自检通过（%dx%d）" % (FONT.width, FONT.height))

    need = set()
    for spec in LINES.values():
        for it in spec:
            need |= set(it["zh"])
    miss = sorted(c for c in need if not FONT.has(c))
    print("用字 %d 个，缺字: %s" % (len(need), miss if miss else "无"))
    if miss:
        return 3

    report = []
    total = 0
    for name in sorted(LINES):
        if args.only and args.only not in name:
            continue
        ap_ = process_file(name, LINES[name], args.out, args.check)
        total += len(ap_)
        report.append({"file": name, "items": ap_})
        print("%-26s %d 处" % (name, len(ap_)))
    print("共 %d 个文件 / %d 处文字 -> %s" % (len(report), total, args.out))
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
