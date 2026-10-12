"""
把 objects.dat 里的碰撞掩膜（maskSize 段的位图）解码成 PNG。
每字节 8 位，MSB = 最左像素；1 = 该像素阻挡（不可通行）。
掩膜宽 = (sprite_width + 7) // 8。

用法：
    python export_mask.py <dat> --key <k> --out <png> [--scale 6]
"""

import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from objects_dat import parse_header, parse_table, split_key   # noqa: E402


def load_blocks(path):
    with open(path, "rb") as f:
        buf = f.read()
    _, _, nobj = parse_header(buf)
    entries = parse_table(buf, nobj)
    order = sorted(range(nobj), key=lambda i: entries[i][1])
    out = {}
    for pos, i in enumerate(order):
        s = entries[i][1]
        e = entries[order[pos + 1]][1] if pos + 1 < len(order) else len(buf)
        out[entries[i][0]] = buf[s:e]
    return out


def mask_of(blob):
    import struct
    w, h = struct.unpack_from("<ii", blob, 4)
    p = 24
    gsize = struct.unpack_from("<i", blob, p)[0]; p += 4 + gsize
    ssize = struct.unpack_from("<i", blob, p)[0]; p += 4 + ssize
    msize = struct.unpack_from("<i", blob, p)[0]; p += 4
    return w, h, blob[p:p + msize], msize


def main():
    a = sys.argv[1:]
    path = a[0]
    k = int(a[a.index("--key") + 1])
    out = a[a.index("--out") + 1]
    scale = int(a[a.index("--scale") + 1]) if "--scale" in a else 6

    blocks = load_blocks(path)
    w, h, m, msize = mask_of(blocks[k])
    cat, num, dmg = split_key(k)
    print(f"key {k}  c{cat} n{num} d{dmg}  sprite {w}x{h}  maskSize={msize}")

    if msize == 0:
        print("  ★ 无掩膜 —— 精灵不参与基于掩膜的碰撞判定")
        Image.new("RGB", (64, 64), (45, 45, 52)).resize(
            (64 * scale, 64 * scale), Image.NEAREST).save(out)
        print(out)
        return 0

    mw = (w + 7) // 8
    img = Image.new("RGB", (mw * 8, h), (30, 30, 36))
    px = img.load()
    total = mw * 8 * h
    ones = 0
    for y in range(h):
        row = y * mw
        if row >= msize:
            break
        for byte_i in range(min(mw, msize - row)):
            b = m[row + byte_i]
            for bit in range(8):
                x = byte_i * 8 + bit
                if x >= mw * 8:
                    break
                if b & (0x80 >> bit):
                    px[x, y] = (255, 40, 200)
                    ones += 1
                else:
                    px[x, y] = (55, 55, 62)
    img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    img.save(out)
    print(f"  掩膜 {mw}x{h} 字节, 置位像素 {ones}/{total}")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
