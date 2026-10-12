"""
导出 Alpine objects.dat 的差异精灵（1998 中文盘 vs 2018 Steam），
并按 category 生成拼接总览图，便于目视确认哪些是汉化内容。

用法：
    python export_alpine_diff.py <a.dat> <b.dat> --keys <csv> --out <dir>
"""

import csv
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from objects_dat import split_key                                # noqa: E402
from export_sprites import load_objects, parse_palette, decode, side_by_side  # noqa: E402

CATNAME = {
    17: "Building", 18: "PillBox", 44: "GunTurret",
    45: "AAGun", 46: "Base", 47: "Auxbase",
}


def font():
    for p in (r"C:\Windows\Fonts\consola.ttf", r"C:\Windows\Fonts\arial.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, 15)
            except Exception:
                pass
    return ImageFont.load_default()


def contact_sheet(items, title, dst, scale=1.0, label_w=230, pad=6, bg=(28, 28, 32)):
    """items: [(label, PIL.Image), ...] 横向拼接成一张总览。"""
    if not items:
        return
    f = font()
    cell_w = max(im.width for _, im in items)
    cell_h = max(im.height for _, im in items) + 22
    head = 34
    W = label_w + len(items) * (cell_w + pad) + pad
    H = head + cell_h + pad
    out = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(out)
    d.text((10, 8), title, fill=(255, 235, 120), font=f)

    x = label_w
    for lbl, im in items:
        y = head + (cell_h - 22 - im.height) // 2
        out.paste(im, (x, y))
        d.text((x, head + cell_h - 20), lbl, fill=(160, 220, 255), font=f)
        d.rectangle([x - 1, head - 1, x + im.width, head + cell_h - 22], outline=(70, 70, 80))
        x += cell_w + pad
    out.save(dst)
    return out


def main():
    a = sys.argv[1:]
    pa, pb = a[0], a[1]
    keys_csv = a[a.index("--keys") + 1]
    outdir = a[a.index("--out") + 1]
    os.makedirs(outdir, exist_ok=True)
    pairdir = os.path.join(outdir, "pairs")
    os.makedirs(pairdir, exist_ok=True)

    pal_a, obj_a = load_objects(pa)
    pal_b, obj_b = load_objects(pb)
    pal_a, pal_b = parse_palette(pal_a), parse_palette(pal_b)

    with open(keys_csv, newline="", encoding="utf-8") as f:
        keys = [int(r["key"]) for r in csv.DictReader(f) if r.get("status") == "diff"]

    groups = {}
    for k in sorted(keys):
        ia, _ = decode(obj_a[k], pal_a)
        ib, _ = decode(obj_b[k], pal_b)
        if ia is None and ib is None:
            print(f"  !! decode failed k={k}")
            continue
        pair = side_by_side(ia, ib)
        cat, num, dmg = split_key(k)
        name = f"k{k}_c{cat}_n{num}_d{dmg}.png"
        pair.save(os.path.join(pairdir, name))
        groups.setdefault(cat, []).append((f"n{num} d{dmg}", pair))

    for cat, items in sorted(groups.items()):
        dst = os.path.join(outdir, f"cat{cat:02d}_{CATNAME.get(cat, '?')}.png")
        sc = 0.5 if any(im.width > 400 for _, im in items) else 1.0
        if sc != 1.0:
            items = [(l, im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))),
                                   Image.LANCZOS)) for l, im in items]
        sheet = contact_sheet(
            items, f"cat {cat}  {CATNAME.get(cat,'?')}   "
                   f"[left = 1998 CN   |   right = 2018 Steam]",
            dst)
        print(f"  cat{cat:02d} {CATNAME.get(cat,'?'):<10} {len(items):>2} 张 -> {os.path.basename(dst)}"
              f"  ({sheet.width}x{sheet.height})")

    print(f"\n逐张对照图: {pairdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
