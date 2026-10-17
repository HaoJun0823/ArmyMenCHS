# -*- coding: utf-8 -*-
r"""把 build_out_am5 组装成**可直接解压到游戏根目录**的 4 代汉化补丁
（《空中战术》/ Air Tactics；目录号 Army5 = 第 5 个做，代次按系列序号算）。

★ 编号说明：目录号 `Army5_*` 是**汉化施工批次**（第 5 个做），
  游戏系列的**第 4 代**是 Air Tactics（本作），第 5 代是 World War（`Army4_*`）。
  面向玩家的说明一律按系列序号称呼。

★ 与其他各代 Tools/ci/make_patch*.py **同构**，但包内结构不同 ——
  这一代没有 dat、没有 rules\、没有 01-title\，界面文本走游戏自己的
  update\strings\，贴图走 update\bitmaps\ + update\data\：

    <游戏>\
      ├─ dinput.dll               ASI Loader（asi/dsound.dll 改名；见下方 ★）
      ├─ ddraw.dll                cnc-ddraw（本作渲染所需，直接落包根）
      ├─ ddraw.ini                cnc-ddraw 配置
      ├─ LICENSE                  项目主许可（仓库根 LICENSE）
      ├─ License.txt              LICENSES/*.txt 合并，供随包分发
      ├─ 必读说明.txt             安装说明（UTF-8 带 BOM + CRLF）
      ├─ 如果不会安装，请把该文件发给AI，让AI教你.txt
      ├─ 将此文件交给AI，让AI协助完善本项目.txt
      ├─ scripts\
      │    Army5_Extend_Dll.asi   ← build_out 里叫 .dll，落包时改名
      │    Hzk16                  ← 中文字库（13x13 点阵；ASI 按 DLL 目录找）
      ├─ audio\                   ← ★ 包根（codesfx / music / scriptsfx）
      ├─ avi\                     ← ★ 包根（cine1..6.smk 中文片头）
      └─ update\
            bitmaps\  data\  strings\
            audio\voice\*.wav     ← 中文配音（qwen3-tts）

★ 为什么 audio\ 与 avi\ 在包根而不是 update\ 下：
  本作只在 update\ 里找**覆盖**资源，audio\ 与 avi\ 是游戏原生目录，
  必须落在包根才能真正替换（已用实机目录逐字节核对：audio 288 /
  avi 7 / update 678 与实机完全一致）。这是本代与其他代最大的落位差异，
  照抄其他代的"全部塞进 update\"会导致片头与配乐不生效。

★ 为什么代理必须落名为 dinput.dll 而不是随便一个名字：
  amat.exe 的导入表**按名字**导入 DINPUT!DirectInputCreateA（见
  docs/15 §1），代理名不对，游戏拿不到输入函数 —— 表现是
  "补丁装了但中文完全不出现且无报错"。

★ 包根说明与许可（与其他各代同一套约定 S11/S12/S13）：
    LICENSE      <- 仓库根 LICENSE（项目主许可，含游戏版权声明）
    License.txt  <- LICENSES/*.txt 合并：ASILoader + cnc-ddraw + qwen3-tts
                    + GPLv3。★ 三方组件的许可要求随产物分发时附上声明。
    必读说明.txt <- Documents/必读说明_空中战术.txt，写 UTF-8 **带 BOM** +
                    CRLF（Windows 记事本靠 BOM 判编码）
    AI 辅助文件  <- 与其他各代同源的两份 txt，同样 BOM + CRLF

★ 本脚本**不含产物断言**（不查文件条数 / 体积 / sha256）：
  判定标准是"每一步正常返回 0"。产物对不对由解压后实机运行确认。

用法：
    python Tools/ci/make_patch_am5.py [--root <仓库根>] [--out stage_am5]

★ root 默认由 __file__ 上溯三层推导，CI 上无需显式传。
"""

import os
import shutil
import sys
import zipfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BUILD_OUT_NAME = "build_out_am5"

# ★ DLL 必须落名为 .asi：Ultimate ASI Loader 只扫描 scripts\*.asi，
#   .dll 直接放进去不会被加载。
DLL_SRC = "Army5_Extend_Dll.dll"
DLL_DST = "scripts/Army5_Extend_Dll.asi"

# scripts\ 下的运行期文件（本代无 ini：译文全在游戏的 update\strings\）
SCRIPTS_FILES = ["Hzk16"]

# 包根文件：由 build_out 直接搬（cnc-ddraw 的 ddraw.dll / ddraw.ini）
ROOT_FROM_BUILD = ["ddraw.dll", "ddraw.ini"]

# build_out 里除运行期/包根文件外的一切 -> 按原名落包根
#   ★ 本代的 audio\ avi\ update\ 各自保持顶层，不合并进 update\。
RUNTIME_TOP = {DLL_SRC, "Hzk16"} | set(ROOT_FROM_BUILD)

# ASI Loader 源。★ 必须是**仓库内已跟踪**的路径：
#   asi/dsound.dll 是 Ultimate ASI Loader（MIT，已入库），与其他各代同一份。
ASI_LOADER_SRC = "asi/dsound.dll"
PROXY_NAME = "dinput.dll"           # ★ 见文件头说明

# 仓库根 LICENSE（项目主许可）-> 包根 LICENSE
LICENSE_SRC = "LICENSE"
# 包内说明：与其他各代同一套约定（统一标准 S11，名为「必读说明.txt」），
# 本代单独一份源文件，避免各代说明混在一起。
README_SRC = "Documents/必读说明_空中战术.txt"
README_DST = "必读说明.txt"
# 两份 AI 辅助文件（统一标准 S12/S13），与必读说明同源目录，随包分发到包根
AI_FILES = [
    "如果不会安装，请把该文件发给AI，让AI教你.txt",
    "将此文件交给AI，让AI协助完善本项目.txt",
]
LICENSE_DIR = "LICENSES"
# ★ 显式清单，不是"目录里有什么就合什么"：LICENSES/ 是各代共用目录，
#   1 代包不该混进只有本代才用到的 qwen3-tts 声明（反之亦然）。
#   合并顺序：先随包分发的第三方（UAL / cnc-ddraw / qwen3-tts），
#   最后 GPLv3.txt 作为主许可正文。
LICENSE_ORDER = ["ASILoader.txt", "cnc-ddraw.txt", "qwen3-tts.txt", "GPLv3.txt"]

# ── Release 附件名 ─────────────────────────────────────────────────────
#   ★ 固定短名，**不带**日期时间戳（唯一性由 Release 的 tag 保证）。
#     按**游戏系列序号**命名，不按目录号：
#       3 代 太空玩具  -> armymen_TIS.zip   (make_patch_am3.py)
#       4 代 空中战术  -> armymen_AT.zip    (本脚本)
#       5 代 世界大战  -> armymen_WW.zip    (make_patch_am4.py)
#     1/2 代仍是 ArmyMen-CHS-Patch-<stamp>.zip / ArmyMen2-...
ZIP_STEM = "armymen_AT"


def main():
    a = sys.argv[1:]
    root = (a[a.index("--root") + 1] if "--root" in a else ROOT)
    out_name = a[a.index("--out") + 1] if "--out" in a else "stage_am5"

    build_out = os.path.join(root, BUILD_OUT_NAME)
    stage = os.path.join(root, out_name)

    if not os.path.isdir(build_out):
        print("!! 缺少 %s —— 请先跑 Tools/ci/ci_build_am5.py" % build_out,
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
    os.makedirs(os.path.join(stage, "scripts"), exist_ok=True)

    n = 0
    total = 0
    missing = []

    # ── 1) scripts/ —— ASI(改名) + Hzk16 ──────────────────────────────
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

    if missing:
        print("!! build_out 中缺少: %s" % ", ".join(missing), file=sys.stderr)
        return 1

    # ── 2) audio/ avi/ update/ —— build_out 里除运行期/包根文件外的一切 ──
    #     ★ 三者各自落**包根**，不合并进 update\（见文件头）。
    for entry in sorted(os.listdir(build_out)):
        if entry in RUNTIME_TOP:
            continue
        sp = os.path.join(build_out, entry)
        if os.path.isfile(sp):
            shutil.copyfile(sp, os.path.join(stage, entry))
            n += 1
            total += os.path.getsize(sp)
            print("   + %s  (%d B)" % (entry, os.path.getsize(sp)))
            continue
        n_dir = 0
        for dp, _, files in os.walk(sp):
            for fn in sorted(files):
                full = os.path.join(dp, fn)
                rel = os.path.relpath(full, build_out).replace(os.sep, "/")
                dp2 = os.path.join(stage, rel.replace("/", os.sep))
                os.makedirs(os.path.dirname(dp2), exist_ok=True)
                shutil.copyfile(full, dp2)
                n += 1
                n_dir += 1
                total += os.path.getsize(full)
        print("   + %s/  (%d 文件)" % (entry, n_dir))

    # ── 3) 包根附加文件 ────────────────────────────────────────────────
    def put_root(src_path, dst_name, label):
        # ★ 必须 nonlocal：这是 main() 的嵌套函数，用 global 会 NameError
        #   （n/total 是 main 的局部变量，不是模块级）。
        nonlocal n, total
        if not os.path.isfile(src_path):
            missing.append(label)
            return
        shutil.copyfile(src_path, os.path.join(stage, dst_name))
        n += 1
        total += os.path.getsize(src_path)
        print("   + %s  <- %s  (%d B)"
              % (dst_name, os.path.relpath(src_path, root),
                 os.path.getsize(src_path)))

    # ★ 这里**不做** PE 位数断言：构建侧只负责搬运，
    #   位数正确性由编译器门禁（compile_dll_wine.py 的 PE 校验）保证。
    put_root(os.path.join(root, ASI_LOADER_SRC), PROXY_NAME,
             "%s (ASI Loader)" % ASI_LOADER_SRC)

    # cnc-ddraw：直接从 build_out 搬（已由 ci_build_am5.py 从 cnc-ddraw/ 取来）
    for f in ROOT_FROM_BUILD:
        put_root(os.path.join(build_out, f), f, f)

    # 项目主许可（含游戏版权声明）
    put_root(os.path.join(root, LICENSE_SRC), "LICENSE", LICENSE_SRC)

    # 必读说明.txt：写 UTF-8 **带 BOM** + CRLF。
    #   ★ Windows 记事本靠 BOM 判断编码，无 BOM 的 UTF-8 在旧版系统上会
    #     显示成乱码；目标用户是中文玩家，双击打开是首要场景。
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
        print("   + %s  (%d B, UTF-8 BOM)  <- %s"
              % (README_DST, os.path.getsize(rp), README_SRC))

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

    # License.txt：把随包分发的第三方声明 + 主许可合并成一份
    #   ★ 用 LICENSE_ORDER 显式清单（LICENSES/ 是各代共用目录，
    #     "目录里有什么就合什么"会让 1 代包混进本代的 TTS 声明）。
    lic_dir = os.path.join(root, LICENSE_DIR)
    if not os.path.isdir(lic_dir):
        missing.append(LICENSE_DIR + "/")
    else:
        have = [f for f in LICENSE_ORDER
                if os.path.isfile(os.path.join(lic_dir, f))]
        absent = [f for f in LICENSE_ORDER if f not in have]
        if absent:
            missing.append("%s/(%s)" % (LICENSE_DIR, ", ".join(absent)))
        if have:
            bar = "=" * 78
            parts = []
            for f in have:
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
                  % (len(have), ", ".join(have)))

    if missing:
        print("!! 缺少: %s" % ", ".join(missing), file=sys.stderr)
        return 1

    # ── 4) 打 zip（ASCII 文件名，GitHub 附件不支持中文）────────────────
    #    CI 里 upload-artifact 取 stage_am5/*.zip，所以 zip 落在 stage 下。
    zpath = os.path.join(stage, ZIP_STEM + ".zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=6) as z:
        for dp, _, files in os.walk(stage):
            for fn in sorted(files):
                full = os.path.join(dp, fn)
                rel = os.path.relpath(full, stage).replace(os.sep, "/")
                if rel == ZIP_STEM + ".zip":   # 别把上一次残留的 zip 打进自己
                    continue
                z.write(full, rel)

    print()
    print("stage: %s  (%d 文件 / %.1f MB)" % (stage, n, total / 1048576))
    print("zip  : %s  (%.2f MB)" % (zpath, os.path.getsize(zpath) / 1048576))
    return 0


if __name__ == "__main__":
    sys.exit(main())
