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
    "RK_LEFT":   (0x446930, "左对齐（主渲染器 / 面板文字）"),
    "RK_DIALOG": (0x446AB0, "对话框（退出确认等）"),
    "RK_CENTER": (0x446C50, "居中文字"),
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
regs = []
for m in re.finditer(
        r"AddHook\(g,\s*(0x[0-9a-fA-F]+),\s*(RK_\w+),\s*(\w+),\s*(\w+),", src):
    addr, kind, alias_s, alias_m = m.groups()
    # 在 AddHook 之前的作用域里找别名定义
    head = src[:m.start()]
    def resolve(alias):
        mm = re.findall(r"static const BYTE\s+%s\[\]\s*=\s*(\w+)\s*;" % alias, head)
        return mm[-1] if mm else None
    regs.append((addr, kind, resolve(alias_s), resolve(alias_m), alias_s, alias_m))

print("target.cpp 里登记的 hook 目标: %d 个" % len(regs))
for a, k, s, mk, als, alm in regs:
    print("   %-11s %-11s sig=%-16s mask=%s" % (k, a, s or ("?" + als), mk or ("?" + alm)))

AM2 = [(a, k, s, mk) for (a, k, s, mk, _, _) in regs
       if s in ("SIG_AM2_STEAM", "SIG_AM2_DLG") and mk]

# ★ 断言真的检查到了条目（防止校验器空转）
if not AM2:
    print("\n!! 没有解析出任何 AM2 hook 条目 —— 校验器失效，不算通过")
    raise SystemExit(1)
print("\n将校验 %d 个 AM2 hook 目标" % len(AM2))

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
    print("全部通过：AM2 的 %d 个文字渲染器地址与签名均正确。" % len(AM2))
else:
    print("!! 有 %d 项问题，不要部署" % fail)
    raise SystemExit(1)
