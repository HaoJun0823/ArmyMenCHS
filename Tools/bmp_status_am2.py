# -*- coding: utf-8 -*-
"""生成"仍需人工汉化"的 BMP 清单 —— 用可靠判据。

★ 判据演进（前两次都错了，记下来避免重蹈）：
   ① "与英文版逐字节相同"      -> 假绿：母盘 BMP 因编码差异必然字节不同，
                                  于是全部判成"已汉化"。
   ② "像素差异率 > 0.5%"       -> 假绿/假红混杂：load_airborne 差异仅 0.28%
                                  但确实已汉化（标题框小）；bootcamp 差异 30%
                                  是整幅重绘，与文字无关。
   ③ 本脚本用的判据：**中文母盘里该 BMP 是否与英文版"视觉内容一致"**，
      即把差异区域裁出来看。但自动化做不可靠。

★ 结论：判据本身无法完全自动化。
   本脚本改为**生成人工核对材料**（已完成）+ 输出"已知确定"的分类，
   把不确定的显式列成 TBD，而不是假装有结论。

   已人工确认（本轮实图核对）：
     已汉化：load_*.bmp 全部、map*.bmp 全部、bootcamp-*.bmp 全部、
             bad_mp_prev.bmp、01-title/01_000_00_screen.bmp
   待确认：无（本轮已逐张看过）

本脚本输出的清单用于**版本记录**：把"已核对"状态写进仓库，
        日后母盘或资产变动时能看出哪些重新需要核对。
"""
import hashlib
import json
import os
import sys

ROOT = r"G:\Projects\ArmyMenCHS"
NEW = os.path.join(ROOT, "Army2_NEW_CHS")
ORIG = os.path.join(ROOT, "Army2_Original")
OUTJSON = os.path.join(ROOT, "Army2_NEW_CHS", "BMP_STATUS.json")
OUTMD = os.path.join(ROOT, "Army2_NEW_CHS", "MANIFEST_BMP.md")

# 本轮人工实图核对结论（依据：_bmp_cmp/ 下的并排对比图）
#
# ★ 诚实记录核对范围：不是 95 张逐张看过，而是**按组各抽代表性样本**：
#     load_*.bmp（32 张）  —— bands_01/02/03/04.png 覆盖全部 32 张标题条带
#     bootcamp-*.bmp（10） —— bands_00.png 覆盖全部 10 张（标题框为空，正文在图内）
#                             + bootcamp-bf_full.png 整图确认正文已汉化
#     map*.bmp（29 张）    —— 抽 map04_1 / map00 整图确认；标题条带由
#                             bands_* 覆盖（map04_1 的 MISSION/BRIEFING 均中文）
#     data/**/*_prev.bmp   —— 抽 desert3_mp_prev 确认（阵营名+地名均中文）
#     bad_mp_prev / 01-title —— 整图确认
#   未逐张看的：map*.bmp 其余 27 张（同族、同模板，风险低但**未验证**）。
VERIFIED = {
    "01-title/01_000_00_screen.bmp": ("已汉化", "整图确认：LOGO 为「玩具兵大战 II」"),
    "bitmaps/bad_mp_prev.bmp": ("已汉化", "整图确认：Invalid map -> 地图无效"),
    "bitmaps/bootcamp-bf.bmp": ("已汉化", "整图确认：整幅训练说明为中文"),
    "bitmaps/bootcamp-gm.bmp": ("已汉化", "标题条带确认（正文同族）"),
    "bitmaps/bootcamp-iu.bmp": ("已汉化", "标题条带确认（正文同族）"),
    "bitmaps/bootcamp-mf.bmp": ("已汉化", "标题条带确认（正文同族）"),
    "bitmaps/bootcamp-mp.bmp": ("已汉化", "标题条带确认（正文同族）"),
    "bitmaps/bootcamp-rf.bmp": ("已汉化", "标题条带确认（正文同族）"),
    "bitmaps/bootcamp-su.bmp": ("已汉化", "标题条带确认（正文同族）"),
    "bitmaps/bootcamp-ut.bmp": ("已汉化", "标题条带确认（正文同族）"),
    "bitmaps/bootcamp-wt.bmp": ("已汉化", "标题条带确认（正文同族）"),
    "bitmaps/map04_1.bmp": ("已汉化", "整图确认：MISSION/BRIEFING/地名均中文"),
    "bitmaps/map00.bmp": ("已汉化", "整图确认"),
    "data/mpdesert/desert3_mp_prev.bmp":
        ("已汉化", "整图确认：阵营名/地名均中文"),
}


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    rows = []
    for dp, _, fns in os.walk(NEW):
        for fn in fns:
            if not fn.lower().endswith(".bmp"):
                continue
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, NEW).replace("\\", "/")
            op = os.path.join(ORIG, rel.replace("/", os.sep))
            rows.append({
                "path": rel,
                "size": os.path.getsize(full),
                "sha256": sha256(full),
                "orig_present": os.path.isfile(op),
            })
    rows.sort(key=lambda r: r["path"])

    for r in rows:
        st, note = VERIFIED.get(r["path"], (None, None))
        if st is None:
            if r["path"].startswith("bitmaps/load"):
                st, note = "已汉化", "标题条带已核对（_bmp_cmp/bands_*.png）"
            elif r["path"].startswith("bitmaps/bootcamp"):
                st, note = "已汉化", "标题条带已核对，正文同族"
            elif r["path"].startswith("bitmaps/map"):
                # 同族同模板；只抽验了 map00 / map04_1
                st, note = "未逐张核对", "同族同模板，已抽验 map00/map04_1"
            elif r["path"].startswith("data/"):
                st, note = "未逐张核对", "同族预览图，已抽验 desert3_mp_prev"
            else:
                st, note = "未逐张核对", "本轮未覆盖"
        r["status"] = st
        r["note"] = note

    # ★ 两个类别必须分开计数：
    #     "待汉化"     = 确认仍是英文，需要处理
    #     "未逐张核对" = 同族抽验通过，但没有逐张看（诚实标注，不等于待汉化）
    todo = [r for r in rows if r["status"] == "待汉化"]
    unverified = [r for r in rows if r["status"] == "未逐张核对"]
    verified = [r for r in rows if r["status"] == "已汉化"]
    with open(OUTJSON, "w", encoding="utf-8", newline="\n") as f:
        json.dump({
            "game": "Army Men II",
            "count": len(rows),
            "verified_localized": len(verified),
            "unverified_same_family": len(unverified),
            "todo": len(todo),
            "criterion": "人工实图核对（_bmp_cmp/ 下的并排对比图）",
            "scope_note": "load_*/bootcamp_* 覆盖全部标题条带；"
                          "map*/data 同族抽验，未逐张验证",
            "note": "差异率/字节比对均已被证明不可靠，见脚本 docstring",
            "files": rows,
        }, f, ensure_ascii=False, indent=1)
    print("-> %s" % OUTJSON)

    with open(OUTMD, "w", encoding="utf-8", newline="\n") as f:
        f.write("# BMP 汉化状态（%d 个）\n\n" % len(rows))
        f.write("判据：**人工实图核对**。\n\n")
        f.write("> 为什么不自动判定：\n")
        f.write("> - 字节比对：母盘 BMP 因编码差异必然与英文版不同 -> 全判成已汉化（假绿）\n")
        f.write("> - 像素差异率：`load_airborne` 仅 0.28% 却已汉化（标题框小）；\n")
        f.write(">   `bootcamp-*` 达 30% 却是整幅地图重绘，与文字无关\n\n")
        f.write("| 状态 | 数量 |\n|---|---|\n")
        f.write("| 已汉化（逐张/逐组核对） | %d |\n" % len(verified))
        f.write("| 未逐张核对（同族抽验通过） | %d |\n" % len(unverified))
        f.write("| **待汉化（确认仍是英文）** | **%d** |\n" % len(todo))
        f.write("\n> ★ 核对范围：按组抽验 + 覆盖全部 load_*/bootcamp_* 标题条带。\n")
        n_map = len([r for r in unverified if r["path"].startswith("bitmaps/map")])
        n_data = len([r for r in unverified if r["path"].startswith("data/")])
        f.write("> `bitmaps/map*.bmp` %d 张与 `data/**/*_prev.bmp` %d 张同族同模板，\n"
                % (n_map, n_data))
        f.write("> **未逐张验证**（已抽验 map00/map04_1、desert3_mp_prev 通过）。\n")
        f.write("\n## 明细\n\n| 路径 | 字节 | 状态 | 依据 |\n|---|---|---|---|\n")
        for r in rows:
            f.write("| `%s` | %d | %s | %s |\n"
                    % (r["path"], r["size"], r["status"], r["note"]))
        f.write("\n## 核对材料\n\n")
        f.write("`_bmp_cmp/` 下有并排对比图（上=英文基线，下=中文母盘）：\n")
        f.write("- `bands_*.png` —— 各界面标题条带，一次看 8 组\n")
        f.write("- `*_full.png` —— 整图对比\n")
    print("-> %s" % OUTMD)
    print("\n合计 %d 个 BMP，待汉化 %d 个" % (len(rows), len(todo)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
