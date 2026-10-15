# -*- coding: utf-8 -*-
"""CI 构建入口（《玩具兵大战 II》）：把汉化载荷组装成 build_out_am2。

★ 与 1 代 Tools/ci/ci_build.py **同构**（刻意保持一致的 4 段式流程）：
    1 代                                  2 代
    build_dll_local.py                    build_dll_local_am2.py
    ci_build.py      -> build_out         ci_build_am2.py  -> build_out_am2
    make_patch.py    -> stage             make_patch_am2.py -> stage_am2
    verify_release.py                     verify_release_am2.py

流程（三步）：
    1. 复制 Army2_NEW_CHS/*            -> build_out_am2/（游戏原生布局）
    2. 复制 Army2_Extend_Dll 运行文件  -> build_out_am2/（dll + ini + strings + Hzk16）
    3. 生成 MANIFEST.json 与校验报告

产物目录结构（= make_patch_am2.py 的输入）：
    build_out_am2/
    ├─ 01-title/  audio/  avi/  bitmaps/  data/  rules/
    ├─ mpmaps.txt  readme.txt  shared.dat  title.dat
    ├─ Army2_Extend_Dll.dll
    ├─ ArmyMenCHS.ini
    ├─ Hzk16
    ├─ ddraw.dll  ddraw.ini                 <- cnc-ddraw（进包根）
    └─ strings\am2_strings.ini

★ cnc-ddraw 由本脚本从仓库 cnc-ddraw/ 取（与 3 代同一份文件）：
    2 代同样是 DirectDraw 程序，在新系统上必须靠 cnc-ddraw 才能渲染。
    早先 2 代说明书写的是"请自行安装 cnc-ddraw"，现在改为**随包分发**，
    ddraw.dll / ddraw.ini 直接落包根（不进 update\，也不进 MANIFEST 载荷）。

★ 为什么 Army2_NEW_CHS 是**权威载荷**而不是"从母盘算出的差异"：
    1 代的 Army1_NEW_CHS 就是「仓库里手工维护、可直接整树覆盖」的载荷，
    ci_build.py 直接拷它，构建期不再做差异推导。
    2 代早期把两件事混在一起（build_update_am2.py 拿 NEW_CHS 当"覆盖层"，
    build_new_chs_am2.py 又把 NEW_CHS 覆盖写回）—— 输入被输出改写，
    一旦中间态过期就会静默毁掉手工成果（手工修的 BMP 会被母盘原图顶掉）。
    现在方向是单向的：
        Army2_NEW_CHS（人工，权威） -> build_out_am2 -> stage_am2
    差异推导脚本（build_update_am2.py / gen_rules_chs_am2.py /
    add_lost_mp_am2.py 等）**降级为维护工具**，只在更新载荷时人工运行，
    不再挂在 CI 上 —— 与 1 代 build_new_chs.py 的定位相同。

用法：
    python Tools/ci/ci_build_am2.py [--root <仓库根>] [--out build_out_am2] [--verify]
"""

import hashlib
import json
import os
import shutil
import sys

# 运行期文件（放 build_out 根，由 make_patch_am2.py 分流到 scripts\）
DLL_NAME = "Army2_Extend_Dll.dll"
INI_NAME = "ArmyMenCHS.ini"
HZK_NAME = "Hzk16"
STRINGS_DIR = "strings"

# ★ 硬约束：载荷里绝不允许出现可执行文件。
#   本项目的核心承诺是"不改游戏文件"，2 代早期就踩过"把 armymen2.exe
#   打进 update 包"的坑（build_update_am2.py 的文件头有记录）。
#   这里作为**最后一道防线**断言，而不是信任上游。
PAYLOAD_FORBIDDEN_EXT = {".exe", ".dll", ".asi", ".sys", ".ocx"}

# 字库来源候选（**仓库内路径优先**：CI 上没有 I:\ 盘）
HZK_CANDIDATES = [
    os.path.join("Army2_CHS", HZK_NAME),
]

# 包根文件（由 cnc-ddraw 提供）——不属于 update\ 载荷，也不进 MANIFEST
ROOT_FILES = ["ddraw.dll", "ddraw.ini"]
CNC_DIR = "cnc-ddraw"


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def copy_tree(src, dst, stats):
    for root_, _, files in os.walk(src):
        for fn in files:
            sp = os.path.join(root_, fn)
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


def clean_dir(path):
    """清空目录内容（不删目录本身：Windows 上目录句柄可能被索引器持有）。"""
    if not os.path.isdir(path):
        return
    for name in os.listdir(path):
        p = os.path.join(path, name)
        try:
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.chmod(p, 0o666)
                os.remove(p)
        except OSError:
            pass


def main():
    args = sys.argv[1:]
    # ★ root 必须由 __file__ 推导，不能写死绝对路径：
    #   CI 在 ubuntu runner 上跑，仓库位于 $GITHUB_WORKSPACE。
    here = os.path.dirname(os.path.abspath(__file__))
    root = (args[args.index("--root") + 1] if "--root" in args else
            os.path.dirname(os.path.dirname(here)))
    out_name = args[args.index("--out") + 1] if "--out" in args else "build_out_am2"
    verify = "--verify" in args

    new_chs = os.path.join(root, "Army2_NEW_CHS")
    dll_dir = os.path.join(root, "Army2_Extend_Dll")
    out = os.path.join(root, out_name)

    if not os.path.isdir(new_chs):
        print(f"!! 缺少载荷目录: {new_chs}", file=sys.stderr)
        return 1

    clean_dir(out)
    os.makedirs(out, exist_ok=True)

    stats = {"files": 0, "bytes": 0}
    print(f"CI build (Army Men II) -> {out}")
    print()

    # ── 1. 载荷：Army2_NEW_CHS 顶层逐项搬到 build_out_am2 根 ────────────
    #     与 1 代 ci_build.py 一样是"整树覆盖"语义：目录名与游戏一致。
    payload = []          # [(相对 payload 根的路径)]
    for entry in sorted(os.listdir(new_chs)):
        src = os.path.join(new_chs, entry)
        dst = os.path.join(out, entry)
        n0 = stats["files"]
        if os.path.isdir(src):
            os.makedirs(dst, exist_ok=True)
            copy_tree(src, dst, stats)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
            stats["files"] += 1
            stats["bytes"] += os.path.getsize(src)
        kind = "dir " if os.path.isdir(src) else "file"
        print("  [1] %-14s %s  +%d files" % (entry, kind, stats["files"] - n0))
    print()

    # ── 2. 运行期文件 ──────────────────────────────────────────────────
    dll_src = os.path.join(dll_dir, "Release", DLL_NAME)
    if os.path.isfile(dll_src):
        shutil.copyfile(dll_src, os.path.join(out, DLL_NAME))
        stats["files"] += 1
        stats["bytes"] += os.path.getsize(dll_src)
        print(f"  [2] {DLL_NAME}  ({os.path.getsize(dll_src)} B)")
    else:
        # ★ 不静默跳过：没有 ASI 就没有汉化，产物必然无效。
        print(f"  [2] !! ASI 未编译: {dll_src}", file=sys.stderr)
        print("      先跑 python Tools/ci/build_dll_local_am2.py", file=sys.stderr)
        return 1

    for f in (INI_NAME,):
        s = os.path.join(dll_dir, f)
        if not os.path.isfile(s):
            print(f"  [2] !! 缺少 {f}: {s}", file=sys.stderr)
            return 1
        shutil.copyfile(s, os.path.join(out, f))
        stats["files"] += 1
        stats["bytes"] += os.path.getsize(s)
        print(f"      {f}  ({os.path.getsize(s)} B)")

    sdir = os.path.join(dll_dir, STRINGS_DIR)
    if not os.path.isdir(sdir):
        print(f"  [2] !! 缺少译文表目录: {sdir}", file=sys.stderr)
        return 1
    copy_tree(sdir, os.path.join(out, STRINGS_DIR), stats)
    print("      strings\\  (%d files)" % len(os.listdir(sdir)))

    # 字库：从仓库内已跟踪的 Army2_CHS/Hzk16 取（CI 上无 I:\ 盘）
    hzk_src = None
    for c in HZK_CANDIDATES:
        p = c if os.path.isabs(c) else os.path.join(root, c)
        if os.path.isfile(p):
            hzk_src = p
            break
    if not hzk_src:
        # 中文字库缺失 = 补丁完全无法显示中文，必须失败而不是静默继续
        print("  [2] !! 找不到 %s（中文将无法显示）: %s"
              % (HZK_NAME, ", ".join(HZK_CANDIDATES)), file=sys.stderr)
        return 1
    shutil.copyfile(hzk_src, os.path.join(out, HZK_NAME))
    stats["files"] += 1
    stats["bytes"] += os.path.getsize(hzk_src)
    print("      %s  <- %s" % (HZK_NAME, os.path.relpath(hzk_src, root)))

    # ── 2b. 包根文件：cnc-ddraw 的 ddraw.dll / ddraw.ini ───────────────
    #   ★ 与 3 代（ci_build_am3.py 第 4 步）取的是**同一个** cnc-ddraw/。
    #     2 代同样是 DirectDraw 程序，不给它就没法在新系统上渲染。
    for f in ROOT_FILES:
        s = os.path.join(root, CNC_DIR, f)
        if not os.path.isfile(s):
            print("  [2b] !! 缺少 %s/%s（随包分发的 cnc-ddraw，不能少）"
                  % (CNC_DIR, f), file=sys.stderr)
            return 1
        shutil.copyfile(s, os.path.join(out, f))
        stats["files"] += 1
        stats["bytes"] += os.path.getsize(s)
        print("      %s  <- %s/%s  (%d B)"
              % (f, CNC_DIR, f, os.path.getsize(s)))
    print()

    print("总计: %d 文件 / %.1f MB" % (stats["files"], stats["bytes"] / 1048576))

    # ── 3. MANIFEST.json（build_out 的权威清单；verify_release_am2 用它核对）──
    #   ★ runtime 里必须含 ROOT_FILES：它们与 dll/ini/Hzk16 一样是**包根**
    #     运行期文件，不属于 update\ 载荷。漏掉的话 ddraw.dll/ini 会被写进
    #     清单，verify_release_am2.py 的 [7] 段就会把它们当成 update\ 内容
    #     去找，报"清单里有但磁盘没有"。
    runtime = {DLL_NAME, INI_NAME, HZK_NAME, STRINGS_DIR} | set(ROOT_FILES)
    rows = []
    for dp, _, fns in os.walk(out):
        for fn in fns:
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, out).replace(os.sep, "/")
            top = rel.split("/")[0]
            if top in runtime:
                continue          # 运行期文件不属于 update\ 载荷
            rows.append((rel, os.path.getsize(full), sha256(full)))
    rows.sort()
    with open(os.path.join(out, "MANIFEST.json"), "w", encoding="utf-8",
              newline="\n") as f:
        json.dump({"game": "Army Men II",
                   "count": len(rows),
                   "note": ("build_out_am2 载荷清单（= Army2_NEW_CHS 快照）。"
                            "update\\ 内容由此清单核对。"),
                   "files": [{"path": r, "size": s, "sha256": h}
                             for r, s, h in rows]},
                  f, ensure_ascii=False, indent=1)
    print("  -> MANIFEST.json  (%d 条载荷)" % len(rows))

    if not verify:
        return 0

    # ── 校验 ───────────────────────────────────────────────────────────
    print()
    print("校验:")
    ok = True
    bad_ext = []
    for dp, _, fns in os.walk(out):
        for fn in fns:
            rel = os.path.relpath(os.path.join(dp, fn), out).replace(os.sep, "/")
            if rel.split("/")[0] in runtime:
                continue
            if os.path.splitext(fn)[1].lower() in PAYLOAD_FORBIDDEN_EXT:
                bad_ext.append(rel)
    if bad_ext:
        print("  !! 载荷含可执行文件（违反「不改游戏文件」约束）: %s"
              % bad_ext[:5])
        ok = False
    else:
        print("  载荷无可执行文件  OK")

    if len(rows) == 0:
        print("  !! 载荷为空")
        ok = False
    else:
        print("  载荷 %d 个文件  OK" % len(rows))

    for k in (DLL_NAME, INI_NAME, HZK_NAME,
              os.path.join(STRINGS_DIR, "am2_strings.ini")) + tuple(ROOT_FILES):
        p = os.path.join(out, k)
        exists = os.path.isfile(p)
        print("  %-34s %s" % (k, "OK" if exists else "缺失"))
        if not exists:
            ok = False

    print("  DLL sha = %s" % sha256(os.path.join(out, DLL_NAME))[:12])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
