# -*- coding: utf-8 -*-
r"""CI 构建入口（《玩具兵大战：空中战术》/ Army Men: Air Tactics）：组装 build_out_am5。

★ 编号说明：本目录号是 `Army5_*` = **第 5 个做汉化**的作品；
  它对应游戏系列的**第 4 代**（Air Tactics）。
  系列第 5 代是《世界大战 / World War》，目录号 `Army4_*`。
  下文提到「其他各代」时按施工批次说，不按系列序号。

★ 本代与其他各代的**根本差异：没有 dat 回包。**
  2/3/5 代都要把 title.dat / shared.dat 从解包工作区**无损回包**，
  本代不需要 —— 本作的界面贴图与文本直接以散文件形式随 update\ 覆盖：

      Army5_NEW_CHS/
        audio/    codesfx music scriptsfx（+ codesfx.txt / voice.txt）
        avi/      cine1..6.smk（中文片头）
        update/   audio\voice（487 个中文配音）+ bitmaps + data + strings

★ 因此组装逻辑退化为**整树复制**，这也正是本代的正确做法：
  Army5_NEW_CHS 的三个顶层目录与「部署到游戏根目录后的样子」逐字节一致
  （已实测：audio 288 / avi 7 / update 678 文件与实机游戏目录完全相同）。
  ★ 注意 audio\ 与 avi\ 落在**包根**，不像其他各代那样全部塞进 update\。

★ 载荷来源全部是仓库内已跟踪路径（CI 上没有 I:\ 盘）：
      Army5_NEW_CHS/                           <> 散文件载荷（973 文件）
      Army5_Extend_Dll/Release/Army5_Extend_Dll.dll
      Army2_CHS/Hzk16                          官方中文版 13x13 宋体点阵
      cnc-ddraw/{ddraw.dll,ddraw.ini}          MIT，包根直落

★ 与其他各代的构建脚本相比，本脚本**刻意不含产物断言**
  （不查 dat 大小、不查配音条数、不查体积指纹）。判定标准是
  「每一步正常返回 0」，产物正确性由人眼与运行期日志确认。

产物目录结构（= make_patch_am5.py 的输入）：

    build_out_am5/
    ├─ audio/  avi/  update/                <- Army5_NEW_CHS 整树
    ├─ ddraw.dll  ddraw.ini                 <- cnc-ddraw（进包根）
    ├─ Army5_Extend_Dll.dll                 <- 进 scripts\*.asi
    └─ Hzk16                                <- 进 scripts\Hzk16

用法：
    python Tools/ci/ci_build_am5.py [--root <仓库根>] [--out build_out_am5]
"""

import os
import shutil
import sys

# ── 载荷 / 运行期产物命名 ──────────────────────────────────────────────
DLL_NAME = "Army5_Extend_Dll.dll"       # 源来自 Army5_Extend_Dll/Release/
HZK_NAME = "Hzk16"                      # 落到 scripts\Hzk16（ASI 按 DLL 目录找）

# 包根文件（由 cnc-ddraw 提供）——不属于 update\ 载荷
ROOT_FILES = ["ddraw.dll", "ddraw.ini"]
CNC_DIR = "cnc-ddraw"

# 字库来源候选（仓库内路径优先：CI 上没有 I:\ 盘）
#   ★ 本作**没有**官方中文母盘（已全盘搜过 amat.exe，无 Hzk16 / RSE\x1a），
#     故复用 2 代官方中文版那份 13x13 宋体点阵，与其他各代同一个文件。
HZK_CANDIDATES = [os.path.join("Army2_CHS", HZK_NAME)]

# 从 Army5_NEW_CHS 复制时要排除的文件（README 是仓库文档，不进包）
PAYLOAD_EXCLUDE_NAMES = {"README.md"}


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


def copy_tree(src, dst, stats, exclude_names=()):
    for dp, _, files in os.walk(src):
        for fn in files:
            if fn in exclude_names:
                continue
            sp = os.path.join(dp, fn)
            rel = os.path.relpath(sp, src)
            out = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            if os.path.exists(out):
                try:
                    os.chmod(out, 0o666)
                except OSError:
                    pass
            shutil.copyfile(sp, out)
            stats["files"] += 1
            stats["bytes"] += os.path.getsize(sp)


def main():
    args = sys.argv[1:]
    # ★ root 必须由 __file__ 推导：CI 在 ubuntu runner 上跑，仓库位于
    #   $GITHUB_WORKSPACE，不能写死作者本机的 G:\ 路径。
    here = os.path.dirname(os.path.abspath(__file__))
    root = (args[args.index("--root") + 1] if "--root" in args else
            os.path.dirname(os.path.dirname(here)))
    out_name = args[args.index("--out") + 1] if "--out" in args else "build_out_am5"

    new_chs = os.path.join(root, "Army5_NEW_CHS")
    dll_dir = os.path.join(root, "Army5_Extend_Dll")
    out = os.path.join(root, out_name)

    if not os.path.isdir(new_chs):
        print("!! 缺少载荷目录: %s" % new_chs, file=sys.stderr)
        return 1

    clean_dir(out)
    os.makedirs(out, exist_ok=True)

    stats = {"files": 0, "bytes": 0}
    print("CI build (Army Men: Air Tactics) -> %s" % out)
    print()

    # ── 1. 载荷：Army5_NEW_CHS 顶层逐项搬到 build_out_am5 根 ──────────
    #     与其他各代一样是"整树覆盖"语义：目录名与游戏一致。
    #     ★ 本代的 audio\ 与 avi\ 落在包根（不是 update\ 的子目录），
    #       这是实机布局决定的，不要为了"和其他代一样"而挪进 update\。
    for entry in sorted(os.listdir(new_chs)):
        if entry in PAYLOAD_EXCLUDE_NAMES:
            print("  [1] %-14s 跳过（仓库文档，不进包）" % entry)
            continue
        src = os.path.join(new_chs, entry)
        dst = os.path.join(out, entry)
        n0 = stats["files"]
        if os.path.isdir(src):
            os.makedirs(dst, exist_ok=True)
            copy_tree(src, dst, stats, PAYLOAD_EXCLUDE_NAMES)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
            stats["files"] += 1
            stats["bytes"] += os.path.getsize(src)
        kind = "dir " if os.path.isdir(src) else "file"
        print("  [1] %-14s %s  +%d files" % (entry, kind, stats["files"] - n0))
    print()

    # ── 2. 运行期文件：ASI 与中文字库 ─────────────────────────────────
    dll_src = os.path.join(dll_dir, "Release", DLL_NAME)
    if not os.path.isfile(dll_src):
        # ★ 不静默跳过：没有 ASI 就没有中文渲染，产物必然无效。
        print("  [2] !! ASI 未编译: %s" % dll_src, file=sys.stderr)
        print("      先跑 python Tools/ci/compile_dll_wine.py "
              "--proj Army5_Extend_Dll", file=sys.stderr)
        return 1
    shutil.copyfile(dll_src, os.path.join(out, DLL_NAME))
    stats["files"] += 1
    stats["bytes"] += os.path.getsize(dll_src)
    print("  [2] %s  (%d B)" % (DLL_NAME, os.path.getsize(dll_src)))

    hzk_src = None
    for c in HZK_CANDIDATES:
        p = c if os.path.isabs(c) else os.path.join(root, c)
        if os.path.isfile(p):
            hzk_src = p
            break
    if not hzk_src:
        # 字库缺失 = 中文完全无法显示，必须失败而不是静默继续
        print("  [2] !! 找不到 %s（中文将无法显示）: %s"
              % (HZK_NAME, ", ".join(HZK_CANDIDATES)), file=sys.stderr)
        return 1
    shutil.copyfile(hzk_src, os.path.join(out, HZK_NAME))
    stats["files"] += 1
    stats["bytes"] += os.path.getsize(hzk_src)
    print("      %s  <- %s  (%d B)"
          % (HZK_NAME, os.path.relpath(hzk_src, root), os.path.getsize(hzk_src)))

    # ── 3. 包根文件：cnc-ddraw 的 ddraw.dll / ddraw.ini ────────────────
    #     ★ 本作是 2000 年的 DirectDraw 程序，新系统上不加 cnc-ddraw 会黑屏 /
    #       无图像 / 鼠标错位。与其他各代同一结论。
    for f in ROOT_FILES:
        s = os.path.join(root, CNC_DIR, f)
        if not os.path.isfile(s):
            print("  [3] !! 缺少 %s/%s（本作渲染依赖 cnc-ddraw，不能少）"
                  % (CNC_DIR, f), file=sys.stderr)
            return 1
        shutil.copyfile(s, os.path.join(out, f))
        stats["files"] += 1
        stats["bytes"] += os.path.getsize(s)
        print("  [3] %s  <- %s/%s  (%d B)"
              % (f, CNC_DIR, f, os.path.getsize(s)))
    print()

    print("总计: %d 文件 / %.1f MB" % (stats["files"], stats["bytes"] / 1048576))
    return 0


if __name__ == "__main__":
    sys.exit(main())
