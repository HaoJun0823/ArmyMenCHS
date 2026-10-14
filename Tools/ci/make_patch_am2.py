"""组装 Army Men II 汉化补丁包（stage）。

输入：
    build_out_am2/update/            资产（由 build_update_am2.py 产出）
    Army2_Extend_Dll/Release/*.dll   编译好的 ASI
    Army2_Extend_Dll/ArmyMenCHS.ini  主配置
    Army2_Extend_Dll/strings/*.ini   译文表

输出：
    stage_am2/
      dinput.dll                   ASI Loader（由 UAL 改名；见下方 ★）
      scripts/
        Army2_Extend_Dll.asi       ← Release 里的 .dll 改名而来
        ArmyMenCHS.ini
        Hzk16                      中文字库
        strings/am2_strings.ini
      update/                      资产目录（ASI Loader 覆盖到游戏视图）
      LICENSE / License.txt / 安装说明.txt

★★ 关于用哪个 DLL 名做 ASI 代理（重要，且与 1 代不同）
   1 代用 dsound.dll。但本作（AM2/TIS）**按序号 1 导入 dsound.dll**，
   而 Ultimate ASI Loader 的导出表是"多 DLL 合并表"：
       序号   1 = XWSAStartup       ← 不是 DirectSoundCreate
       序号 263 = DirectSoundCreate
   直接沿用 dsound.dll 会让游戏拿到错误的 DirectSoundCreate（无声音且无报错）。
   而 AM2/TIS **按名字**导入 dinput.dll!DirectInputCreateA，
   UAL 导出表里有该名字（序号 255），命中可靠。
   所以本补丁用 **dinput.dll** 作代理名。

用法：
    python Tools/ci/make_patch_am2.py
"""

import os
import shutil
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILD_OUT = os.path.join(ROOT, "build_out_am2")
DLL_DIR = os.path.join(ROOT, "Army2_Extend_Dll")
STAGE = os.path.join(ROOT, "stage_am2")

# ASI Loader 源（1 代产物里已验证可用的 UAL 9.7.4）
UAL_CANDIDATES = [
    os.path.join(ROOT, "stage", "dsound.dll"),
    os.path.join(ROOT, "dist", "dsound.dll"),
]

PROXY_NAME = "dinput.dll"          # ★ 见文件头说明
ASI_NAME = "Army2_Extend_Dll.asi"


def find_ual():
    for p in UAL_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def pe_machine(path):
    with open(path, "rb") as f:
        b = f.read(0x400)
    if b[:2] != b"MZ":
        return None
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    return struct.unpack_from("<H", b, pe + 4)[0]


def main():
    dll = os.path.join(DLL_DIR, "Release", "Army2_Extend_Dll.dll")
    ini = os.path.join(DLL_DIR, "ArmyMenCHS.ini")
    strings = os.path.join(DLL_DIR, "strings", "am2_strings.ini")

    for p, what in ((dll, "ASI DLL"), (ini, "主配置"), (strings, "译文表")):
        if not os.path.isfile(p):
            print("!! 缺少%s: %s" % (what, p), file=sys.stderr)
            return 1
    if pe_machine(dll) != 0x14C:
        print("!! ASI 不是 32 位 PE", file=sys.stderr)
        return 1

    ual = find_ual()
    if not ual:
        print("!! 找不到 Ultimate ASI Loader（stage\\dsound.dll 或 dist\\dsound.dll）",
              file=sys.stderr)
        print("   它不在仓库里（第三方二进制）。请先跑一次 1 代的 make_patch.py，", file=sys.stderr)
        print("   或手工放一份 UAL 到 stage\\dsound.dll。", file=sys.stderr)
        return 1

    # 先整体删除（不做静默容错 —— 1 代坑 6.2：清理失败会混入陈旧文件）
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    os.makedirs(os.path.join(STAGE, "scripts", "strings"))

    # ① ASI Loader 改名
    shutil.copyfile(ual, os.path.join(STAGE, PROXY_NAME))

    # ② ASI 本体（必须改名 .asi：UAL 只扫描 scripts\*.asi）
    shutil.copyfile(dll, os.path.join(STAGE, "scripts", ASI_NAME))

    # ③ 配置与译文
    shutil.copyfile(ini, os.path.join(STAGE, "scripts", "ArmyMenCHS.ini"))
    shutil.copyfile(strings, os.path.join(STAGE, "scripts", "strings",
                                         "am2_strings.ini"))

    # ④ 中文字库（从中文母盘取，放进 scripts\ 让 DLL 优先找到）
    hzk_src = None
    for c in (r"I:\LocalGames\Army Men\玩具兵大战2\Hzk16",
              os.path.join(BUILD_OUT, "update", "Hzk16")):
        if os.path.isfile(c):
            hzk_src = c
            break
    if hzk_src:
        shutil.copyfile(hzk_src, os.path.join(STAGE, "scripts", "Hzk16"))
    else:
        print("   !! 找不到 Hzk16（中文将无法显示）", file=sys.stderr)

    # ⑤ 资产
    upd = os.path.join(BUILD_OUT, "update")
    if os.path.isdir(upd):
        shutil.copytree(upd, os.path.join(STAGE, "update"), dirs_exist_ok=True)
        # Hzk16 已放 scripts\，update\ 里的副本可以去掉（避免两份）
        dup = os.path.join(STAGE, "update", "Hzk16")
        if os.path.isfile(dup):
            os.remove(dup)
    else:
        print("   !! 没有 build_out_am2/update（只打包 DLL，无资产）", file=sys.stderr)

    # ⑥ 许可与说明
    for src, dst in ((os.path.join(ROOT, "LICENSE"), "LICENSE"),):
        if os.path.isfile(src):
            shutil.copyfile(src, os.path.join(STAGE, dst))

    shutil.copyfile(os.path.join(ROOT, "LICENSES", "Ultimate-ASI-Loader.txt"),
                    os.path.join(STAGE, "License.txt")) \
        if os.path.isfile(os.path.join(ROOT, "LICENSES", "Ultimate-ASI-Loader.txt")) else None

    with open(os.path.join(STAGE, "安装说明.txt"), "w", encoding="utf-8-sig",
              newline="\r\n") as f:
        f.write(
            "《玩具兵大战2》(Army Men II) 简体中文补丁\n"
            "========================================\n\n"
            "本补丁基于 1999 年上海育碧发行的官方简体中文版制作。\n"
            "**不修改游戏的任何 exe/dll 文件**，全部通过内存注入实现，\n"
            "卸载只需删除本补丁加入的文件。\n\n"
            "【安装】\n"
            "  1. 关闭游戏\n"
            "  2. 把本包内所有文件解压到游戏根目录\n"
            "     （ArmyMen2.exe 所在目录，解压后会覆盖/新增 dinput.dll）\n"
            "  3. 启动游戏\n\n"
            "【验证是否生效】\n"
            "  安装后脚本目录下会生成日志：\n"
            "     scripts\\ArmyMen2CHS.log\n"
            "  日志里应能看到：\n"
            "     InstallAll: 适配档位 = ArmyMenII\n"
            "     Renderer: 已 hook RVA=0x46930\n"
            "     strings: applied=N\n"
            "  若日志里是 \"目标识别失败\" 或 \"签名校验失败\"，说明游戏版本不符，\n"
            "  补丁会主动停用（不会破坏游戏）。\n\n"
            "【卸载】\n"
            "  删除以下内容即可：\n"
            "    dinput.dll\n"
            "    scripts\\ 目录（如果里面只有本补丁的文件）\n"
            "    update\\  目录\n\n"
            "【说明】\n"
            "  * 中文字库 Hzk16 来自官方中文版，放在 scripts\\ 下。\n"
            "  * 电影为原版画面 + 中文配音音轨（画面本身无字幕文字）。\n"
            "  * 若出现异常，请把 scripts\\ArmyMen2CHS.log 一并反馈。\n"
        )

    # ── 报告 ──────────────────────────────────────────────────────────
    total = 0
    n = 0
    for dp, dn, fn in os.walk(STAGE):
        for x in fn:
            total += os.path.getsize(os.path.join(dp, x))
            n += 1
    print("stage -> %s" % STAGE)
    print("  文件 %d 个，%.2f MB" % (n, total / 1048576))
    for k in sorted(os.listdir(STAGE)):
        p = os.path.join(STAGE, k)
        if os.path.isdir(p):
            c = sum(len(f) for _, _, f in os.walk(p))
            print("    %-16s <目录> %d 文件" % (k, c))
        else:
            print("    %-16s %d 字节" % (k, os.path.getsize(p)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
