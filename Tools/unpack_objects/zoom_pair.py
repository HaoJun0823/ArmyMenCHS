"""
把单张 pair 图按整数倍放大（最近邻，保持像素边缘），用于细看贴图里的汉字。

用法：
    python zoom_pair.py <in.png> <out.png> [--scale 4] [--crop x0,y0,x1,y1]
"""

import os
import sys

from PIL import Image


def main():
    a = sys.argv[1:]
    src, dst = a[0], a[1]
    scale = int(a[a.index("--scale") + 1]) if "--scale" in a else 4
    im = Image.open(src).convert("RGBA")

    if "--crop" in a:
        box = tuple(int(x) for x in a[a.index("--crop") + 1].split(","))
        im = im.crop(box)

    # 透明区域填成棋盘，方便看清轮廓
    bg = Image.new("RGBA", im.size, (60, 60, 66, 255))
    bg.alpha_composite(im)
    im = bg.convert("RGB")

    im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    im.save(dst)
    print(f"{os.path.basename(src)}  {im.width}x{im.height} -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
