"""列出 PE 的导入 DLL 与文件相关函数。"""
import struct
import sys


def main():
    p = sys.argv[1] if len(sys.argv) > 1 else \
        r"I:\LocalGames\Army Men\Army Men I STEAM\Armymen.exe"
    b = open(p, "rb").read()
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    nsec = struct.unpack_from("<H", b, pe + 6)[0]
    optsz = struct.unpack_from("<H", b, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", b, opt)[0]
    dd = opt + (96 if magic == 0x10B else 112)

    # DataDirectory[1] = Import Table
    imp_rva = struct.unpack_from("<I", b, dd + 8)[0]

    secs = []
    so = opt + optsz
    for i in range(nsec):
        q = so + i * 40
        secs.append((struct.unpack_from("<I", b, q + 12)[0],   # VirtualAddress
                     struct.unpack_from("<I", b, q + 8)[0],    # VirtualSize
                     struct.unpack_from("<I", b, q + 20)[0]))  # PointerToRawData

    def r2o(rva):
        for va, vs, ro in secs:
            if va <= rva < va + max(vs, 1):
                return ro + (rva - va)
        return None

    KEY = ("fopen", "CreateFile", "ReadFile", "_open", "OpenFile",
           "GetFileAttributes", "FindFirstFile", "mmioOpen",
           "LoadImage", "LoadBitmap", "SetCurrentDirectory", "GetCurrentDirectory")

    o = r2o(imp_rva)
    print(f"import dir RVA=0x{imp_rva:X} -> off 0x{o:X}")
    print()
    while True:
        if o is None or o + 20 > len(b):
            break
        name_rva, _, _, first = struct.unpack_from("<IIII", b, o)
        if name_rva == 0:
            break
        no = r2o(name_rva)
        dll = b[no:no + 64]
        dll = dll[:dll.index(b"\0")].decode()
        thunk = r2o(first)
        funcs = []
        while thunk and thunk + 4 <= len(b):
            v = struct.unpack_from("<I", b, thunk)[0]
            if v == 0:
                break
            if not (v & 0x80000000):
                nr = r2o(v)
                if nr:
                    s = b[nr + 2:nr + 80]
                    z = s.find(b"\0")
                    if z >= 0:
                        funcs.append(s[:z].decode("ascii", "replace"))
            thunk += 4
        hits = [f for f in funcs if any(k in f for k in KEY)]
        line = f"  {dll:<18} {len(funcs):3} 函数"
        if hits:
            line += f"   文件相关: {', '.join(hits)}"
        print(line)
        o += 20


if __name__ == "__main__":
    main()
