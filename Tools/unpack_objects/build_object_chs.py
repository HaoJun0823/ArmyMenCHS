"""
构建 Army1_Object_CHS：只提取"确实被本地化"的对象块。

设计（与 CI 配合）：
    Object_CHS 存放解包后的**差异对象块**（默认 cat18/44-47 = 已验证的中文 UI 贴图）。
    CI 打包时以 Steam objects.dat 为基底，把这些块覆盖上去：

        pack_diff.py <steam objects.dat> Army1_Object_CHS/<T> out.dat \
                     --categories 18 44 45 46 47

    ★ cat 17 (Building) **不在此列表**：
      Alpine 的 cat 17 有 4 个差异块（num 328/903 的 dmg0/dmg1），经目视与
      像素比对确认两版视觉完全一致、**无任何中文**，唯一差异是 1998 母盘
      多了碰撞掩膜（maskSize 5264/5824）——正是「高山第三关羊肠河吉普车
      被油桶卡住」的成因。故保持 Steam 版，不纳入覆盖。

为什么不必担心"尺寸不一致损坏文件"（已实测验证）：
    objects.dat 目录表存 (key, offset)，每个对象块自带完整头部
    (key/width/height/flags/hotspot/linkspot/graphicSize + 数据 + shadow + mask + maskRect)，
    块长度本就可变。pack 阶段顺序写入并重算 offset，不存在等长约束。
    实测：覆盖 41 个差异 key 后文件 11477687 -> 11488775（+11088 字节），
    1674 个块头部全部合法，key 集合不变。

用法：
    python build_object_chs.py [--root G:\\Projects\\ArmyMenCHS]
                               [--categories 18 44 45 46 47] [--keep-full]
"""

import os
import sys
import json
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from objects_dat import split_key, parse_header, parse_table

DEFAULT_CATS = {18, 44, 45, 46, 47}


def load_objects(path):
    """返回 {key: bytes}。"""
    with open(path, "rb") as f:
        buf = f.read()
    _, _, nobj = parse_header(buf)
    entries = parse_table(buf, nobj)
    order = sorted(range(nobj), key=lambda i: entries[i][1])
    data = {}
    for pos, i in enumerate(order):
        s = entries[i][1]
        e = entries[order[pos + 1]][1] if pos + 1 < len(order) else len(buf)
        data[entries[i][0]] = buf[s:e]
    return data


def main():
    args = sys.argv[1:]
    # root 由 __file__ 上溯两层推导（Tools/unpack_objects -> 仓库根），
    # 不写死绝对路径，保证在任何 clone 位置都能跑
    root = (args[args.index("--root") + 1] if "--root" in args else
            os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))))
    cats = set(DEFAULT_CATS)
    if "--categories" in args:
        i = args.index("--categories") + 1
        cats = set()
        while i < len(args) and not args[i].startswith("--"):
            cats.add(int(args[i]))
            i += 1

    src = os.path.join(root, "Army1_Object_CHS")
    chs = os.path.join(root, "Army1_CHS", "terrain")
    steam = os.path.join(root, "Army1_Original", "terrain")

    print(f"Object_CHS: {src}")
    print(f"categories: {sorted(cats)}")
    print()

    total_kept = 0
    total_removed = 0
    report = []

    for terrain in ("Alpine", "Bayou", "Desert"):
        tdir = os.path.join(src, terrain)
        man_path = os.path.join(tdir, "manifest.json")
        if not os.path.isfile(man_path):
            report.append(f"  {terrain:<8} SKIP (no manifest)")
            continue

        with open(man_path, "r", encoding="utf-8") as f:
            man = json.load(f)

        # Steam 基底：只保留「与它确实不同」的块，避免存冗余
        steam_objs = load_objects(os.path.join(steam, terrain, "objects.dat"))
        chs_objs = load_objects(os.path.join(chs, terrain, "objects.dat"))

        raw_dir = os.path.join(tdir, "raw")
        kept = removed = 0
        kept_bytes = 0
        orphan = 0
        for o in man["objects"]:
            in_cat = o["category"] in cats
            fp = os.path.join(raw_dir, o["file"])
            has_file = os.path.isfile(fp)

            # ★ 幂等性修复（本脚本会删除 raw/ 文件，故必须可重复运行）：
            #   若 raw/<file> 已被上一次运行删除，则不能因为"读不到文件"
            #   就判定"与 Steam 不同" —— 那会让所有块在第二次运行时
            #   全部被重新标记为 included（实测 37 -> 273）。
            #   正确做法：始终从**中文母盘原始对象**读取待比较的数据，
            #   raw/ 只是缓存，缺失时可随时从母盘重新导出。
            #   注意变量名不要叫 src —— 它会遮蔽外层的目录路径 str。
            chs_blob = chs_objs.get(o["key"])
            if chs_blob is None or o["key"] not in steam_objs:
                same_as_steam = True          # 无法比较 -> 视为不需要覆盖
            else:
                same_as_steam = (chs_blob == steam_objs[o["key"]])

            inc = in_cat and not same_as_steam
            o["included"] = inc
            o["same_as_steam"] = same_as_steam
            if inc:
                kept += 1
                kept_bytes += o["size"]
                if not has_file:
                    orphan += 1
            else:
                if has_file:
                    os.remove(fp)
                removed += 1

        # 记录来源与打包指令
        man["_source"] = f"Army1_CHS/terrain/{terrain}/objects.dat"
        man["_base"] = f"Army1_Original/terrain/{terrain}/objects.dat"
        man["_included_categories"] = sorted(cats)
        man["_included_count"] = kept
        man["_note"] = ("raw/ 仅含 included=true 的对象块；"
                        "CI 用 pack_diff.py 覆盖到 Steam 基底上。"
                        "若 raw/ 丢失，用 objects_dat.py unpack 从 _source 重建。")
        if orphan:
            print(f"  !! {terrain}: {orphan} 个 included 块在 raw/ 中缺失，"
                  f"需重新 unpack")

        with open(man_path, "w", encoding="utf-8") as f:
            json.dump(man, f, indent=2, ensure_ascii=False)

        total_kept += kept
        total_removed += removed
        report.append(f"  {terrain:<8} kept={kept:<4} ({kept_bytes/1024:.0f} KB)"
                      f"  removed={removed:<5}")

    for r in report:
        print(r)
    print()
    print(f"合计: 保留 {total_kept} 个对象块, 移除 {total_removed} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
