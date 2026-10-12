"""
配对 Steam 英文串块 与 中文 exe 中文串块，产出内存补丁表。

背景：两个 exe 布局不同（v0.1.2.0 vs v0.1.0.0），不能按 RVA 对齐，
      但**同一张字符串表的内部顺序一致**，因此可按序号配对。

已验证的锚点：
    Steam .data RVA 0xBDBB0 = "Radar Building"（对象名表起始）
    CHS   文件偏移 0x93B20 = "雷达站"（同一张表的中文版）

用法：
    python pair_tables.py <steam.exe> <chs.exe> \
        --en-rva 0xBDBB0 --chs-off 0x93B20 --count 40 [--csv out.csv]

输出 CSV：index, en_rva, en_fileoff, en_text, cap, chs_text, need_translate
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
        sections.append({
            "name": name,
            "vaddr": struct.unpack_from("<I", buf, p + 12)[0],
            "vsize": struct.unpack_from("<I", buf, p + 8)[0],
            "rsize": struct.unpack_from("<I", buf, p + 16)[0],
            "roff": struct.unpack_from("<I", buf, p + 20)[0],
        })
    return {"image_base": image_base, "sections": sections, "buf": buf}


def rva_to_off(pe, rva):
    for s in pe["sections"]:
        if s["vaddr"] <= rva < s["vaddr"] + max(s["vsize"], s["rsize"]):
            return s["roff"] + (rva - s["vaddr"])
    return None


def read_slots(buf, off, count, encoding):
    out = []
    p = off
    for _ in range(count):
        start = p
        raw = bytearray()
        while p < len(buf) and buf[p] != 0:
            raw.append(buf[p])
            p += 1
        nxt = p + 1
        nxt += (4 - (nxt % 4)) % 4
        try:
            text = raw.decode(encoding)
        except Exception:
            text = raw.decode(encoding, "replace")
        out.append({"off": start, "text": text, "cap": nxt - start})
        p = nxt
    return out


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return 1
    steam_p, chs_p = args[0], args[1]

    en_rva = None
    en_off_arg = 0xBB784      # Steam: "Special Itme"
    chs_off = 0x93B00         # CHS:   "特殊物品"
    count = 40
    csv_out = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--en-rva" and i + 1 < len(args):
            en_rva = int(args[i + 1], 16)
        elif a == "--en-off" and i + 1 < len(args):
            en_off_arg = int(args[i + 1], 16)
            en_rva = None
        elif a == "--chs-off" and i + 1 < len(args):
            chs_off = int(args[i + 1], 16)
        elif a == "--count" and i + 1 < len(args):
            count = int(args[i + 1])
        elif a == "--csv" and i + 1 < len(args):
            csv_out = args[i + 1]
        i += 1

    steam = parse_pe(steam_p)
    chs = parse_pe(chs_p)
    if en_rva is not None:
        en_off = rva_to_off(steam, en_rva)
        if en_off is None:
            print(f"cannot map RVA 0x{en_rva:X}")
            return 1
    else:
        en_off = en_off_arg
    if en_rva is None:
        # 由文件偏移反推 RVA，便于 DLL 使用
        en_rva = None
        for s in steam["sections"]:
            if s["roff"] <= en_off < s["roff"] + s["rsize"]:
                en_rva = s["vaddr"] + (en_off - s["roff"])
                break

    en = read_slots(steam["buf"], en_off, count, "ascii")
    cz = read_slots(chs["buf"], chs_off, count, "gbk")

    # 避免 Windows 控制台 GBK 编码崩溃：强制 UTF-8 输出
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print(f"Steam base=0x{steam['image_base']:X}  en_off=0x{en_off:X} "
          f"en_rva=0x{en_rva:X}")
    print(f"CHS   base=0x{chs['image_base']:X}  chs_off=0x{chs_off:X}")
    print()
    print(f"{'#':>3}  {'EN RVA':<10} {'cap':>4}  {'EN':<18} {'CHS':<16} flag")
    print("-" * 72)
    rows = []
    for i in range(min(len(en), len(cz))):
        e, c = en[i], cz[i]
        rva = en_rva + (e["off"] - en_off)
        # 中文串仍是英文原文 => 官方未翻译，需要我们补
        need = "NEED" if c["text"] == e["text"] else ""
        print(f"{i:>3}  0x{rva:08X} {e['cap']:>4}  {e['text']:<18} "
              f"{c['text']:<16} {need}")
        rows.append([i, f"0x{rva:08X}", f"0x{e['off']:08X}",
                     e["text"], e["cap"], c["text"], need])

    if csv_out:
        with open(csv_out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["index", "en_rva", "en_fileoff", "english",
                        "capacity", "chs_official", "need_translate"])
            w.writerows(rows)
        print(f"\nCSV -> {csv_out}")

    n_need = sum(1 for r in rows if r[6] == "NEED")
    print(f"\n官方已译: {len(rows) - n_need} / {len(rows)}   "
          f"待补译: {n_need}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
