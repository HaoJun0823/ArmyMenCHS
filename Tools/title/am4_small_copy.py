# -*- coding: utf-8 -*-
"""12 张小控件图：直接把 3 代成品按 key 映射复制到 4 代 png_control_chs/。

依据（已实测）：
  · 这批图是**跨代通用控件**（4 阵营 × game load / setup / paused 三态），
    与地形、调色板无关。
  · 3 代成品的全部颜色**精确存在于 4 代调色板**（最大色差 = 0），
    故不存在回包时的最近色吸附失真。
  · 两代仅索引号不同，key 完全一致（0x0099C2xx 等）。

用法：
    python Tools/title/am4_small_copy.py --dry-run
    python Tools/title/am4_small_copy.py
"""
import argparse
import hashlib
import os
import shutil
import sys

SHARED = r"G:\Projects\ArmyMenCHS\Army4_Object_CHS\shared"
EN_DIR = os.path.join(SHARED, "png_control_en")
A3_DIR = os.path.join(SHARED, "png_control_army_3")
OUT = os.path.join(SHARED, "png_control_chs")

# 4 代面板（大图，由 am4_panel_build.py 处理）——本脚本跳过
PANEL_PREFIX = "0058"   # key 以 0058 开头的是 4 张大面板


def key_of(n):
    return n.split("_k")[1].replace(".png", "")


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # 以 png_control_en 的文件名为准（它就是 4 代的名字清单）
    en = {key_of(f): f for f in os.listdir(EN_DIR) if f.endswith(".png")}
    a3 = {key_of(f): f for f in os.listdir(A3_DIR) if f.endswith(".png")}

    jobs = []
    missing = []
    for k, f4 in sorted(en.items()):
        if k.startswith(PANEL_PREFIX):
            continue                       # 大面板走另一条管线
        if k not in a3:
            missing.append((k, f4))
            continue
        jobs.append((k, os.path.join(A3_DIR, a3[k]), f4))

    print("=" * 74)
    print("12 张小控件图：3 代成品 -> 4 代 %s" % OUT +
          ("（DRY RUN）" if args.dry_run else ""))
    print("=" * 74)
    print("待复制 %d 个（4 代名 <- 3 代名）:" % len(jobs))
    for k, src, f4 in jobs:
        print("   %-28s <- %s" % (f4, os.path.basename(src)))
    if missing:
        print("\n!! 3 代成品缺 %d 个:" % len(missing))
        for k, f4 in missing:
            print("     %s" % f4)

    if args.dry_run:
        print("\n（dry-run，未写入任何文件）")
        return 0

    os.makedirs(OUT, exist_ok=True)
    n = 0
    for k, src, f4 in jobs:
        dst = os.path.join(OUT, f4)
        shutil.copyfile(src, dst)
        assert sha(src) == sha(dst), "复制后哈希不符: %s" % f4
        n += 1
    print("\n已复制 %d 个（每个均校验复制后 sha256 一致）" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
