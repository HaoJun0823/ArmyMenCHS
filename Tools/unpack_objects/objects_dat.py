"""
Army Men objects.dat 解包 / 打包工具
=====================================

格式依据 src/fileio.cpp 的 OpenDataFile()：

    偏移 0     : int FILEID          == 132415161 (0x7E3D2B9)
    偏移 4     : 256 x RGBQUAD       = 1024 字节   256 色调色板
    偏移 1028  : int nObjects
    偏移 1032  : nObjects x { key:DWORD, offset:DWORD }   8 字节/项
    之后       : 每个对象的 RLE 压缩位图（offset 为绝对文件偏移）

key 生成公式（compobj.cpp:451）：
    key = damagelevel + (number << 5) + (category << 15)

用法：
    python objects_dat.py unpack <in.dat> <outdir>
    python objects_dat.py pack   <outdir> <out.dat>
    python objects_dat.py info   <in.dat>

依赖：仅标准库（打包为 CI 友好）。
"""

import struct
import sys
import os
import json

FILEID = 132415161
HEADER_SIZE = 4 + 1024 + 4          # FILEID + palette + nObjects
TABLE_ENTRY_SIZE = 8


# ---------------------------------------------------------------- 基础读取

def read_u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def parse_header(buf):
    fileid = read_u32(buf, 0)
    if fileid != FILEID:
        raise ValueError(f"FILEID mismatch: got {fileid}, expect {FILEID}")
    palette = buf[4:4 + 1024]
    nobj = read_u32(buf, 1028)
    return fileid, palette, nobj


def parse_table(buf, nobj):
    """返回 [(key, offset), ...]，按文件顺序。"""
    entries = []
    base = HEADER_SIZE
    for i in range(nobj):
        off = base + i * TABLE_ENTRY_SIZE
        key = read_u32(buf, off)
        data_off = read_u32(buf, off + 4)
        entries.append((key, data_off))
    return entries


def split_key(key):
    damagelevel = key & 0x1F
    number = (key >> 5) & 0x3FF
    category = (key >> 15) & 0x7F
    return category, number, damagelevel


def make_key(category, number, damagelevel):
    return damagelevel + (number << 5) + (category << 15)


# ---------------------------------------------------------------- 解包

def cmd_unpack(in_path, out_dir):
    with open(in_path, "rb") as f:
        buf = f.read()

    fileid, palette, nobj = parse_header(buf)
    entries = parse_table(buf, nobj)

    os.makedirs(out_dir, exist_ok=True)

    # 调色板存为 256 色 RGB 表（便于外部工具加载）
    pal_path = os.path.join(out_dir, "palette.bin")
    with open(pal_path, "wb") as f:
        f.write(palette)

    # 目录表存为 JSON，便于人工查看/编辑顺序
    meta = []
    raw_dir = os.path.join(out_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)

    for idx, (key, data_off) in enumerate(entries):
        # 对象数据边界 = 下一个对象的 offset；最后一个到文件尾。
        # 注意：目录表里的 offset 不保证升序，故先排序求边界。
        meta.append({"index": idx, "key": key, "offset": data_off})

    # 求每个对象的长度（按 offset 升序后，用下一个 offset 作为结束）
    order = sorted(range(nobj), key=lambda i: entries[i][1])
    bounds = {}
    for pos, i in enumerate(order):
        start = entries[i][1]
        if pos + 1 < len(order):
            end = entries[order[pos + 1]][1]
        else:
            end = len(buf)
        bounds[i] = (start, end)

    for idx, (key, data_off) in enumerate(entries):
        start, end = bounds[idx]
        data = buf[start:end]
        cat, num, dmg = split_key(key)
        name = f"obj_{idx:04d}_c{cat:02d}_n{num:03d}_d{dmg}.bin"
        with open(os.path.join(raw_dir, name), "wb") as f:
            f.write(data)
        meta[idx].update({"category": cat, "number": num,
                          "damagelevel": dmg, "file": name,
                          "size": end - start,
                          "orig_offset": data_off})

    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"fileid": fileid, "nObjects": nobj,
                   "headerSize": HEADER_SIZE, "objects": meta}, f, indent=2)

    print(f"unpacked {nobj} objects -> {out_dir}")
    print(f"  palette : {pal_path}")
    print(f"  objects : {raw_dir} ({len(meta)} files)")
    return 0


# ---------------------------------------------------------------- 打包

def cmd_pack(in_dir, out_path):
    manifest_path = os.path.join(in_dir, "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as f:
        man = json.load(f)

    with open(os.path.join(in_dir, "palette.bin"), "rb") as f:
        palette = f.read()
    if len(palette) != 1024:
        raise ValueError(f"palette must be 1024 bytes, got {len(palette)}")

    objs = sorted(man["objects"], key=lambda o: o["index"])
    nobj = len(objs)

    raw_dir = os.path.join(in_dir, "raw")
    blobs = {}
    for o in objs:
        with open(os.path.join(raw_dir, o["file"]), "rb") as f:
            blobs[o["index"]] = f.read()

    table_size = nobj * TABLE_ENTRY_SIZE
    data_start = HEADER_SIZE + table_size

    # 数据块的物理排放顺序 = 原 offset 升序（不是目录表顺序！）。
    # 实测：目录表第 0 项 offset 可能远大于 data 起点，说明 compobj 按
    # 某种（分类/大小）顺序写数据，目录表顺序与之不同。
    # pack 时用原 offset 的相对次序还原；若缺失原 offset 信息，则按 index。
    phys_order = sorted(objs, key=lambda o: o.get("orig_offset", o["index"]))

    out = bytearray()
    out += struct.pack("<I", FILEID)
    out += palette
    out += struct.pack("<I", nobj)

    new_offsets = {}
    cur = data_start
    for o in phys_order:
        new_offsets[o["index"]] = cur
        cur += len(blobs[o["index"]])

    for o in objs:
        out += struct.pack("<II", o["key"], new_offsets[o["index"]])

    for o in phys_order:
        out += blobs[o["index"]]

    with open(out_path, "wb") as f:
        f.write(bytes(out))

    print(f"packed {nobj} objects -> {out_path} ({len(out)} bytes)")
    return 0


# ---------------------------------------------------------------- 信息

def cmd_info(in_path):
    with open(in_path, "rb") as f:
        buf = f.read()
    fileid, palette, nobj = parse_header(buf)
    entries = parse_table(buf, nobj)
    print(f"file      : {in_path}")
    print(f"size      : {len(buf)} bytes")
    print(f"FILEID    : 0x{fileid:X} ({fileid})")
    print(f"nObjects  : {nobj}")
    print(f"table     : {HEADER_SIZE} .. {HEADER_SIZE + nobj * 8}")
    offs = [e[1] for e in entries]
    print(f"data offs : min={min(offs)} max={max(offs)}")
    print(f"sorted?   : {offs == sorted(offs)}")
    cats = {}
    for k, _ in entries:
        c, _, _ = split_key(k)
        cats[c] = cats.get(c, 0) + 1
    print(f"categories: {dict(sorted(cats.items()))}")
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
