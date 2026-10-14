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
        [f"/Fp{build}/{PROJ}.pch", f"/Fo{build}/", "pch.cpp"]
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
            [f"/Fp{build}/{PROJ}.pch",
             f"/Fo{build}/{out_name}", s]
        print(f"── 编译 {s} ──")
        r = subprocess.run(cmd, env=env)
        if r.returncode != 0:
            print(f"!! 编译 {s} 失败", file=sys.stderr)
            os.chdir(root)
            return 1
        objs.append(f"{build}/{out_name}")

    # 3) 链接
    out_dll = f"{build}/{PROJ}.dll"
    cmd = [link] + LINK_FLAGS + objs + LINK_LIBS + \
        [f"/OUT:{out_dll}", f"/IMPLIB:{build}/{PROJ}.lib"]
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
