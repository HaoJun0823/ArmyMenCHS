"""
生成 exe 内存补丁表：定位英文串 -> 中文译文，供 DLL 用。

核心思路：
  1. 在 Steam exe 里，用"锚点串"定位 UI 字符串块（紧凑 C 串 + 4 字节对齐 padding）。
  2. 在中文 exe 里，用同样的相对结构定位对应位置的中文串。
  3. 产出 (RVA, 英文原文, 中文译文, 槽容量) 表，DLL 照表覆写。

已知锚点（Steam .data 段）：
  0x000BDBB0 : "Radar Building" —— 对象/单位/武器名表起始
               顺序对应 Object.h 的 OBJECT_TYPES + 单位/武器

用法：
    python build_patch_table.py <steam.exe> <chs.exe> --anchor 0x000BDBB0
                                [--count N] [--csv out.csv]
"""

import sys
import struct
import csv


def parse_pe(path):
    with open(path, "rb") as f:
        buf = f.read()
    pe_off = struct.unpack_from("<I", buf, 0x3C)[0]
    nsec = struct.unpack_from("<H", buf, pe_off + 6)[0]
    opt_size = struct.unpack_from("<H", buf, pe_off + 20)[0]
    opt_off = pe_off + 24
    magic = struct.unpack_from("<H", buf, opt_off)[0]
    image_base = (struct.unpack_from("<I", buf, opt_off + 28)[0]
                  if magic == 0x10B else
                  struct.unpack_from("<Q", buf, opt_off + 24)[0])
    sec_off = opt_off + opt_size
    sections = []
    for i in range(nsec):
        p = sec_off + i * 40
        name = buf[p:p + 8].rstrip(b"\0").decode("ascii", "replace")
        vsize = struct.unpack_from("<I", buf, p + 8)[0]
        vaddr = struct.unpack_from("<I", buf, p + 12)[0]
        rsize = struct.unpack_from("<I", buf, p + 16)[0]
        roff = struct.unpack_from("<I", buf, p + 20)[0]
        sections.append({"name": name, "vsize": vsize, "vaddr": vaddr,
                         "rsize": rsize, "roff": roff})
    return {"image_base": image_base, "sections": sections, "buf": buf}


def rva_to_off(pe, rva):
    for s in pe["sections"]:
        if s["vaddr"] <= rva < s["vaddr"] + max(s["vsize"], s["rsize"]):
            return s["roff"] + (rva - s["vaddr"])
    return None


def read_slots(buf, off, count, encoding="ascii"):
    """按 'C串 + padding 到 4' 读取 count 个槽。
    返回 [(file_off, text, slot_capacity), ...]"""
    out = []
    p = off
    for _ in range(count):
        start = p
        s = bytearray()
        while p < len(buf) and buf[p] != 0:
            s.append(buf[p])
            p += 1
        # 跳过 NUL，对齐到 4
        nxt = p + 1
        pad = (4 - (nxt % 4)) % 4
        nxt += pad
        text = s.decode(encoding, "replace")
        out.append((start, text, nxt - start))
        p = nxt
    return out


def find_anchor(pe, text, encoding="ascii"):
    """在全文件里找 C 串（后跟 NUL）的位置，返回 file offset 列表。"""
    pat = text.encode(encoding) + b"\0"
    b = pe["buf"]
    hits = []
    i = b.find(pat)
    while i != -1:
        hits.append(i)
        i = b.find(pat, i + 1)
    return hits


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return 1
    steam_p, chs_p = args[0], args[1]
    anchor = 0xBDBB0
    count = 24
    csv_out = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--anchor" and i + 1 < len(args):
            anchor = int(args[i + 1], 16)
        elif a == "--count" and i + 1 < len(args):
            count = int(args[i + 1])
        elif a == "--csv" and i + 1 < len(args):
            csv_out = args[i + 1]
        i += 1

    steam = parse_pe(steam_p)
    chs = parse_pe(chs_p)
    print(f"Steam imageBase=0x{steam['image_base']:X}")
    print(f"CHS   imageBase=0x{chs['image_base']:X}")

    s_off = rva_to_off(steam, anchor)
    if s_off is None:
        print(f"anchor RVA 0x{anchor:X} not mapped in Steam exe")
        return 1
    print(f"anchor RVA 0x{anchor:X} -> Steam file off 0x{s_off:X}")

    en_slots = read_slots(steam["buf"], s_off, count, "ascii")
    print(f"\n=== Steam 英文槽（{len(en_slots)} 项）===")
    for off, t, cap in en_slots:
        rva = anchor + (off - s_off)
        print(f"  RVA 0x{rva:08X}  cap={cap:3d}  '{t}'")

    # 在中文 exe 里找第一项的中文译文：用"锚点串"反查
    # 策略：中文 exe 里搜索同样的表结构 —— 先用英文首字母不可行，
    # 改为在中文 exe 里定位相同 RVA 偏移处（若两 exe 布局一致）。
    print(f"\n=== 中文 exe 同 RVA 处读取 ===")
    c_off = rva_to_off(chs, anchor)
    if c_off is None:
        print("  中文 exe 无法映射该 RVA（布局不同）")
    else:
        gb = None
        try:
            gb = "gbk"
            ch_slots = read_slots(chs["buf"], c_off, count, gb)
            for off, t, cap in ch_slots:
                rva = anchor + (off - c_off)
                print(f"  RVA 0x{rva:08X}  cap={cap:3d}  '{t}'")
        except Exception as e:
            print(f"  读取失败: {e}")

    if csv_out:
        with open(csv_out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["rva", "file_off", "capacity", "english",
                        "chinese", "note"])
            for i, (off, t, cap) in enumerate(en_slots):
                rva = anchor + (off - s_off)
                w.writerow([f"0x{rva:08X}", f"0x{off:08X}", cap, t, "", ""])
        print(f"\nCSV -> {csv_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
