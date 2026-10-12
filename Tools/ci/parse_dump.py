"""
解析 Windows minidump（.dmp）—— 修正版。

要点（实测得出）：
  1. 线程的 Context RVA 是 **dump 文件内的偏移**，直接 seek 读，不经内存映射。
  2. i386 CONTEXT 关键字段偏移（MINIDUMP 用的 DECLSPEC_ALIGN(8) 布局）：
       ContextFlags 0x00, Dr0..Dr7 0x04..0x18, FloatSave 0x1C(112B),
       SegGs..SegDs 0x8C..0x98, Edi 0x9C, Esi 0xA0, Ebx 0xA4, Edx 0xA8,
       Ecx 0xAC, Eax 0xB0, Ebp 0xB4, Eip 0xB8, SegCs 0xBC, EFlags 0xC0,
       Esp 0xC4, SegSs 0xC8
  3. 栈内存要走 MemoryList(5) 按虚拟地址查，不是 Memory64List(9)。

用法：python parse_dump.py <dump> [--limit N]
"""

import struct
import sys

STREAM_THREAD_LIST = 3
STREAM_MODULE_LIST = 4
STREAM_MEMORY_LIST = 5
STREAM_EXCEPTION = 6
STREAM_SYSTEM_INFO = 7
STREAM_MISC_INFO = 15


class Dump:
    def __init__(self, path):
        self.f = open(path, "rb")
        f = self.f
        sig, ver, n, rva, chk, ts, fl = struct.unpack("<4sIIIIIQ", f.read(32))
        if sig not in (b"MDMP", b"PMDM"):
            raise ValueError(f"bad signature {sig!r}")
        self.nstreams = n
        f.seek(rva)
        self.dirs = []
        for _ in range(n):
            t, s, r = struct.unpack("<III", f.read(12))
            self.dirs.append((t, s, r))
        self.mods = self._modules()
        self.mem = self._memory()
        self.threads = self._threads()

    def _stream(self, t):
        for a, b, c in self.dirs:
            if a == t:
                return b, c
        return None

    def _modules(self):
        got = self._stream(STREAM_MODULE_LIST)
        if not got:
            return []
        _, mr = got
        f = self.f
        f.seek(mr)
        n, = struct.unpack("<I", f.read(4))
        out = []
        for i in range(n):
            f.seek(mr + 4 + i * 108)
            base, size, chk, ts, nr = struct.unpack("<QIIII", f.read(24))
            f.seek(nr)
            ln, = struct.unpack("<I", f.read(4))
            raw = f.read(ln)
            try:
                name = raw.decode("utf-16-le")
            except Exception:
                name = raw.decode("latin1", "replace")
            name = name.split("\\")[-1]
            out.append((base, size, name))
        return out

    def _memory(self):
        got = self._stream(STREAM_MEMORY_LIST)
        if not got:
            return []
        _, mr = got
        f = self.f
        f.seek(mr)
        n, = struct.unpack("<I", f.read(4))
        out = []
        for _ in range(n):
            st, sz, rr = struct.unpack("<QII", f.read(16))
            out.append((st, sz, rr))
        return out

    def _threads(self):
        got = self._stream(STREAM_THREAD_LIST)
        if not got:
            return []
        _, tr = got
        f = self.f
        f.seek(tr)
        n, = struct.unpack("<I", f.read(4))
        out = []
        for i in range(n):
            f.seek(tr + 4 + i * 48)
            (tid, susp, pc, pr, teb, ss, sz, srva, cs, crva) = \
                struct.unpack("<IIIIQQIIII", f.read(48))
            out.append({"tid": tid, "stack_start": ss, "stack_size": sz,
                        "ctx_size": cs, "ctx_off": crva})
        return out

    def ctx_bytes(self, th):
        self.f.seek(th["ctx_off"])
        return self.f.read(th["ctx_size"])

    def rd(self, addr, length):
        """按虚拟地址从 MemoryList 读。"""
        for st, sz, rr in self.mem:
            if st <= addr < st + sz:
                off = addr - st
                avail = min(length, sz - off)
                self.f.seek(rr + off)
                return self.f.read(avail)
        return b""

    def mod_of(self, addr):
        if addr == 0:
            return "NULL"
        for b, s, n in self.mods:
            if b <= addr < b + max(s, 1):
                return f"{n}+0x{addr - b:X}"
        return "?"


def parse_ctx_i386(ctx):
    if len(ctx) < 0xCC:
        return None
    flags, = struct.unpack_from("<I", ctx, 0)
    edi, esi, ebx, edx, ecx, eax, ebp, eip, cs, efl, esp, ss = \
        struct.unpack_from("<IIIIIIIIIIII", ctx, 0x9C)
    return {"flags": flags, "edi": edi, "esi": esi, "ebx": ebx, "edx": edx,
            "ecx": ecx, "eax": eax, "ebp": ebp, "eip": eip,
            "cs": cs, "eflags": efl, "esp": esp, "ss": ss}


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 30
    d = Dump(args[0])

    print(f"streams={d.nstreams} modules={len(d.mods)} "
          f"mem={len(d.mem)} threads={len(d.threads)}")

    got = d._stream(STREAM_SYSTEM_INFO)
    if got:
        sz, r = got
        d.f.seek(r)
        b = d.f.read(sz)
        arch, lvl, rev, ncpu, pt, major, minor, build, plat = \
            struct.unpack_from("<HHHBBIIII", b, 0)
        print(f"OS: {major}.{minor} build {build}  ncpu={ncpu} arch={arch}")

    got = d._stream(STREAM_EXCEPTION)
    if got:
        sz, r = got
        d.f.seek(r)
        b = d.f.read(sz)
        # MINIDUMP_EXCEPTION_STREAM:
        #   ULONG32 ThreadId          @0
        #   ULONG32 __alignment       @4
        #   MINIDUMP_EXCEPTION        @8   <- 内含 64 位字段!
        #     ULONG32 ExceptionCode        +0
        #     ULONG32 ExceptionFlags       +4
        #     ULONG64 ExceptionRecord      +8
        #     ULONG64 ExceptionAddress     +16
        #     ULONG32 NumberParameters     +24
        #     ULONG32 __unusedAlignment    +28
        #     ULONG64 ExceptionInformation[15]  +32
        #   MINIDUMP_LOCATION_DESCRIPTOR ThreadContext @160
        tid, _ = struct.unpack_from("<II", b, 0)
        base = 8
        code = struct.unpack_from("<I", b, base + 0)[0]
        eflags = struct.unpack_from("<I", b, base + 4)[0]
        exc_rec = struct.unpack_from("<Q", b, base + 8)[0]
        addr = struct.unpack_from("<Q", b, base + 16)[0]
        nparam = struct.unpack_from("<I", b, base + 24)[0]
        info = [struct.unpack_from("<Q", b, base + 32 + 8 * i)[0]
                for i in range(min(nparam, 15))]
        ctx_size, ctx_rva = struct.unpack_from("<II", b, 160)
        addr &= 0xFFFFFFFF          # 32 位进程，取低 32 位

        print()
        print("=" * 72)
        print(f"异常代码 : 0x{code:08X}")
        print(f"异常地址 : 0x{addr:08X}   {d.mod_of(addr)}")
        print(f"线程     : {tid}")
        print(f"上下文   : size={ctx_size} fileoff=0x{ctx_rva:X}")
        if code == 0xC0000005:
            op = {0: "读", 1: "写", 8: "执行"}.get(info[0] if info else -1, "?")
            tgt = info[1] if len(info) > 1 else 0
            print(f"参数     : {[hex(x) for x in info]}")
            print(f"          -> 访问违例：试图{op}地址 0x{tgt:08X}")
        # 崩溃线程的上下文
        for th in d.threads:
            if th["tid"] != tid:
                continue
            ctx = parse_ctx_i386(d.ctx_bytes(th))
            if not ctx:
                print("  (拿不到 i386 上下文)")
                break
            print()
            print(f"EIP=0x{ctx['eip']:08X}  {d.mod_of(ctx['eip'])}")
            print(f"ESP=0x{ctx['esp']:08X}  EBP=0x{ctx['ebp']:08X}")
            print(f"EAX=0x{ctx['eax']:08X}  EBX=0x{ctx['ebx']:08X}  "
                  f"ECX=0x{ctx['ecx']:08X}  EDX=0x{ctx['edx']:08X}")
            print(f"ESI=0x{ctx['esi']:08X}  EDI=0x{ctx['edi']:08X}")

            print()
            print("EBP 链回溯:")
            cur = ctx["ebp"]
            seen = set()
            for i in range(limit):
                if cur == 0 or cur in seen or cur < 0x1000:
                    break
                seen.add(cur)
                fr = d.rd(cur, 8)
                if len(fr) < 8:
                    print(f"  #{i:02d} EBP=0x{cur:08X} 读取失败")
                    break
                prev, ret = struct.unpack("<II", fr)
                print(f"  #{i:02d} ret=0x{ret:08X}  {d.mod_of(ret)}")
                if prev <= cur:
                    break
                cur = prev

            print()
            print("栈扫描（ESP 起，模块内地址）:")
            raw = d.rd(ctx["esp"], 0x800)
            c = 0
            for o in range(0, len(raw) - 4, 4):
                v = struct.unpack_from("<I", raw, o)[0]
                nm = d.mod_of(v)
                if nm != "?":
                    print(f"  [esp+0x{o:03X}] 0x{v:08X}  {nm}")
                    c += 1
                    if c >= limit:
                        break
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
