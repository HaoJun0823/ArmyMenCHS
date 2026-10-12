"""
构建 Army1_NEW_CHS —— 汉化补丁载荷（游戏原生目录布局）

设计（与 CI 配合）：
    Army1_NEW_CHS/   只放"与 Steam 不同"的文件，目录名与游戏一致，
                     可直接整树复制到游戏安装目录。
    Army1_Object_CHS/ objects.dat 解包后的差异对象块，CI 时再用
                     pack_diff.py 打包回 objects.dat。

    CI 流程：
        1. 复制 Army1_NEW_CHS/*  → 游戏目录
        2. pack_diff.py <游戏 objects.dat> Army1_Object_CHS/<T> → 覆盖
        3. 复制 Army1_Extend_Dll（含 ini/strings/Release dll）

目录布局（对齐 玩具兵大战1\\ 与 Steam 版）：
    Audio\\  AVI\\  Campaigns\\  Maps\\  Screens\\  Stratmap\\
    （Alpine/Bayou/Desert 的 objects.dat 由 Object_CHS 处理，
      其余文件与 Steam 相同，不需下发）

用法：
    python build_new_chs.py [--root G:\\Projects\\ArmyMenCHS] [--dry-run]
                            [--full-dirs]
"""

import os
import sys
import shutil
import hashlib

# (源相对路径, 目标相对路径, 是否全量下发)
# 视频按用户要求全量下发：中文版部分帧含汉化内容（已用逐帧差异分析确认），
# 逐帧判定成本高，直接以中文版为准，与凱風补丁行为一致。
DIR_MAP = [
    ("audio",          "Audio",        False),
    ("video",          "AVI",          True),
    ("text/campaigns", "Campaigns",    False),
    ("text/maps",      "Maps",         False),
    ("ui/Screens",     "Screens",      False),
    ("ui/Stratmap",    "Stratmap",     False),
]

# 在这些目录里，还要从 maps/Maps 合并 .rul / .txt / .BMP
MAPS_SRC = "maps/Maps"


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def walk(base):
    out = {}
    if not os.path.isdir(base):
        return out
    for root, _, files in os.walk(base):
        for fn in files:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, base).replace("\\", "/")
            out[rel] = full
    return out


def main():
    args = sys.argv[1:]
    # root 由 __file__ 的父目录推导（Tools/ -> 仓库根），不写死绝对路径
    root = (args[args.index("--root") + 1] if "--root" in args else
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    dry = "--dry-run" in args
    full_dirs = "--full-dirs" in args

    steam = os.path.join(root, "Army1_Original")
    chs = os.path.join(root, "Army1_CHS")
    dst = os.path.join(root, "Army1_NEW_CHS")
    if not os.path.isdir(steam) or not os.path.isdir(chs):
        print("missing source dirs")
        return 1

    if os.path.isdir(dst) and not dry:
        # 目录内文件可能被占用，逐个删除并容错
        for r_, d_, f_ in os.walk(dst, topdown=False):
            for fn_ in f_:
                try:
                    os.chmod(os.path.join(r_, fn_), 0o666)
                    os.remove(os.path.join(r_, fn_))
                except OSError: pass
            for dn_ in d_:
                try: os.rmdir(os.path.join(r_, dn_))
                except OSError: pass
    if not dry:
        os.makedirs(dst, exist_ok=True)

    print(f"build Army1_NEW_CHS  dry_run={dry}  full_dirs={full_dirs}")
    print()
    report = []
    total_ship = 0
    total_bytes = 0

    for src_rel, dst_rel, always in DIR_MAP:
        s_dir = os.path.join(steam, src_rel.replace("/", os.sep))
        c_dir = os.path.join(chs, src_rel.replace("/", os.sep))
        d_dir = os.path.join(dst, dst_rel.replace("/", os.sep))

        s_files = walk(s_dir)
        c_files = walk(c_dir)
        if not s_files and not c_files:
            continue

        # 并集（中文可能多出文件）
        rels = sorted(set(s_files) | set(c_files))
        ship = 0
        ship_b = 0
        for rel in rels:
            sp = s_files.get(rel)
            cp = c_files.get(rel)
            use = None
            if cp and sp:
                if always or full_dirs:
                    use = cp
                elif sha256(cp) != sha256(sp):
                    use = cp          # 中文有差异 → 下发
            elif cp and not sp:
                use = cp              # 中文独有 → 下发
            if not use:
                continue
            out_path = os.path.join(d_dir, rel.replace("/", os.sep))
            if not dry:
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                if os.path.exists(out_path):
                    try: os.chmod(out_path, 0o666)
                    except OSError: pass
                shutil.copyfile(use, out_path)
            ship += 1
            ship_b += os.path.getsize(use)
        if ship:
            total_ship += ship
            total_bytes += ship_b
        report.append(f"  {dst_rel:<12} ship={ship:<4} ({ship_b/1024:8.0f} KB)")

    # Maps：额外从 maps/Maps 合并差异 .BMP / .rul / .txt
    ms = walk(os.path.join(steam, MAPS_SRC.replace("/", os.sep)))
    mc = walk(os.path.join(chs, MAPS_SRC.replace("/", os.sep)))
    d_dir = os.path.join(dst, "Maps")
    ship = ship_b = 0
    for rel in sorted(set(ms) | set(mc)):
        sp = ms.get(rel)
        cp = mc.get(rel)
        use = None
        if cp and sp:
            if full_dirs:
                use = cp
            elif sha256(cp) != sha256(sp):
                use = cp
        elif cp and not sp:
            use = cp
        if not use:
            continue
        out_path = os.path.join(d_dir, rel.replace("/", os.sep))
        if not dry:
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            if os.path.exists(out_path):
                try: os.chmod(out_path, 0o666)
                except OSError: pass
            shutil.copyfile(use, out_path)
        ship += 1
        ship_b += os.path.getsize(use)
    total_ship += ship
    total_bytes += ship_b
    report.append(f"  {'Maps(合并)':<12} ship={ship:<4} ({ship_b/1024:8.0f} KB)")

    for r in report:
        print(r)
    print()
    print(f"下发文件: {total_ship} ({total_bytes/1024/1024:.1f} MB)")
    if not dry:
        n = sum(len(f) for _, _, f in os.walk(dst))
        print(f"实际写出: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
