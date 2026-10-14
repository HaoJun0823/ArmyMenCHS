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

# AM2 Steam 的全部 hook（含本轮新增的文本测量）。
#
# ★ 这里以前是硬编码 3 个渲染器 + 固定 patchLen/STUB_N=5。
#   加了 RK_MEASURE（patchLen=7）之后，那种写法会**漏掉新 hook**，
#   而且就算不遗漏也会用错的长度去核对 —— 属于"校验器与实现脱节"。
#   现在改为从 target.cpp 里解析 Steam 档位的 AddHook 调用（含 patchLen）。
PROFILE_ID = "ArmyMenII"          # 只取 Steam 档位（与 EXE 对应）


def _read_hooks():
    """从 target.cpp 解析 Steam 档位的 (va, kind, patchLen)。"""
    src = open(TARGET_CPP, encoding="utf-8").read()

    # 定位每个档位块的起止（g.id = "xxx" 到下一条 g.id 或 v.push_back）
    marks = [(m.start(), m.group(1))
             for m in re.finditer(r'g\.id\s*=\s*"([^"]+)"', src)]
    if not marks:
        print("!! 没能解析出任何档位（g.id = ...）")
        sys.exit(1)

    def profile_at(pos):
        cur = None
        for p, name in marks:
            if p < pos:
                cur = name
            else:
                break
        return cur

    out = []
    # 形如：AddHook(g, 0x446E00, RK_MEASURE, _sm, _mm, (int)sizeof(_sm), 7);
    # 第 6 参（patchLen）可省略（AddHook 形参默认 5）。
    # ★ 第 5 参是 `(int)sizeof(_sl)` —— 含**嵌套括号**，
    #   用 `\([^)]*\)` 会在第一个 ')' 处提前结束导致整条匹配失败。
    #   改用 `[^,]+`（参数字段里不会出现逗号）。
    pat = re.compile(
        r"AddHook\(g,\s*(0x[0-9a-fA-F]+),\s*(RK_\w+),\s*\w+,\s*\w+,\s*"
        r"[^,]+(?:,\s*(\d+))?\s*\)")
    for m in pat.finditer(src):
        if profile_at(m.start()) != PROFILE_ID:
            continue
        va = int(m.group(1), 16)
        kind = m.group(2)
        plen = int(m.group(3)) if m.group(3) else 5   # 默认 5（AddHook 形参默认值）
        out.append((va, kind, plen))
    return out


HOOKS = _read_hooks()
if not HOOKS:
    print("!! 没解析出 %s 档位的 hook —— 校验器失效，不算通过" % PROFILE_ID)
    sys.exit(1)

# 覆盖度断言：这几类都必须被校验到（防止新增 hook 被静默漏掉）
EXPECT_KINDS = {"RK_LEFT", "RK_DIALOG", "RK_CENTER", "RK_MEASURE"}
_missing = EXPECT_KINDS - {k for _, k, _ in HOOKS}
if _missing:
    print("!! 以下 hook 类别没被校验到: %s" % ", ".join(sorted(_missing)))
    sys.exit(1)

print("从 target.cpp 解析到 %s 档位 %d 个 hook："
      % (PROFILE_ID, len(HOOKS)))
for va, kind, plen in HOOKS:
    print("   VA=%#010x %-11s patchLen=%d" % (va, kind, plen))


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

md = Cs(CS_ARCH_X86, CS_MODE_32)
print("=" * 74)
print("stub 边界核对（每个 hook 用自己的 patchLen，stub 即复制这么长）")
print("=" * 74)

fail = 0
for va, kind, len_ in HOOKS:
    rva = va - IB
    o = r2o(secs, rva)
    if o is None:
        print("!! %s VA=%#x 不在段内" % (kind, va))
        fail += 1
        continue
    code = d[o:o + 48]
    # ★ 必须把整个窗口反汇编完，而不是"累计到 patchLen 就停" ——
    #   否则指令列表里只有第一条，后面检查"是否指令边界"必然失败
    #   （这属于校验器自身的假绿/假红，本项目已踩过两次）。
    insns = list(md.disasm(code, va))

    print("\n%s  VA=%#x  patchLen=%d" % (kind, va, len_))
    print("  机器码: %s" % code[:12].hex(" "))
    acc = 0
    for ins in insns:
        if acc >= len_ + 8:
            break
        mark = ""
        acc += ins.size
        if acc == len_:
            mark = "   <== patchLen 边界"
        elif acc > len_:
            mark = "   <== !! patchLen 切在这条指令中间"
        print("    +%-2d  %-8s %-28s%s"
              % (ins.address - va, ins.mnemonic, ins.op_str, mark))

    # 逐条累加，检查 patchLen 是否恰好落在某条指令结束后
    starts = {0}
    acc = 0
    for ins in insns:
        acc += ins.size
        starts.add(acc)

    if len_ in starts:
        print("  >> patchLen=%d 恰在指令边界上 ✓" % len_)
    else:
        print("  >> !! patchLen=%d **不是**指令边界：写 jmp 会把某条指令切成两半。"
              % len_)
        print("     运行时因整段被 jmp 跳过而看不出问题，"
              "但 stub 会复制半条指令 -> 从中间执行 -> 崩溃。")
        fail += 1

    # stub 复制 len_ 字节后跳到 +len_，该偏移也必须是边界（同上条件）

print()
if fail == 0:
    print("全部通过：%d 个 hook 的 patchLen 均落在指令边界上，stub 方案安全。"
          % len(HOOKS))
else:
    print("!! %d 项有问题，stub 方案不能启用" % fail)
    sys.exit(1)
