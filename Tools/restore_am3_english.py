#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""restore_am3_english.py —— 把 3 代游戏的 strings.txt 还原为英文原文。

用途：汉化测试后一键回滚（译文是独立文件，回滚不影响 exe / DLL）。

英文原文来源：Army3_Original/strings/strings.txt
（导入时已逐字节校验，SHA256 与游戏原文件一致）

用法：
    python Tools/restore_am3_english.py                # 还原
    python Tools/restore_am3_english.py --dry-run      # 只看会做什么
    python Tools/restore_am3_english.py --check        # 只比对现状
"""
import argparse
import hashlib
import os
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP = os.path.join(REPO, "Army3_Original", "strings", "strings.txt")

# 游戏目录（可用 --game 覆盖）
DEFAULT_GAME = r"I:\LocalGames\Army Men\Army Men - Toys in Space STEAM"

# 导入时记录的原文件哈希（见 Army3_Original/_filehash.csv）
EXPECT_SHA256 = "1A4B98E97819CBD15E90F2D0A4E71B6B3D0157829FE199290F78F32DCD246697"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default=DEFAULT_GAME, help="游戏根目录")
    ap.add_argument("--dry-run", action="store_true", help="只显示计划，不写文件")
    ap.add_argument("--check", action="store_true", help="只比对现状，不写文件")
    args = ap.parse_args()

    target = os.path.join(args.game, "strings", "strings.txt")

    if not os.path.isfile(BACKUP):
        print(f"!! 找不到英文原文备份: {BACKUP}", file=sys.stderr)
        return 2
    if not os.path.isfile(target):
        print(f"!! 找不到游戏内的 strings.txt: {target}", file=sys.stderr)
        return 2

    backup_sha = sha256(BACKUP)
    cur_sha = sha256(target)

    print(f"英文原文备份 : {BACKUP}")
    print(f"               sha256 {backup_sha}")
    print(f"                 （与游戏原文件一致: {backup_sha == EXPECT_SHA256}）")
    print(f"游戏当前文件 : {target}")
    print(f"               sha256 {cur_sha}")
    print(f"               已是英文原文: {cur_sha == backup_sha}")
    print(f"               已是中文译文: {cur_sha != backup_sha}")

    if args.check:
        return 0

    if cur_sha == backup_sha:
        print("\n无需还原：当前已是英文原文。")
        return 0

    if args.dry_run:
        print(f"\n[dry-run] 将把 {BACKUP} 覆盖到 {target}")
        return 0

    shutil.copy2(BACKUP, target)
    now = sha256(target)
    ok = (now == backup_sha)
    print(f"\n已还原 -> sha256 {now}")
    print("结果:", "成功" if ok else "!! 校验失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
