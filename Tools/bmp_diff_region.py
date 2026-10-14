# -*- coding: utf-8 -*-
"""定位两个 BMP 的差异区域，裁出对比图（供人眼判定"是否已汉化"）。

为什么需要：
  像素差异率低（0.1%~0.3%）不能直接判定"未汉化"——
  也可能只是"标题两个英文字换成了两个汉字"（改动面积本来就小）。
  反过来差异率 30% 也不一定是汉化（可能是地图重绘）。
  唯一可靠办法：把差异区域裁出来给人看。

输出：out/<name>_cmp.png  —— 左：英文基线，右：中文母盘，红线框出差异区
"""
import os
import struct
import sys

ROOT = r"G:\Projects\ArmyMenCHS"
NEW = os.path.join(ROOT, "Army2_NEW_CHS")
ORIG = os.path.join(ROOT, "Army2_Original")
OUT = os.path.join(ROOT, "_bmp_cmp")

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("需要 Pillow: python -m pip install Pillow")
    sys.exit(1)


def load(path):
    with open(path, "rb") as f:
        d = f.read()
    if d[:2] != b"BM":
        return None
    off = struct.unpack_from("<I", d, 10)[0]
    w, h = struct.unpack_from("<ii", d, 18)
    bpp = struct.unpack_from("<H", d, 28)[0]
    ncol = struct.unpack_from("<I", d, 46)[0] or (1 << bpp if bpp <= 8 else 0)
    pal = d[54:54 + ncol * 4] if bpp <= 8 else b""
    return {"w": w, "h": abs(h), "bpp": bpp, "topdown": h < 0,
            "pal": pal, "data": d[off:], "off": off, "raw": d}


def diff_bbox(a, b):
    """返回差异像素的包围盒 (x0,y0,x1,y1) 与差异数"""
    A, B = load(a), load(b)
    if not A or not B or (A["w"], A["h"]) != (B["w"], B["h"]):
        return None, 0
    w, h, bpp = A["w"], A["h"], A["bpp"]
    if bpp != B["bpp"]:
        return None, 0
    stride = ((w * bpp + 31) // 32) * 4
    da, db = A["data"], B["data"]
    if len(da) < stride * h or len(db) < stride * h:
        return None, 0
    # 调色板不同时，先按"调色板索引"比较（等价于比较像素形状）
    x0, y0, x1, y1, n = w, h, -1, -1, 0
    for y in range(h):
        ra = da[y * stride:(y + 1) * stride]
        rb = db[y * stride:(y + 1) * stride]
        if ra == rb:
            continue
        for x in range(w):
            ia = ra[x * bpp // 8] if bpp == 8 else ra[x * bpp // 8]
            ib = rb[x * bpp // 8] if bpp == 8 else rb[x * bpp // 8]
            if ia != ib:
                n += 1
                if x < x0: x0 = x
                if x > x1: x1 = x
                if y < y0: y0 = y
                if y > y1: y1 = y
    if n == 0:
        return None, 0
    return (x0, y0, x1, y1), n


def to_image(path):
    """BMP -> PIL Image（用 Pillow 读，处理调色板）"""
    im = Image.open(path)
    return im.convert("RGB")


def main():
    os.makedirs(OUT, exist_ok=True)
    targets = sys.argv[1:] or [
        "bitmaps/load_airborne.bmp",
        "bitmaps/load_homeland.bmp",
        "bitmaps/load_default.bmp",
    ]
    for rel in targets:
        new_p = os.path.join(NEW, rel.replace("/", os.sep))
        orig_p = os.path.join(ORIG, rel.replace("/", os.sep))
        if not (os.path.isfile(new_p) and os.path.isfile(orig_p)):
            print("跳过（缺文件）: %s" % rel)
            continue
        bbox, n = diff_bbox(new_p, orig_p)
        name = os.path.splitext(os.path.basename(rel))[0]
        print("%-44s 差异像素=%6d  包围盒=%s" % (rel, n, bbox))
        if not bbox:
            continue
        x0, y0, x1, y1 = bbox
        # 稍微外扩，便于看上下文
        pad = 12
        x0 = max(0, x0 - pad); y0 = max(0, y0 - pad)
        x1 = min(639, x1 + pad); y1 = min(479, y1 + pad)

        ia = to_image(orig_p).crop((x0, y0, x1 + 1, y1 + 1))
        ib = to_image(new_p).crop((x0, y0, x1 + 1, y1 + 1))
        # 放大 3 倍便于观察
        sc = 3
        ia = ia.resize((ia.width * sc, ia.height * sc), Image.NEAREST)
        ib = ib.resize((ib.width * sc, ib.height * sc), Image.NEAREST)
        canvas = Image.new("RGB", (ia.width, ia.height * 2 + 8), (255, 0, 0))
        canvas.paste(ia, (0, 0))
        canvas.paste(ib, (0, ia.height + 8))
        p = os.path.join(OUT, "%s_cmp.png" % name)
        canvas.save(p)
        print("   -> %s   (区域 %dx%d, 上=英文 下=中文母盘)"
              % (p, x1 - x0 + 1, y1 - y0 + 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
