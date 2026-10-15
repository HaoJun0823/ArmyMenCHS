"""
BMP <-> PNG 可逆转换工具（针对 Army3 8-bit 调色板 BMP）

用途：
  to-png  把 bitmaps/ 下所有 8-bit BMP 转成 24-bit RGB PNG，输出到 bitmaps_png/，供手动改图。
  to-bmp  把 bitmaps_png/ 下改好的 PNG 转回 8-bit BMP，输出到 bitmaps_cn/，保留原调色板。

设计要点（为什么要这么做）：
  - 反向转换时，原图调色板被完整保留（背景灰阶、青色色键 0,255,255 都不变）。
  - 只确保调色板里存在黑色(0,0,0)与白色(255,255,255)两个索引（若缺失，则占用一个
    原图未使用的槽位；若全被占用则占用最少使用的槽位），其余颜色一律不动。
  - 每个像素按"最近调色板色"映射：原背景灰阶像素因无损读取会精确命中原索引，
    手画的纯黑/纯白命中黑/白索引，编辑器产生的抗锯齿灰边会落到最近的背景灰阶上。

注意：本工具不覆盖原始 bitmaps/ 下的任何文件。
"""
import os
import sys
import numpy as np
from PIL import Image

BASE = r"G:\Projects\ArmyMenCHS\Army3_NEW_CHS"
SRC_BMP = os.path.join(BASE, "bitmaps")
SRC_PNG = os.path.join(BASE, "bitmaps_png")
DST_PNG = SRC_PNG
DST_BMP = os.path.join(BASE, "bitmaps_cn")


def bmp_to_png():
    os.makedirs(DST_PNG, exist_ok=True)
    count = 0
    for f in sorted(os.listdir(SRC_BMP)):
        if not f.lower().endswith(".bmp"):
            continue
        im = Image.open(os.path.join(SRC_BMP, f)).convert("RGB")
        out = os.path.join(DST_PNG, os.path.splitext(f)[0] + ".png")
        im.save(out)
        count += 1
        print("wrote", out)
    print(f"done: {count} bmp -> png")


def ensure_color(pal_arr, hist, color):
    """确保 color 在调色板中，返回其索引。"""
    color = tuple(int(c) for c in color)
    for i in range(256):
        if tuple(int(x) for x in pal_arr[i]) == color:
            return i
    # 用一个原图未使用的槽位
    for i in range(256):
        if hist[i] == 0:
            pal_arr[i] = color
            hist[i] = 1
            return i
    # 否则占用最少使用的槽位
    i = int(np.argmin(hist))
    pal_arr[i] = color
    return i


def png_to_bmp():
    os.makedirs(DST_BMP, exist_ok=True)
    count = 0
    for f in sorted(os.listdir(SRC_PNG)):
        if not f.lower().endswith(".png"):
            continue
        base = os.path.splitext(f)[0]
        bmp_path = os.path.join(SRC_BMP, base + ".bmp")
        if not os.path.exists(bmp_path):
            print(f"skip {f}: 找不到对应原图 {bmp_path}")
            continue
        orig = Image.open(bmp_path)  # mode 'P'
        pal = orig.getpalette()[:768]
        pal_arr = np.array(pal, dtype=np.uint8).reshape(256, 3)
        orig_idx = np.array(orig)
        hist = np.bincount(orig_idx.ravel(), minlength=256).astype(np.int64)

        exact = {tuple(int(x) for x in pal_arr[i]): i for i in range(256)}
        black_i = ensure_color(pal_arr, hist, (0, 0, 0))
        white_i = ensure_color(pal_arr, hist, (255, 255, 255))

        edited = np.array(Image.open(os.path.join(SRC_PNG, f)).convert("RGB"), dtype=np.uint8)
        h, w, _ = edited.shape
        flat = edited.reshape(-1, 3)
        uniques, inv = np.unique(flat, axis=0, return_inverse=True)
        mapped = np.empty(len(uniques), dtype=np.int64)
        pal_int = pal_arr.astype(np.int64)
        for k, u in enumerate(uniques):
            t = (int(u[0]), int(u[1]), int(u[2]))
            if t in exact:
                mapped[k] = exact[t]
            elif t == (0, 0, 0):
                mapped[k] = black_i
            elif t == (255, 255, 255):
                mapped[k] = white_i
            else:
                d = np.sum((pal_int - u.astype(np.int64)) ** 2, axis=1)
                mapped[k] = int(np.argmin(d))
        out_idx = mapped[inv].reshape(h, w).astype(np.uint8)
        out_im = Image.fromarray(out_idx, mode="P")
        out_im.putpalette(pal_arr.astype(np.uint8).flatten().tolist()[:768])
        out_path = os.path.join(DST_BMP, base + ".bmp")
        out_im.save(out_path)
        count += 1
        print(f"wrote {out_path}  (black_idx={black_i}, white_idx={white_i})")
    print(f"done: {count} png -> bmp")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("to-png", "to-bmp"):
        print("用法: python bmp_png_tool.py to-png|to-bmp")
        sys.exit(1)
    if sys.argv[1] == "to-png":
        bmp_to_png()
    else:
        png_to_bmp()


if __name__ == "__main__":
    main()
