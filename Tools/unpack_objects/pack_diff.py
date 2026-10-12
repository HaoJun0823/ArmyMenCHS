"""
差异打包：以 Steam objects.dat 为基底，只覆盖选定 key 的中文数据。

这是"精细化汉化"的核心：不整包替换，只把确认是本地化的精灵换掉。

二进制安全性依据（已实测验证）：
  objects.dat 的目录表存 (key, offset)，每个对象块自带完整头部
  (key/width/height/flags/hotspot/linkspot/graphicSize + 数据 + shadow + mask + maskRect)。
  因此**每个对象的长度可变**，只要重算 offset 即可，不存在"尺寸必须一致"的约束。
  唯一的整体约束是：数据区各块不重叠、offset 单调，由 pack 阶段顺序写入保证。

用法：
    python pack_diff.py <base_objects.dat> <overlay_dir> <out.dat> \
        [--keys KEY1 KEY2 ...] [--categories 44 45 46 47] [--palette] \
        [--strip-mask KEY1 KEY2 ...]

  base:        Steam 原版 objects.dat
  overlay_dir: Army1_Object_CHS/<Terrain> （含 raw/ 与 manifest.json）
  --keys:      要覆盖的 key 列表（显式）
  --categories:要覆盖的 category 列表（按分类批量）
  --palette:   是否同时用 overlay 的调色板（默认否，保留 base 的）
  --strip-mask:要剥离碰撞掩膜的 key 列表（见下）

★ --strip-mask —— 碰撞掩膜剥离（修复"高山第三关羊肠河吉普车被油桶卡住"）

  症状：1998 中文母盘的 Alpine/objects.dat 会让高山第三关「羊肠河」绿军营地的
        吉普车被油桶卡住，必须引爆油桶才能开动，严重损伤吉普车。英文原版无此问题。

  根因：母盘 Alpine/objects.dat 里 Building(cat 17) 的 num 328 / 903 在
        damage level 0/1 上各带一块 5264 / 5824 字节的**碰撞掩膜**，解码后
        25280/37600 像素置位，整片盖住木屋下方本该能通行的地块；Steam v1.2
        已删除（maskSize = 0）。游戏的通行判定分支在 Map.cpp:3311/3420/3581/3651
        的 `if (pobj->cell.pSprite->pMask)`：掩膜存在时该建筑占满整块地，
        吉普车路径规划撞上就卡死。

  ★ 该掩膜与汉化**完全无关**：cat 17 这 4 个块在 1998/2018 两版之间视觉完全
    一致（同一栋木屋的完好/损坏态），没有任何中文。1998 版独有的是额外的
    flags 位 0x40(BM_SYSTEMMEMORY) 和这块掩膜；2018 版为 flags=0x08 / maskSize=0。

  ★ 本开关只把 maskSize 写成 0 并丢弃掩膜字节，**不动 graphic / shadow /
    hotspot / linkspot / maskRect / flags**，故不损失任何汉化像素。
"""

import sys
import os
import json
import struct
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from objects_dat import (FILEID, HEADER_SIZE, TABLE_ENTRY_SIZE,
                         parse_header, parse_table, split_key, make_key)


def load_objects_raw(path):
    """按 (key -> bytes, rva顺序) 读入所有对象块。"""
    with open(path, "rb") as f:
        buf = f.read()
    fileid, palette, nobj = parse_header(buf)
    entries = parse_table(buf, nobj)
    order = sorted(range(nobj), key=lambda i: entries[i][1])
    bounds = {}
    for pos, i in enumerate(order):
        s = entries[i][1]
        e = entries[order[pos + 1]][1] if pos + 1 < len(order) else len(buf)
        bounds[i] = (s, e)
    # 输出顺序 = 原文件物理顺序（order）
    result = []
    for i in order:
        s, e = bounds[i]
        result.append((entries[i][0], buf[s:e]))
    return fileid, palette, result


def normalize_flags(blob, quiet=True):
    """规范化对象块的 sprite_flags（**默认不启用**，需 --normalize）。

    背景：中文 v1.0 与 Steam v1.2 的 flags 有细微差异，例如部分块
    CHS=0x48 而 Steam=0x08（多一个 BM_SYSTEMMEMORY）。

    ★ 注意：**Steam 自己的文件里也有大量 0x48 块**（Alpine 574 个），
      所以 0x40 并非非法标志。此函数仅作为排查手段，默认关闭，
      以免产出与两版都不同的第三种结果。

    只在结构完全自洽时才改写，否则原样返回。
    """
    if len(blob) < 28:
        return blob, False
    key, w, h, flags = struct.unpack_from("<iiii", blob, 0)
    if w <= 0 or h <= 0 or w > 4096 or h > 4096:
        return blob, False

    gsize = struct.unpack_from("<i", blob, 24)[0]
    if gsize < 0:
        return blob, False
    p = 28 + gsize
    if p + 4 > len(blob):
        return blob, False
    ssize = struct.unpack_from("<i", blob, p)[0]
    p += 4 + max(ssize, 0)
    if p + 4 > len(blob):
        return blob, False
    msize = struct.unpack_from("<i", blob, p)[0]
    p += 4 + max(msize, 0) + 16
    if p != len(blob):
        return blob, False

    KEEP = 0x01 | 0x02 | 0x04 | 0x08 | 0x10 | 0x20
    new_flags = flags & KEEP
    if new_flags == 0 or new_flags == flags:
        return blob, False

    out = bytearray(blob)
    struct.pack_into("<i", out, 12, new_flags)
    if not quiet:
        c = (key >> 15) & 0x7F
        print(f"  normalize key={key} (cat {c}) flags 0x{flags:X} -> 0x{new_flags:X}")
    return bytes(out), True


def strip_mask(blob):
    """剥离对象块的碰撞掩膜（maskSize -> 0），返回 (新块, 是否改动)。

    ★ 语义依据 fileio.cpp:1424-1434：
        fread(&ibuf, sizeof(int), 1, fp);       // mask size
        if (ibuf > 0) { malloc; fread(pMask); } // >0 才分配并加载掩膜
    所以 maskSize = 0 即"无掩膜"，Map.cpp 的通行判定会走另一条路径。

    ★ 为什么不用 2018 版的整块替换：
        这两块在两版之间 flags 也不同（0x48 vs 0x08）。0x40 是 BM_SYSTEMMEMORY，
        而 Steam 自己的 Alpine objects.dat 里也有 574 个 0x48 块，
        说明 0x40 合法、不是错误。保留 base 的 flags、只清 mask，变更面最小。

    结构不合法时原样返回（返回 False），绝不猜边界。
    """
    if len(blob) < 44:
        return blob, False
    key, w, h, flags = struct.unpack_from("<iiii", blob, 0)
    if w <= 0 or h <= 0 or w > 4096 or h > 4096:
        return blob, False

    p = 24
    gsize = struct.unpack_from("<i", blob, p)[0]; p += 4
    if gsize < 0 or p + gsize > len(blob):
        return blob, False
    p += gsize

    if p + 4 > len(blob):
        return blob, False
    ssize = struct.unpack_from("<i", blob, p)[0]; p += 4
    if ssize < 0 or p + ssize > len(blob):
        return blob, False
    p += ssize

    if p + 4 > len(blob):
        return blob, False
    msize = struct.unpack_from("<i", blob, p)[0]; p += 4
    if msize < 0 or p + msize > len(blob):
        return blob, False
    if msize == 0:
        return blob, False                       # 本来就没掩膜

    if p + msize + 16 != len(blob):
        return blob, False                       # 尾部 maskRect 对不上，别动

    out = bytearray()
    out += blob[:p]                              # ... 到 maskSize 字段为止
    struct.pack_into("<i", out, p - 4, 0)        # maskSize = 0
    out += blob[p + msize:]                      # maskRect 及其后（丢弃掩膜字节）
    return bytes(out), True


def load_overlay_index(overlay_dir):
    """从 manifest.json 建立 key -> 文件路径。"""
    with open(os.path.join(overlay_dir, "manifest.json"), "r",
              encoding="utf-8") as f:
        man = json.load(f)
    idx = {}
    for o in man["objects"]:
        idx[o["key"]] = os.path.join(overlay_dir, "raw", o["file"])
    return idx


def main():
    args = sys.argv[1:]
    if len(args) < 3:
        print(__doc__)
        return 1
    base_p, overlay_dir, out_p = args[0], args[1], args[2]

    keys = set()
    cats = set()
    strip = set()
    use_palette = False
    normalize = False
    i = 3
    while i < len(args):
        a = args[i]
        if a == "--normalize":
            normalize = True
        elif a == "--strip-mask":
            i += 1
            while i < len(args) and not args[i].startswith("--"):
                strip.add(int(args[i]))
                i += 1
            continue
        elif a == "--keys":
            i += 1
            while i < len(args) and not args[i].startswith("--"):
                keys.add(int(args[i]))
                i += 1
            continue
        elif a == "--categories":
            i += 1
            while i < len(args) and not args[i].startswith("--"):
                cats.add(int(args[i]))
                i += 1
            continue
        elif a == "--palette":
            use_palette = True
        i += 1

    fileid, base_palette, base_objs = load_objects_raw(base_p)
    ov_idx = load_overlay_index(overlay_dir)

    if use_palette:
        with open(os.path.join(overlay_dir, "palette.bin"), "rb") as f:
            palette = f.read()
    else:
        palette = base_palette

    # 决定要覆盖哪些 key
    target = set(keys)
    if cats:
        for k, _ in base_objs:
            c, _, _ = split_key(k)
            if c in cats:
                target.add(k)

    replaced, missing, unchanged = 0, 0, 0
    out_objs = []
    size_delta = 0
    norm_count = 0
    for k, blob in base_objs:
        if k in target:
            fp = ov_idx.get(k)
            if fp and os.path.isfile(fp):
                with open(fp, "rb") as f:
                    nb = f.read()
                if normalize:
                    nb, _ch = normalize_flags(nb)
                    if _ch:
                        norm_count += 1
                size_delta += len(nb) - len(blob)
                out_objs.append((k, nb))
                replaced += 1
                continue
            else:
                missing += 1
        out_objs.append((k, blob))
        unchanged += 1

    # --strip-mask：剥离指定 key 的碰撞掩膜
    #   修 Alpine 高山第三关「羊肠河」吉普车被油桶卡住。
    #   注意是在 **覆盖之后** 执行，因此若某 key 既被汉化覆盖又被指定 strip，
    #   剥离的是覆盖后的块 —— 这是期望行为（汉化数据保留，只摘掩膜）。
    strip_requested = len(strip)
    stripped = 0
    strip_failed = []
    if strip:
        fixed = []
        for k, blob in out_objs:
            if k in strip:
                nb, ch = strip_mask(blob)
                if ch:
                    stripped += 1
                    size_delta -= len(blob) - len(nb)
                elif blob is not nb:
                    strip_failed.append(k)
                fixed.append((k, nb))
            else:
                fixed.append((k, blob))
        out_objs = fixed

    # 重打包
    nobj = len(out_objs)
    data_start = HEADER_SIZE + nobj * TABLE_ENTRY_SIZE

    out = bytearray()
    out += struct.pack("<I", FILEID)
    out += palette
    out += struct.pack("<I", nobj)

    # ★★ 目录表必须 **按 key 升序** 排列！
    #
    #   游戏用二分查找定位对象（fileio.cpp:1224 GetObjectTableIndex）：
    #       min = 0; max = ODF.nObjects;
    #       while (max > min) {
    #           i = min + ((max-min) >> 1);
    #           ikey = ODF.ObjectTable[i].key;
    #           if (ikey == key) return i;
    #           else if (ikey < key) min = i + 1;
    #           else max = i;
    #       }
    #       return -1;      // 找不到
    #
    #   若目录表不是按 key 升序，二分查找会失败 → GetObjectTableIndex 返回 -1
    #   → 对象"无法加载"。这正是早期版本"贴图不显示/加载失败"的根因。
    #
    #   数据区（物理存放顺序）与目录表顺序**相互独立**：目录表里存的是每块
    #   的绝对 offset，所以可以"数据随意排、目录按 key 排"。
    #
    # 1) 先按当前顺序（沿用 base 的物理顺序）分配 offset 并写出数据
    phys = list(out_objs)
    offsets = {}
    cur = data_start
    for k, blob in phys:
        offsets[k] = cur
        cur += len(blob)

    # 2) 目录表按 key 升序写
    table = sorted(((k, offsets[k]) for k, _ in phys), key=lambda x: x[0])
    if len(table) != nobj:
        print(f"!! 目录表条目数 {len(table)} != nObjects {nobj}")
        return 1
    for k, off in table:
        out += struct.pack("<II", k, off)

    # 3) 数据区按物理顺序写
    for _, blob in phys:
        out += blob

    with open(out_p, "wb") as f:
        f.write(bytes(out))

    print(f"base    : {base_p}  ({len(base_objs)} objs, palette={'overlay' if use_palette else 'base'})")
    print(f"overlay : {overlay_dir}")
    print(f"target  : {len(target)} keys "
          f"(keys={len(keys)}, cats={sorted(cats)})")
    print(f"result  : replaced={replaced} unchanged={unchanged} "
          f"missing_in_overlay={missing}")
    print(f"table   : sorted by key (ascending), {len(table)} entries")
    if strip_requested:
        detail = f"strip   : requested {strip_requested}, actually stripped {stripped}"
        if stripped < strip_requested:
            # 基底（Steam v1.2）本来就已删除这些掩膜 -> 预期情形，非错误
            detail += "  (= 其余的基底块本就无掩膜，符合预期)"
        print(detail)
        for k in strip_failed:
            print(f"  !! strip_mask 结构解析失败，未改动 key={k}")
    print(f"size    : {os.path.getsize(base_p)} -> {len(out)} "
          f"(delta {size_delta:+d} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
