"""
直接从两个 objects.dat 解码同一 key 的精灵，生成像素级差异高亮图。
洋红 = 只有 1998(左) 有；青色 = 只有 2018(右) 有；白 = 两版都有；深灰 = 两版都没有。
用于一眼看清"汉化文字画在哪、以及改了哪些像素"。

用法：
    python diff_highlight_dat.py <a.dat> <b.dat> --key <k> --out <png> [--scale 6]
    python diff_highlight_dat.py <a.dat> <b.dat> --keys <csv> --outdir <dir> [--scale 6]
"""

import csv
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from objects_dat import split_key                                  # noqa: E402
from export_sprites import load_objects, parse_palette, decode      # noqa: E402


def build(ia, ib, scale, pad=6):
    """ia/ib: RGBA 或 None。返回高亮图。"""
    W = max(ia.width if ia else 0, ib.width if ib else 0) or 1
    H = max(ia.height if ia else 0, ib.height if ib else 0) or 1
    if ia is None:
        ia = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if ib is None:
        ib = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    out = Image.new("RGB", (W * 2 + pad * 3, H + pad * 2), (24, 24, 28))
    n_new = n_only = n_common = 0
    px = out.load()
    pa, pb = ia.load(), ib.load()

    for y in range(H):
        for x in range(W):
            a = pa[x, y][:3] if (x < ia.width and y < ia.height) else (0, 0, 0)
            b = pb[x, y][:3] if (x < ib.width and y < ib.height) else (0, 0, 0)
            a_on = a != (0, 0, 0)
            b_on = b != (0, 0, 0)
            if a_on and not b_on:
                c = (255, 0, 210)          # 1998 独有（疑似汉化文字）
                n_only += 1
            elif b_on and not a_on:
                c = (0, 220, 255)          # 2018 独有
                n_new += 1
            elif a_on and b_on:
                c = (225, 225, 225)        # 两版都有
                n_common += 1
            else:
                c = (40, 40, 46)
            ox = pad
            px[ox + x, pad + y] = c
            ox = W + pad * 2
            px[ox + x, pad + y] = c

    out = out.resize((out.width * scale, out.height * scale), Image.NEAREST)
    return out, (n_only, n_new, n_common, W * H)


def main():
    a = sys.argv[1:]
    pa, pb = a[0], a[1]
    scale = int(a[a.index("--scale") + 1]) if "--scale" in a else 6

    pal_a, obj_a = load_objects(pa)
    pal_b, obj_b = load_objects(pb)
    pal_a, pal_b = parse_palette(pal_a), parse_palette(pal_b)

    if "--keys" in a:
        cs = a[a.index("--keys") + 1]
        outdir = a[a.index("--outdir") + 1]
        os.makedirs(outdir, exist_ok=True)
        with open(cs, newline="", encoding="utf-8") as f:
            keys = [int(r["key"]) for r in csv.DictReader(f) if r.get("status") == "diff"]
        for k in sorted(keys):
            ia, _ = decode(obj_a[k], pal_a)
            ib, _ = decode(obj_b[k], pal_b)
            if ia is None and ib is None:
                continue
            cat, num, dmg = split_key(k)
            out, st = build(ia, ib, scale)
            dst = os.path.join(outdir, f"hl_k{k}_c{cat}_n{num}_d{dmg}.png")
            out.save(dst)
            print(f"  c{cat:<2} n{num:<4} d{dmg}  1998独有={st[0]:<5} 2018独有={st[1]:<5} "
                  f"共有={st[2]:<6} 共{st[3]}  -> {os.path.basename(dst)}")
    else:
        k = int(a[a.index("--key") + 1])
        out = a[a.index("--out") + 1]
        ia, _ = decode(obj_a[k], pal_a)
        ib, _ = decode(obj_b[k], pal_b)
        img, st = build(ia, ib, scale)
        img.save(out)
        cat, num, dmg = split_key(k)
        print(f"key {k} (c{cat} n{num} d{dmg}): 1998独有={st[0]} 2018独有={st[1]} "
              f"共有={st[2]} / {st[3]}")
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
