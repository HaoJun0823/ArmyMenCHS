"""
把 build_out 组装成**可直接解压到游戏根目录**的汉化补丁。

★ 目录布局遵循用户约定（asi loader 把 update/ 当工作目录并覆盖游戏视图）：
    <Game>\\
      ├─ dsound.dll                  ASI Loader（Ultimate ASI Loader v6.4, MIT）
      ├─ 安装说明.txt
      ├─ LICENSE                     项目主许可（含游戏版权声明）
      ├─ License.txt                 LICENSES/*.txt 合并，供随包分发
      ├─ scripts\\
      │    Army1_Extend_Dll.asi      ← build_out 里叫 .dll，落包时改名
      │    ArmyMenCHS.ini
      │    strings\\*.ini
      └─ update\\
           Audio AVI Campaigns Maps Screens
           Alpine Bayou Desert

用法：
    python Tools/ci/make_patch.py [--root <仓库根>] [--out stage]

★ root 默认由 __file__ 上溯三层推导，CI 上无需显式传。
"""

import os
import sys
import shutil
import zipfile
import hashlib
from datetime import datetime, timezone

# build_out 下的内容，各自归入 scripts/ 或 update/
# ★ DLL 必须落名为 .asi：Ultimate ASI Loader 只扫描 scripts\*.asi，
#   .dll 直接放进去不会被加载（实测线上部署即为 Army1_Extend_Dll.asi）。
DLL_SRC = "Army1_Extend_Dll.dll"
DLL_DST = "scripts/Army1_Extend_Dll.asi"
SCRIPTS_ITEMS = ["ArmyMenCHS.ini", "strings"]
UPDATE_DIRS = ["Audio", "AVI", "Campaigns", "Maps", "Screens",
               "Alpine", "Bayou", "Desert"]

# ASI Loader（Win32 v6.4，ThirteenAG，MIT）。放在**包根**，与 scripts\ 同级。
# 游戏必须经由它加载 scripts\*.asi，缺了汉化完全不生效。
# 命名沿用 Ultimate ASI Loader 的惯例：dsound.dll 代理原版 dsound.dll。
ASI_LOADER_SRC = "asi/dsound.dll"
ASI_LOADER_DST = "dsound.dll"

# 仓库根 LICENSE（项目主许可，含游戏版权声明）-> 包根 LICENSE
LICENSE_SRC = "LICENSE"
README_SRC = "Documents/安装说明.txt"
README_DST = "安装说明.txt"
LICENSE_DIR = "LICENSES"
# 合并顺序：先第三方（随包分发者），最后 GPLv3.txt 作为主许可正文
LICENSE_ORDER = ["ASILoader.txt", "GPLv3.txt"]


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    a = sys.argv[1:]
    # ★ root 必须由 __file__ 推导，不能写死绝对路径：
    #   CI 在 Linux runner 上跑，仓库位于 $GITHUB_WORKSPACE，
    #   写死 G:\Projects\... 会让脚本把产物输出到不存在的盘符下。
    #   （ci_build.py / verify_release.py 同理，都从 __file__ 上溯三层。）
    root = (a[a.index("--root") + 1] if "--root" in a else
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))))
    out_name = a[a.index("--out") + 1] if "--out" in a else "stage"

    build_out = os.path.join(root, "build_out")
    stage = os.path.join(root, out_name)
    if os.path.isdir(stage):
        shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)

    n = 0
    total = 0
    missing = []

    def put(src_rel, dst_rel):
        nonlocal n, total
        sp = os.path.join(build_out, src_rel)
        dp = os.path.join(stage, dst_rel)
        if not os.path.isfile(sp):
            missing.append(src_rel)
            return
        os.makedirs(os.path.dirname(dp), exist_ok=True)
        shutil.copyfile(sp, dp)
        n += 1
        total += os.path.getsize(sp)

    # 1) scripts/ —— DLL(改名为 .asi) + ini + strings
    dll_sp = os.path.join(build_out, DLL_SRC)
    if os.path.isfile(dll_sp):
        dll_dp = os.path.join(stage, DLL_DST.replace("/", os.sep))
        os.makedirs(os.path.dirname(dll_dp), exist_ok=True)
        shutil.copyfile(dll_sp, dll_dp)
        n += 1
        total += os.path.getsize(dll_sp)
    else:
        missing.append(DLL_SRC)

    for it in SCRIPTS_ITEMS:
        sp = os.path.join(build_out, it)
        if os.path.isdir(sp):
            for f in sorted(os.listdir(sp)):
                if os.path.isdir(os.path.join(sp, f)):
                    continue
                put(it + "/" + f, "scripts/" + it + "/" + f)
        else:
            put(it, "scripts/" + it)

    # 2) update/ —— 载荷与地形包
    for d in UPDATE_DIRS:
        dp0 = os.path.join(build_out, d)
        if not os.path.isdir(dp0):
            missing.append(d)
            continue
        for root_, _, files in os.walk(dp0):
            for fn in sorted(files):
                sp = os.path.join(root_, fn)
                rel = os.path.relpath(sp, build_out).replace("\\", "/")
                put(rel, "update/" + rel)

    if missing:
        print("!! build_out 中缺少: %s" % ", ".join(missing), file=sys.stderr)
        return 1

    # 3) 包根附加文件：dsound.dll（ASI Loader）/ LICENSE / License.txt / 安装说明.txt
    def put_root(src_path, dst_name, label):
        """从仓库任意路径复制一个文件到包根。"""
        nonlocal n, total
        if not os.path.isfile(src_path):
            missing.append(label)
            return
        dp = os.path.join(stage, dst_name)
        shutil.copyfile(src_path, dp)
        n += 1
        total += os.path.getsize(src_path)

    put_root(os.path.join(root, ASI_LOADER_SRC), ASI_LOADER_DST,
             "%s (ASI Loader)" % ASI_LOADER_SRC)
    put_root(os.path.join(root, LICENSE_SRC), "LICENSE", LICENSE_SRC)

    # 安装说明.txt 写 UTF-8 **带 BOM**：Windows 记事本靠 BOM 判断编码，
    # 无 BOM 的 UTF-8 在旧版系统上会显示成乱码。目标用户是中文玩家，
    # 直接双击打开是首要场景。
    readme_src = os.path.join(root, README_SRC)
    if not os.path.isfile(readme_src):
        missing.append(README_SRC)
    else:
        rp = os.path.join(stage, README_DST)
        with open(readme_src, "r", encoding="utf-8") as fh:
            txt = fh.read()
        with open(rp, "w", encoding="utf-8-sig", newline="\r\n") as fh:
            fh.write(txt)
        n += 1
        total += os.path.getsize(rp)

    # License.txt：把 LICENSES/ 下各 txt 合并成一份，便于随包分发
    lic_dir = os.path.join(root, LICENSE_DIR)
    if not os.path.isdir(lic_dir):
        missing.append(LICENSE_DIR + "/")
    else:
        files = sorted(f for f in os.listdir(lic_dir)
                       if f.lower().endswith(".txt"))
        if not files:
            missing.append(LICENSE_DIR + "/ (无 txt)")
        else:
            known = [f for f in LICENSE_ORDER if f in files]
            rest = [f for f in files if f not in LICENSE_ORDER]
            bar = "=" * 78
            parts = []
            for f in known + rest:
                with open(os.path.join(lic_dir, f), "r",
                          encoding="utf-8-sig", errors="replace") as fh:
                    parts.append("%s\n== %s\n%s\n\n%s\n"
                                 % (bar, f, bar, fh.read().strip()))
            lp = os.path.join(stage, "License.txt")
            with open(lp, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("\n\n".join(parts) + "\n")
            n += 1
            total += os.path.getsize(lp)
            print("  License.txt 合并 %d 份: %s"
                  % (len(files), ", ".join(known + rest)))

    if missing:
        print("!! 缺少: %s" % ", ".join(missing), file=sys.stderr)
        return 1

    # 4) 打 zip（ASCII 文件名，GitHub 附件不支持中文）
    #    CI 里 upload-artifact 取 stage/*.zip，所以 zip 落在 stage/ 下；
    #    本地默认同时写一份到 dist/ 方便查找。
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    zname = "ArmyMen-CHS-Patch-%s.zip" % stamp
    zpaths = [os.path.join(stage, zname)]
    dist_dir = os.path.join(root, "dist")
    os.makedirs(dist_dir, exist_ok=True)
    if not os.path.samefile(stage, dist_dir):
        zpaths.append(os.path.join(dist_dir, zname))

    for zpath in zpaths:
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED,
                             compresslevel=6) as z:
            for root_, _, files in os.walk(stage):
                for fn in sorted(files):
                    full = os.path.join(root_, fn)
                    rel = os.path.relpath(full, stage).replace("\\", "/")
                    if rel == zname:          # 别把上一次残留的 zip 打进自己
                        continue
                    z.write(full, rel)

    print("stage: %s  (%d 文件 / %.1f MB)" % (stage, n, total / 1024 / 1024))
    for zpath in zpaths:
        print("zip  : %s  (%.1f MB)"
              % (zpath, os.path.getsize(zpath) / 1024 / 1024))
    for key in ("update/Alpine/objects.dat", DLL_DST, ASI_LOADER_DST,
                "LICENSE", "License.txt", README_DST):
        p = os.path.join(stage, key.replace("/", os.sep))
        if os.path.isfile(p):
            print("  %-34s %9d  sha=%s" % (key, os.path.getsize(p),
                                          sha256(p)[:16]))
    return 0


if __name__ == "__main__":
    sys.exit(main())