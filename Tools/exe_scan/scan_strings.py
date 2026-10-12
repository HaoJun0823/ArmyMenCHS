"""
扫描 PE 文件（Armymen.exe）的可读字符串，输出 RVA + 文件偏移 + 字符串。

用途：定位 exe 内需要汉化的硬编码 UI 文本，为 DLL 内存补丁提供地址表。

用法：
    python scan_strings.py <exe> [--min N] [--csv out.csv] [--section .rdata]

32 位 PE：ImageBase 通常为 0x400000，加载后 RVA + ImageBase = 虚拟地址。
"""

import sys
import struct
import csv


def parse_pe(path):
    with open(path, "rb") as f:
        buf = f.read()
    if buf[:2] != b"MZ":
        raise ValueError("not a PE file")

    pe_off = struct.unpack_from("<I", buf, 0x3C)[0]
    if buf[pe_off:pe_off + 4] != b"PE\0\0":
        raise ValueError("bad PE signature")

    machine = struct.unpack_from("<H", buf, pe_off + 4)[0]
    nsec = struct.unpack_from("<H", buf, pe_off + 6)[0]
    opt_size = struct.unpack_from("<H", buf, pe_off + 20)[0]
    opt_off = pe_off + 24

    # Optional header magic: 0x10b = PE32, 0x20b = PE32+
    magic = struct.unpack_from("<H", buf, opt_off)[0]
    if magic == 0x10B:
        image_base = struct.unpack_from("<I", buf, opt_off + 28)[0]
    else:
        image_base = struct.unpack_from("<Q", buf, opt_off + 24)[0]

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
    return {"machine": machine, "image_base": image_base,
            "sections": sections, "buf": buf}


def rva_to_file(pe, rva):
    for s in pe["sections"]:
        if s["vaddr"] <= rva < s["vaddr"] + max(s["vsize"], s["rsize"]):
            return s["roff"] + (rva - s["vaddr"])
    return None


def extract_strings(data, base_rva, min_len):
    """提取连续可打印 ASCII 串（含空格、常见标点）。"""
    out = []
    cur = bytearray()
    start = 0
    for i, b in enumerate(data):
        if 32 <= b <= 126:
            if not cur:
                start = i
            cur.append(b)
        else:
            if len(cur) >= min_len:
                out.append((base_rva + start, cur.decode("ascii"), len(cur)))
            cur = bytearray()
    if len(cur) >= min_len:
        out.append((base_rva + start, cur.decode("ascii"), len(cur)))
    return out


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    path = args[0]
    min_len = int(args[args.index("--min") + 1]) if "--min" in args else 4
    csv_out = args[args.index("--csv") + 1] if "--csv" in args else None
    want = args[args.index("--section") + 1] if "--section" in args else None

    pe = parse_pe(path)
    print(f"file       : {path}")
    print(f"machine    : 0x{pe['machine']:X} "
          f"({'i386' if pe['machine'] == 0x14c else 'other'})")
    print(f"imageBase  : 0x{pe['image_base']:X}")
    print("sections   :")
    for s in pe["sections"]:
        print(f"   {s['name']:<10} RVA=0x{s['vaddr']:08X} "
              f"VS=0x{s['vsize']:06X} RS=0x{s['rsize']:06X} "
              f"FileOff=0x{s['roff']:06X}")

    rows = []
    for s in pe["sections"]:
        if want and s["name"] != want:
            continue
        if s["name"] not in (".rdata", ".data", ".text", "DATA", "CONST"):
            continue
        if s["rsize"] == 0:
            continue
        data = pe["buf"][s["roff"]:s["roff"] + s["rsize"]]
        for rva, text, n in extract_strings(data, s["vaddr"], min_len):
            foff = rva_to_file(pe, rva)
            rows.append((s["name"], rva, foff, n, text))

    print(f"\nstrings    : {len(rows)} (min_len={min_len})")

    if csv_out:
        with open(csv_out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["section", "rva", "file_off", "len", "text"])
            for r in rows:
                w.writerow([r[0], f"0x{r[1]:08X}",
                            f"0x{r[2]:08X}" if r[2] is not None else "",
                            r[3], r[4]])
        print(f"CSV -> {csv_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
