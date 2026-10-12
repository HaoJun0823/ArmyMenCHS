"""
由配对 CSV 生成 DLL 消费的 INI 翻译数据文件。

输入：pair_tables.py 产出的 CSV
      (index, en_rva, en_fileoff, english, capacity, chs_official, need_translate)
输出：strings/*.ini —— DLL 运行时读取

对 need_translate=NEED 的条目（官方未译），译文留空并标 TODO，
交由人工填写；已译条目直接使用官方译文。

用法：
    python emit_ini.py <pair.csv> <out.ini> [--block-name NAME]
"""

import sys
import csv
import os

# 官方未译、需人工补译的条目：此处给出建议译文（可人工覆盖）
SUGGESTED = {
    "Sarge": ("中士", ""),
    "Truck": ("卡车", ""),
    "HalfTrack": ("半履带车", ""),
    "Tank": ("坦克", ""),
    "Jeep": ("吉普车", ""),
    "No Vehicle": ("无车辆", ""),
    "No Weapon": ("无武器", ""),
    "Tower Rifle": ("塔步枪", "[疑] 疑为哨塔步枪"),
    "Mine": ("地雷", ""),
    "Detonator": ("起爆器", ""),
    "Mine Sweeper": ("扫雷器", ""),
    "Auto Rifle": ("自动步枪", ""),
    "Rifle": ("步枪", ""),
    "Mortar": ("迫击炮", ""),
    "Bazooka": ("火箭筒", ""),
    "Grenade": ("手榴弹", ""),
    "Flame Thrower": ("火焰喷射器", ""),
    "Heavy Machine Gun": ("重机枪", ""),
    "Medium Machine Gun": ("中机枪", ""),
    "Light Machine Gun": ("轻机枪", ""),
    "Large Cannon": ("大口径炮", ""),
    "No Item": ("无物品", ""),
    "Unknown Item Type": ("未知物品类型", ""),
    "Null Item": ("空物品", ""),
    "PillBox": ("碉堡", "[疑] 官方译'医疗箱'，疑误译；PillBox 为军事地堡"),
}


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return 1
    csv_in, out_path = args[0], args[1]
    block = args[args.index("--block-name") + 1] if "--block-name" in args else "UI Block"

    with open(csv_in, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("empty csv")
        return 1

    base_rva = rows[0]["en_rva"]
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    lines = []
    lines.append(f"; {block}")
    lines.append("; 自动生成 by Tools/exe_scan/emit_ini.py")
    lines.append("; 译文来源：中文官方 exe（1998 上海育碧）")
    lines.append("; need_translate 条目为官方未译，已按建议译文填充，请人工校对")
    lines.append("")
    lines.append("[Meta]")
    lines.append(f"BaseRVA={base_rva}")
    lines.append("Encoding=GBK")
    lines.append("Layout=packed4")
    lines.append(f"Count={len(rows)}")
    lines.append("")
    lines.append("[Entries]")
    lines.append("; 序号 = 中文译文    ; 英文原文 [备注]")

    n_todo = 0
    for r in rows:
        idx = r["index"]
        en = r["english"]
        cap = r["capacity"]
        official = r["chs_official"]
        need = r["need_translate"] == "NEED"

        if need:
            if en in SUGGESTED:
                zh, note = SUGGESTED[en]
            else:
                zh, note = "", "TODO"
                n_todo += 1
        else:
            zh = official
            note = ""
            # 官方译文存疑的，覆盖并标注
            if en in SUGGESTED and SUGGESTED[en][1]:
                zh, note = SUGGESTED[en]

        remark = f" ; {en}"
        if note:
            remark += f" [{note}]"
        if cap:
            remark += f" cap={cap}"
        lines.append(f"{idx}={zh}{remark}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"written {out_path}")
    print(f"  entries : {len(rows)}")
    print(f"  base    : {base_rva}")
    print(f"  todo    : {n_todo} (需人工补译)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
