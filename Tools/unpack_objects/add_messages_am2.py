"""补录 POWER-UPS 与通讯消息。

★ 问题 1：POWER-UPS 漏译
  宝物/单位表的**真实首项名称指针在 0x865D8**（POWER-UPS），
  而 add_unit_names_am2.py 把 TBL_FIRST 设在 0x865FC（Random Power-up），
  相差正好一条 0x24 字节 → POWER-UPS 整条被跳过。
  修：把 TBL_FIRST 改为 0x865D8。

★ 问题 2：通讯消息未汉化
  STEAM 0x871DC..0x87400 是多人游戏的通讯/状态消息。
  中文版**有完整译文**，但字符串池布局不同（中文更短），
  固定偏移法失败（我试过 0x204，只有前两条对）。
  正确做法：按**语义**逐条配对（内容已人工核对）。

容量以 DLL 实际规则为准：len(GBK)+1 <= len(英文)+1。

用法：
    python Tools/unpack_objects/add_messages_am2.py
"""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INI = os.path.join(ROOT, "Army2_Extend_Dll", "strings", "am2_strings.ini")

STEAM = (sys.argv[sys.argv.index("--steam") + 1] if "--steam" in sys.argv
         else r"I:\LocalGames\Army Men\Army Men II STEAM\ArmyMen2.exe")
CHS = (sys.argv[sys.argv.index("--chs") + 1] if "--chs" in sys.argv
       else r"I:\LocalGames\Army Men\玩具兵大战2\ArmyMen2.exe")

IB = 0x400000

# 通讯消息按语义配对：(STEAM RVA, CHS RVA)
#   ★ 用语义配对而非固定偏移 —— 中文长度不同，池中并非等距排布。
MSG_PAIRS = [
    (0x871DC, 0x86FD8),   # Host is ready...      创建者就绪，等待各玩家按就绪按钮。
    (0x87210, 0x86FFC),   # Not everybody...      版本／地图／规则没有统一。
    (0x87240, 0x87018),   # %s is ready.          %s准备就绪。
    (0x87250, 0x87028),   # Game type changed     创建者改变游戏类型。
    (0x8726C, 0x87040),   # Map changed           创建者改变地图。
    (0x87284, 0x87054),   # damaged map           %s的地图坏了。
    (0x8729C, 0x87064),   # damaged rules file    %s的规则文件坏了。
    (0x872BC, 0x87078),   # damaged installation  %s的安装坏了。
    (0x872DC, 0x87088),   # does not have map     %s没有地图。
    (0x872F4, 0x87098),   # does not have rules   %s没有游戏规则。
    (0x873A4, 0x87144),   # Options changed       创建者改变选项。
    (0x873DC, 0x8717C),   # -- Computer --        计算机
    (0x873EC, 0x87184),   # Not responding%s      没有响应%s
]


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
            o = ra + (rva - va)
            if o < ra + rs:
                return o
    return None


def get(d, secs, rva, limit=256):
    o = r2o(secs, rva)
    if o is None:
        return None
    e = d.find(b"\0", o, o + limit)
    return d[o:e] if e > 0 else None


def escape(s):
    if not s:
        return s
    lead = len(s) - len(s.lstrip(" "))
    trail = len(s) - len(s.rstrip(" "))
    if lead == 0 and trail == 0:
        return s
    core = s[lead:len(s) - trail] if trail else s[lead:]
    return "\\x20" * lead + core + "\\x20" * trail


def main():
    for p in (STEAM, CHS):
        if not os.path.isfile(p):
            print("!! 找不到 %s" % p)
            return 1
    stm = open(STEAM, "rb").read()
    chs = open(CHS, "rb").read()
    ss, cs = sections(stm), sections(chs)

    text = open(INI, encoding="utf-8", newline="").read()
    lines = text.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    existing = {l.split("=", 1)[0].upper() for l in lines if l.startswith("0x")}

    added = skipped = failed = 0
    for s_rva, c_rva in MSG_PAIRS:
        en = get(stm, ss, s_rva)
        zh = get(chs, cs, c_rva)
        if not en or not zh:
            print("[FAIL] %#010x 取串失败" % s_rva)
            failed += 1
            continue
        e = en.decode("latin1")
        try:
            z = zh.decode("gbk")
        except Exception:
            print("[FAIL] %#010x 中文版非 GBK" % s_rva)
            failed += 1
            continue
        key = "0x%08X" % s_rva
        if key.upper() in existing:
            skipped += 1
            continue
        cap = len(en) + 1
        need = len(z.encode("gbk")) + 1
        if need > cap:
            print("[FAIL] %s %-34s -> %-16s 需 %d > 容量 %d"
                  % (key, e[:33], z[:15], need, cap))
            failed += 1
            continue
        lines.append("%s=%s|%s" % (key, escape(e), z))
        existing.add(key.upper())
        added += 1
        print("[ OK ] %s %-34s -> %s" % (key, e[:33], z))

    with open(INI, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    total = len([l for l in open(INI, encoding="utf-8").read().split("\n")
                 if l.startswith("0x")])
    print()
    print("新增 %d，已存在 %d，失败 %d；INI 现共 %d 条"
          % (added, skipped, failed, total))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
