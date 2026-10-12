"""
把 objects.dat 中的精灵解码为 PNG。

对象数据块布局（依据 src/fileio.cpp 的 LoadODFSprite，行 1346-1439）：

    int   key
    int   width
    int   height
    int   sprite_flags      决定 RLE 类型
    SPOINT hotspot          (int x, int y)  注意：源码是 fread SPOINT，编译期可能带对齐
    SPOINT linkspot         (int x, int y)
    int   graphicSize       若 > 0，紧跟 graphicSize 字节的主图
    int   shadowSize        若 > 0，紧跟 shadowSize 字节阴影
    int   maskSize          若 > 0，紧跟 maskSize 字节遮罩
    RECT  maskRect          (left, top, right, bottom)

RLE 数据（LoadRLE256Stream，fileio.cpp:702）：
    前 4 字节是 WIDTH, HEIGHT（精灵内部尺寸，通常等于 srect 宽高）
    然后 height 个行偏移（DRLE 用 DWORD，其他用 WORD）
    每行数据: [skip:1][count:1][count 字节] 重复至累计 >= width

SPRITE 标志位（SP_*）需从 Sprite.h 确认。若为 0 则是未压缩 BMP。

用法：
    python sprite_decode.py <objects.dat> <out_dir> [--keys ...] [--limit N]
                            [--diff-only <other.dat>]
"""

import sys
import os
import struct
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from objects_dat import parse_header, parse_table, split_key

# sprite_flags 位（核实自 src/Dd.h:302-310 与 Sprite.h:166-170）
#   BM_TRANSPARENT 0x00 / BM_RLE 0x02 / BM_DRLE 0x04 / BM_WRLE 0x08
#   BM_TRLE 0x10 / BM_SRLE 0x20
SP_RLE = 0x02
SP_DRLE = 0x04
SP_WRLE = 0x08
SP_TRLE = 0x10
SP_SRLE = 0x20


def load_objects(path):
    with open(path, "rb") as f:
        buf = f.read()
    _, palette, nobj = parse_header(buf)
    entries = parse_table(buf, nobj)
    order = sorted(range(nobj), key=lambda i: entries[i][1])
    bounds = {}
    for pos, i in enumerate(order):
        s = entries[i][1]
        e = entries[order[pos + 1]][1] if pos + 1 < len(order) else len(buf)
        bounds[i] = (s, e)
    data = {entries[i][0]: buf[bounds[i][0]:bounds[i][1]] for i in range(nobj)}
    return palette, data


def parse_palette(pal):
    out = []
    for i in range(256):
        b, g, r, _ = pal[i * 4:i * 4 + 4]
        out.append((r, g, b))
    return out


def parse_obj_header(blob):
    """解析对象头部，返回 dict 或 None。"""
    if len(blob) < 40:
        return None
    # 实测布局（key=9830945 @ offset 9972961）：
    #   [+0] int key  [+4] int width  [+8] int height  [+12] int sprite_flags
    #   [+16] SPOINT hotspot (2 x SHORT)  [+20] SPOINT linkspot (2 x SHORT)
    #   [+24] int graphicSize  [+28] 主图数据
    key, w, h, flags = struct.unpack_from("<iiii", blob, 0)
    if w <= 0 or h <= 0 or w > 4096 or h > 4096:
        return None
    hs_x, hs_y = struct.unpack_from("<hh", blob, 16)
    ls_x, ls_y = struct.unpack_from("<hh", blob, 20)
    gsize = struct.unpack_from("<i", blob, 24)[0]
    p = 28
    if gsize < 0 or gsize > len(blob):
        return None
    return {"key": key, "w": w, "h": h, "flags": flags,
            "hotspot": (hs_x, hs_y), "linkspot": (ls_x, ls_y),
            "graphicSize": gsize, "graphicOff": p}


def rle_type_from_flags(flags):
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


def decode_rle256(data, palette_rgb, kind):
    """data 是 RLE 流（不含对象头）。返回 PIL Image。"""
    if len(data) < 4:
        return None
    w, h = struct.unpack_from("<HH", data, 0)
    if w == 0 or h == 0 or w > 4096 or h > 4096:
        return None

    drle = (kind == "DRLE")
    off_size = 4 if drle else 2
    tbl = 4
    if len(data) < tbl + off_size * h:
        return None

    offs = []
    for i in range(h):
        p = tbl + i * off_size
        if drle:
            offs.append(struct.unpack_from("<I", data, p)[0])
        else:
            offs.append(struct.unpack_from("<H", data, p)[0])

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    for y in range(h):
        ro = offs[y]
        if ro <= 0 or ro >= len(data):
            continue
        sp = ro
        x = 0
        guard = 0
        while x < w and guard < 65536:
            guard += 1
            if sp + 2 > len(data):
                break
            skip = data[sp]
            cnt = data[sp + 1]
            sp += 2
            x += skip
            for _ in range(cnt):
                if sp >= len(data) or x >= w:
                    break
                idx = data[sp]
                r, g, b = palette_rgb[idx]
                if x >= 0:
                    px[x, y] = (r, g, b, 255)
                sp += 1
                x += 1
    return img


def decode_bmp256(data, w, h, palette_rgb):
    """未压缩 BMP 精灵：w*h 字节索引。"""
    if len(data) < w * h:
        return None
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    for y in range(h):
        for x in range(w):
            idx = data[y * w + x]
            r, g, b = palette_rgb[idx]
            px[x, y] = (r, g, b, 255)
    return img


def decode_object(blob, palette_rgb):
    hdr = parse_obj_header(blob)
    if hdr is None:
        return None, None
    kind = rle_type_from_flags(hdr["flags"])
    goff = hdr["graphicOff"]
    gsize = hdr["graphicSize"]
    gdata = blob[goff:goff + gsize]
    if len(gdata) < gsize:
        return hdr, None
    if kind == "BMP":
        img = decode_bmp256(gdata, hdr["w"], hdr["h"], palette_rgb)
    else:
        img = decode_rle256(gdata, palette_rgb, kind)
    return hdr, img


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return 1
    dat, out_dir = args[0], args[1]

    keys = None
    if "--keys" in args:
        i = args.index("--keys")
        keys = []
        for r in args[i + 1:]:
            if r.startswith("--"):
                break
            keys.append(int(r, 0))
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    diff_with = args[args.index("--diff-only") + 1] if "--diff-only" in args else None
    verbose = "--verbose" in args

    palette, data = load_objects(dat)
    pal_rgb = parse_palette(palette)

    if diff_with:
        _, data2 = load_objects(diff_with)
        target = [k for k in sorted(data) if k in data2 and data[k] != data2[k]]
    elif keys:
        target = [k for k in keys if k in data]
    else:
        target = sorted(data)
    if limit:
        target = target[:limit]

    os.makedirs(out_dir, exist_ok=True)
    ok = 0
    fail = 0
    for k in target:
        hdr, img = decode_object(data[k], pal_rgb)
        cat, num, dmg = split_key(k)
        if img is None:
            fail += 1
            if verbose:
                hh = hdr if hdr else {}
                print(f"  FAIL key={k} c{cat} n{num} d{dmg} hdr={hh}")
            continue
        kind = rle_type_from_flags(hdr["flags"]) if hdr else "?"
        name = f"k{k}_c{cat}_n{num}_d{dmg}_{kind}.png"
        img.save(os.path.join(out_dir, name))
        ok += 1
        if verbose:
            print(f"  OK   key={k} c{cat} n{num} d{dmg} {kind} "
                  f"{hdr['w']}x{hdr['h']} flags=0x{hdr['flags']:X} "
                  f"gsize={hdr['graphicSize']}")
    print(f"decoded {ok} sprites, {fail} failed -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
