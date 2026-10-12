"""
解析 .AMM 地图文件的 chunk 结构，提取脚本文件名等元数据。

chunk ID（Map.cpp:495-507）：
    TILE 0x454C4954   地图格数据
    DESC 0x43534544   描述
    TRIG 0x47495254   触发器
    PADS 0x53444150   停机坪
    AFIL 0x4C494641   任务脚本文件名
    OFIL 0x4C49464F   对象脚本文件名
    PFIL 0x4C494650   （同类）

.AMM 结构（Map.cpp:1120+ 的读取循环）：
    DWORD chunk_id
    DWORD chunk_size
    BYTE  data[chunk_size]

用法：
    python parse_amm.py <map.AMM> [--strings]
"""

import sys
import struct

CHUNKS = {
    0x454C4954: "TILE",
    0x43534544: "DESC",
    0x47495254: "TRIG",
    0x53444150: "PADS",
    0x4C494641: "AFIL",
    0x4C49464F: "OFIL",
    0x4C494650: "PFIL",
}


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    path = args[0]
    show_strings = "--strings" in args

    with open(path, "rb") as f:
        buf = f.read()

    print(f"file : {path}")
    print(f"size : {len(buf)}")
    print()
    print(f"{'#':>3} {'off':>10} {'chunk':>6} {'id':>10} {'size':>10}  preview")
    print("-" * 72)

    p = 0
    idx = 0
    found_files = []
    while p + 8 <= len(buf):
        cid, csize = struct.unpack_from("<II", buf, p)
        name = CHUNKS.get(cid)
        if name is None:
            # 未知 id：可能是数据开始（非 chunk 结构），尝试跳过
            print(f"{idx:>3} 0x{p:08X} {'????':>6} 0x{cid:08X} {csize:>10}  "
                  f"<未知 chunk，停止>")
            break
        data = buf[p + 8:p + 8 + csize]
        preview = ""
        if name in ("AFIL", "OFIL", "PFIL", "DESC"):
            z = data.find(b"\0")
            s = data[:z] if z >= 0 else data
            preview = repr(s.decode("ascii", "replace"))
            found_files.append((name, preview))
        else:
            preview = data[:8].hex()
        print(f"{idx:>3} 0x{p:08X} {name:>6} 0x{cid:08X} {csize:>10}  {preview}")
        p += 8 + csize
        idx += 1
        if idx > 40:
            print("... (超过 40 个 chunk，停止)")
            break

    print()
    if found_files:
        print("脚本文件名:")
        for n, v in found_files:
            print(f"  {n} = {v}")
    if show_strings:
        print()
        print("全文件可打印字符串:")
        cur = bytearray()
        start = 0
        for i, c in enumerate(buf):
            if 32 <= c < 127:
                if not cur:
                    start = i
                cur.append(c)
            else:
                if len(cur) >= 4:
                    print(f"  0x{start:06X}: {cur.decode('ascii')}")
                cur = bytearray()
        if len(cur) >= 4:
            print(f"  0x{start:06X}: {cur.decode('ascii')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
