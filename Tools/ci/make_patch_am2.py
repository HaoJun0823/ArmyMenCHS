# -*- coding: utf-8 -*-
"""把 build_out_am2 组装成**可直接解压到游戏根目录**的汉化补丁。

★ 与 1 代 Tools/ci/make_patch.py **同构**（刻意保持一致的布局与做法）：
    <Game>\\
      ├─ dinput.dll                 ASI Loader（asi/dsound.dll 改名；见下方 ★）
      ├─ 必读说明.txt
      ├─ 如果不会安装，请把该文件发给AI，让AI教你.txt
      ├─ 将此文件交给AI，让AI协助完善本项目.txt
      ├─ LICENSE                     项目主许可（含游戏版权声明）
      ├─ License.txt                 LICENSES/*.txt 合并，供随包分发
      ├─ Disable_AM2ExeWinCompatShim.reg    ← 2 代特有（1 代无此需求）
      ├─ Restore_AM2ExeWinCompatShim.reg
      ├─ scripts\\
      │    Army2_Extend_Dll.asi      ← build_out 里叫 .dll，落包时改名
      │    ArmyMenCHS.ini
      │    Hzk16
      │    strings\\am2_strings.ini
      └─ update\\
           01-title audio avi bitmaps data rules mpmaps.txt readme.txt
           shared.dat title.dat

★ 与 1 代的唯一结构差异是包根的 dinput.dll 名与两个 .reg：
    · 代理名不同：1 代用 dsound.dll；本作按**序号**导入 dsound.dll，
      而 UAL 导出表是多 DLL 合并表，序号 1 并非 DirectSoundCreate，
      沿用会让游戏拿到错误函数（无声音且无报错）。本作按**名字**导入
      dinput.dll!DirectInputCreateA，用该名作代理可可靠命中。
    · 两个 .reg 是 Steam 给 ArmyMen2.exe 打的兼容性 shim 的抵消/恢复脚本，
      1 代无此需求。它们来自仓库 compat/，随包原样分发（UTF-16LE + BOM）。

用法：
    python Tools/ci/make_patch_am2.py [--root <仓库根>] [--out stage_am2]

★ root 默认由 __file__ 上溯三层推导，CI 上无需显式传。
"""

import os
import shutil
import sys
import zipfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BUILD_OUT_NAME = "build_out_am2"

# build_out 下的内容，各自归入 scripts/ 或 update/
# ★ DLL 必须落名为 .asi：Ultimate ASI Loader 只扫描 scripts\*.asi，
#   .dll 直接放进去不会被加载。
DLL_SRC = "Army2_Extend_Dll.dll"
DLL_DST = "scripts/Army2_Extend_Dll.asi"
SCRIPTS_FILES = ["ArmyMenCHS.ini", "Hzk16"]
SCRIPTS_DIRS = ["strings"]
# update/ 的内容 = build_out 里除运行期文件之外的一切（目录名与游戏一致）
RUNTIME_TOP = {"Army2_Extend_Dll.dll", "ArmyMenCHS.ini", "Hzk16",
               "strings", "MANIFEST.json", "MANIFEST.md"}

# ASI Loader 源。
# ★ 用仓库内 asi/dsound.dll（Ultimate ASI Loader，MIT，已入库）——
#   与 1 代 make_patch.py 的 ASI_LOADER_SRC 指向**同一个文件**。
#   早先这里有四个候选路径（含 I:\ 本机盘符与已 gitignore 的 stage/、dist/），
#   CI 上拿不到就失败、本地却因为文件在而看不出问题。
#   教训：构建输入必须来自**仓库内已跟踪**的路径。现在只留一条。
ASI_LOADER_SRC = "asi/dsound.dll"
PROXY_NAME = "dinput.dll"           # ★ 见文件头说明（与 1 代的 dsound.dll 不同）

# 仓库根 LICENSE（项目主许可）-> 包根 LICENSE
LICENSE_SRC = "LICENSE"
# 包内说明：与 1 代同一套约定（统一标准 S11，名为「必读说明.txt」），
# 但 2 代单独一份源文件，避免两代说明混在一起。
README_SRC = "Documents/必读说明_玩具兵大战II.txt"
README_DST = "必读说明.txt"
# 两份 AI 辅助文件（统一标准 S12/S13），与必读说明同源目录，随包分发到包根
AI_FILES = [
    "如果不会安装，请把该文件发给AI，让AI教你.txt",
    "将此文件交给AI，让AI协助完善本项目.txt",
]
LICENSE_DIR = "LICENSES"
# 合并顺序：先第三方（随包分发者），最后 GPLv3.txt 作为主许可正文
LICENSE_ORDER = ["ASILoader.txt", "GPLv3.txt"]

# Windows 兼容性 shim 的抵消/恢复脚本（2 代特有，来自仓库 compat/）
COMPAT_REG_DIR = "compat"
COMPAT_REGS = [
    "Disable_AM2ExeWinCompatShim.reg",
    "Restore_AM2ExeWinCompatShim.reg",
]


def sha256(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    a = sys.argv[1:]
    # ★ root 必须由 __file__ 推导，不能写死绝对路径：
    #   CI 在 Linux runner 上跑，仓库位于 $GITHUB_WORKSPACE。
    root = (a[a.index("--root") + 1] if "--root" in a else ROOT)
    out_name = a[a.index("--out") + 1] if "--out" in a else "stage_am2"

    build_out = os.path.join(root, BUILD_OUT_NAME)
    stage = os.path.join(root, out_name)

    if not os.path.isdir(build_out):
        print("!! 缺少 %s —— 请先跑 Tools/ci/ci_build_am2.py" % build_out,
              file=sys.stderr)
        return 1

    # 清理 stage：必须保证**没有陈旧文件混入**。
    #   ★ 不断言"整个目录能删掉"：Windows 上目录本身可能被索引器/杀软/
    #     Git 缓存临时持有句柄，rmtree(dir) 会 PermissionError，
    #     而那与"产物是否干净"无关。改为**清空内容**。
    if os.path.isdir(stage):
        for name in os.listdir(stage):
            p = os.path.join(stage, name)
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    os.remove(p)
                except OSError:
                    pass
    os.makedirs(os.path.join(stage, "scripts", "strings"), exist_ok=True)

    n = 0
    total = 0
    missing = []

    # ── 1) scripts/ —— DLL(改名为 .asi) + ini + Hzk16 + strings ─────────
    dll_sp = os.path.join(build_out, DLL_SRC)
    if os.path.isfile(dll_sp):
        dll_dp = os.path.join(stage, DLL_DST.replace("/", os.sep))
        os.makedirs(os.path.dirname(dll_dp), exist_ok=True)
        shutil.copyfile(dll_sp, dll_dp)
        n += 1
        total += os.path.getsize(dll_sp)
        print("   + %s  (%d B)" % (DLL_DST, os.path.getsize(dll_sp)))
    else:
        missing.append(DLL_SRC)

    for f in SCRIPTS_FILES:
        sp = os.path.join(build_out, f)
        if not os.path.isfile(sp):
            missing.append(f)
            continue
        shutil.copyfile(sp, os.path.join(stage, "scripts", f))
        n += 1
        total += os.path.getsize(sp)
        print("   + scripts/%s  (%d B)" % (f, os.path.getsize(sp)))

    for d in SCRIPTS_DIRS:
        sp = os.path.join(build_out, d)
        if not os.path.isdir(sp):
            missing.append(d)
            continue
        for root_, _, files in os.walk(sp):
            for fn in sorted(files):
                full = os.path.join(root_, fn)
                rel = os.path.relpath(full, build_out).replace(os.sep, "/")
                dp = os.path.join(stage, "scripts", rel)
                os.makedirs(os.path.dirname(dp), exist_ok=True)
                shutil.copyfile(full, dp)
                n += 1
                total += os.path.getsize(full)
                print("   + scripts/%s  (%d B)" % (rel, os.path.getsize(full)))

    if missing:
        print("!! build_out 中缺少: %s" % ", ".join(missing), file=sys.stderr)
        return 1

    # ── 2) update/ —— build_out 里除运行期文件外的一切 ──────────────────
    upd_dst = os.path.join(stage, "update")
    n_upd = 0
    for entry in sorted(os.listdir(build_out)):
        if entry in RUNTIME_TOP:
            continue
        sp = os.path.join(build_out, entry)
        if os.path.isfile(sp):
            rel = entry
            os.makedirs(upd_dst, exist_ok=True)
            shutil.copyfile(sp, os.path.join(upd_dst, rel))
            n += 1
            n_upd += 1
            total += os.path.getsize(sp)
        else:
            for root_, _, files in os.walk(sp):
                for fn in sorted(files):
                    full = os.path.join(root_, fn)
                    rel = os.path.relpath(full, build_out).replace(os.sep, "/")
                    dp = os.path.join(upd_dst, rel.replace("/", os.sep))
                    os.makedirs(os.path.dirname(dp), exist_ok=True)
                    shutil.copyfile(full, dp)
                    n += 1
                    n_upd += 1
                    total += os.path.getsize(full)
    print("   + update/  (%d 文件)" % n_upd)
    if n_upd == 0:
        print("!! update/ 为空 —— 载荷缺失，产物无意义", file=sys.stderr)
        return 1

    # ── 3) 包根附加文件 ────────────────────────────────────────────────
    def put_root(src_path, dst_name, label):
        nonlocal n, total
        if not os.path.isfile(src_path):
            missing.append(label)
            return
        shutil.copyfile(src_path, os.path.join(stage, dst_name))
        n += 1
        total += os.path.getsize(src_path)

    # ★ 这里**不做** PE 位数断言：UAL 的位数由 verify_release_am2.py
    #   独立校验（含导出表检查），构建侧只负责搬运，避免两处判据不一致。
    put_root(os.path.join(root, ASI_LOADER_SRC), PROXY_NAME,
             "%s (ASI Loader)" % ASI_LOADER_SRC)
    put_root(os.path.join(root, LICENSE_SRC), "LICENSE", LICENSE_SRC)

    # 必读说明.txt 写 UTF-8 **带 BOM**：Windows 记事本靠 BOM 判断编码，
    # 无 BOM 的 UTF-8 在旧版系统上会显示成乱码。目标用户是中文玩家，
    # 直接双击打开是首要场景。（与 1 代 make_patch.py 完全同一做法。）
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
        print("   + %s  (%d B, UTF-8 BOM)" % (README_DST, os.path.getsize(rp)))

    # 两份 AI 辅助文件（S12/S13）：同样 UTF-8 带 BOM + CRLF
    for ai in AI_FILES:
        ai_src = os.path.join(root, "Documents", ai)
        if not os.path.isfile(ai_src):
            missing.append("Documents/%s" % ai)
            continue
        ap = os.path.join(stage, ai)
        with open(ai_src, "r", encoding="utf-8") as fh:
            ai_txt = fh.read()
        with open(ap, "w", encoding="utf-8-sig", newline="\r\n") as fh:
            fh.write(ai_txt)
        n += 1
        total += os.path.getsize(ap)

    # Windows 兼容性 shim（2 代特有）：随包原样分发，**必须逐字节保真**
    # （UTF-16LE + BOM；任何换行转换都会让注册表导入报"不是有效的注册表脚本"）
    for reg in COMPAT_REGS:
        src = os.path.join(root, COMPAT_REG_DIR, reg)
        if not os.path.isfile(src):
            print("!! 缺少兼容性 shim 文件: %s" % src, file=sys.stderr)
            print("   必读说明里引用了它，缺了会让玩家照做时找不到文件。",
                  file=sys.stderr)
            return 1
        shutil.copyfile(src, os.path.join(stage, reg))
        n += 1
        total += os.path.getsize(src)
        print("   + %s  (%d B)" % (reg, os.path.getsize(src)))

    # License.txt：把 LICENSES/ 下各 txt 合并成一份，便于随包分发
    lic_dir = os.path.join(root, LICENSE_DIR)
    if not os.path.isdir(lic_dir):
        missing.append(LICENSE_DIR + "/")
    else:
        import os as _os
        files = sorted(f for f in _os.listdir(lic_dir)
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
            print("   + License.txt（合并 %d 份: %s）"
                  % (len(files), ", ".join(known + rest)))

    if missing:
        print("!! 缺少: %s" % ", ".join(missing), file=sys.stderr)
        return 1

    # ── 4) 打 zip（ASCII 文件名，GitHub 附件不支持中文）────────────────
    #    CI 里 upload-artifact 取 stage_am2/*.zip，所以 zip 落在 stage 下。
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    zname = "ArmyMen2-CHS-Patch-%s.zip" % stamp
    zpath = os.path.join(stage, zname)

    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=6) as z:
        for root_, _, files in os.walk(stage):
            for fn in sorted(files):
                full = os.path.join(root_, fn)
                rel = os.path.relpath(full, stage).replace(os.sep, "/")
                if rel == zname:          # 别把上一次残留的 zip 打进自己
                    continue
                z.write(full, rel)

    # 自证：zip 必须真的能打开且条目数与非压缩文件数一致
    #   （防"声称打了包但实际是空 zip/损坏 zip"）
    with zipfile.ZipFile(zpath) as z:
        bad = z.testzip()
        if bad is not None:
            print("!! zip 校验失败: %s" % bad, file=sys.stderr)
            return 1
        n_zip = len(z.namelist())

    print()
    print("stage: %s  (%d 文件 / %.1f MB)" % (stage, n, total / 1048576))
    print("zip  : %s  (%.2f MB)"
          % (zpath, os.path.getsize(zpath) / 1048576))
    if n_zip != n:
        print("!! zip 条目数 %d != stage 文件数 %d" % (n_zip, n), file=sys.stderr)
        return 1
    print("     zip 自检通过：%d 条目，CRC 全部正确" % n_zip)

    for key in ("scripts/Army2_Extend_Dll.asi", "scripts/Hzk16", PROXY_NAME,
                "LICENSE", "License.txt", README_DST):
        p = os.path.join(stage, key.replace("/", os.sep))
        if os.path.isfile(p):
            print("  %-34s %9d  sha=%s" % (key, os.path.getsize(p),
                                           sha256(p)[:16]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
