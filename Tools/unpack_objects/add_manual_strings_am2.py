"""补录经人工确认的单条译文（生成器词典覆盖不到的项）。

背景：
  gen_am2_strings_ini.py 用"双语词典硬闸门"保证零错译，代价是
  **词典未覆盖的串一律不收**。有些串需要人工确认后单独补录：

  1. 难度 Hard/Medium/Easy（单汉字"难/中/易"，被 cjk>=2 过滤）
     -> 由 add_difficulty_am2.py 用锚点定位处理
  2. "Play Against Computer Only"（多人菜单里的单人对抗电脑选项）
     -> 本脚本处理。中文版此处**也是英文**（且拼写错误 Againest），
        说明官方当年没翻，属于新增翻译。

每条都做容量校验（GBK 字节数 + NUL <= 原长 + NUL），超长则报错不写。

用法：
    python Tools/unpack_objects/add_manual_strings_am2.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INI = os.path.join(ROOT, "Army2_Extend_Dll", "strings", "am2_strings.ini")
STM_EXE = (sys.argv[sys.argv.index("--steam") + 1] if "--steam" in sys.argv
           else r"I:\LocalGames\Army Men\Army Men II STEAM\ArmyMen2.exe")

import struct


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


# ★ 键是 **RVA**（不是 VA）—— DLL 侧用 base + rva 定位。
#   写错成 VA 会算出映像外地址，被越界检查静默跳过（补丁不生效但不崩）。
# (RVA, 英文原文, 中文译文)
MANUAL = [
    # 多人菜单：单人对抗电脑（VA 由 xref 到 sub_40E530 确认）
    (0x00075300, "Play Against Computer Only", "仅与电脑对战"),
]


def main():
    if not os.path.isfile(STM_EXE):
        print("!! 找不到 Steam exe: %s" % STM_EXE)
        return 1
    d = open(STM_EXE, "rb").read()
    secs = sections(d)

    text = open(INI, encoding="utf-8", newline="").read()
    lines = text.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()

    added = skipped = 0
    for rva, en, zh in MANUAL:
        key = "0x%08X" % rva
        # 1) 先与 exe 实际字节核对原文（防止写错槽位）
        off = r2o(secs, rva)
        if off is None:
            print("[FAIL] %s RVA %#x 不在映像内" % (key, rva))
            continue
        e = d.find(b"\0", off, off + 1024)
        actual = d[off:e].decode("latin1") if e > 0 else ""
        if actual != en:
            print("[FAIL] %s 原文不符：期望 %r 实得 %r -> 跳过" % (key, en, actual))
            continue
        # 2) 容量校验
        gbk = zh.encode("gbk")
        if len(gbk) + 1 > len(en) + 1:
            print("[FAIL] %s 译文超长 %d > %d" % (key, len(gbk) + 1, len(en) + 1))
            continue
        # 3) 去重
        if any(l.upper().startswith(key.upper()) for l in lines):
            print("[skip] %s 已存在" % key)
            skipped += 1
            continue
        lines.append("%s=%s|%s" % (key, en, zh))
        added += 1
        print("[ OK ] 追加 %s=%s|%s  (GBK %d / 槽位 %d)"
              % (key, en, zh, len(gbk) + 1, len(en) + 1))

    with open(INI, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    total = len([l for l in open(INI, encoding="utf-8").read().split("\n")
                 if l.startswith("0x")])
    print("\n新增 %d 条，已存在 %d 条；INI 现共 %d 条" % (added, skipped, total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
