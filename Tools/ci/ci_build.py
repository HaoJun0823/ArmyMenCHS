"""
CI 构建入口：把汉化载荷组装成可直接复制到游戏目录的成品。

流程（与你设计的 CI 一致）：
    1. 复制 Army1_NEW_CHS/*            -> 输出目录（游戏原生布局）
    2. pack_diff.py 打包 objects.dat   -> 输出目录 <Terrain>/objects.dat
    3. 复制 Army1_Extend_Dll 运行文件  -> 输出目录（dll + ini + strings）
    4. 生成 MANIFEST 与校验报告

产物目录结构（= 游戏安装目录布局）：
    out\
    ├─ Audio/  AVI/  Campaigns/  Maps/  Screens/
    ├─ Alpine/objects.dat  Bayou/objects.dat  Desert/objects.dat
    ├─ Army1_Extend_Dll.dll
    ├─ ArmyMenCHS.ini
    └─ strings/*.ini

用法：
    python ci_build.py [--root G:\\Projects\\ArmyMenCHS] [--out dist] [--verify]
"""

import os
import sys
import shutil
import subprocess
import hashlib

TERRAINS = ("Alpine", "Bayou", "Desert")

# ★ 只覆盖"确实是汉化"的分类。
#   cat 17 (Building) 的 4 个差异块经目视 + 像素比对证明**无中文**，
#   且携带导致「高山第三关羊肠河吉普车被油桶卡住」的额外碰撞掩膜
#   （1998 母盘 maskSize=5264/5824，Steam v1.2 已删除），
#   故**不纳入覆盖范围** —— 保持 Steam 版即无此 bug，且不损失任何汉化。
LOCALIZED_CATS = "18 44 45 46 47"

# ★ 需要剥离碰撞掩膜的 key（防御性保险）。
#   基底已是 Steam v1.2（本来就无掩膜），因此当前构建下这 4 个 key
#   会报告 "0 actually stripped" —— 这是**预期结果**，不是失败。
#   保留此列表的意义：万一将来有人把基底换成中文母盘，规则会自动生效。
STRIP_MASK_KEYS = {
    "Alpine": [567552, 567553, 585952, 585953],
    "Bayou": [],
    "Desert": [],
}


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def copy_tree(src, dst, stats):
    if not os.path.isdir(src):
        return
    for root, _, files in os.walk(src):
        for fn in files:
            sp = os.path.join(root, fn)
            rel = os.path.relpath(sp, src)
            dp = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(dp), exist_ok=True)
            if os.path.exists(dp):
                try:
                    os.chmod(dp, 0o666)
                except OSError:
                    pass
            shutil.copyfile(sp, dp)
            stats["files"] += 1
            stats["bytes"] += os.path.getsize(sp)


def main():
    args = sys.argv[1:]
    # ★ root 必须由 __file__ 推导，不能写死绝对路径：
    #   CI 在 ubuntu runner 上跑，仓库位于 $GITHUB_WORKSPACE。
    #   写死 G:\Projects\... 会让脚本把 build_out 输出到不存在的盘符下，
    #   随后 make_patch/verify 校验空目录，报错信息完全误导。
    here = os.path.dirname(os.path.abspath(__file__))
    root = (args[args.index("--root") + 1] if "--root" in args else
            os.path.dirname(os.path.dirname(here)))
    out_name = args[args.index("--out") + 1] if "--out" in args else "dist"
    verify = "--verify" in args

    tool = os.path.join(here, "..", "unpack_objects")
    pack = os.path.normpath(os.path.join(tool, "pack_diff.py"))
    new_chs = os.path.join(root, "Army1_NEW_CHS")
    obj_chs = os.path.join(root, "Army1_Object_CHS")
    dll_dir = os.path.join(root, "Army1_Extend_Dll")
    steam_terrain = os.path.join(root, "Army1_Original", "terrain")

    out = os.path.join(root, out_name)
    if os.path.isdir(out):
        for r_, d_, f_ in os.walk(out, topdown=False):
            for fn_ in f_:
                try:
                    os.chmod(os.path.join(r_, fn_), 0o666)
                    os.remove(os.path.join(r_, fn_))
                except OSError:
                    pass
            for dn_ in d_:
                try:
                    os.rmdir(os.path.join(r_, dn_))
                except OSError:
                    pass
    os.makedirs(out, exist_ok=True)

    stats = {"files": 0, "bytes": 0}
    print(f"CI build -> {out}")
    print()

    # 1. 载荷
    for d in ("Audio", "AVI", "Campaigns", "Maps", "Screens", "Stratmap"):
        s = os.path.join(new_chs, d)
        if os.path.isdir(s):
            n0 = stats["files"]
            copy_tree(s, os.path.join(out, d), stats)
            print(f"  [1] {d:<12} +{stats['files']-n0} files")
    print()

    # 2. objects.dat
    #    注意：这里以 **中文母盘的 objects.dat 结构** 为基底不行 ——
    #    必须用 Steam 原版做基底，才能保住非汉化精灵的画质。
    for t in TERRAINS:
        odir = os.path.join(obj_chs, t)
        base = os.path.join(steam_terrain, t, "objects.dat")
        dst_dir = os.path.join(out, t)
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, "objects.dat")
        cmd = [sys.executable, pack, base, odir, dst,
               "--categories"] + LOCALIZED_CATS.split()
        sk = STRIP_MASK_KEYS.get(t) or []
        if sk:
            cmd += ["--strip-mask"] + [str(k) for k in sk]
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            print(f"  [2] {t:<8} PACK FAILED\n{r.stderr}")
            return 1
        for l in r.stdout.splitlines():
            if l.startswith("result") or l.startswith("strip"):
                print(f"  [2] {t:<8} {l}")
        stats["files"] += 1
        stats["bytes"] += os.path.getsize(dst)
    print()

    # 3. DLL + 配置
    dll_src = os.path.join(dll_dir, "Release", "Army1_Extend_Dll.dll")
    if os.path.isfile(dll_src):
        shutil.copyfile(dll_src, os.path.join(out, "Army1_Extend_Dll.dll"))
        stats["files"] += 1
        stats["bytes"] += os.path.getsize(dll_src)
        print(f"  [3] Army1_Extend_Dll.dll")
    else:
        print(f"  [3] DLL 未编译（跳过）: {dll_src}")

    for f in ("ArmyMenCHS.ini",):
        s = os.path.join(dll_dir, f)
        if os.path.isfile(s):
            shutil.copyfile(s, os.path.join(out, f))
            stats["files"] += 1
            print(f"      {f}")

    sdir = os.path.join(dll_dir, "strings")
    if os.path.isdir(sdir):
        copy_tree(sdir, os.path.join(out, "strings"), stats)
        n = len(os.listdir(sdir))
        print(f"      strings\\ ({n} blocks)")
    print()

    print(f"总计: {stats['files']} 文件 / {stats['bytes']/1024/1024:.1f} MB")

    if verify:
        print()
        print("校验:")
        ok = True
        for t in TERRAINS:
            p = os.path.join(out, t, "objects.dat")
            if not os.path.isfile(p):
                print(f"  {t}: 缺失")
                ok = False
                continue
            print(f"  {t}: {os.path.getsize(p)} bytes  sha={sha256(p)[:12]}")
        print(f"  DLL: {'OK' if os.path.isfile(os.path.join(out,'Army1_Extend_Dll.dll')) else '缺失'}")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
