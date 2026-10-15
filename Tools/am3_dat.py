"""
Army Men: Toys in Space (3 代) .dat 解包 / 回包工具
==================================================

3 代 dat 与 2 代 objects.dat **同构**，仅 FILEID（幻数）不同：

    偏移 0     : int FILEID        3 代 = 0x81920667 (title) / 0x81920668 (shared)
    偏移 4     : 256 x RGBQUAD    = 1024 字节   256 色调色板
    偏移 1028  : int nObjects
    偏移 1032  : nObjects x { key:DWORD, offset:DWORD }   8 字节/项
    之后       : 各对象的**未压缩 256 色位图**（offset 为绝对文件偏移）

对象块布局（本工具实测，3 代 title.dat/shared.dat 全部对象一致）：

    [+0]  int key
    [+4]  int width
    [+8]  int height
    [+12] int sprite_flags      0 = 未压缩 BMP；0x02/0x04/0x08/0x10/0x20 = RLE 族
    [+16] SPOINT hotspot        (short x, short y)
    [+20] SPOINT linkspot       (short x, short y)
    [+24] int graphicSize
    [+28] graphicSize 字节图像数据

**无损优先**：unpack 同时保证两种产物 ——
  1. raw/*.bin  —— 对象原始字节，**逐字节无损**，pack 直接回填（CI 首选）
  2. png/*.png  —— 解码后的图像，供人工改图；pack 时若存在同名 png 则回编码

用法：
    python am3_dat.py unpack <in.dat> <out_dir>
    python am3_dat.py pack   <in_dir> <out.dat>
    python am3_dat.py info   <in.dat>

依赖：标准库 + Pillow（仅 png 导出/回编码需要；纯 raw 往返不需要）。
"""

import os
import sys
import json
import struct
import hashlib

HEADER_TABLE_OFF = 1028 + 4          # FILEID + palette(1024) + nObjects(4)
ENTRY_SIZE = 8

SP_RLE = 0x02
SP_DRLE = 0x04
SP_WRLE = 0x08
SP_TRLE = 0x10
SP_SRLE = 0x20


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def _i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def parse_container(buf):
    fileid = _u32(buf, 0)
    palette = buf[4:4 + 1024]
    nobj = _u32(buf, 1028)
    if nobj > 200000:
        raise ValueError("nObjects 过大 (%d)，不像 3 代 dat" % nobj)
    entries = []
    for i in range(nobj):
        off = HEADER_TABLE_OFF + i * ENTRY_SIZE
        key = _u32(buf, off)
        data_off = _u32(buf, off + 4)
        entries.append((key, data_off))
    if not entries:
        raise ValueError("空目录表")
    offs = [o for _, o in entries]
    if min(offs) < HEADER_TABLE_OFF or max(offs) >= len(buf):
        raise ValueError("目录表 offset 越界，不是有效 dat")
    return fileid, palette, entries


def object_bounds(buf, entries):
    """按 offset 升序求每个对象的 [start,end)。"""
    n = len(entries)
    order = sorted(range(n), key=lambda i: entries[i][1])
    bounds = {}
    for pos, i in enumerate(order):
        s = entries[i][1]
        e = entries[order[pos + 1]][1] if pos + 1 < n else len(buf)
        bounds[i] = (s, e)
    return bounds


def parse_object_header(blob):
    if len(blob) < 28:
        return None
    key, w, h, flags = struct.unpack_from("<iiii", blob, 0)
    if not (0 < w <= 8192 and 0 < h <= 8192):
        return None
    hs = struct.unpack_from("<hh", blob, 16)
    ls = struct.unpack_from("<hh", blob, 20)
    gsize = _i32(blob, 24)
    if gsize < 0 or 28 + gsize > len(blob):
        return None
    return {"key": key, "w": w, "h": h, "flags": flags,
            "hotspot": list(hs), "linkspot": list(ls), "graphicSize": gsize}


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


# ---------------------------------------------------------------- 解码

def palette_rgb(pal):
    out = []
    for i in range(256):
        b, g, r, _ = pal[i * 4:i * 4 + 4]
        out.append((r, g, b))
    return out


def decode_bmp(idx, w, h, pal_rgb, Image):
    """未压缩 256 色位图。

    ★ 两个坑，都必须处理，否则图像会坏：

    1) **行按 4 字节对齐**（stride = align4(w)），不是紧密 w 字节。
       按 w 紧读会让每行少吞填充字节，错位逐行累积 -> **斜向撕裂**。
       实测 3 代 869 个 BMP 对象全部满足 graphicSize == align4(w) * h。

    2) **行序自下而上**（标准 BMP 约定）：文件里第一行是图像的**最底行**。
       按自上而下读 -> 图像**上下镜像**（文字倒过来）。
    """
    stride = (w + 3) & ~3
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    for y in range(h):
        row = (h - 1 - y) * stride          # ← bottom-up
        for x in range(w):
            r, g, b = pal_rgb[idx[row + x]]
            px[x, y] = (r, g, b, 255)
    return img


def decode_rle(data, pal_rgb, kind, Image):
    """data = [w:WORD][h:WORD][h x rowOffset][rows...]；行内 [skip][count][count 字节]。"""
    if len(data) < 4:
        return None
    w, h = struct.unpack_from("<HH", data, 0)
    if not (0 < w <= 8192 and 0 < h <= 8192):
        return None
    ow = 4 if kind == "DRLE" else 2
    if len(data) < 4 + ow * h:
        return None
    offs = []
    for i in range(h):
        p = 4 + i * ow
        offs.append(_u32(data, p) if ow == 4 else struct.unpack_from("<H", data, p)[0])

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    for y in range(h):
        ro = offs[y]
        if ro <= 0 or ro >= len(data):
            continue
        sp = ro
        x = 0
        guard = 0
        while x < w and guard < 1 << 20:
            guard += 1
            if sp + 2 > len(data):
                break
            skip = data[sp]
            cnt = data[sp + 1]
            sp += 2
            x += skip
            for _ in range(cnt):
                if sp >= len(data):
                    break
                if 0 <= x < w:
                    r, g, b = pal_rgb[data[sp]]
                    px[x, y] = (r, g, b, 255)
                sp += 1
                x += 1
    return img


def export_png(blob, pal_rgb, out_png, Image):
    hdr = parse_object_header(blob)
    if hdr is None:
        return None
    kind = kind_of(hdr["flags"])
    g = blob[28:28 + hdr["graphicSize"]]
    if kind == "BMP":
        if len(g) < hdr["w"] * hdr["h"]:
            return None
        img = decode_bmp(g, hdr["w"], hdr["h"], pal_rgb, Image)
    else:
        img = decode_rle(g, pal_rgb, kind, Image)
    if img is None:
        return None
    img.save(out_png)
    return hdr


# ---------------------------------------------------------------- 编码

def encode_bmp(img, pal_rgb, palette_lookup):
    """RGBA -> 256 色索引流（精确匹配调色板，找不到取最近色）。

    ★ 与 decode_bmp 严格对称：
      - 每行按 **4 字节对齐**（stride = align4(w)），填充字节写 0
      - 行序 **自下而上**（先写图像最底行）
      否则重打包后游戏按原约定读取会出现撕裂 / 镜像。
    """
    w, h = img.size
    stride = (w + 3) & ~3
    px = img.convert("RGB").load()
    out = bytearray(stride * h)
    cache = {}
    for y in range(h):
        base = (h - 1 - y) * stride          # ← bottom-up，与解码对称
        for x in range(w):
            c = px[x, y]
            idx = cache.get(c)
            if idx is None:
                idx = palette_lookup.get(c)
                if idx is None:
                    # 最近色（曼哈顿距离，够用且快）
                    best, bd = 0, 1 << 30
                    for i, (r, g, b) in enumerate(pal_rgb):
                        d = abs(r - c[0]) + abs(g - c[1]) + abs(b - c[2])
                        if d < bd:
                            bd, best = d, i
                            if d == 0:
                                break
                    idx = best
                cache[c] = idx
            out[base + x] = idx
        # 填充字节保持 0（与原始数据一致）
    return bytes(out)


def build_palette_lookup(pal_rgb):
    lookup = {}
    for i, c in enumerate(pal_rgb):
        lookup.setdefault(c, i)
    return lookup


# ---------------------------------------------------------------- 命令

def cmd_unpack(in_path, out_dir):
    from PIL import Image

    buf = open(in_path, "rb").read()
    fileid, palette, entries = parse_container(buf)
    bounds = object_bounds(buf, entries)
    pal_rgb = palette_rgb(palette)

    raw_dir = os.path.join(out_dir, "raw")
    png_dir = os.path.join(out_dir, "png")
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(png_dir, exist_ok=True)

    with open(os.path.join(out_dir, "palette.bin"), "wb") as f:
        f.write(palette)

    metas = []
    png_ok = png_fail = 0
    for i, (key, orig_off) in enumerate(entries):
        s, e = bounds[i]
        blob = buf[s:e]
        raw_name = "obj_%04d_k%08X.bin" % (i, key)
        with open(os.path.join(raw_dir, raw_name), "wb") as f:
            f.write(blob)

        hdr = parse_object_header(blob)
        kind = kind_of(hdr["flags"]) if hdr else "?"
        png_name = None
        png_size = None
        png_sha = None
        if hdr is not None:
            png_name = "obj_%04d_k%08X.png" % (i, key)
            path = os.path.join(png_dir, png_name)
            try:
                if export_png(blob, pal_rgb, path, Image):
                    png_ok += 1
                    png_size = os.path.getsize(path)
                    png_sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
                else:
                    png_fail += 1
                    if os.path.exists(path):
                        os.remove(path)
                    png_name = None
            except Exception:
                png_fail += 1
                if os.path.exists(path):
                    os.remove(path)
                png_name = None
        else:
            png_fail += 1

        metas.append({
            "index": i,
            "key": key,
            "key_hex": "0x%08X" % key,
            "orig_offset": orig_off,
            "size": e - s,
            "raw": raw_name,
            "png": png_name,
            "sha256": hashlib.sha256(blob).hexdigest(),
            "width": hdr["w"] if hdr else None,
            "height": hdr["h"] if hdr else None,
            "flags": hdr["flags"] if hdr else None,
            "kind": kind,
            "hotspot": hdr["hotspot"] if hdr else None,
            "linkspot": hdr["linkspot"] if hdr else None,
            "graphicSize": hdr["graphicSize"] if hdr else None,
            "png_size": png_size,
            "png_sha256_at_unpack": png_sha,
        })

    manifest = {
        "source": os.path.basename(in_path),
        "source_size": len(buf),
        "source_sha256": hashlib.sha256(buf).hexdigest(),
        "fileid": "0x%08X" % fileid,
        "nObjects": len(entries),
        "headerTableOff": HEADER_TABLE_OFF,
        "objects": metas,
    }
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print("unpack %s -> %s" % (os.path.basename(in_path), out_dir))
    print("  objects : %d  (raw %d, png ok %d / fail %d)" %
          (len(entries), len(entries), png_ok, png_fail))
    print("  palette : palette.bin  manifest.json")
    return 0


def cmd_pack(in_dir, out_path):
    man = json.load(open(os.path.join(in_dir, "manifest.json"), "r", encoding="utf-8"))
    objs = sorted(man["objects"], key=lambda o: o["index"])

    raw_dir = os.path.join(in_dir, "raw")
    png_dir = os.path.join(in_dir, "png")
    palette = open(os.path.join(in_dir, "palette.bin"), "rb").read()
    if len(palette) != 1024:
        raise ValueError("palette.bin 必须 1024 字节")

    edited = 0
    blobs = {}
    for o in objs:
        png_path = os.path.join(png_dir, o["png"]) if o.get("png") else None
        raw_path = os.path.join(raw_dir, o["raw"])
        use_png = False
        if png_path and os.path.isfile(png_path) and o.get("png"):
            png_sha = hashlib.sha256(open(png_path, "rb").read()).hexdigest()
            if o.get("png_sha256_at_unpack") and png_sha != o["png_sha256_at_unpack"]:
                use_png = True
            elif not o.get("raw"):
                use_png = True
        if use_png:
            from PIL import Image
            img = Image.open(png_path)
            pal_rgb = palette_rgb(palette)
            lut = build_palette_lookup(pal_rgb)
            idx = encode_bmp(img, pal_rgb, lut)
            hdr = {"key": o["key"], "w": img.size[0], "h": img.size[1],
                   "flags": o.get("flags") or 0,
                   "hotspot": o.get("hotspot") or [0, 0],
                   "linkspot": o.get("linkspot") or [0, 0],
                   "graphicSize": len(idx)}
            head = struct.pack("<iiii", hdr["key"], hdr["w"], hdr["h"], hdr["flags"])
            head += struct.pack("<hh", hdr["hotspot"][0], hdr["hotspot"][1])
            head += struct.pack("<hh", hdr["linkspot"][0], hdr["linkspot"][1])
            head += struct.pack("<i", hdr["graphicSize"])
            blobs[o["index"]] = head + idx
            edited += 1
        else:
            blobs[o["index"]] = open(raw_path, "rb").read()

    n = len(objs)
    data_start = HEADER_TABLE_OFF + n * ENTRY_SIZE
    phys = sorted(objs, key=lambda o: o.get("orig_offset", o["index"]))

    out = bytearray()
    out += struct.pack("<I", int(man["fileid"], 16))
    out += palette
    out += struct.pack("<I", n)

    new_off = {}
    cur = data_start
    for o in phys:
        new_off[o["index"]] = cur
        cur += len(blobs[o["index"]])
    for o in objs:
        out += struct.pack("<II", o["key"], new_off[o["index"]])
    for o in phys:
        out += blobs[o["index"]]

    open(out_path, "wb").write(bytes(out))
    print("pack %s -> %s (%d bytes, %d objects, %d 由 PNG 重编码)" %
          (in_dir, out_path, len(out), n, edited))
    return 0


def cmd_info(in_path):
    buf = open(in_path, "rb").read()
    fileid, palette, entries = parse_container(buf)
    bounds = object_bounds(buf, entries)
    print("file     :", in_path)
    print("size     :", len(buf))
    print("FILEID   : 0x%08X" % fileid)
    print("nObjects :", len(entries))
    kinds = {}
    dims = {}
    for i, (k, o) in enumerate(entries):
        s, e = bounds[i]
        hdr = parse_object_header(buf[s:e])
        if not hdr:
            continue
        kinds[kind_of(hdr["flags"])] = kinds.get(kind_of(hdr["flags"]), 0) + 1
        dims[(hdr["w"], hdr["h"])] = dims.get((hdr["w"], hdr["h"]), 0) + 1
    print("kinds    :", kinds)
    print("top dims :", sorted(dims.items(), key=lambda x: -x[1])[:10])
    return 0


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    if cmd == "unpack":
        return cmd_unpack(sys.argv[2], sys.argv[3])
    if cmd == "pack":
        return cmd_pack(sys.argv[2], sys.argv[3])
    if cmd == "info":
        return cmd_info(sys.argv[2])
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
