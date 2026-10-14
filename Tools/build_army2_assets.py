# -*- coding: utf-8 -*-
"""构建 Army2_Original / Army2_CHS 资产树（照 1 代仓库约定）。

约定来源：Army1_Original / Army1_CHS
  每个目录含：完整资产树 + MANIFEST.md + _filehash.csv（全量 sha256）

排除项（照 1 代 + 本项目约束）：
  1. 主程序 exe          —— 1 代同样排除；本项目硬约束"不改 exe"
  2. IDA 数据库          —— .i64/.id0/.id1/.id2/.nam/.til 是会话产物，非游戏资产
  3. 我们注入的文件       —— scripts/、update/、安装说明.txt、LICENSE、
                            Disable/Restore_AM2ExeWinCompatShim.reg
  4. 运行期生成/配置      —— Options.cfg、ddraw.ini、save/、MPLAYNOW.INI
  5. 非资产二进制         —— .dll/.ico/.url/.vdf/.isu/.sdb/.reg
  6. 英文文档             —— Manual.pdf/Readme.wri（1 代同样排除）
  7. 第三方广告           —— 3do.smk/3do.url/msn.url（1 代排除了 3DO 广告）
  8. 启动器（用户已决定不纳入）—— mplaynow.exe/mplayer.ico/mplayer.url/MPLAYNOW.INI

用法：
    python Tools/build_army2_assets.py --dry-run
    python Tools/build_army2_assets.py
"""
import argparse
import hashlib
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STEAM = r"I:\LocalGames\Army Men\Army Men II STEAM"
CHS = r"I:\LocalGames\Army Men\玩具兵大战2"

# ── 排除规则 ────────────────────────────────────────────────────────────
EXCLUDE_EXT = {
    ".exe", ".dll", ".ico", ".url", ".vdf", ".isu", ".sdb", ".reg",
    ".i64", ".id0", ".id1", ".id2", ".nam", ".til",
    ".cfg", ".ini", ".pdf", ".wri", ".sav",
}
# 精确文件名（小写比较）
EXCLUDE_NAME = {
    "安装说明.txt", "license", "options.cfg", "ddraw.ini", "mplaynow.ini",
    "3do.smk", "3do.url", "3dosupport.url", "msn.url",
    "uninst.isu", "armymen2_installscript.vdf",
    "disable_am2exewincompat.shim.reg", "restore_am2exewincompat.shim.reg",
}
# 顶层目录/文件：我们注入的，或运行期数据
EXCLUDE_TOP = {
    "scripts",      # 我们的注入目录
    "update",       # 我们的补丁负载
    "save",         # 运行期存档
}


def sha256(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(buf), b""):
            h.update(chunk)
    return h.hexdigest()


def collect(base, label):
    """返回 {相对路径: 绝对路径}（已过滤）"""
    out, skipped = {}, []
    for dirpath, dirnames, filenames in os.walk(base):
        rel_dir = os.path.relpath(dirpath, base).replace("\\", "/")
        if rel_dir == ".":
            rel_dir = ""
        top = rel_dir.split("/")[0] if rel_dir else ""
        if top.lower() in EXCLUDE_TOP:
            dirnames[:] = []
            continue
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = (rel_dir + "/" + fn) if rel_dir else fn
            ext = os.path.splitext(fn)[1].lower()
            if ext in EXCLUDE_EXT or fn.lower() in EXCLUDE_NAME:
                skipped.append((rel, ext or fn.lower()))
                continue
            out[rel.replace("\\", "/")] = full
    return out, skipped


def report(label, files):
    tot = sum(os.path.getsize(p) for p in files.values())
    print("  %-16s %4d 文件  %9.1f MB" % (label, len(files), tot / 1048576))
    return tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--steam", default=STEAM)
    ap.add_argument("--chs", default=CHS)
    args = ap.parse_args()

    jobs = [
        ("Army2_Original", args.steam, "Steam 英文基线"),
        ("Army2_CHS", args.chs, "1999 上海育碧简体中文母盘"),
    ]

    print("=" * 74)
    print("Army2 资产树构建" + ("（DRY RUN）" if args.dry_run else ""))
    print("=" * 74)

    plans = []
    for dirname, src, desc in jobs:
        if not os.path.isdir(src):
            print("!! 源目录不存在: %s" % src)
            return 1
        files, skipped = collect(src, dirname)
        print("\n[%s]  %s" % (dirname, desc))
        print("  源: %s" % src)
        tot = report(dirname, files)
        # 被排除项按扩展名汇总
        agg = {}
        for rel, key in skipped:
            agg.setdefault(key, []).append(rel)
        print("  排除 %d 个：" % len(skipped))
        for k in sorted(agg, key=lambda k: -len(agg[k])):
            print("     %-12s %3d" % (k, len(agg[k])))
        plans.append((dirname, src, desc, files, tot))

    grand = sum(p[4] for p in plans)
    print("\n" + "=" * 74)
    print("合计待写入: %.1f MB" % (grand / 1048576))
    print("=" * 74)

    if args.dry_run:
        print("\n（dry-run，未写入任何文件）")
        return 0

    for dirname, src, desc, files, tot in plans:
        dst = os.path.join(ROOT, dirname)
        if os.path.isdir(dst):
            print("\n清空已存在的 %s" % dst)
            shutil.rmtree(dst)
        os.makedirs(dst)
        rows = []
        for rel in sorted(files):
            s = files[rel]
            d = os.path.join(dst, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copyfile(s, d)
            rows.append((rel, os.path.getsize(s), sha256(s)))

        # ★ 这里**不再**往资产树里塞 compat/。
        #   那两棵目录树是"母盘/Steam 版的逐文件镜像"，只放来自游戏的文件；
        #   我们自造的运行时配套（两个兼容性 shim 的 .reg）放仓库根 compat/。
        #   早先塞进来过一次，既污染镜像、又需要额外的暂存目录来绕过
        #   rmtree，纯属自找麻烦。

        print("\n[%s] 已写入 %d 文件" % (dirname, len(rows)))

        # _filehash.csv（照 1 代格式：relative,size,sha256）
        with open(os.path.join(dst, "_filehash.csv"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write('"relative","size","sha256"\n')
            for rel, size, h in rows:
                f.write('"%s","%d","%s"\n' % (rel.replace("/", "\\"), size, h))
        print("  -> _filehash.csv")

        # MANIFEST.md 骨架（统计部分；差异分析由后续脚本补）
        ext_agg = {}
        for rel, size, h in rows:
            e = os.path.splitext(rel)[1].lower() or "(无扩展名)"
            a = ext_agg.setdefault(e, [0, 0])
            a[0] += 1
            a[1] += size
        with open(os.path.join(dst, "MANIFEST.md"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write("# %s —— %s\n\n" % (dirname, desc))
            f.write("> 源：`%s`\n" % src)
            f.write("> 生成：`Tools/build_army2_assets.py`"
                    "（全量 sha256，详见 `_filehash.csv`）\n\n")
            f.write("## 总量\n\n")
            f.write("| 项 | 值 |\n|---|---|\n")
            f.write("| 文件数 | %d |\n" % len(rows))
            f.write("| 总体积 | %.1f MB |\n" % (tot / 1048576))
            biggest = max(rows, key=lambda r: r[1])
            f.write("| 单文件最大 | %.1f MB (`%s`) |\n"
                    % (biggest[1] / 1048576, biggest[0]))
            f.write("\n## 按扩展名\n\n")
            f.write("| 扩展名 | 文件数 | 体积 (MB) |\n|---|---|---|\n")
            for e in sorted(ext_agg, key=lambda k: -ext_agg[k][1]):
                c, sz = ext_agg[e]
                f.write("| `%s` | %d | %.1f |\n" % (e, c, sz / 1048576))
            f.write("\n## 未收录\n\n")
            f.write("主程序 exe、`*.dll`、IDA 数据库、我们注入的 `scripts/`+`update/`、\n")
            f.write("运行期配置（`Options.cfg`/`ddraw.ini`/`save/`）、英文文档、\n")
            f.write("第三方广告（`3do.smk` 等）、启动器文件。\n")
        print("  -> MANIFEST.md")

    print("\n完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
