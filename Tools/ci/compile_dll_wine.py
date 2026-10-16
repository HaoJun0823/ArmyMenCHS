"""
在 Linux (msvc-wine) 下编译 Army1_Extend_Dll 的 32 位 DLL。

为什么不用 MSBuild：
    msvc-wine 只提供 cl.exe / link.exe，没有 MSBuild。
    所以把 vcxproj 的 Release|Win32 配置**逐项翻译**成 cl/link 命令行。

vcxproj Release|Win32 关键设置（翻译来源）：
    ConfigurationType : DynamicLibrary
    PlatformToolset   : v141_xp   -> 实际用 VC 14.16 (cl 19.16) 编译，
                                     不传 XP 专属链接选项（msvc-wine 无 XP SDK）
    CharacterSet      : Unicode   -> -D_UNICODE -DUNICODE
    AdditionalOptions : /utf-8    -> cl 的 /utf-8
    预编译头          : pch.h     -> /Yu"pch.h" + 单独编译 pch.cpp 生成 .pch

翻译表：
    /GS /GL /W3 /Gy /Zc:wchar_t /Gm- /O2 /Oi /Zc:inline /fp:precise
    /D "_WINDLL" /D "_UNICODE" /D "UNICODE" /D "NDEBUG"
    /errorReport:prompt /WX- /Zc:forScope /Gd /Oy- /MT /Fa"Release/"
    /EHsc /nologo /Fo"Release/" /Fp"Release/Army1_Extend_Dll.pch" /utf-8

链接：
    /DLL /MACHINE:X86 /OPT:REF /OPT:ICF /INCREMENTAL:NO /SUBSYSTEM:WINDOWS
    导出：ArmyMenCHS_Install / ArmyMenCHS_Uninstall（源码里已 __declspec(dllexport)）

用法（CI）：
    python3 Tools/ci/compile_dll_wine.py --msvc-prefix .msvc
"""

import os
import sys
import subprocess
import shutil

# ── 工程配置表 ─────────────────────────────────────────────────────────
# ★ 为什么做成表：1 代与 2 代的源码清单、包含路径、导出都不同，
#   而 1 代早期把 SOURCES 硬编码在模块顶层，导致 2 代只能整份复制脚本
#   （两份脚本各维护一份 cl/link 参数，早晚对不上）。
#   现在按工程名选配置，wine 下的编译流程（pch /Yu /link /PE 校验）完全共用。
PROJECTS = {
    "Army1_Extend_Dll": {
        "sources": ["dllmain.cpp", r"src\hooks.cpp", r"src\ini_reader.cpp",
                    "pch.cpp"],
        "includes": ["."],          # pch.h 在根，src/*.h 用 "hooks.h" 相对自身目录
    },
    "Army2_Extend_Dll": {
        # 2 代源码在 src\，且多了 target/renderer/hzk16/strings/codepatch/log
        "sources": [
            "dllmain.cpp",
            r"src\hooks.cpp",
            r"src\target.cpp",
            r"src\renderer.cpp",
            r"src\hzk16.cpp",
            r"src\strings.cpp",
            r"src\codepatch.cpp",
            r"src\log.cpp",
        ],
        "includes": ["src", "."],
    },
    "Army3_Extend_Dll": {
        # 3 代源码同样在 src\。
        # ★ 与 2 代的差异：没有 strings.cpp / codepatch.cpp
        #   —— 3 代的界面文本全在游戏自己的 strings\strings.txt，
        #   不需要内存字符串补丁与译文表（见 dllmain.cpp 的设计要点）。
        # 源码清单必须与 Army3_Extend_Dll.vcxproj 的 <ClCompile> **完全一致**。
        #   ★ 漏一个会怎样（两类都会让 CI 直接红，不是"参考清单"）：
        #     · 漏 .cpp -> 链接期 LNK2019 无法解析的外部符号
        #       （hooks.cpp 无条件调用 MpUnlockInstall / MpUnlockRemove，
        #        它们的实现在 src\mpunlock.cpp）
        #     · 漏被 #include 的头 -> 编译期 C1083 无法打开包括文件
        #   vcxproj 与这份清单是两处独立维护的同一事实，改一处必须改另一处。
        "sources": [
            "dllmain.cpp",
            r"src\hooks.cpp",
            r"src\mpunlock.cpp",
            r"src\hzk16.cpp",
            r"src\log.cpp",
            r"src\renderer.cpp",
            r"src\target.cpp",
        ],
        # ★ includes 里 **不需要** 加 "src"：3 代源码的头文件引用一律写成
        #   "src\hooks.h"（dllmain.cpp）或 "hooks.h"（src/ 内部互引）。
        #   后者靠"包含当前文件所在目录"即可解析；前者相对工程根。
        #   这里加 "." 是为了 pch.h / framework.h 在工程根也能被找到。
        "includes": ["."],
    },
    "Army4_Extend_Dll": {
        # 4 代（World War / 世界大战）源码树与 3 代**逐文件对应**
        # （dllmain + hooks/mpunlock/hzk16/log/renderer/target），
        # 但签名、patchLen、全局表地址全部重测过（见 docs/12）——
        # 故**不能**复用 Army3 的清单，必须独立一项。
        # 源码清单必须与 Army4_Extend_Dll.vcxproj 的 <ClCompile> 完全一致。
        "sources": [
            "dllmain.cpp",
            r"src\hooks.cpp",
            r"src\mpunlock.cpp",
            r"src\hzk16.cpp",
            r"src\log.cpp",
            r"src\renderer.cpp",
            r"src\target.cpp",
        ],
        "includes": ["."],
    },
}

PROJ = "Army1_Extend_Dll"
DEFINES = ["_WINDLL", "_UNICODE", "UNICODE", "NDEBUG"]
CL_FLAGS = [
    "/nologo", "/c", "/GS", "/W3", "/Gy", "/Zc:wchar_t", "/Zc:inline",
    "/Zc:forScope", "/Gd", "/O2", "/Oi", "/Oy-", "/fp:precise", "/MT",
    "/EHsc", "/errorReport:prompt", "/utf-8",
]
LINK_FLAGS = [
    "/nologo", "/DLL", "/MACHINE:X86", "/OPT:REF", "/OPT:ICF",
    "/INCREMENTAL:NO", "/SUBSYSTEM:WINDOWS",
]
LINK_LIBS = ["kernel32.lib", "user32.lib", "gdi32.lib", "advapi32.lib"]


def main():
    args = sys.argv[1:]
    prefix = args[args.index("--msvc-prefix") + 1] if "--msvc-prefix" in args \
        else os.environ.get("MSVC_WINE_PREFIX", ".msvc")
    proj_dir = args[args.index("--proj") + 1] if "--proj" in args else PROJ

    if proj_dir not in PROJECTS:
        print(f"!! 未知工程 {proj_dir}；可选：{', '.join(sorted(PROJECTS))}",
              file=sys.stderr)
        return 1
    cfg = PROJECTS[proj_dir]
    SOURCES = cfg["sources"]
    INCLUDES = cfg["includes"]
    # ★★ 输出名必须绑定到**实际工程目录名**，不能用模块级 PROJ（写死 Army1）。
    #   踩过的坑（CI run 38555347853）：
    #     `--proj Army2_Extend_Dll` 只切换了 SOURCES/INCLUDES，而下面
    #     /Fp{build}/{PROJ}.pch、/OUT:{PROJ}.dll 仍用 PROJ="Army1_Extend_Dll"，
    #     于是 2 代编出来的产物叫 Army1_Extend_Dll.dll。
    #     编译步骤**报绿**（"✓ Army2_Extend_Dll/Release/Army1_Extend_Dll.dll"），
    #     随后 ci_build_am2.py 找不到 Army2_Extend_Dll.dll 才失败 ——
    #     症状离根因隔了两步，非常容易误判成"资产缺失"。
    #   2 代与 1 代同在一个 job 里编译，但各自在**自己的目录**下构建，
    #   故用 proj_dir 作产物前缀是安全的（不会互相覆盖）。
    #   ★ 用独立变量名而不是复用 PROJ：给 PROJ 赋值会让它变成局部变量，
    #     上面第 80 行的 `else PROJ` 回退就会 UnboundLocalError。
    OUT_STEM = proj_dir

    bin_dir = os.path.join(prefix, "bin", "x86")
    cl = os.path.join(bin_dir, "cl")
    link = os.path.join(bin_dir, "link")
    for t in (cl, link):
        if not os.path.exists(t):
            print(f"!! 未找到 {t}", file=sys.stderr)
            return 1

    env = os.environ.copy()
    # ★★ C1356 坑（本地实测复现，MajestyIIExtend CI 亦记录）：
    #   bin/x86/cl（Hostx64/x86，64位宿主编32位目标）启动时按 PATH 找
    #   mspdbcore.dll，而该文件只存在于 Hostx64/x64 目录。
    #   只把 bin/x86 加进 PATH 会报 "fatal error C1356: unable to find
    #   mspdbcore.dll"。msvc-wine 的 msvcenv.sh 会在 WINEPATH 末尾追加
    #   Hostx64/x64，但前提是 CI 下载时 --architecture 必须含 x64。
    #   这里再显式补一次，双保险。
    extra = [bin_dir]
    b64 = os.path.join(prefix, "bin", "x64")
    if os.path.isdir(b64):
        extra.append(b64)
    env["PATH"] = os.pathsep.join(extra) + os.pathsep + env.get("PATH", "")

    root = os.getcwd()
    os.chdir(proj_dir)

    build = "Release"
    os.makedirs(build, exist_ok=True)

    # 1) 生成预编译头：pch.cpp 用 /Yc
    pch_cmd = [cl] + CL_FLAGS + ["/Yc" "pch.h"] + \
        [f"/D{d}" for d in DEFINES] + \
        [f"/I{i}" for i in INCLUDES] + \
        [f"/Fp{build}/{OUT_STEM}.pch", f"/Fo{build}/", "pch.cpp"]
    print("── 生成预编译头 ──")
    print(" ".join(pch_cmd))
    r = subprocess.run(pch_cmd, env=env)
    if r.returncode != 0:
        print("!! 预编译头失败", file=sys.stderr)
        os.chdir(root)
        return 1

    # 2) 编译其余源（用 /Yu）
    objs = [f"{build}/pch.obj"]
    for s in SOURCES:
        if s == "pch.cpp":
            continue
        out_name = s.replace("\\", "_").replace(".cpp", ".obj")
        cmd = [cl] + CL_FLAGS + ["/Yu" "pch.h"] + \
            [f"/D{d}" for d in DEFINES] + \
            [f"/I{i}" for i in INCLUDES] + \
            [f"/Fp{build}/{OUT_STEM}.pch",
             f"/Fo{build}/{out_name}", s]
        print(f"── 编译 {s} ──")
        r = subprocess.run(cmd, env=env)
        if r.returncode != 0:
            print(f"!! 编译 {s} 失败", file=sys.stderr)
            os.chdir(root)
            return 1
        objs.append(f"{build}/{out_name}")

    # 3) 链接
    out_dll = f"{build}/{OUT_STEM}.dll"
    cmd = [link] + LINK_FLAGS + objs + LINK_LIBS + \
        [f"/OUT:{out_dll}", f"/IMPLIB:{build}/{OUT_STEM}.lib"]
    print("── 链接 ──")
    r = subprocess.run(cmd, env=env)
    os.chdir(root)
    if r.returncode != 0:
        print("!! 链接失败", file=sys.stderr)
        return 1

    dll_path = os.path.join(proj_dir, out_dll)
    if not os.path.isfile(dll_path):
        print(f"!! 未产出 {dll_path}", file=sys.stderr)
        return 1
    size = os.path.getsize(dll_path)
    print(f"✓ {dll_path}  {size} bytes")

    # 4) 校验 PE：必须是 32 位
    with open(dll_path, "rb") as f:
        b = f.read()
    import struct
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    machine = struct.unpack_from("<H", b, pe + 4)[0]
    if machine != 0x14C:
        print(f"!! 不是 32 位 PE (machine=0x{machine:X})", file=sys.stderr)
        return 1
    print(f"✓ PE machine=0x{machine:X} (i386)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
