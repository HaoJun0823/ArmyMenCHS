import os
"""补录"难度"三项（Hard/Medium/Easy -> 难/中/易）。

为什么单独处理：
  中文版里这三个串是**单汉字**（难/中/易），而生成器要求 cjk>=2 才纳入候选，
  所以它们被过滤掉了，导致难度选择界面始终显示英文（甚至因 ASCII 路径异常而空白）。

  不能简单放宽 cjk>=2 —— 会引入大量单字噪声。
  改用**显式锚点**定位：在两版中，"alpine" 与 "02_014_00_difficulty.bmp"
  都存在且相邻，难度三项正好夹在它们之间。按槽位序号即可精确取出。

  实测对应（中文版 vs Steam）：
      alpine ... 难 / 中 / 易 ... 02_014_00_difficulty.bmp
      alpine ... Hard / Medium / Easy ... 02_014_00_difficulty.bmp
  槽位一一对应。
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_am2_strings_ini as G  # noqa

CHS = sys.argv[sys.argv.index("--chs")+1] if "--chs" in sys.argv else r"I:\LocalGames\Army Men\玩具兵大战2\ArmyMen2.exe"
STM = sys.argv[sys.argv.index("--steam")+1] if "--steam" in sys.argv else r"I:\LocalGames\Army Men\Army Men II STEAM\ArmyMen2.exe"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INI = os.path.join(ROOT, "Army2_Extend_Dll", "strings", "am2_strings.ini")

ANCHOR_BEFORE = b"alpine"
ANCHOR_AFTER = b"02_014_00_difficulty.bmp"
EXPECT = [("Hard", "难"), ("Medium", "中"), ("Easy", "易")]


def find_slot(slots, want, start=0):
    for i in range(start, len(slots)):
        if slots[i][1] == want:
            return i
    return None


def main():
    chs = open(CHS, "rb").read()
    stm = open(STM, "rb").read()
    cs, ss = G.sections(chs), G.sections(stm)
    cslots = G.slots(chs, cs)
    sslots = G.slots(stm, ss)

    # 在两侧各找一次锚点（取靠后的那组，避免命中别处）
    ci = find_slot(cslots, ANCHOR_BEFORE)
    si = find_slot(sslots, ANCHOR_BEFORE)
    if ci is None or si is None:
        print("!! 找不到锚点 'alpine'")
        return 1
    # 锚点后必须紧跟着 difficulty.bmp（中间就是难度三项）
    cj = find_slot(cslots, ANCHOR_AFTER, ci)
    sj = find_slot(sslots, ANCHOR_AFTER, si)
    if cj is None or sj is None:
        print("!! 找不到锚点 'difficulty.bmp'")
        return 1
    print("CHS   锚点: alpine@%d  difficulty@%d  中间 %d 槽"
          % (ci, cj, cj - ci))
    print("STEAM 锚点: alpine@%d  difficulty@%d  中间 %d 槽"
          % (si, sj, sj - si))

    # 中间的槽位一一对应（跳过空槽计数差异：按非空串配对）
    c_mid = [(r, b) for (r, b) in cslots[ci + 1:cj] if b]
    s_mid = [(r, b) for (r, b) in sslots[si + 1:sj] if b]
    print("\n中间槽位:")
    print("  CHS  :", [b.decode("gbk", "replace") for _, b in c_mid])
    print("  STEAM:", [b.decode("ascii", "replace") for _, b in s_mid])

    if len(c_mid) != 3 or len(s_mid) != 3:
        print("\n!! 中间槽位数不是 3，需要人工核对（不自动写入）")
        return 1

    # 逐条核对：CHS 中文必须是"难/中/易"，Steam 必须是 Hard/Medium/Easy
    ok = True
    for i, (want_en, want_zh) in enumerate(EXPECT):
        got_zh = c_mid[i][1].decode("gbk", "replace")
        got_en = s_mid[i][1].decode("ascii", "replace")
        good = (got_zh == want_zh and got_en == want_en)
        ok = ok and good
        print("  %-8s -> %-4s  %s" % (got_en, got_zh, "OK" if good else "<!! 不符"))
    if not ok:
        print("\n!! 内容不符，不写入")
        return 1

    # 写入 INI（追加到 [Strings] 末尾）
    lines = open(INI, encoding="utf-8", newline="").read().split("\n")
    # 去掉末尾空行
    while lines and not lines[-1].strip():
        lines.pop()
    lines.append("; ── 难度（单汉字，由 _am2_add_difficulty.py 用锚点定位补录；"
                 "官方中文版对应 难/中/易）──")
    for i, (want_en, want_zh) in enumerate(EXPECT):
        stm_rva = s_mid[i][0]
        gbk = want_zh.encode("gbk")
        if len(gbk) + 1 > len(want_en) + 1:
            print("!! '%s' 槽位不足（%d > %d）" % (want_en, len(gbk) + 1, len(want_en) + 1))
            return 1
        lines.append("0x%08X=%s|%s" % (stm_rva, want_en, want_zh))
    # ★ newline="" 防止 Windows 把 \n 变成 \r\n，
    #   否则 CR(0x0d) 会被当成译文的一部分写进游戏内存。
    with open(INI, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print("\n已写入 %s（+3 条）" % INI)
    return 0


if __name__ == "__main__":
    sys.exit(main())
