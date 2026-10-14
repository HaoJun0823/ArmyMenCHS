"""离线验证：target.cpp 里为 AM2 登记的 3 个渲染器
（左对齐/对话框/居中）签名是否与 exe 实际字节一致。

上一轮实机失败的根本原因是"只 hook 了 1 个渲染器"，
这次必须**在部署前**就把 3 个签名都验过，避免又让你白跑一次。
"""
import re
import sys
import os
import struct

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TARGET_CPP = os.path.join(ROOT, "Army2_Extend_Dll", "src", "target.cpp")
EXE = sys.argv[sys.argv.index("--exe")+1] if "--exe" in sys.argv else r"I:\LocalGames\Army Men\Army Men II STEAM\ArmyMen2.exe"
IB = 0x400000

# 期望的 3 个渲染器（IDA 实测地址）
EXPECT = {
    "RK_LEFT":    (0x446930, "左对齐（主渲染器 / 面板文字）"),
    "RK_DIALOG":  (0x446AB0, "对话框（退出确认等）"),
    "RK_CENTER":  (0x446C50, "居中文字"),
    "RK_MEASURE": (0x446E00, "文本测量（汉字须按 15 计，防裁剪矩形错）"),
}

# 每个 hook 覆盖的字节数（必须落在**指令边界**上）
EXPECT_PATCHLEN = {
    0x446930: 5,   # mov eax,[0x4fdf80]   A1 imm32
    0x446AB0: 5,   # 同上
    0x446C50: 5,   # 同上
    0x446E00: 7,   # mov ecx,[esp+8]; push esi; mov edx,ecx
}


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


src = open(TARGET_CPP, encoding="utf-8").read()


def parse_macro(name):
    idx = src.find("#define " + name)
    if idx < 0:
        return None
    seg = src[idx:]
    end = seg.find("}")
    if end < 0:
        return None
    seg = seg[:end + 1].replace("\\\n", " ")
    inner = re.search(r"\{(.*)\}", seg, re.S)
    if not inner:
        return None
    out = []
    for t in inner.group(1).split(","):
        t = t.strip()
        if t:
            out.append(int(t, 16) if t.lower().startswith("0x") else int(t))
    return out


# 从 target.cpp 里抓 AddHook(g, 0xADDR, RK_XXX, <局部变量>, <局部变量>, ...)，
# 再回溯该作用域里 `static const BYTE <局部变量>[] = <宏>;` 找出真正的宏名。
#
# ★ 这里踩过一个"假绿"的坑：最初直接把第 4 个参数当宏名用，
#   而实际传的是局部别名 _sl/_sd，于是过滤条件匹配不到任何条目，
#   脚本"什么都没校验"却打印了"全部通过"。
#   凡是校验器，必须同时断言"实际检查的条目数 > 0"。
#
# ★★ 另一个坑（本轮）：target.cpp 里有**多个档位**共用一份 AddHook 代码：
#     ArmyMenII      -> Steam 英文版 exe（本脚本校验的对象）
#     ArmyMenII-CHS  -> 中文母盘 exe（地址/签名完全不同）
#     ToysInSpace    -> TIS exe
#   若不加区分地把所有 SIG_AM2_* 都拿来跟 Steam exe 比，
#   CHS 那条必然"不匹配"——那是**假红**，会掩盖真正的问题。
#   故：先按 g.id = "..." 切分档位块，只校验 Steam 档位。
regs = []
PROFILE_RE = re.compile(r'g\.id\s*=\s*"([^"]+)"')
marks = [(m.start(), m.group(1)) for m in PROFILE_RE.finditer(src)]
if not marks:
    print("!! 没能解析出任何档位（g.id = ...）—— 校验器失效")
    raise SystemExit(1)


def profile_at(pos):
    cur = None
    for p, name in marks:
        if p < pos:
            cur = name
        else:
            break
    return cur


for m in re.finditer(
        r"AddHook\(g,\s*(0x[0-9a-fA-F]+),\s*(RK_\w+),\s*(\w+),\s*(\w+),\s*"
        r"[^,]+(?:,\s*(\d+))?\s*\)", src):
    addr, kind, alias_s, alias_m, plen = m.groups()
    # 在 AddHook 之前的作用域里找别名定义
    head = src[:m.start()]
    def resolve(alias):
        mm = re.findall(r"static const BYTE\s+%s\[\]\s*=\s*(\w+)\s*;" % alias, head)
        return mm[-1] if mm else None
    regs.append((addr, kind, resolve(alias_s), resolve(alias_m),
                 alias_s, alias_m, profile_at(m.start())))

print("target.cpp 里登记的 hook 目标: %d 个" % len(regs))
for a, k, s, mk, als, alm, prof in regs:
    print("   %-12s %-11s sig=%-16s mask=%-16s [%s]"
          % (k, a, s or ("?" + als), mk or ("?" + alm), prof))

# 只取 Steam 档位（与 EXE 对应）
AM2 = [(a, k, s, mk) for (a, k, s, mk, _, _, prof) in regs
       if prof == "ArmyMenII" and s and mk]

# ★ 断言真的检查到了条目（防止校验器空转）
if not AM2:
    print("\n!! 没有解析出任何 AM2 hook 条目 —— 校验器失效，不算通过")
    raise SystemExit(1)

# ★★ 覆盖度断言（本轮新增）
#   以前这里写的是 `s in ("SIG_AM2_STEAM", "SIG_AM2_DLG")` —— 一个**白名单**。
#   于是新加的 SIG_AM2_MEASURE 被静默过滤掉，脚本照样打印"全部通过"，
#   而实际上**新增的那个 hook 一个字节都没校验**。
#   这正是"校验器空转报绿"，本项目已经栽过两次（另一次是 stub 边界校验）。
#   现在：改成按前缀匹配 + 断言期望的 hook 集合都被覆盖。
AM2_EXPECT_KINDS = {"RK_LEFT", "RK_DIALOG", "RK_CENTER", "RK_MEASURE"}
got_kinds = set(k for _, k, _, _ in AM2)
missing = AM2_EXPECT_KINDS - got_kinds
if missing:
    print("\n!! 以下 hook 类别没有被校验到: %s" % ", ".join(sorted(missing)))
    print("   校验器覆盖不全，不算通过（避免假绿）")
    raise SystemExit(1)
print("\n将校验 %d 个 AM2 hook 目标（覆盖 %d 类：%s）"
      % (len(AM2), len(got_kinds), ", ".join(sorted(got_kinds))))

d = open(EXE, "rb").read()
secs = sections(d)

fail = 0
for addr_s, kind, sig_name, msk_name in AM2:
    va = int(addr_s, 16)
    rva = va - IB
    sig = parse_macro(sig_name)
    msk = parse_macro(msk_name)
    if not sig or not msk or len(sig) != len(msk):
        print("!! %s / %s 宏解析失败或长度不一致" % (sig_name, msk_name))
        fail += 1
        continue

    o = r2o(secs, rva)
    actual = d[o:o + len(sig)] if o is not None else b""
    exp_va, desc = EXPECT.get(kind, (None, "?"))
    tag = "OK " if exp_va == va else "!! "
    if exp_va != va:
        fail += 1
    print("\n%s %-11s VA=%#x  RVA=%#x  (%s)" % (tag, kind, va, rva, desc))
    print("      用宏: %s / %s（%d 字节）" % (sig_name, msk_name, len(sig)))

    bad = []
    for i in range(len(sig)):
        if msk[i] == 0:
            continue
        if actual[i] != sig[i]:
            bad.append((i, sig[i], actual[i]))
    if bad:
        fail += 1
        print("      签名不匹配 %d 处: %s" % (
            len(bad), " ".join("+%d 期望%02X 实得%02X" % b for b in bad[:6])))
    else:
        print("      签名 %d 字节全部匹配 ✓" % len(sig))
    print("      实际序言: %s" % actual[:16].hex(" "))

print()
if fail == 0:
    print("全部通过：AM2 的 %d 个 hook 地址与签名均正确。" % len(AM2))
else:
    print("!! 有 %d 项问题，不要部署" % fail)
    raise SystemExit(1)


# ══════════════════════════════════════════════════════════════════════════
#  patchLen 指令边界校验
# ══════════════════════════════════════════════════════════════════════════
#  ★ 为什么必须单独查：
#    hook 的做法是在函数入口写 `jmp rel32`（5 字节），覆盖 patchLen 个字节。
#    若 patchLen 落在一條指令中间，stub 会把半条指令复制走，
#    再 jmp 到 +patchLen —— 等于从指令中间开始执行，必崩。
#    本项目的血泪史：patchLen=7 把 `sub esp,0x2c` 切成两半。
#
#    现在测量函数用 7（三条完整指令），渲染器用 5（一条），
#    两个值都必须逐字节验证，不能凭记忆。
try:
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
except ImportError:
    print("\n!! 缺少 capstone，无法校验 patchLen 边界（不算通过）")
    raise SystemExit(1)

print("\n" + "=" * 70)
print("patchLen 指令边界校验")
print("=" * 70)

md = Cs(CS_ARCH_X86, CS_MODE_32)
bounds_fail = 0
for addr_s, kind, sig_name, msk_name in AM2:
    va = int(addr_s, 16)
    rva = va - IB
    o = r2o(secs, rva)
    want = EXPECT_PATCHLEN.get(va)
    if want is None:
        print("  ?? %-11s VA=%#x 未登记期望 patchLen" % (kind, va))
        bounds_fail += 1
        continue

    # 线性反汇编，累积到 >= want，检查是否**恰好**落在边界
    raw = d[o:o + 32]
    acc = 0
    hit = None
    for ins in md.disasm(raw, va):
        acc += ins.size
        if acc == want:
            hit = ins
            break
        if acc > want:
            break

    if hit is None:
        print("  [FAIL] %-11s VA=%#x patchLen=%d **不在指令边界上**"
              % (kind, va, want))
        bounds_fail += 1
        continue

    # 打印覆盖的指令，便于人工复核
    acc2 = 0
    covered = []
    for ins in md.disasm(raw, va):
        acc2 += ins.size
        covered.append("%s %s" % (ins.mnemonic, ins.op_str))
        if acc2 >= want:
            break
    print("  [ OK ] %-11s VA=%#x patchLen=%d  = %s"
          % (kind, va, want, " ; ".join(covered)))

if bounds_fail:
    print("\n!! patchLen 边界校验失败 %d 项，不要部署" % bounds_fail)
    raise SystemExit(1)
print("\n全部通过：patchLen 均落在指令边界上。")
