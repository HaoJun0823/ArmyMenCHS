"""
把 objects.dat 的精灵解码导出为 PNG，供人工检查。

支持两种模式：
  --diff   只导出"与对照版不同"的精灵（默认）
  --all    导出全部
  --cats   指定分类（默认 44 45 46 47）

若给 --compare，则把两版同一 key 拼成左右对照图（左=原版 右=CHS），
便于逐个目视检查是否为汉化内容。

输出目录结构：
    Archives/objects/<Terrain>/
    ├─ diff/         差异 key 的对照图  k<key>_c<cat>_n<num>_d<dmg>.png
    └─ all/          全量（可选）

用法：
    python export_sprites.py --root G:\\Projects\\ArmyMenCHS --out Archives
                             [--cats 44 45 46 47] [--diff|--all]
"""

import os
import sys
import struct
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from objects_dat import parse_header, parse_table, split_key

# sprite_flags 位（src/Dd.h:302-310）
SP_DRLE = 0x04
SP_WRLE = 0x08
SP_TRLE = 0x10
SP_SRLE = 0x20
SP_RLE = 0x02


def load_objects(path):
    with open(path, "rb") as f:
        buf = f.read()
    _, palette, nobj = parse_header(buf)
    entries = parse_table(buf, nobj)
    order = sorted(range(nobj), key=lambda i: entries[i][1])
    data = {}
    for pos, i in enumerate(order):
        s = entries[i][1]
        e = entries[order[pos + 1]][1] if pos + 1 < len(order) else len(buf)
        data[entries[i][0]] = buf[s:e]
    return palette, data


def parse_palette(pal):
    return [(pal[i * 4 + 2], pal[i * 4 + 1], pal[i * 4])
            for i in range(256)]     # RGBQUAD 存 BGR


def kind_of(flags):
    if flags & SP_DRLE:
        return "DRLE"
    if flags & SP_WRLE:
        return "WRLE"
    if flags & SP_TRLE:
        return "TRLE"
    if flags & SP_SRLE:
        return "SRLE"
    if flags & SP_RLE:
        return "RLE"
    return "BMP"


def decode(blob, pal):
    """返回 (img, hdr) 或 (None, None)。"""
    if len(blob) < 28:
        return None, None
    key, w, h, flags = struct.unpack_from("<iiii", blob, 0)
    if w <= 0 or h <= 0 or w > 4096 or h > 4096:
        return None, None
    gsize = struct.unpack_from("<i", blob, 24)[0]
    if gsize <= 0 or gsize > len(blob):
        return None, None
    g = blob[28:28 + gsize]
    kind = kind_of(flags)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    try:
        if kind == "BMP":
            for y in range(h):
                for x in range(w):
                    i = y * w + x
                    if i < len(g):
                        px[x, y] = pal[g[i]] + (255,)
        else:
            if len(g) < 4:
                return None, None
            iw, ih = struct.unpack_from("<HH", g, 0)
            if iw == 0 or ih == 0 or iw > 4096 or ih > 4096:
                return None, None
            use_d = (kind == "DRLE")
            osz = 4 if use_d else 2
            if len(g) < 4 + osz * ih:
                return None, None
            offs = []
            for i in range(ih):
                p = 4 + i * osz
                offs.append(struct.unpack_from("<I", g, p)[0] if use_d
                            else struct.unpack_from("<H", g, p)[0])
            for y in range(ih):
                ro = offs[y]
                if ro <= 0 or ro >= len(g):
                    continue
                sp = ro
                x = 0
                guard = 0
                while x < iw and guard < 65536:
                    guard += 1
                    if sp + 2 > len(g):
                        break
                    skip = g[sp]
                    cnt = g[sp + 1]
                    sp += 2
                    x += skip
                    for _ in range(cnt):
                        if sp >= len(g) or x >= iw:
                            break
                        if 0 <= y < h and 0 <= x < w:
                            px[x, y] = pal[g[sp]] + (255,)
                        sp += 1
                        x += 1
    except Exception:
        return None, None
    return img, {"w": w, "h": h, "kind": kind}


def side_by_side(a, b):
    """左右拼接，中间留 8px 分隔。"""
    if a is None:
        a = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    if b is None:
        b = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    pad = 8
    W = a.width + b.width + pad
    H = max(a.height, b.height)
    out = Image.new("RGBA", (W, H), (40, 40, 40, 255))
    out.alpha_composite(a, (0, 0))
    out.alpha_composite(b, (a.width + pad, 0))
    return out


def main():
    args = sys.argv[1:]
    # root 由 __file__ 上溯两层推导（Tools/unpack_objects -> 仓库根）
    root = (args[args.index("--root") + 1] if "--root" in args else
            os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))))
    outdir = args[args.index("--out") + 1] if "--out" in args else "Archives"
    cats = {44, 45, 46, 47}
    if "--cats" in args:
        i = args.index("--cats") + 1
        cats = set()
        while i < len(args) and not args[i].startswith("--"):
            cats.add(int(args[i]))
            i += 1
    mode = "all" if "--all" in args else "diff"

    base_root = os.path.join(root, "Army1_Original", "terrain")
    chs_root = os.path.join(root, "Army1_CHS", "terrain")
    dst = os.path.join(root, outdir, "objects")
    os.makedirs(dst, exist_ok=True)

    total = 0
    for t in ("Alpine", "Bayou", "Desert"):
        pal_b, objs_b = load_objects(os.path.join(base_root, t, "objects.dat"))
        pal_c, objs_c = load_objects(os.path.join(chs_root, t, "objects.dat"))
        pal_b, pal_c = parse_palette(pal_b), parse_palette(pal_c)

        keys = sorted(set(objs_b) & set(objs_c))
        keys = [k for k in keys if split_key(k)[0] in cats]

        if mode == "diff":
            keys = [k for k in keys if objs_b[k] != objs_c[k]]

        d = os.path.join(dst, t, mode)
        os.makedirs(d, exist_ok=True)
        n = 0
        for k in keys:
            cat, num, dmg = split_key(k)
            ia, ha = decode(objs_b[k], pal_b)
            ib, hb = decode(objs_c[k], pal_c)
            if ia is None and ib is None:
                continue
            out = side_by_side(ia, ib)
            name = f"k{k}_c{cat}_n{num}_d{dmg}.png"
            out.save(os.path.join(d, name))
            n += 1
        total += n
        print(f"  {t:<8} {mode:<5} {n} 张 -> {d}")

    print()
    print(f"合计 {total} 张（左=Steam原版 右=中文版，中间 8px 分隔）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
