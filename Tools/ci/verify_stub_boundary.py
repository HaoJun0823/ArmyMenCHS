"""离线核对：三个渲染器的前 5 字节是否是**一条完整指令**。

★ 为什么必须查：
  我们的 hook 在函数入口写 `jmp rel32`（5 字节，另 2 字节 NOP）。
  为了让 ASCII 段还能调用"原始行为"，需要造 stub：
      <原始前 5 字节> + jmp 原函数+5
  但如果前 5 字节不是一条完整指令（例如是 3 字节指令 + 2 字节指令的一半），
  跳到 +5 就会落在指令中间 -> 崩溃。

  AM2 三个渲染器的序言实测都是 `A1 xx xx xx xx` = mov eax,[imm32]，
  正好 5 字节一条指令。本脚本用 capstone 反汇编确认（而不是靠眼看）。

用法：
    python Tools/ci/verify_stub_boundary.py
"""
import os
import re
import struct
import sys

try:
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
except ImportError:
    print("!! 需要 capstone：pip install capstone")
    sys.exit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TARGET_CPP = os.path.join(ROOT, "Army2_Extend_Dll", "src", "target.cpp")
EXE = (sys.argv[sys.argv.index("--exe") + 1] if "--exe" in sys.argv
       else r"I:\LocalGames\Army Men\Army Men II STEAM\ArmyMen2.exe")

# 期望的 3 个 AM2 Steam 渲染器
EXPECT = [(0x446930, "RK_LEFT"), (0x446AB0, "RK_DIALOG"), (0x446C50, "RK_CENTER")]
# ★ 从 target.cpp 读实际 patchLen，避免"校验器和实现不一致"的假绿。
def _read_patch_len():
    try:
        src = open(TARGET_CPP, encoding="utf-8").read()
        m = re.findall(r"g\.patchLen\s*=\s*(\d+)", src)
        if m:
            vals = {int(x) for x in m}
            if len(vals) != 1:
                print("!! target.cpp 里 patchLen 值不一致:", vals)
                sys.exit(1)
            return vals.pop()
    except Exception as e:
        print("!! 读取 patchLen 失败:", e)
        sys.exit(1)
    print("!! 没找到 patchLen 赋值")
    sys.exit(1)
PATCH_LEN = _read_patch_len()


def sections(d):
    o = struct.unpack_from("<I", d, 0x3C)[0]
    n = struct.unpack_from("<H", d, o + 4)[0]
    so = o + 24 + struct.unpack_from("<H", d, o + 20)[0]
    out = []
    for i in range(n):
        nm = d[so + i * 40: so + i * 40 + 8].rstrip(b"\0").decode("latin1")
        vs, va, rs, ra = struct.unpack_from("<IIII", d, so + i * 40 + 8)
        out.append((nm, va, vs, ra, rs))
    return out


def r2o(secs, rva):
    for nm, va, vs, ra, rs in secs:
        if va <= rva < va + max(vs, rs):
            return ra + (rva - va)
    return None


d = open(EXE, "rb").read()
secs = sections(d)
IB = 0x400000
STUB_N = 5

md = Cs(CS_ARCH_X86, CS_MODE_32)
print("=" * 74)
print("stub 边界核对（stub 采样 %d 字节后跳到原函数 +%d）" % (STUB_N, STUB_N))
print("=" * 74)

fail = 0
for va, kind in EXPECT:
    rva = va - IB
    o = r2o(secs, rva)
    if o is None:
        print("!! %s VA=%#x 不在段内" % (kind, va))
        fail += 1
        continue
    code = d[o:o + 32]
    # ★ 必须把整个窗口反汇编完，而不是"累计到 STUB_N 就停" ——
    #   否则指令列表里只有第一条，后面检查"+5 是否指令边界"必然失败
    #   （这属于校验器自身的假绿/假红，本项目已踩过两次）。
    insns = list(md.disasm(code, va))

    print("\n%s  VA=%#x" % (kind, va))
    print("  机器码: %s" % code[:8].hex(" "))
    for ins in insns:
        print("    +%-2d  %-8s %s" % (ins.address - va, ins.mnemonic, ins.op_str))

    first = insns[0] if insns else None
    first_size = first.size if first else 0
    boundary_ok = (first_size == STUB_N)

    if boundary_ok:
        print("  >> 首条指令恰好 %d 字节 -> stub 边界安全 ✓" % first_size)
    else:
        print("  >> !! 首条指令 %d 字节，不等于 %d：stub 会跳到指令中间"
              % (first_size, STUB_N))
        fail += 1

    # 顺带确认 patchLen 覆盖的字节正好是整数条指令
    if len(insns) >= 2:
        covered = 0
        for ins in insns:
            if covered + ins.size <= PATCH_LEN:
                covered += ins.size
        print("     patchLen=%d 覆盖 %d 字节 = %d 条完整指令"
              % (PATCH_LEN, covered, sum(1 for i in insns
                                          if i.address - va < covered)))
        if covered != PATCH_LEN:
            print("     >> !! patchLen=%d 不是指令边界：写 jmp 会把某条指令切成两半。"
                  % PATCH_LEN)
            print("        运行时因整段被 jmp 跳过而看不出问题，"
                  "但卸载/跳回该偏移会执行到指令中间 -> 崩溃。")
            fail += 1
        else:
            print("     >> patchLen 恰在指令边界上 ✓")

    # 再确认 stub 跳转目标（+STUB_N）也是指令边界
    starts = {i.address - va for i in insns}
    if STUB_N not in starts:
        print("     >> !! stub 跳转目标 +%d 不是指令边界" % STUB_N)
        fail += 1

print()
if fail == 0:
    print("全部通过：%d 个渲染器的前 5 字节均为一条完整指令，stub 边界安全。"
          % len(EXPECT))
else:
    print("!! %d 项有问题，stub 方案不能启用" % fail)
    sys.exit(1)
