"""
按键设置界面（Keyboard/Joystick Config）显示名块扫描器。

背景：这些名字在 exe 里有**两份独立副本**：
    - 0xBD9xx 附近  → USA.h 的 *Title_Text（控制说明列，已被 ui_block.ini 处理）
    - 0xD07xx 附近  → 按键设置界面的 name 字段（**实际显示用的，此前未处理**）
两者互不影响，必须分别处理。

该块不是紧凑连续槽（项之间夹杂指针/数值数据），因此不能按 packed4
连续扫描，而要**逐个定位字符串的 RVA**。

用法：
    python scan_keynames.py <ArmyMen.exe> --start 0xD0714 --end 0xD0E00
                              [--min-len 3] [--csv out.csv]
"""

import sys
import struct


def parse_pe(path):
    with open(path, "rb") as f:
        buf = f.read()
    pe = struct.unpack_from("<I", buf, 0x3C)[0]
    nsec = struct.unpack_from("<H", buf, pe + 6)[0]
    optsz = struct.unpack_from("<H", buf, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", buf, opt)[0]
    secs = []
    so = opt + optsz
    for i in range(nsec):
        q = so + i * 40
        secs.append({
            "name": buf[q:q + 8].rstrip(b"\0").decode("ascii", "replace"),
            "vsize": struct.unpack_from("<I", buf, q + 8)[0],
            "vaddr": struct.unpack_from("<I", buf, q + 12)[0],
            "rsize": struct.unpack_from("<I", buf, q + 16)[0],
            "roff": struct.unpack_from("<I", buf, q + 20)[0],
        })
    return buf, secs


def rva_to_off(secs, rva):
    for s in secs:
        if s["vaddr"] <= rva < s["vaddr"] + max(s["vsize"], s["rsize"]):
            return s["roff"] + (rva - s["vaddr"])
    return None


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    exe = args[0]
    start = int(args[args.index("--start") + 1], 16) if "--start" in args else 0xD0714
    end = int(args[args.index("--end") + 1], 16) if "--end" in args else 0xD0E00
    minlen = int(args[args.index("--min-len") + 1]) if "--min-len" in args else 3
    csv_out = args[args.index("--csv") + 1] if "--csv" in args else None

    buf, secs = parse_pe(exe)
    o = rva_to_off(secs, start)
    e = rva_to_off(secs, end)
    if o is None or e is None:
        print("RVA 映射失败")
        return 1

    print(f"# 扫描 RVA 0x{start:X} .. 0x{end:X}")
    print(f"# {'RVA':>10}  {'len':>4}  text")
    rows = []
    p = o
    while p < e:
        q = p
        raw = bytearray()
        while q < e and buf[q] != 0:
            raw.append(buf[q])
            q += 1
        if q >= e:
            break
        if len(raw) >= minlen:
            # 必须是可打印 ASCII，且首字符是字母
            if all(32 <= c < 127 for c in raw) and chr(raw[0]).isalpha():
                text = raw.decode("ascii")
                rva = start + (p - o)
                rows.append((rva, text))
                print(f"  0x{rva:08X}  {len(raw):>4}  {text}")
                p = q + 1
                continue
        p = q + 1

    print()
    print(f"# 共 {len(rows)} 条")
    if csv_out:
        import csv
        with open(csv_out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["rva", "english"])
            for rva, t in rows:
                w.writerow([f"0x{rva:08X}", t])
        print(f"# CSV -> {csv_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
