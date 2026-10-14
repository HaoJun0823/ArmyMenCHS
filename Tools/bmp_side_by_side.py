# -*- coding: utf-8 -*-
"""整图并排对比（英文基线 vs 中文母盘），供人眼判定烧字是否已汉化。

比 bmp_diff_region.py 更适合"找文字"：
  差异包围盒只框住"有差异的像素"，若差异是噪点，框内看不到文字。
  整图并排则一眼能看到标题文字到底写的是什么。
"""
import os
import sys

ROOT = r"G:\Projects\ArmyMenCHS"
NEW = os.path.join(ROOT, "Army2_NEW_CHS")
ORIG = os.path.join(ROOT, "Army2_Original")
OUT = os.path.join(ROOT, "_bmp_cmp")

from PIL import Image, ImageDraw


def main():
    os.makedirs(OUT, exist_ok=True)
    targets = sys.argv[1:]
    if not targets:
        print("用法: python bmp_side_by_side.py <相对路径> [...]")
        return 1
    for rel in targets:
        new_p = os.path.join(NEW, rel.replace("/", os.sep))
        orig_p = os.path.join(ORIG, rel.replace("/", os.sep))
        if not (os.path.isfile(new_p) and os.path.isfile(orig_p)):
            print("跳过（缺文件）: %s" % rel)
            continue
        a = Image.open(orig_p).convert("RGB")
        b = Image.open(new_p).convert("RGB")
        if a.size != b.size:
            print("尺寸不同: %s  %s vs %s" % (rel, a.size, b.size))
            continue
        canvas = Image.new("RGB", (a.width, a.height * 2 + 10), (255, 0, 0))
        canvas.paste(a, (0, 0))
        canvas.paste(b, (0, a.height + 10))
        name = os.path.splitext(os.path.basename(rel))[0]
        p = os.path.join(OUT, "%s_full.png" % name)
        canvas.save(p)
        print("%-46s -> %s  (上=英文 下=中文)" % (rel, os.path.basename(p)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
