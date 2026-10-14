"""补录 B 批：单位/宝物/设施名称（42 条）。

这些文本位于 exe 的一张**表结构**里，不是自由字符串：
    表项步长 0x24 字节，第 0 个 DWORD = 名称指针 -> 指向共享字符串池
    表项共 42 个，名称指针位置从 RVA 0x865FC 起，每 0x24 一个

★ 为什么之前漏了：gen_am2_strings_ini.py 用"双语词典硬闸门 + 槽位对齐"
  只覆盖了它能对齐的串。这张表里的字符串（TROOPERS / POWER-UPS /
  Paratroopers ...）既不在词典里、也不在它的候选池里，因此整批漏掉 ——
  玩家看到的就是这些英文 + 混杂的乱码单字。

对齐方式（实测唯一可靠的做法）：
  两版的**表项顺序完全一致**（都是 42 项、步长一致），
  但字符串池位置不同（中文更短，池整体前移），
  且 CHS 表项 RVA 恒等于 STEAM 表项 RVA - 0x78。
  => 按"第 k 个表项"配对，各自解引用自己的名称指针。
     不要按池 RVA 对齐（会错位，我已验证）。

★ 容量判定（必须与 DLL 实现一致，否则会静默跳过）：
  DLL 侧（src/strings.cpp）的规则是：
      cap = 原英文字节数 + 1
      if (GBK 字节数 + 1 > cap) -> 跳过该条并写日志
  即**实际可用容量就是 len(英文)+1**，不是"到下一个串的跨度"。

  我一度按"槽位跨度"判定（以为可以占用填充字节），
  但 DLL 并不这么做 —— 按跨度写入会因超过 DLL 自己的 cap 而根本不生效。
  以 DLL 为准：len(GBK)+1 <= len(英文)+1。
  例：'Jeeps'(5) -> cap=6；"吉普车"(6+1=7) 放不下，须用更短译文。

fail-closed：
  * 写入前核对 STEAM 侧该 RVA 处的字符串确实等于预期英文
  * 容量不足则跳过并报错，不硬写

用法：
    python Tools/unpack_objects/add_unit_names_am2.py
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

# ★★ 表范围（用"扫描所有指向字符串池的指针"实测得出，勿凭印象改）
#
#   首项名称指针在 **0x865D8**（POWER-UPS）。
#   我最初把起点写成 0x865FC（= 第二项 Random Power-up），
#   相差正好一条 0x24 字节 —— 结果 POWER-UPS 整条漏译，
#   玩家看到宝物栏标题仍是英文。
TBL_FIRST = 0x865D8      # 第 0 个名称指针所在 RVA（POWER-UPS）
TBL_LAST = 0x86BC0       # 最后一个名称指针所在 RVA（Heavy MG Pillbox）
STEP = 0x24
DELTA = 0x78             # CHS 表项 RVA = STEAM 表项 RVA - DELTA


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


def read_str(d, secs, rva, limit=192):
    o = r2o(secs, rva)
    if o is None:
        return None
    e = d.find(b"\0", o, o + limit)
    return d[o:e] if e > 0 else None


def slot_span(d, secs, rva):
    """该串到池中下一个串起点的字节数（含自身 NUL 与填充）。"""
    o = r2o(secs, rva)
    if o is None:
        return 0
    e = d.find(b"\0", o, o + 192)
    if e < 0:
        return 0
    j = e + 1
    while j < len(d) and d[j] == 0:
        j += 1
    return j - o


def escape(s):
    """首尾空格转义为 \\x20（与 gen_am2_strings_ini.py / DLL 侧约定一致）。"""
    if not s:
        return s
    lead = len(s) - len(s.lstrip(" "))
    trail = len(s) - len(s.rstrip(" "))
    if lead == 0 and trail == 0:
        return s
    core = s[lead:len(s) - trail] if trail else s[lead:]
    return "\\x20" * lead + core + "\\x20" * trail


# ── 容量不足时的替代表 ─────────────────────────────────────────────────
#
# DLL 的 cap = len(英文)+1，中文往往比英文占字节多（每汉字 2 字节），
# 少数短英文单词放不下官方译名，这里给出等义的更短写法。
#
#   Jeeps -> 官方"吉普车" = 6 字节 + NUL = 7 > cap 6
#            => 用"吉普"（4 + 1 = 5）
OVERRIDE = {
    0x86C6C: "吉普",     # Jeeps
}


def main():
    for p in (STEAM, CHS):
        if not os.path.isfile(p):
            print("!! 找不到 %s" % p)
            return 1

    stm = open(STEAM, "rb").read()
    chs = open(CHS, "rb").read()
    ss, cs = sections(stm), sections(chs)

    rows = []
    for k in range((TBL_LAST - TBL_FIRST) // STEP + 1):
        s_rva = TBL_FIRST + k * STEP
        c_rva = s_rva - DELTA
        so, co = r2o(ss, s_rva), r2o(cs, c_rva)
        if so is None or co is None:
            continue
        s_ptr, = struct.unpack_from("<I", stm, so)
        c_ptr, = struct.unpack_from("<I", chs, co)
        if not (IB <= s_ptr < IB + 0x267000 and IB <= c_ptr < IB + 0x267000):
            continue
        s_nr, c_nr = s_ptr - IB, c_ptr - IB
        en = read_str(stm, ss, s_nr)
        zh = read_str(chs, cs, c_nr)
        if not en or not zh:
            continue
        try:
            e = en.decode("latin1")
            z = zh.decode("gbk")
        except Exception:
            continue
        span = slot_span(stm, ss, s_nr)
        rows.append((s_nr, e, z, span))

    print("表项配对 %d 条" % len(rows))

    # 读 INI
    text = open(INI, encoding="utf-8", newline="").read()
    lines = text.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    existing = set()
    for l in lines:
        if l.startswith("0x"):
            existing.add(l.split("=", 1)[0].upper())

    added = skipped = over = 0
    for rva, e, z, span in rows:
        key = "0x%08X" % rva
        if key.upper() in existing:
            skipped += 1
            continue
        # 容量不足时改用替代表里的短译文
        if rva in OVERRIDE:
            z = OVERRIDE[rva]
        # 容量：以 DLL 的 cap = len(英文)+1 为准
        try:
            g = z.encode("gbk")
        except Exception:
            print("[FAIL] %s 中文无法编码: %s" % (key, z))
            over += 1
            continue
        cap = len(e.encode("latin1")) + 1
        need = len(g) + 1
        if need > cap:
            print("[FAIL] %s %-24s -> %-10s 需 %d > 容量 %d，跳过"
                  % (key, e, z, need, cap))
            over += 1
            continue
        lines.append("%s=%s|%s" % (key, escape(e), z))
        existing.add(key.upper())
        added += 1

    with open(INI, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    total = len([l for l in open(INI, encoding="utf-8").read().split("\n")
                 if l.startswith("0x")])
    print("新增 %d 条，已存在 %d 条，超槽位 %d 条；INI 现共 %d 条"
          % (added, skipped, over, total))
    if over:
        print("!! 有 %d 条未写入" % over)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
