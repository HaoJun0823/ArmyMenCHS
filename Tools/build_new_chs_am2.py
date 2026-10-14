# -*- coding: utf-8 -*-
"""把汉化补丁载荷写进 Army2_NEW_CHS（照 Army1_NEW_CHS 约定）。

约定（对照 Army1_NEW_CHS，git 追踪 216 个文件）：
    Army*_NEW_CHS/ = **纯载荷**，目录名与游戏一致，可直接整树覆盖到游戏目录。
                     不含 MANIFEST（清单在 build_out 里）。

Army2 的载荷来自 build_out_am2/update（差异打包产物），
外加 scripts/（ASI 模块 + Hzk16 + ini）。

用法：
    python Tools/build_new_chs_am2.py --dry-run
    python Tools/build_new_chs_am2.py
"""
import argparse
import hashlib
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_UPDATE = os.path.join(ROOT, "build_out_am2", "update")
SRC_SCRIPTS = os.path.join(ROOT, "stage_am2", "scripts")
DST = os.path.join(ROOT, "Army2_NEW_CHS")


def sha256(p, buf=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(buf), b""):
            h.update(c)
    return h.hexdigest()


def walk(base):
    out = {}
    for dp, _, fns in os.walk(base):
        for fn in fns:
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, base)
            out[rel] = full
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.isdir(SRC_UPDATE):
        print("!! 缺少 %s —— 请先跑 build_update_am2.py" % SRC_UPDATE)
        return 1

    # ① update/ 的差异资产 -> 直接落到 NEW_CHS 根（目录名与游戏一致）
    files = {}
    upd = walk(SRC_UPDATE)
    for rel, full in upd.items():
        files[rel] = full
    # ② scripts/ 内容 -> NEW_CHS/scripts/（ASI 模块等由安装流程放到游戏根，
    #    这里保持与 stage_am2 一致，便于人工核对）
    if os.path.isdir(SRC_SCRIPTS):
        for rel, full in walk(SRC_SCRIPTS).items():
            files[os.path.join("scripts", rel)] = full

    tot = sum(os.path.getsize(p) for p in files.values())
    print("=" * 74)
    print("Army2_NEW_CHS 载荷构建" + ("（DRY RUN）" if args.dry_run else ""))
    print("=" * 74)
    print("  源 update/  : %d 文件" % len(upd))
    print("  合计        : %d 文件  %.1f MB" % (len(files), tot / 1048576))

    agg = {}
    for rel in files:
        e = os.path.splitext(rel)[1].lower() or "(无)"
        a = agg.setdefault(e, [0, 0])
        a[0] += 1
        a[1] += os.path.getsize(files[rel])
    print("\n  按扩展名：")
    for e in sorted(agg, key=lambda k: -agg[k][1]):
        c, sz = agg[e]
        print("     %-8s %4d 个  %8.1f MB" % (e, c, sz / 1048576))

    if args.dry_run:
        print("\n（dry-run，未写入）")
        return 0

    # 清空重建（保留 _filehash.csv 由本脚本生成）
    if os.path.isdir(DST):
        print("\n清空 %s" % DST)
        shutil.rmtree(DST)
    os.makedirs(DST)

    rows = []
    for rel in sorted(files):
        s = files[rel]
        d = os.path.join(DST, rel)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copyfile(s, d)
        rows.append((rel, os.path.getsize(s), sha256(s)))
    print("\n已写入 %d 文件到 %s" % (len(rows), DST))

    # _filehash.csv（与 Army2_Original/CHS 同格式，便于版本记录）
    with open(os.path.join(DST, "_filehash.csv"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write('"relative","size","sha256"\n')
        for rel, size, h in rows:
            f.write('"%s","%d","%s"\n' % (rel.replace("/", "\\"), size, h))
    print("  -> _filehash.csv")

    # 记号文件：说明本目录用途（Army1 没有，但这里值得留一份，
    # 因为载荷含"用户待手工汉化的 bmp"）
    with open(os.path.join(DST, "README.md"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write("# Army2_NEW_CHS —— 汉化补丁载荷\n\n")
        f.write("目录名与游戏安装目录一致，可整树覆盖。\n\n")
        f.write("| 项 | 值 |\n|---|---|\n")
        f.write("| 文件数 | %d |\n" % len(rows))
        f.write("| 总体积 | %.1f MB |\n" % (tot / 1048576))
        f.write("\n## 按扩展名\n\n| 扩展名 | 文件数 | 体积 (MB) |\n|---|---|---|\n")
        for e in sorted(agg, key=lambda k: -agg[k][1]):
            c, sz = agg[e]
            f.write("| `%s` | %d | %.1f |\n" % (e, c, sz / 1048576))
        f.write("\n## 待人工处理\n\n")
        f.write("部分 `bitmaps/*.bmp` 尚未汉化（中文母盘里仍是英文烧字），\n")
        f.write("需手工处理后覆盖本目录同名文件。详见 `MANIFEST_BMP.md`。\n")
        f.write("\n全量 sha256 见 `_filehash.csv`。\n")
    print("  -> README.md")

    # BMP 专项清单：区分"中文母盘已含中文"与"仍是英文"
    bmps = [r for r in rows if r[0].lower().endswith(".bmp")]
    with open(os.path.join(DST, "MANIFEST_BMP.md"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write("# BMP 清单（%d 个）\n\n" % len(bmps))
        f.write("判据：与 Steam 基线逐字节比对。**两版相同 = 母盘未本地化，需手工处理**。\n\n")
        f.write("| 路径 | 字节 | 状态 |\n|---|---|---|\n")
        base = os.path.join(ROOT, "Army2_Original")
        same, diff = [], []
        for rel, size, h in sorted(bmps):
            b = os.path.join(base, rel.replace("/", os.sep))
            if os.path.isfile(b):
                bh = sha256(b)
                st = "**与英文版相同（待汉化）**" if bh == h else "已含中文"
            else:
                st = "英文版无此文件（新增）"
            (same if "待汉化" in st else diff).append(rel)
            f.write("| `%s` | %d | %s |\n" % (rel, size, st))
        f.write("\n## 汇总\n\n")
        f.write("- 已含中文：%d\n" % len(diff))
        f.write("- **待汉化：%d**\n" % len(same))
    print("  -> MANIFEST_BMP.md")
    print("\n完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
