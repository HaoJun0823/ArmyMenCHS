"""离线核对：target.cpp 里为各作登记的全局量 VA，
是否真的落在该 exe 的映像范围内（[ImageBase, ImageBase+SizeOfImage)）。

★ 这个检查直接对应那次崩溃：
   surfaceVA 我填的是 0x4FE1A8（IDA 显示值 = 绝对 VA），
   但 renderer.cpp 里读的时候又加了 ImageBase，变成 0x8FE1A8 野地址 -> 崩。

   所以"VA 必须落在映像内"这一条，恰好能同时抓出
   * 把 RVA 当 VA 填（值会偏小，落在映像外）
   * 读取时多加基址（值会偏大，落在映像外）
   这就是 RendererValidateEnv 做的事，这里在离线阶段先跑一遍。
"""
import os
import re
import struct
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
TARGET_CPP = r"G:\Projects\ArmyMenCHS\Army2_Extend_Dll\src\target.cpp"

BINS = {
    "ArmyMenII":      r"I:\LocalGames\Army Men\Army Men II STEAM\ArmyMen2.exe",
    "ArmyMenII-CHS":  r"I:\LocalGames\Army Men\玩具兵大战2\ArmyMen2.exe",
    "ToysInSpace":    r"I:\LocalGames\Army Men\Army Men - Toys in Space STEAM\ARMYMENTIS.exe",
}

# 需要核对的字段名
FIELDS = ["blitVA", "rectVA", "atlasOffsetVA", "atlasBaseVA",
          "charWidthVA", "surfaceVA", "pitchVA"]


def pe_range(path):
    with open(path, "rb") as f:
        b = f.read(0x400)
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    opt = pe + 24
    imageBase, = struct.unpack_from("<I", b, opt + 28)
    sizeOfImage, = struct.unpack_from("<I", b, opt + 56)
    return imageBase, sizeOfImage


src = open(TARGET_CPP, encoding="utf-8").read()

# 按 profile 块切分：每个 g.id = "XXX" 到下一个 g.id
blocks = []
for m in re.finditer(r'g\.id\s*=\s*"([^"]+)"', src):
    blocks.append((m.group(1), m.start()))
blocks.append((None, len(src)))

fail = 0
for i in range(len(blocks) - 1):
    gid, start = blocks[i]
    end = blocks[i + 1][1]
    body = src[start:end]
    if gid not in BINS:
        continue

    imageBase, sizeOfImage = pe_range(BINS[gid])
    hi = imageBase + sizeOfImage
    print("=" * 76)
    print("### %s   (%s)" % (gid, os.path.basename(BINS[gid])))
    print("    映像: %#010x .. %#010x" % (imageBase, hi))

    for fld in FIELDS:
        # 抓 g.<fld> = 0x....;  或  g.<fld>   = 0x....;
        # 允许 "0x41C710;" 或 "0x41C710 - RVA;" 两种写法；后者说明填的是 RVA，
        # 对"应当填绝对 VA"的字段来说是错误，必须报出来。
        m = re.search(r"g\.%s\s*=\s*(0x[0-9a-fA-F]+)(\s*-\s*RVA)?\s*;" % fld, body)
        if not m:
            print("    %-14s （未设置）" % fld)
            continue
        va = int(m.group(1), 16)
        is_rva = bool(m.group(2))
        ok = (not is_rva) and (imageBase <= va < hi)
        if not ok:
            fail += 1
        note = "OK" if ok else (
            "<!! 写成 RVA（减了 ImageBase）—— 必须写绝对 VA" if is_rva
            else "<!! 不在映像内")
        print("    %-14s = %#010x  %s" % (fld, va, note))

    # 顺带核对 hooks[] 的地址（这些填的是 VA，换算成 RVA 用）
    for m in re.finditer(r"AddHook\(g,\s*(0x[0-9a-fA-F]+),\s*(RK_\w+)", body):
        va = int(m.group(1), 16)
        rva = va - imageBase
        ok = 0 < rva < sizeOfImage
        if not ok:
            fail += 1
        print("    hook %-9s = %#010x (RVA %#x) %s"
              % (m.group(2), va, rva, "OK" if ok else "<!! 不在映像内"))

print()
if fail == 0:
    print("全部通过：登记的全局量 VA 均在各自映像范围内。")
else:
    print("!! 有 %d 项不在映像内 —— 地址语义很可能搞错了，不要部署" % fail)
    sys.exit(1)
