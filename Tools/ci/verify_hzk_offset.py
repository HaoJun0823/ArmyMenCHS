# -*- coding: utf-8 -*-
"""Hzk16 字形偏移公式的**判据性**回归测试。

★ 为什么要有这个脚本：
  第 1 轮：我"离线验证"公式时，拿噪声点阵当成了工整字形（目视误判）。
  第 2 轮：一个子代理分析后主张"缺 dataStart，所有字都读错"，
           并给出看似严谨的推导 —— 但结论是错的。
  两轮都是**判据太弱**：汉字在 13x13 里"看着都像字"，
  而"墨迹量在 8..110"更是随便一段数据都能满足。

★ 本脚本用不可辩驳的判据：**GB2312 第 3 区的全角 ASCII**。
      Ａ-Ｚ = 0xA3C1..0xA3DA      （形状 = 半角 A-Z）
      ０-９ = 0xA3B0..0xA3B9      （形状 = 半角 0-9）
  这些字形与半角字母形状完全一致。错位的读法要恰好拼出
  一串正确的 A/B/C/D/1/2…… 概率为零。
  于是判据从"看着像不像字"变成"**能不能认出是哪封信**"。

★ 同时验证「一/二/三」的横线条数（1/2/3），作为第二重判据。

判据来源：官方 sub_426DB0 的 base 在运行时指向 `文件 + 0x694C`，
         `- 9688` 就是相对该 base 的补偿量。
         故文件层面正确公式为 off = 26*N - 9688（N<373 时 +9776）。

用法：
    python Tools/ci/verify_hzk_offset.py
    python Tools/ci/verify_hzk_offset.py --file <Hzk16 路径>
"""
import argparse
import os
import sys

PER = 26
DATA_START = 0x694C


def N_of(lead, trail):
    return trail + 94 * lead - 15295


def off_official(n):
    """官方公式在**文件层面**的等价形式（当前实现）"""
    off = PER * n - 9688
    return off + 9776 if off < 0 else off


def off_bad_addbase(n):
    """错误假设：再额外加一次 dataStart（子代理的主张）"""
    return DATA_START + off_official(n)


# ── 判据 1：全角 ASCII 的形状指纹 ──────────────────────────────────────
#   把"认字"变成"比对像素结构"，避免目视误判。
#   （含墨迹行数, 墨迹总数）实测自当前正确公式。
#
#   ★ 为什么这两个数就够：
#     全角字母占 10 行（下方 3 行空白），数字占 13 行 —— 这一条就能
#     把"字母区"和"数字区"分开，错位的读法几乎不可能同时满足
#     行数与墨迹总数。13x13 里 26 字节任意切片的这两个数落在
#     同一组值的概率极低（见下方"判据有效性自证"）。
FULLWIDTH = [
    # (字符, lead, trail, 含墨迹行数, 墨迹总数)
    ("Ａ", 0xA3, 0xC1, 10, 28),
    ("Ｂ", 0xA3, 0xC2, 10, 37),
    ("Ｃ", 0xA3, 0xC3, 10, 24),
    ("Ｄ", 0xA3, 0xC4, 10, 32),
    ("Ｅ", 0xA3, 0xC5, 10, 40),
    ("Ｆ", 0xA3, 0xC6, 10, 31),
    ("０", 0xA3, 0xB0, 13, 30),
    ("１", 0xA3, 0xB1, 13, 19),
    ("２", 0xA3, 0xB2, 13, 27),
    ("３", 0xA3, 0xB3, 13, 23),
]

# ── 判据 2：一二三的横线条数 + 墨迹总数 ────────────────────────────────
BANDS = [("一", 0xD2, 0xBB, 1, 13),
         ("二", 0xB6, 0xFE, 2, 22),
         ("三", 0xC8, 0xFD, 3, 33)]


def glyph_bytes(d, off):
    if off < 0 or off + PER > len(d):
        return None
    return d[off:off + PER]


def rows(g):
    return ["".join("#" if (g[y * 2 + x // 8] >> (7 - x % 8)) & 1 else "."
                    for x in range(13)) for y in range(13)]


def ink_rows(g):
    return sum(1 for r in rows(g) if "#" in r)


def ink_total(g):
    return sum(r.count("#") for r in rows(g))


def band_count(g):
    rs = rows(g)
    ink = [("#" in r) for r in rs]
    b, prev = 0, False
    for v in ink:
        if v and not prev:
            b += 1
        prev = v
    return b


def art(g, indent="      "):
    return "\n".join(indent + r for r in rows(g))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file",
                    default=r"I:\LocalGames\Army Men\玩具兵大战2\Hzk16")
    args = ap.parse_args()

    if not os.path.isfile(args.file):
        print("!! 字库不存在: %s" % args.file)
        return 1
    d = open(args.file, "rb").read()
    print("字库: %s  (%d 字节)" % (args.file, len(d)))

    fail = 0
    checked = 0

    print("\n" + "=" * 72)
    print("判据 1：全角 ASCII 的形状（应能认出是哪封信/哪个数字）")
    print("=" * 72)
    for ch, lead, trail, want_rows, want_ink in FULLWIDTH:
        n = N_of(lead, trail)
        off = off_official(n)
        g = glyph_bytes(d, off)
        if g is None:
            print("\n!! %s off=%#x 越界" % (ch, off))
            fail += 1
            continue
        got_rows, got_ink = ink_rows(g), ink_total(g)
        ok = (got_rows == want_rows and got_ink == want_ink)
        checked += 1
        print("\n--- 全角 %s  N=%d  off=%#x  含墨迹行=%d(期望%d) 墨迹总数=%d(期望%d) %s"
              % (ch, n, off, got_rows, want_rows, got_ink, want_ink,
                 "OK" if ok else "<== 不符"))
        print(art(g))
        if not ok:
            fail += 1

    print("\n" + "=" * 72)
    print("判据 2：一二三的横线条数（应为 1 / 2 / 3）")
    print("=" * 72)
    for ch, lead, trail, want, want_ink in BANDS:
        n = N_of(lead, trail)
        g = glyph_bytes(d, off_official(n))
        if g is None:
            fail += 1
            continue
        got = band_count(g)
        got_ink = ink_total(g)
        checked += 1
        ok = (got == want and got_ink == want_ink)
        print("  %s 横线=%d(期望%d) 墨迹=%d(期望%d)  %s"
              % (ch, got, want, got_ink, want_ink, "OK" if ok else "!! 不符"))
        if not ok:
            fail += 1

    # ★ 反向断言：证明这个判据**能**区分错误公式（否则它是无效判据）
    #   做法：把"错误公式"换成**所有可能偏移**做扫描，统计误通过率。
    #   若误通过率很低，说明判据有区分力；若很高，判据无效。
    print("\n" + "=" * 72)
    print("判据有效性自证：全偏移扫描，统计误通过率")
    print("=" * 72)
    fps = None  # 占位（原写法多余，删除以免误导）
    want_set = [(a, b) for _, _, _, a, b in FULLWIDTH]
    total_slots = len(d) - PER
    false_pass = 0
    for off in range(0, total_slots, 1):
        g = d[off:off + PER]
        key = (ink_rows(g), ink_total(g))
        if key in want_set:
            false_pass += 1
    rate = 100.0 * false_pass / total_slots
    print("  字库共 %d 个可能偏移；同时命中 %d 个指纹之一的占 %d 个 = %.3f%%"
          % (total_slots, len(want_set), false_pass, rate))
    if rate > 1.0:
        print("  !! 误通过率 >1%%，判据区分力不足，需加强")
        fail += 1
    else:
        print("  OK：误通过率 %.3f%% —— 判据具备区分力" % rate)

    print("\n" + "=" * 72)
    if fail == 0:
        print("全部通过：%d 项判据成立，字形偏移公式正确。" % checked)
    else:
        print("!! %d 项失败" % fail)
    print("=" * 72)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
