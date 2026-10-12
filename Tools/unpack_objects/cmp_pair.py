"""
导出同一 key 的两版原图（不叠加、不二值化），并排 + 上/下排版，
大图自动缩放。用于直接目视确认汉化/改动。

用法：
    python cmp_pair.py <a.dat> <b.dat> --key <k> --out <png> [--scale 1] [--layout h|v]
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from objects_dat import split_key                                # noqa: E402
from export_sprites import load_objects, parse_palette, decode  # noqa: E402

CATNAME = {
    17: "Building", 18: "PillBox", 44: "GunTurret",
    45: "AAGun", 46: "Base", 47: "Auxbase",
}


def font(sz=16):
    for p in (r"C:\Windows\Fonts\consola.ttf", r"C:\Windows\Fonts\msyh.ttc"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz)
            except Exception:
                pass
    return ImageFont.load_default()


def flatten(im):
    bg = Image.new("RGBA", im.size, (235, 235, 235, 255))
    bg.alpha_composite(im)
    return bg.convert("RGB")


def main():
    a = sys.argv[1:]
    pa, pb = a[0], a[1]
    k = int(a[a.index("--key") + 1])
    out = a[a.index("--out") + 1]
    scale = float(a[a.index("--scale") + 1]) if "--scale" in a else 1.0
    layout = a[a.index("--layout") + 1] if "--layout" in a else "h"

    pal_a, obj_a = load_objects(pa)
    pal_b, obj_b = load_objects(pb)
    pal_a, pal_b = parse_palette(pal_a), parse_palette(pal_b)
    ia, _ = decode(obj_a[k], pal_a)
    ib, _ = decode(obj_b[k], pal_b)
    cat, num, dmg = split_key(k)

    A = flatten(ia) if ia else Image.new("RGB", (64, 64), (60, 60, 60))
    B = flatten(ib) if ib else Image.new("RGB", (64, 64), (60, 60, 60))
    if scale != 1.0:
        A = A.resize((int(A.width * scale), int(A.height * scale)), Image.NEAREST)
        B = B.resize((int(B.width * scale), int(B.height * scale)), Image.NEAREST)

    f = font(18)
    lbl_h, pad, lbl_w = 26, 8, 96
    if layout == "v":
        W = max(A.width, B.width) + lbl_w + pad * 2
        H = A.height + B.height + lbl_h * 2 + pad * 3
    else:
        W = A.width + B.width + lbl_w + pad * 3
        H = max(A.height, B.height) + lbl_h + pad * 2

    o = Image.new("RGB", (W, H), (30, 30, 36))
    d = ImageDraw.Draw(o)
    title = (f"key {k}   cat {cat} ({CATNAME.get(cat,'?')})   "
             f"num {num}   dmg {dmg}")
    if layout == "v":
        o.paste(A, (lbl_w + pad, lbl_h))
        o.paste(B, (lbl_w + pad, lbl_h * 2 + A.height + pad))
        d.text((10, lbl_h // 2), "1998 CN", fill=(120, 220, 255), font=f)
        d.text((10, lbl_h * 2 + A.height + pad + lbl_h // 2), "2018 Steam",
               fill=(255, 210, 120), font=f)
    else:
        o.paste(A, (lbl_w + pad, lbl_h))
        o.paste(B, (lbl_w * 2 + A.width + pad, lbl_h))
        d.text((8, lbl_h // 2), "1998 CN", fill=(120, 220, 255), font=f)
        d.text((lbl_w + A.width + pad, lbl_h // 2), "2018 Steam",
               fill=(255, 210, 120), font=f)
    d.text((10, 2), title, fill=(200, 200, 210), font=font(14))
    o.save(out)
    print(f"{out}  {o.width}x{o.height}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
