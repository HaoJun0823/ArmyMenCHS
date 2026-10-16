# -*- coding: utf-8 -*-
r"""CI 构建入口（《玩具兵大战：世界大战》/ Army Men: World War）：组装 build_out_am4。

★ 与 1 代 Tools/ci/ci_build.py、2 代 Tools/ci/ci_build_am2.py、3 代
  Tools/ci/ci_build_am3.py **同构**（刻意保持一致的 4 段式流程）：

    1 代                     2 代                       3 代                       4 代
    build_dll_local.py       build_dll_local_am2.py    compile_dll_wine.py       compile_dll_wine.py
                                                       --proj Army3_Extend_Dll   --proj Army4_Extend_Dll
    ci_build.py -> build_out ci_build_am2.py -> _am2   ci_build_am3.py -> _am3   ci_build_am4.py -> _am4
    make_patch.py -> stage   make_patch_am2.py -> _am2 make_patch_am3.py -> _am3 make_patch_am4.py -> _am4
    verify_release.py        verify_release_am2.py      verify_release_am3.py      verify_release_am4.py

★ 4 代与 3 代的**四处实质差异**（不是抄漏了）：

  1. **两条 dat 的权威值全部不同**（实测，见 docs/11 §2.1 与 docs/12）：
         title.dat   3 代 4298896 B / 203 对象  ->  4 代 3502576 B / 197 对象
         shared.dat  3 代 2936433 B / 1113 对象 ->  4 代 2729541 B / 969 对象
     FILEID 魔数**相同**（0x81920667 / 0x81920668），故 am3_dat.py 的解析
     逻辑可直接复用 —— 但 expect_size 与逐对象断言必须按 4 代重写。

  2. **shared 也有中文覆盖层**（3 代 shared 为 None）。
     4 代实测 shared/png_control_chs/ 有 16 张（含 _report.json）。
     3 代当初没有 shared 覆盖层，这条差异是 4 代独有的，不能照抄 None。

  3. **中文配音是外部载荷，且是当前唯一未完成的载荷。**
     4 代英文原声 audio/vos 共 298 个（3 代 239 个），中文配音
     Army4_Voice_CHS/audio/ 目前**为空**（见下方 ★TODO）。
     构建期作为第 5 步载荷单独拷入 build_out，并纳入 MANIFEST.json ——
     否则这些文件会绕过 verify_release_am4.py 的 K 段载荷对照，成为校验盲区。

  4. **包根同样需要 cnc-ddraw**（ddraw.dll / ddraw.ini），与 2/3 代一致：
     4 代同样是 DirectDraw 程序，且注入点同为 dinput.dll 按名导入
     DirectInputCreateA（实测，见 docs/11 §1）。

★ 载荷来源全部是**仓库内已跟踪**路径，不依赖作者本机的 I:\\ 盘：
     Army4_NEW_CHS/（去掉 README.md）
     Army4_Object_CHS/{title,shared}/
     Army4_Extend_Dll/Release/Army4_Extend_Dll.dll
     Army2_CHS/Hzk16（官方中文版 13x13 宋体点阵，与 2/3 代共用同一份）
     Army4_Voice_CHS/audio/（★ 待生成，见 TODO）
     cnc-ddraw/{ddraw.dll,ddraw.ini}

★ 硬约束：update/ 载荷里**绝不允许**出现可执行文件（本项目承诺"不改游戏文件"）。
  这里作为最后一道防线断言，而不是信任上游。

产物目录结构（= make_patch_am4.py 的输入）：

    build_out_am4/
    ├─ 01-title/  bitmaps/  strings/  data/  rules/   <- Army4_NEW_CHS 载荷
    ├─ audio/vos/*.wav                      <- 中文配音（进 update\audio\）
    ├─ title.dat  shared.dat                <- 回包产物（无损）
    ├─ ddraw.dll  ddraw.ini                 <- cnc-ddraw（进包根）
    ├─ Army4_Extend_Dll.dll                 <- 进 scripts\*.asi
    ├─ Hzk16                                <- 进 scripts\Hzk16
    └─ MANIFEST.json

用法：
    python Tools/ci/ci_build_am4.py [--root <仓库根>] [--out build_out_am4]
                                    [--audio Army4_Voice_CHS/audio] [--verify]
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys

# ── 载荷 / 运行期产物命名 ──────────────────────────────────────────────
DLL_NAME = "Army4_Extend_Dll.dll"       # 源来自 Army4_Extend_Dll/Release/
HZK_NAME = "Hzk16"                      # 落到 scripts\Hzk16（ASI 按 DLL 目录找）

# 回包对象：解包工作区 -> 输出文件名
#   ★ expect_size 是**硬编码的权威值**（来自 4 代 GOG 原版 dat），
#     不是从工作区里读出来的 —— 判据不能来自被校验对象自身。
#     title.dat  3502576 B / 197 对象 / FILEID 0x81920667
#     shared.dat 2729541 B / 969 对象 / FILEID 0x81920668
DAT_JOBS = [
    {
        "src": os.path.join("Army4_Object_CHS", "title"),
        "out": "title.dat",
        "overlay": os.path.join("Army4_Object_CHS", "title", "png_control_chs"),
        "expect_size": 3502576,
    },
    {
        "src": os.path.join("Army4_Object_CHS", "shared"),
        "out": "shared.dat",
        # ★ 与 3 代不同：4 代的 shared 也做了中文覆盖层（16 张控件）。
        #   3 代此处是 None —— 那是 3 代的实际情况，不是可抄的约定。
        "overlay": os.path.join("Army4_Object_CHS", "shared", "png_control_chs"),
        "expect_size": 2729541,
    },
]

# 包根文件（由 cnc-ddraw 提供）——不属于 update\ 载荷
ROOT_FILES = ["ddraw.dll", "ddraw.ini"]
CNC_DIR = "cnc-ddraw"

# ── 中文配音 ──────────────────────────────────────────────────────────
#   ★ 与 3 代的差异：3 代英文原声 239 个、实际配了 171 个（音效类 68 个未配）。
#     4 代英文原声是 298 个（Army4_Original/audio/vos）。
#
# ★TODO(配音)：Army4_Voice_CHS/audio/vos 目前为空。配音生成流程见
#     docs/11-am4-reuse-plan.md §2.2（ASR -> 中译 -> 音色参考 -> 批量生成）。
#     当前 AUDIO_EXPECT_FILES 取**英文原声总数 298**（一一对应是最强不变量）；
#     台词表定稿、确定哪些是"音效不配"之后，必须回来把 298 改成实际配音数
#     —— 否则配音做完了 CI 依然是红的。
AUDIO_DIR_NAME = "audio"
AUDIO_SRC_DEFAULT = os.path.join("Army4_Voice_CHS", AUDIO_DIR_NAME)
AUDIO_EXPECT_FILES = 298
AUDIO_MIN_BYTES = 10000000        # ~9.5 MiB；明显低于此值说明拷漏了
# 配音文件名必须是英文原声的子集（同名单一一对应，游戏按原名加载）
AUDIO_BASELINE_DIR = os.path.join("Army4_Original", AUDIO_DIR_NAME, "vos")

# 字库来源候选（仓库内路径优先：CI 上没有 I:\ 盘）
HZK_CANDIDATES = [os.path.join("Army2_CHS", HZK_NAME)]

# ★ 载荷里绝不允许出现的可执行文件扩展名
PAYLOAD_FORBIDDEN_EXT = {".exe", ".dll", ".asi", ".sys", ".ocx"}

# build_out 里属于"运行期/包根"的顶层项，不算 update\ 载荷
RUNTIME_TOP = {DLL_NAME, HZK_NAME, "MANIFEST.json", "MANIFEST.md"} | set(ROOT_FILES)

# 从 Army4_NEW_CHS 复制时要排除的文件（README 是仓库文档，不进包）
PAYLOAD_EXCLUDE_NAMES = {"README.md"}


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _disp(p, root):
    """展示用相对路径。

    ★ 不能直接 os.path.relpath(p, root)：--audio 允许传**绝对路径**，
      Windows 上若落在别的盘（如 C:\\ 临时目录）会抛
      ValueError: path is on mount 'C:', start on mount 'G:'。
      日志打印不该因为盘符不同就崩掉整个构建。
    """
    try:
        return os.path.relpath(p, root)
    except ValueError:
        return p


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
    out_name = args[args.index("--out") + 1] if "--out" in args else "build_out_am4"
    verify = "--verify" in args
    audio_src_rel = (args[args.index("--audio") + 1] if "--audio" in args
                     else AUDIO_SRC_DEFAULT)

    new_chs = os.path.join(root, "Army4_NEW_CHS")
    dll_dir = os.path.join(root, "Army4_Extend_Dll")
    out = os.path.join(root, out_name)

    if not os.path.isdir(new_chs):
        print("!! 缺少载荷目录: %s" % new_chs, file=sys.stderr)
        return 1

    clean_dir(out)
    os.makedirs(out, exist_ok=True)

    stats = {"files": 0, "bytes": 0}
    print("CI build (Army Men: World War) -> %s" % out)
    print()

    # ── 1. 载荷：Army4_NEW_CHS 顶层逐项搬到 build_out_am4 根 ──────────
    #     与 1/2/3 代一样是"整树覆盖"语义：目录名与游戏一致。
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

    # ── 2. 回包 title.dat / shared.dat（★ 4 代特有）────────────────────
    #     ★ 必须走 Tools/am3_dat_pack.py，**不能**用 am3_dat.py pack：
    #       后者会丢掉每个重编码对象尾部的 24 字节，文件变短、其后对象
    #       偏移全部前移。4 代的 dat 魔数与 3 代相同，该工具可直接用；
    #       但**权威值（大小/对象数）必须按 4 代重测**（见 DAT_JOBS）。
    packer = os.path.join(root, "Tools", "am3_dat_pack.py")
    if not os.path.isfile(packer):
        print("!! 缺少回包工具: %s" % packer, file=sys.stderr)
        return 1

    for job in DAT_JOBS:
        src_dir = os.path.join(root, job["src"])
        if not os.path.isdir(src_dir):
            print("!! 缺少解包目录: %s" % src_dir, file=sys.stderr)
            return 1
        dst_dat = os.path.join(out, job["out"])
        cmd = [sys.executable, packer, src_dir, dst_dat,
               "--expect-size", str(job["expect_size"])]
        if job["overlay"]:
            ovl = os.path.join(root, job["overlay"])
            if not os.path.isdir(ovl):
                print("!! 缺少中文控件覆盖层: %s" % ovl, file=sys.stderr)
                return 1
            cmd += ["--overlay", ovl]
        print("  [2] 回包 %s" % job["out"])
        r = subprocess.run(cmd)
        if r.returncode != 0:
            print("!! 回包失败: %s" % job["out"], file=sys.stderr)
            return 1
        size = os.path.getsize(dst_dat)
        if size != job["expect_size"]:
            print("!! %s 大小 %d != 期望 %d"
                  % (job["out"], size, job["expect_size"]), file=sys.stderr)
            return 1
        stats["files"] += 1
        stats["bytes"] += size
    print()

    # ── 3. 运行期文件：ASI 与中文字库 ─────────────────────────────────
    dll_src = os.path.join(dll_dir, "Release", DLL_NAME)
    if os.path.isfile(dll_src):
        shutil.copyfile(dll_src, os.path.join(out, DLL_NAME))
        stats["files"] += 1
        stats["bytes"] += os.path.getsize(dll_src)
        print("  [3] %s  (%d B)" % (DLL_NAME, os.path.getsize(dll_src)))
    else:
        # ★ 不静默跳过：没有 ASI 就没有中文渲染，产物必然无效。
        print("  [3] !! ASI 未编译: %s" % dll_src, file=sys.stderr)
        print("      先跑 python Tools/ci/compile_dll_wine.py "
              "--proj Army4_Extend_Dll", file=sys.stderr)
        return 1

    # 字库：从仓库内已跟踪的 Army2_CHS/Hzk16 取
    #   ★ 4 代官方 exe 内**没有** Hzk16（无中文母盘），复用 2 代中文版那份。
    #     ASI 在 <DLL 目录>\Hzk16 找它，故包内落 scripts\Hzk16。
    hzk_src = None
    for c in HZK_CANDIDATES:
        p = c if os.path.isabs(c) else os.path.join(root, c)
        if os.path.isfile(p):
            hzk_src = p
            break
    if not hzk_src:
        # 字库缺失 = 中文完全无法显示，必须失败而不是静默继续
        print("  [3] !! 找不到 %s（中文将无法显示）: %s"
              % (HZK_NAME, ", ".join(HZK_CANDIDATES)), file=sys.stderr)
        return 1
    shutil.copyfile(hzk_src, os.path.join(out, HZK_NAME))
    stats["files"] += 1
    stats["bytes"] += os.path.getsize(hzk_src)
    print("      %s  <- %s  (%d B)"
          % (HZK_NAME, os.path.relpath(hzk_src, root), os.path.getsize(hzk_src)))

    # ── 4. 包根文件：cnc-ddraw 的 ddraw.dll / ddraw.ini ────────────────
    for f in ROOT_FILES:
        s = os.path.join(root, CNC_DIR, f)
        if not os.path.isfile(s):
            print("  [4] !! 缺少 %s/%s（4 代渲染依赖 cnc-ddraw，不能少）"
                  % (CNC_DIR, f), file=sys.stderr)
            return 1
        shutil.copyfile(s, os.path.join(out, f))
        stats["files"] += 1
        stats["bytes"] += os.path.getsize(s)
        print("  [4] %s  <- %s/%s  (%d B)"
              % (f, CNC_DIR, f, os.path.getsize(s)))
    print()

    # ── 5. 中文配音：Army4_Voice_CHS/audio -> build_out_am4/audio ──────
    #     ★ 保持 vos\ 子目录结构：游戏读 update\audio\vos\*.wav。
    #     ★ 数量与体积都要核：只查"目录非空"挡不住"只拷了 3 个文件"。
    audio_src = (audio_src_rel if os.path.isabs(audio_src_rel)
                 else os.path.join(root, audio_src_rel))
    if not os.path.isdir(audio_src):
        print("  [5] !! 缺少配音目录: %s" % audio_src, file=sys.stderr)
        print("      它是仓库内载荷（Army4_Voice_CHS/audio）；"
              "缺失则 4 代包不带中文配音。", file=sys.stderr)
        return 1
    audio_dst = os.path.join(out, AUDIO_DIR_NAME)
    os.makedirs(audio_dst, exist_ok=True)
    n_audio0 = stats["files"]
    copy_tree(audio_src, audio_dst, stats)
    n_audio = stats["files"] - n_audio0
    audio_bytes = 0
    for dp, _, fns in os.walk(audio_dst):
        for fn in fns:
            audio_bytes += os.path.getsize(os.path.join(dp, fn))
    print("  [5] %s/  %d 文件 / %.2f MB  <- %s"
          % (AUDIO_DIR_NAME, n_audio, audio_bytes / 1048576,
             _disp(audio_src, root)))

    # ★ 配音文件名必须是英文原声的子集：游戏按原名加载，名字对不上
    #   等于没配（静默失效，不报错）。这条与 3 代不同 —— 3 代只核了数量。
    baseline = os.path.join(root, AUDIO_BASELINE_DIR)
    if os.path.isdir(baseline):
        known = {f.lower() for f in os.listdir(baseline)}
        stray = []
        for dp, _, fns in os.walk(audio_dst):
            for fn in fns:
                if fn.lower() not in known:
                    stray.append(os.path.relpath(os.path.join(dp, fn), out))
        if stray:
            print("  [5] !! 配音含 %d 个英文原声里没有的文件名（游戏不会加载）:"
                  " %s" % (len(stray), stray[:5]), file=sys.stderr)
            return 1
        print("      文件名全部对应英文原声  OK（基线 %s）"
              % os.path.relpath(baseline, root))
    else:
        print("  [5] !! 找不到英文配音基线目录: %s（无法核文件名对应关系）"
              % baseline, file=sys.stderr)
        return 1

    if n_audio != AUDIO_EXPECT_FILES or audio_bytes < AUDIO_MIN_BYTES:
        print("  [5] !! 配音数量/体积不符：%d 文件（期望 %d）/ %d B（下限 %d）"
              % (n_audio, AUDIO_EXPECT_FILES, audio_bytes, AUDIO_MIN_BYTES),
              file=sys.stderr)
        print("      ★TODO：中文配音尚未生成（Army4_Voice_CHS/audio 为空）。"
              "生成流程见 docs/11-am4-reuse-plan.md §2.2。", file=sys.stderr)
        return 1
    print()

    print("总计: %d 文件 / %.1f MB" % (stats["files"], stats["bytes"] / 1048576))

    # ── 6. MANIFEST.json（build_out 的权威清单；verify_release_am4 用它核对）──
    rows = []
    for dp, _, fns in os.walk(out):
        for fn in fns:
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, out).replace(os.sep, "/")
            if rel.split("/")[0] in RUNTIME_TOP:
                continue          # 运行期/包根文件不属于 update\ 载荷
            rows.append((rel, os.path.getsize(full), sha256(full)))
    rows.sort()
    with open(os.path.join(out, "MANIFEST.json"), "w", encoding="utf-8",
              newline="\n") as f:
        json.dump({"game": "Army Men: World War",
                   "count": len(rows),
                   "note": ("build_out_am4 载荷清单（= Army4_NEW_CHS 快照 + "
                            "回包后的 title.dat/shared.dat + 中文配音）。"
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

    # 载荷不得含可执行文件
    bad_ext = []
    for dp, _, fns in os.walk(out):
        for fn in fns:
            rel = os.path.relpath(os.path.join(dp, fn), out).replace(os.sep, "/")
            if rel.split("/")[0] in RUNTIME_TOP:
                continue
            if os.path.splitext(fn)[1].lower() in PAYLOAD_FORBIDDEN_EXT:
                bad_ext.append(rel)
    if bad_ext:
        print("  !! 载荷含可执行文件（违反「不改游戏文件」约束）: %s"
              % bad_ext[:5])
        ok = False
    else:
        print("  载荷无可执行文件  OK")

    if not rows:
        print("  !! 载荷为空")
        ok = False
    else:
        print("  载荷 %d 个文件  OK" % len(rows))

    # 必备项逐一存在
    required = [
        DLL_NAME, HZK_NAME,
        os.path.join("01-title", "01_000_00_screen.bmp"),
        os.path.join("strings", "strings.txt"),
        "title.dat", "shared.dat",
    ] + ROOT_FILES
    for rel in required:
        p = os.path.join(out, rel.replace("/", os.sep))
        exists = os.path.isfile(p)
        print("  %-38s %s" % (rel, "OK" if exists else "缺失"))
        if not exists:
            ok = False

    # 回包产物必须与原版等长（这是"偏移不变"的前提）
    for job in DAT_JOBS:
        p = os.path.join(out, job["out"])
        if not os.path.isfile(p):
            ok = False
            continue
        sz = os.path.getsize(p)
        good = sz == job["expect_size"]
        print("  %-14s %9d B  sha=%s  %s"
              % (job["out"], sz, sha256(p)[:12],
                 "OK" if good else "!! 大小不符 %d" % job["expect_size"]))
        if not good:
            ok = False

    print("  DLL sha = %s" % sha256(os.path.join(out, DLL_NAME))[:12])

    # 配音必须真的落到 build_out（不是"拷了 0 个文件也算过"）
    n_wav = 0
    for dp, _, fns in os.walk(audio_dst):
        n_wav += sum(1 for fn in fns if fn.lower().endswith(".wav"))
    print("  %-38s %s" % ("audio/vos/*.wav",
                          "%d 个 OK" % n_wav if n_wav >= AUDIO_EXPECT_FILES
                          else "%d 个 !! 少于预期 %d"
                          % (n_wav, AUDIO_EXPECT_FILES)))
    if n_wav < AUDIO_EXPECT_FILES:
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
