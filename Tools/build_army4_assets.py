# -*- coding: utf-8 -*-
"""构建 Army4_Original 资产树（i18n 精确入库，沿用 3 代方案 B）。

参照 Tools/build_army3_assets.py 的约定。4 代（Army Men: World War, 2000）
与 3 代文本载体**结构同构**（已实测：amww.exe 内 `strings.txt` 字面量同为 5 处，
`Invalid installation` / `wrong number of strings` / `cannot be read` 文案同源，
加载器同为 ExtnText.cpp 的 ExtnTextLoad），故入库口径与 3 代一致：

  入库
    · 全部 *.txt          —— 文本载体（strings.txt / 地图脚本 / rules / 顶层表）
    · 全部 *.bmp          —— 可能烧入文字（简报、战略图、载入图、预览图）
    · audio/vos/*.wav     —— 英文配音基线，298 个 / 87.84 MB（经确认全量入库）
  排除
    · 主程序 exe / *.dll / IDA 库 / 安装器 / 英文文档(PDF)
    · 运行期 save/、update/ 整目录（★ 见下）
    · GOG 根目录 EULA.txt（安装器附带文档，非游戏文本；3 代源目录无此文件）
    · audio/music/（17 个音轨，无人声）
    · avi/（英文视频，无中文母盘可比对）
    · 非文本资产 .ani/.amm/.atl/.dat/.aai（无文字）
    · 非资产 .ico/.hashdb/.info/.script/.sdb/.ini/.msg/.lnk/.zip

★ 为什么必须排除 update/
    游戏根目录下的 update/ 是**本补丁安装后的产物**。而本脚本是从游戏目录
    **重建英文基线**的 —— 若不排除，重跑会用中文补丁内容覆盖英文基线，
    且 sha256 全部"新"，校验器抓不到。3 代踩过此坑，4 代照搬该排除项。

★ 为什么不删除已存在的目标目录
    3 代脚本用 shutil.rmtree 清空，本脚本改为**移入仓库 _trash/**——
    遵循"禁止直接删除文件"的纪律，且 _trash/ 在 .gitignore 内，不会入库。

★ 4 代与 3 代的实测差异（供后续汉化参考，影响翻译阶段不影响入库）
    · strings/strings.txt：4 代 **323 行**（3 代 320 行）；exe 内下界闸门
      立即数同为 320。3 代「320 行 = 数组容量 = 零余量」的推论**不适用于 4 代**，
      数组容量需在翻译阶段用 IDA 实测。
    · bitmaps/：4 代 65 个，与 3 代仅 5 个同名，命名体系全换
      （3 代 bcs001.bmp/load_*.bmp → 4 代 BCS01.bmp/MAP_01.bmp/mp_*.bmp）。

用法:
    python Tools/build_army4_assets.py --dry-run
    python Tools/build_army4_assets.py
    python Tools/build_army4_assets.py --reset      # 非空目标目录先移入 _trash/
"""
import argparse
import hashlib
import os
import shutil
import sys
import time

SRC = r"I:\LocalGames\Army Men\Army Men - World War GOG"
DST = r"G:\Projects\ArmyMenCHS\Army4_Original"

# 方案 B：按扩展名入库
INCLUDE_EXT = {".txt", ".bmp"}

# 逐目录例外：只有 audio/vos 下的 .wav 入（人声台词基线）
INCLUDE_DIR_EXT = {"audio/vos": {".wav"}}

# 顶层目录整目录排除
# ★ update/ 是本补丁安装后的产物，必须排除，否则重跑会污染英文基线
EXCLUDE_TOP = {"save", "update"}

# 精确文件名排除（小写）
# ★ eula.txt 是 GOG 安装器自带文档，非游戏文本载体（3 代源目录无此文件）
EXCLUDE_NAME = {"3do.smk", "eula.txt"}


def sha256(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(buf), b""):
            h.update(chunk)
    return h.hexdigest()


def collect(base):
    inc, exc = {}, {}
    for dirpath, dirnames, filenames in os.walk(base):
        rel_dir = os.path.relpath(dirpath, base)
        rel_dir = "" if rel_dir == "." else rel_dir.replace("\\", "/")
        top = rel_dir.split("/")[0] if rel_dir else ""
        if top.lower() in EXCLUDE_TOP:
            dirnames[:] = []
            continue
        extra_ext = set()
        for d, exts in INCLUDE_DIR_EXT.items():
            if rel_dir.lower() == d.lower():
                extra_ext |= exts
        for fn in filenames:
            rel = (rel_dir + "/" + fn) if rel_dir else fn
            ext = os.path.splitext(fn)[1].lower()
            key = ext or fn.lower()
            if (ext in INCLUDE_EXT or ext in extra_ext) and \
                    fn.lower() not in EXCLUDE_NAME:
                inc[rel] = os.path.join(dirpath, fn)
            else:
                exc.setdefault(key, []).append(rel)
    return inc, exc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reset", action="store_true",
                    help="目标目录非空时，先移入仓库 _trash/（不删除）")
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--dst", default=DST)
    args = ap.parse_args()

    if not os.path.isdir(args.src):
        print("!! 源目录不存在: %s" % args.src)
        return 1

    inc, exc = collect(args.src)
    tot = sum(os.path.getsize(p) for p in inc.values())
    exc_tot = sum(os.path.getsize(os.path.join(args.src, r.replace("/", os.sep)))
                  for lst in exc.values() for r in lst
                  if os.path.isfile(os.path.join(args.src, r.replace("/", os.sep))))

    print("=" * 74)
    print("Army4_Original 资产树构建（i18n 精确入库）" +
          ("（DRY RUN）" if args.dry_run else ""))
    print("=" * 74)
    print("源: %s" % args.src)
    print()
    print("[入库] %d 文件 / %.2f MB" % (len(inc), tot / 1048576))
    agg = {}
    for rel in inc:
        e = os.path.splitext(rel)[1].lower()
        a = agg.setdefault(e, [0, 0])
        a[0] += 1
        a[1] += os.path.getsize(inc[rel])
    for e in sorted(agg, key=lambda k: -agg[k][1]):
        print("   %-8s %4d  %8.2f MB" % (e, agg[e][0], agg[e][1] / 1048576))
    print()
    print("   顶层分布:")
    top_agg = {}
    for rel in inc:
        t = rel.split("/")[0] if "/" in rel else "(根)"
        a = top_agg.setdefault(t, [0, 0])
        a[0] += 1
        a[1] += os.path.getsize(inc[rel])
    for t in sorted(top_agg, key=lambda k: -top_agg[k][1]):
        print("     %-14s %4d  %8.2f MB" %
              (t, top_agg[t][0], top_agg[t][1] / 1048576))
    print()
    print("[排除] %d 文件 / %.2f MB" %
          (sum(len(v) for v in exc.values()), exc_tot / 1048576))
    for k in sorted(exc, key=lambda k: -len(exc[k])):
        sz = sum(os.path.getsize(os.path.join(args.src, r.replace("/", os.sep)))
                 for r in exc[k] if os.path.isfile(
                     os.path.join(args.src, r.replace("/", os.sep))))
        print("   %-12s %4d  %8.2f MB" % (k, len(exc[k]), sz / 1048576))

    if args.dry_run:
        print("\n（dry-run，未写入任何文件）")
        return 0

    if os.path.isdir(args.dst):
        existing = list(os.scandir(args.dst))
        if existing:
            if not args.reset:
                print("\n!! 目标目录非空：%s（%d 项）" % (args.dst, len(existing)))
                print("   按纪律不直接删除。确认要重建请加 --reset"
                      "（现有内容移入仓库 _trash/，不删除）。")
                return 2
            repo = os.path.dirname(os.path.abspath(args.dst))
            trash = os.path.join(repo, "_trash",
                                 "Army4_Original-%s" % time.strftime("%Y%m%d-%H%M%S"))
            os.makedirs(os.path.dirname(trash), exist_ok=True)
            print("\n--reset：把现有 %s 移入 %s" % (args.dst, trash))
            shutil.move(args.dst, trash)
    os.makedirs(args.dst, exist_ok=True)

    rows = []
    for rel in sorted(inc):
        s = inc[rel]
        d = os.path.join(args.dst, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copyfile(s, d)
        rows.append((rel, os.path.getsize(s), sha256(s)))
    print("\n已写入 %d 文件" % len(rows))

    with open(os.path.join(args.dst, "_filehash.csv"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write('"relative","size","sha256"\n')
        for rel, size, h in rows:
            f.write('"%s","%d","%s"\n' % (rel.replace("/", "\\"), size, h))
    print("  -> _filehash.csv")

    with open(os.path.join(args.dst, "MANIFEST.md"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write("# Army4_Original —— World War 英文基线（i18n 精确入库）\n\n")
        f.write("> 源：`%s`\n" % args.src)
        f.write("> 生成：`Tools/build_army4_assets.py`"
                "（全量 sha256，详见 `_filehash.csv`）\n\n")
        f.write("> 校验：`Tools/verify_army4_assets.py`\n\n")
        f.write("## 与 Army3_Original 的差别\n\n")
        f.write("入库口径**完全相同**（3 代无官方中文母盘，4 代同样无 —— "
                "两代 exe 内 `Hzk16` / `RSE\\x1a` 均 0 命中），"
                "故本树同样收 `.txt` + `.bmp` + `audio/vos/*.wav`。\n")
        f.write("4 代与 3 代文本载体**结构同构**（实测：`amww.exe` 内 "
                "`strings.txt` 字面量同为 5 处，`Invalid installation` / "
                "`wrong number of strings` / `cannot be read` 文案同源，"
                "加载器同为 `ExtnText.cpp` 的 `ExtnTextLoad`）。\n")
        f.write("`audio/vos`（298 个英文台词）入库的原因：它是配音汉化的"
                "**对照基线** —— 与将来的 `Army4_Voice_CHS/audio/vos` "
                "同名单一一对应，缺了它就无法核哪句被替换、哪句漏了。\n")
        f.write("★ `update/` 整目录排除：那是本补丁**安装后**的产物，"
                "入库会污染英文基线（详见脚本头部注释）。\n")
        f.write("★ 根目录 `EULA.txt` 排除：GOG 安装器附带文档，非游戏文本，"
                "3 代源目录无此文件。\n\n")
        f.write("## 4 代与 3 代的两处实测差异（影响翻译阶段，不影响本树）\n\n")
        f.write("| 项 | 3 代 | 4 代 |\n|---|---|---|\n")
        f.write("| `strings/strings.txt` 行数 | 320 行（= 数组容量，零余量） | "
                "**323 行** |\n")
        f.write("| `strings.txt` 下界闸门立即数 | `cmp ..., 320` | "
                "`cmp ..., 320`（同） |\n")
        f.write("| `bitmaps/` 文件数 | 61（`bcs001`/`load_*` 体系） | "
                "**65**（`BCS01`/`MAP_01`/`mp_*` 体系） |\n")
        f.write("| 与 3 代同名 BMP | — | 仅 **5** 个 |\n\n")
        f.write("> 注意：3 代「320 行 = 数组容量 = 零余量」的推论**不适用于 "
                "4 代**：\n"
                "> 4 代出厂即 323 行而闸门仍为 320 下界，说明其字符串指针数组"
                "容量必然 >= 323。\n"
                "> 翻译阶段拆行前，必须先用 IDA 实测该数组起点/终点。\n\n")
        f.write("## 总量\n\n| 项 | 值 |\n|---|---|\n")
        f.write("| 文件数 | %d |\n" % len(rows))
        f.write("| 总体积 | %.2f MB |\n" % (tot / 1048576))
        biggest = max(rows, key=lambda r: r[1])
        f.write("| 单文件最大 | %.2f MB (`%s`) |\n\n"
                % (biggest[1] / 1048576, biggest[0]))
        f.write("## 按扩展名\n\n| 扩展名 | 文件数 | 体积 (MB) |\n|---|---|---|\n")
        for e in sorted(agg, key=lambda k: -agg[k][1]):
            f.write("| `%s` | %d | %.2f |\n" % (e, agg[e][0], agg[e][1] / 1048576))
        f.write("\n## 顶层分布\n\n| 顶层 | 文件数 | 体积 (MB) |\n|---|---|---|\n")
        for t in sorted(top_agg, key=lambda k: -top_agg[k][1]):
            f.write("| `%s` | %d | %.2f |\n"
                    % (t, top_agg[t][0], top_agg[t][1] / 1048576))
        f.write("\n## 未收录（完整清单）\n\n")
        f.write("| 类别 | 文件数 | 体积 (MB) | 原因 |\n|---|---|---|---|\n")
        reason = {
            ".wav": "音效(audio/)与音乐(audio/music/)，无人声台词（台词在 audio/vos/，已入库）",
            ".smk": "英文视频，无中文母盘可比对",
            ".ani": "动画帧数据，无文字",
            ".amm": "地图数据，无文字",
            ".atl": "图集数据，无文字",
            ".dat": "打包数据（title/shared/objects），走差异移植",
            ".aai": "AI 行为表，非显示文本",
            ".exe": "主程序（硬约束：不改 exe）",
            ".dll": "第三方/兼容 DLL",
            ".pdf": "英文文档",
            ".ico": "图标",
            ".hashdb": "GOG 安装器附带数据库",
            ".info": "GOG 安装器附带信息文件",
            ".script": "GOG 启动脚本",
            ".sdb": "兼容性数据库",
            ".ini": "兼容层配置",
            ".msg": "安装器消息表",
            ".lnk": "安装器快捷方式",
            ".zip": "GOG webcache",
            "3do.smk": "第三方广告",
            "eula.txt": "GOG 安装器附带文档，非游戏文本",
        }
        for k in sorted(exc, key=lambda k: -len(exc[k])):
            sz = sum(os.path.getsize(os.path.join(args.src, r.replace("/", os.sep)))
                     for r in exc[k] if os.path.isfile(
                         os.path.join(args.src, r.replace("/", os.sep))))
            f.write("| `%s` | %d | %.2f | %s |\n"
                    % (k, len(exc[k]), sz / 1048576, reason.get(k, "非 i18n 载体")))
        f.write("\n另有运行期 `save/` 整目录未收（存档，非资产）。\n")
    print("  -> MANIFEST.md")
    print("\n完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
