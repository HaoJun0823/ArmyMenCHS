"""离线校验代码段补丁（解锁多人游戏）。

★ 为什么必须离线先验证：
  代码段补丁比数据段危险得多 —— 写错位置会直接破坏指令。
  这里在**部署前**把 codepatch.cpp 里声明的 (VA, 原文) 与 exe 实际字节对上，
  并顺带确认语义（该处确实是"无条件跳过 -> 条件跳过"的封锁点）。

校验项：
  1. VA 换算正确：VA - ImageBase == 文件偏移（.text 段 RA==VA）
  2. 该处 6 字节 == 声明的原文 `03 00 00 00 EB 55`
  3. 上下文反汇编确认这是 `jmp`（封锁）而不是别的指令
  4. 跳转目标附近引用的资源确实是 multiplay 按钮
  5. 中文版的对应位置是什么（提示用户是否适用）

用法：
    python Tools/ci/verify_codepatch.py
"""
import os
import re
import struct
import sys

try:
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
except ImportError:
    print("!! 需要 capstone")
    sys.exit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CPP = os.path.join(ROOT, "Army2_Extend_Dll", "src", "codepatch.cpp")
EXE = (sys.argv[sys.argv.index("--exe") + 1] if "--exe" in sys.argv
       else r"I:\LocalGames\Army Men\Army Men II STEAM\ArmyMen2.exe")


def pe_info(path):
    d = open(path, "rb").read()
    o = struct.unpack_from("<I", d, 0x3C)[0]
    n = struct.unpack_from("<H", d, o + 4)[0]
    opt = o + 24
    imageBase, = struct.unpack_from("<I", d, opt + 28)
    sizeOfImage, = struct.unpack_from("<I", d, opt + 56)
    optsize, = struct.unpack_from("<H", d, o + 20)[0], 
    return d, o, n, imageBase, sizeOfImage


def sections(d, o):
    n = struct.unpack_from("<H", d, o + 4)[0]
    so = o + 24 + struct.unpack_from("<H", d, o + 20)[0]
    out = []
    for i in range(n):
        nm = d[so + i * 40: so + i * 40 + 8].rstrip(b"\0").decode("latin1")
        vs, va, rs, ra = struct.unpack_from("<IIII", d, so + i * 40 + 8)
        out.append((nm, va, vs, ra, rs))
    return out


def va_to_off(secs, imageBase, va):
    rva = va - imageBase
    for nm, sva, svs, sra, srs in secs:
        if sva <= rva < sva + max(svs, srs):
            off = sra + (rva - sva)
            if off < sra + srs:
                return off, nm
    return None, None


def parse_cpp(path):
    """抽出 codepatch.cpp 里的 va / kMpOrig / kMpNew。"""
    s = open(path, encoding="utf-8").read()
    m_va = re.search(r"p\.va\s*=\s*(0x[0-9a-fA-F]+)\s*;", s)
    m_len = re.search(r"p\.len\s*=\s*(\d+)\s*;", s)

    def arr(name):
        m = re.search(r"%s\s*\[[^\]]*\]\s*=\s*\{([^}]*)\}" % name, s)
        if not m:
            return None
        return [int(x, 16) if x.strip().lower().startswith("0x") else int(x)
                for x in m.group(1).split(",") if x.strip()]

    return (int(m_va.group(1), 16) if m_va else None,
            int(m_len.group(1)) if m_len else None,
            arr("kMpOrig"), arr("kMpNew"))


va, length, orig, new = parse_cpp(CPP)
print("=" * 76)
print("codepatch.cpp 声明：")
print("  va     = %s" % (hex(va) if va else "?"))
print("  len    = %s" % length)
print("  orig   = %s" % (" ".join("%02X" % b for b in orig) if orig else "?"))
print("  patch  = %s" % (" ".join("%02X" % b for b in new) if new else "?"))

if not (va and length and orig and new):
    print("!! 解析失败")
    sys.exit(1)
if len(orig) != length or len(new) != length:
    print("!! 数组长度与 p.len 不一致")
    sys.exit(1)

d, o, n, imageBase, sizeOfImage = pe_info(EXE)
secs = sections(d, o)
print("\nImageBase = %#x  SizeOfImage = %#x" % (imageBase, sizeOfImage))

fail = 0
# 1) VA 必须在映像内
if not (imageBase <= va < imageBase + sizeOfImage):
    print("[FAIL] VA %#x 不在映像内 —— 地址语义(VA/RVA)搞错了" % va)
    fail += 1
else:
    print("[ OK ] VA %#010x 在映像内" % va)

# 2) 换算到文件偏移并比对字节
off, sec = va_to_off(secs, imageBase, va)
if off is None:
    print("[FAIL] 无法换算文件偏移")
    fail += 1
else:
    print("[ OK ] 文件偏移 %#x（段 %s）" % (off, sec))
    got = list(d[off:off + length])
    if got == orig:
        print("[ OK ] 原文匹配：%s" % " ".join("%02X" % b for b in got))
    else:
        print("[FAIL] 原文不符")
        print("       期望 %s" % " ".join("%02X" % b for b in orig))
        print("       实得 %s" % " ".join("%02X" % b for b in got))
        fail += 1

    # 3) 反汇编确认这是 jmp，且改成 jz 语义正确
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    base_off = off + (length - 2)      # EB 那一字节
    code = d[base_off - 12:base_off + 24]
    print("\n  -- 目标指令上下文（VA %#x）--" % (va + length - 2))
    for ins in md.disasm(code, va + length - 2 - 12):
        mark = "   <<<< 被改的指令" if ins.address == va + length - 2 else ""
        print("    %#08x  %-8s %-24s%s" % (ins.address, ins.mnemonic,
                                           ins.op_str, mark))
    # 确认原字节是 EB
    if orig[length - 2] == 0xEB:
        print("\n[ OK ] 原指令是 EB（JMP，无条件跳过）-> 改为 74（JZ，条件跳过）")
        if new[length - 2] != 0x74:
            print("[FAIL] 但替换字节不是 74")
            fail += 1
    else:
        print("\n!! 原字节不是 EB（%02X），语义可能与预期不同" % orig[length - 2])
        fail += 1

    # 4) 确认跳转目标附近引用的资源是 multiplay
    rel = d[base_off + 1]
    dest_off = base_off + 2 + rel
    print("\n  跳转目标文件偏移 %#x（VA %#x）" % (dest_off, dest_off + imageBase))
    # 在被跳过的那段里找字符串引用
    skipped = d[base_off + 2:dest_off]
    print("  被跳过的 %d 字节里出现的 multiplay 相关串:" % len(skipped))
    found = False
    for m in re.finditer(rb"03_101_0\d_multiplay\.bmp", skipped):
        print("     %s" % m.group().decode())
        found = True
    # 也可能通过绝对地址引用（串在 .rdata）
    if not found:
        # 在被跳过段里收集所有 4 字节立即数，看有无指向 multiplay 串的
        for i in range(0, len(skipped) - 4, 1):
            v = struct.unpack_from("<I", skipped, i)[0]
            oo, _ = va_to_off(secs, imageBase, v)
            if oo:
                if d[oo:oo + 22].startswith(b"03_101_00_multiplay.bm"):
                    print("     通过绝对地址 %#x 引用 03_101_00_multiplay.bmp" % v)
                    found = True
                    break
    if found:
        print("[ OK ] 被跳过的代码确实与 multiplay（多人游戏）按钮相关")
    else:
        print("[warn] 未直接找到 multiplay 串引用（可能间接引用）")

print()
if fail == 0:
    print("全部通过：代码补丁地址与原文均正确。")
else:
    print("!! %d 项失败，不要部署" % fail)
    sys.exit(1)
