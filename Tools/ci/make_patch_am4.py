# -*- coding: utf-8 -*-
"""把 build_out_am4 组装成**可直接解压到游戏根目录**的 4 代汉化补丁。

★ 与 1/2/3 代 Tools/ci/make_patch*.py **同构**：

    <游戏>\\
      ├─ dinput.dll               ASI Loader（asi/dsound.dll 改名；见下方 ★）
      ├─ ddraw.dll                cnc-ddraw（4 代渲染所需，直接落包根）
      ├─ ddraw.ini                cnc-ddraw 配置
      ├─ LICENSE                  项目主许可（仓库根 LICENSE）
      ├─ License.txt              LICENSES/*.txt 合并，供随包分发
      ├─ 必读说明.txt             安装说明（UTF-8 带 BOM + CRLF）
      ├─ 如果不会安装，请把该文件发给AI，让AI教你.txt
      ├─ 将此文件交给AI，让AI协助完善本项目.txt
      ├─ scripts\\
      │    Army4_Extend_Dll.asi   ← build_out 里叫 .dll，落包时改名
      │    Hzk16                  ← 中文字库（13x13 点阵；ASI 按 DLL 目录找）
      └─ update\\
           01-title\\  bitmaps\\  data\\  rules\\  strings\\
           audio\\vos\\*.wav      ← 中文配音（qwen3-tts 生成）
           title.dat  shared.dat

★ 与 3 代的差异（都是刻意的）：

  · 代理 DLL 名同样是 **dinput.dll**：amww.exe 的导入表**按名字**导入
    dinput.dll!DirectInputCreateA（实测，见 docs/11 §1），故用该名作代理
    可可靠命中。与 2/3 代同一结论。
  · ASI 是 **Army4_Extend_Dll**，导出 `ArmyMenWW_Install` /
    `ArmyMenWW_Uninstall`（3 代是 ArmyMenTIS_*）。校验器按 4 代名断言。
  · 必读说明取 `Documents/必读说明_世界大战.txt`（3 代是「_太空玩具」）。
  · 4 代的 title.dat / shared.dat 进 **update\\**（与 2/3 代同位置）。
  · update\\audio\\vos\\ 是中文配音，由 ci_build_am4.py 第 5 步拷进
    build_out，这里随 update\\ 一起搬，不需要单独分支。

★ 为什么代理必须落名为 dinput.dll 而不是随便一个名字：
  游戏是按名字解析导入的；代理名不对，DirectInputCreateA 解析失败，
  游戏拿不到函数 —— 表现是"补丁装了但中文完全不出现且无报错"。
  这是必须在 CI 上拦下的失效模式（见 verify_release_am4.py）。

★ 包根说明与许可（与 1/2/3 代同一套约定 S11/S12/S13）：
    LICENSE      <- 仓库根 LICENSE（项目主许可，含游戏版权声明）
    License.txt  <- LICENSES/*.txt 合并：ASILoader + cnc-ddraw + qwen3-tts
                    + GPLv3。★ 三方组件（UAL / cnc-ddraw / qwen3-tts）的
                    许可要求随二进制或产物分发时附上版权声明，缺一不可。
    必读说明.txt <- Documents/必读说明_世界大战.txt，写 UTF-8 **带 BOM** +
                    CRLF（Windows 记事本靠 BOM 判编码，目标用户直接双击打开）
    AI 辅助文件  <- 与 1/2/3 代同源的两份 txt，同样 BOM + CRLF

用法：
    python Tools/ci/make_patch_am4.py [--root <仓库根>] [--out stage_am4]

★ root 默认由 __file__ 上溯三层推导，CI 上无需显式传。
"""

import hashlib
import os
import shutil
import sys
import zipfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BUILD_OUT_NAME = "build_out_am4"

# ★ DLL 必须落名为 .asi：Ultimate ASI Loader 只扫描 scripts\*.asi，
#   .dll 直接放进去不会被加载。
DLL_SRC = "Army4_Extend_Dll.dll"
DLL_DST = "scripts/Army4_Extend_Dll.asi"

# scripts\ 下的运行期文件（4 代无 ini）
SCRIPTS_FILES = ["Hzk16"]

# 包根文件：由 build_out 直接搬（cnc-ddraw 的 ddraw.dll / ddraw.ini）
ROOT_FROM_BUILD = ["ddraw.dll", "ddraw.ini"]

# build_out 里除运行期/包根文件外的一切 -> update\
RUNTIME_TOP = {DLL_SRC, "Hzk16", "MANIFEST.json", "MANIFEST.md"} | set(ROOT_FROM_BUILD)

# ASI Loader 源。★ 必须是**仓库内已跟踪**的路径：
#   asi/dsound.dll 是 Ultimate ASI Loader（MIT，已入库），与 1/2/3 代同一份文件。
ASI_LOADER_SRC = "asi/dsound.dll"
PROXY_NAME = "dinput.dll"           # ★ 见文件头说明

# 仓库根 LICENSE（项目主许可）-> 包根 LICENSE
LICENSE_SRC = "LICENSE"
# 包内说明：与 1/2/3 代同一套约定（统一标准 S11，名为「必读说明.txt」），
# 4 代单独一份源文件，避免四代说明混在一起。
README_SRC = "Documents/必读说明_世界大战.txt"
README_DST = "必读说明.txt"
# 两份 AI 辅助文件（统一标准 S12/S13），与必读说明同源目录，随包分发到包根
AI_FILES = [
    "如果不会安装，请把该文件发给AI，让AI教你.txt",
    "将此文件交给AI，让AI协助完善本项目.txt",
]
LICENSE_DIR = "LICENSES"
# ★ 显式清单，不是"目录里有什么就合什么"：LICENSES/ 是四代共用目录，
#   1 代包不该混进 4 代才用到的 qwen3-tts 声明（反之亦然）。
#   合并顺序：先随包分发的第三方（UAL / cnc-ddraw / qwen3-tts），
#   最后 GPLv3.txt 作为主许可正文。
LICENSE_ORDER = ["ASILoader.txt", "cnc-ddraw.txt", "qwen3-tts.txt", "GPLv3.txt"]

# 配音落位自证：只确认"确实拷了一批中文配音 wav"，不硬数数量——
#   配音条数随台词表与音效甄别浮动，且游戏对缺失配音静默回退英文原声。
#   真正的质量闸门在 ci_build_am4.py（体积下限）与 verify_release_am4.py（抽样探针）。
AUDIO_REL = "update/audio/vos"


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    a = sys.argv[1:]
    root = (a[a.index("--root") + 1] if "--root" in a else ROOT)
    out_name = a[a.index("--out") + 1] if "--out" in a else "stage_am4"

    build_out = os.path.join(root, BUILD_OUT_NAME)
    stage = os.path.join(root, out_name)

    if not os.path.isdir(build_out):
        print("!! 缺少 %s —— 请先跑 Tools/ci/ci_build_am4.py" % build_out,
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
    os.makedirs(os.path.join(stage, "update"), exist_ok=True)

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

    # ── 2) update/ —— build_out 里除运行期/包根文件外的一切 ─────────────
    upd_dst = os.path.join(stage, "update")
    n_upd = 0
    for entry in sorted(os.listdir(build_out)):
        if entry in RUNTIME_TOP:
            continue
        sp = os.path.join(build_out, entry)
        if os.path.isfile(sp):
            os.makedirs(upd_dst, exist_ok=True)
            shutil.copyfile(sp, os.path.join(upd_dst, entry))
            n += 1
            n_upd += 1
            total += os.path.getsize(sp)
        else:
            for dp, _, files in os.walk(sp):
                for fn in sorted(files):
                    full = os.path.join(dp, fn)
                    rel = os.path.relpath(full, build_out).replace(os.sep, "/")
                    dp2 = os.path.join(upd_dst, rel.replace("/", os.sep))
                    os.makedirs(os.path.dirname(dp2), exist_ok=True)
                    shutil.copyfile(full, dp2)
                    n += 1
                    n_upd += 1
                    total += os.path.getsize(full)
    print("   + update/  (%d 文件)" % n_upd)
    if n_upd == 0:
        print("!! update/ 为空 —— 载荷缺失，产物无意义", file=sys.stderr)
        return 1

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

    # ★ 这里**不做** PE 位数断言：UAL 的位数由 verify_release_am4.py
    #   独立校验（含导出表检查），构建侧只负责搬运，避免两处判据不一致。
    put_root(os.path.join(root, ASI_LOADER_SRC), PROXY_NAME,
             "%s (ASI Loader)" % ASI_LOADER_SRC)

    # cnc-ddraw：直接从 build_out 搬（已由 ci_build_am4.py 从 cnc-ddraw/ 取来）
    for f in ROOT_FROM_BUILD:
        put_root(os.path.join(build_out, f), f, f)

    # 项目主许可（含游戏版权声明）
    put_root(os.path.join(root, LICENSE_SRC), "LICENSE", LICENSE_SRC)

    # 必读说明.txt：写 UTF-8 **带 BOM** + CRLF。
    #   ★ Windows 记事本靠 BOM 判断编码，无 BOM 的 UTF-8 在旧版系统上会
    #     显示成乱码；目标用户是中文玩家，双击打开是首要场景。
    #     （与 1/2/3 代 make_patch*.py 完全同一做法。）
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
    #   ★ 用 LICENSE_ORDER 显式清单（LICENSES/ 是四代共用目录，
    #     "目录里有什么就合什么"会让 1 代包混进 4 代的 TTS 声明）。
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
    #    CI 里 upload-artifact 取 stage_am4/*.zip，所以 zip 落在 stage 下。
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    zname = "ArmyMen4-CHS-Patch-%s.zip" % stamp
    zpath = os.path.join(stage, zname)

    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=6) as z:
        for dp, _, files in os.walk(stage):
            for fn in sorted(files):
                full = os.path.join(dp, fn)
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
    print("zip  : %s  (%.2f MB)" % (zpath, os.path.getsize(zpath) / 1048576))
    if n_zip != n:
        print("!! zip 条目数 %d != stage 文件数 %d" % (n_zip, n), file=sys.stderr)
        return 1
    print("     zip 自检通过：%d 条目，CRC 全部正确" % n_zip)

    for key in ("scripts/Army4_Extend_Dll.asi", "scripts/Hzk16", PROXY_NAME,
                "ddraw.dll", "ddraw.ini", "LICENSE", "License.txt", README_DST,
                "update/title.dat", "update/shared.dat"):
        p = os.path.join(stage, key.replace("/", os.sep))
        if os.path.isfile(p):
            print("  %-38s %9d  sha=%s" % (key, os.path.getsize(p),
                                           sha256(p)[:16]))
        else:
            print("  %-38s !! 缺失" % key)
            return 1

    # 配音落位自证：只确认"确实拷了一批中文配音 wav"，不数数量
    vos = os.path.join(stage, AUDIO_REL.replace("/", os.sep))
    n_wav = sum(1 for f in os.listdir(vos)
                if f.lower().endswith(".wav")) if os.path.isdir(vos) else 0
    if n_wav == 0:
        print("  %-38s !! 0 个 wav —— 中文配音未拷入" % (AUDIO_REL + "/*.wav"),
              file=sys.stderr)
        return 1
    print("  %-38s %9d 个 wav（不硬校验数量：缺失的会静默回退英文原声）"
          % (AUDIO_REL + "/*.wav", n_wav))
    return 0


if __name__ == "__main__":
    sys.exit(main())
