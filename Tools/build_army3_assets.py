# -*- coding: utf-8 -*-
"""构建 Army3_Original 资产树（i18n 精确入库，方案 B）。

参照 Tools/build_army2_assets.py 的约定，但 3 代**无官方中文母盘**，
因此只入库"可能承载可译文本"的文件类别：

  入库（方案 B）
    · 全部 *.txt          —— 文本载体（strings.txt / 地图脚本 / rules / 顶层表）
    · 全部 *.bmp          —— 可能烧入文字（菜单、简报、载入图、战略图）
    · audio/vos/*.wav     —— 英文配音基线，239 个 / 12.86 MB
  排除
    · 主程序 exe / *.dll / IDA 库 / 安装器 / 英文文档(PDF)
    · 运行期 save/、第三方广告 3do.smk
    · **update/ 整目录**（★ 见下）
    · audio/ 根的音效与 audio/music/（无人声，非 i18n 载体）
    · avi/（无中文母盘，暂无可译内容）
    · 非文本资产 .ani/.amm/.atl/.dat/.aai（无文字）
    · 非资产 .ico/.vdf/.sdb

★ 为什么必须排除 update/
    游戏根目录下的 update/ 是**本补丁安装后的产物**（3 代汉化载荷 97 个
    .txt/.bmp）。而本脚本是从游戏目录**重建英文基线**的 —— 若不排除，
    重跑会用中文补丁内容覆盖英文基线，且 sha256 全部"新"，校验器抓不到。
    早期版本只排除了 save/，这是真实踩过的坑：装过补丁的机器上重跑即污染。

★ 为什么 audio/vos 入库而 audio/ 根不入
    只有 audio/vos/ 是人声台词（配音汉化的对照基线，与
    Army3_Voice_CHS/audio/vos 逐文件一一对应）；
    audio/ 根是 106 个音效、music/ 是 147 MB 音轨，都不含台词。

用法:
    python Tools/build_army3_assets.py --dry-run
    python Tools/build_army3_assets.py
"""
import argparse
import hashlib
import os
import shutil
import sys

SRC = r"I:\LocalGames\Army Men\Army Men - Toys in Space STEAM"
DST = r"G:\Projects\ArmyMenCHS\Army3_Original"

# 方案 B：按扩展名入库
INCLUDE_EXT = {".txt", ".bmp"}

# 逐目录例外：只有 audio/vos 下的 .wav 入（人声台词基线）
INCLUDE_DIR_EXT = {"audio/vos": {".wav"}}

# 顶层目录整目录排除
# ★ update/ 是本补丁安装后的产物，必须排除，否则重跑会污染英文基线
EXCLUDE_TOP = {"save", "update"}

# 精确文件名排除（小写）
EXCLUDE_NAME = {"3do.smk"}


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
    print("Army3_Original 资产树构建（i18n 精确入库）" +
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
        print("\n清空已存在的 %s" % args.dst)
        shutil.rmtree(args.dst)
    os.makedirs(args.dst)

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
        f.write("# Army3_Original —— Steam 英文基线（i18n 精确入库）\n\n")
        f.write("> 源：`%s`\n" % args.src)
        f.write("> 生成：`Tools/build_army3_assets.py`"
                "（全量 sha256，详见 `_filehash.csv`）\n\n")
        f.write("> 校验：`Tools/verify_army3_assets.py`\n\n")
        f.write("## 与 Army2_Original 的差别\n\n")
        f.write("2 代**有** 1999 上海育碧官方简体中文母盘，所以整棵资产树"
                "（含中文配音/贴图/视频）都属 i18n 依据。\n")
        f.write("3 代**无**官方中文母盘（已核实），可译面只有文本载体，"
                "故本树收 `.txt` + `.bmp` + `audio/vos/*.wav`。\n")
        f.write("`audio/vos`（239 个英文台词）入库的原因：它是配音汉化的"
                "**对照基线** —— 与 `Army3_Voice_CHS/audio/vos` 同名单一一对应，"
                "缺了它就无法核\"哪句被替换、哪句漏了\"。\n")
        f.write("其余媒体与二进制资产留在游戏目录，不入库；"
                "完整排除清单见下。\n")
        f.write("★ `update/` 整目录排除：那是本补丁**安装后**的产物，"
                "入库会污染英文基线（详见脚本头部注释）。\n\n")
        f.write("## 总量\n\n| 项 | 值 |\n|---|---|\n")
        f.write("| 文件数 | %d |\n" % len(rows))
        f.write("| 总体积 | %.2f MB |\n" % (tot / 1048576))
        biggest = max(rows, key=lambda r: r[1])
        f.write("| 单文件最大 | %.2f MB (`%s`) |\n\n"
                % (biggest[1] / 1048576, biggest[0]))
        f.write("## 按扩展名\n\n| 扩展名 | 文件数 | 体积 (MB) |\n|---|---|---|\n")
        for e in sorted(agg, key=lambda k: -agg[k][1]):
            f.write("| `%s` | %d | %.2f |\n" % (e, agg[e][0], agg[e][1] / 1048576))
        f.write("\n## 未收录（完整清单）\n\n")
        f.write("| 类别 | 文件数 | 体积 (MB) | 原因 |\n|---|---|---|---|\n")
        reason = {
            ".wav": "音效(audio/)与音乐(audio/music/)，无人声台词"
                    "（台词在 audio/vos/，已入库）",
            ".smk": "英文视频，无中文母盘可比对",
            ".ani": "动画帧数据，无文字",
            ".amm": "地图数据，无文字",
            ".atl": "图集数据，无文字",
            ".dat": "打包数据（objects/title/shared）",
            ".aai": "AI 行为表，非显示文本",
            ".exe": "主程序（硬约束：不改 exe）",
            ".dll": "第三方/兼容 DLL",
            ".pdf": "英文文档",
            ".ico": "图标",
            ".vdf": "Steam 安装脚本",
            ".sdb": "兼容性数据库",
            ".i64": "IDA 数据库（会话产物）",
            "3do.smk": "第三方广告",
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
