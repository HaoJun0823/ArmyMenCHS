"""
在 Windows 本地用真实 MSVC 2017 (v141) 编译 32 位 Army1_Extend_Dll.dll。

CI 上走 compile_dll_wine.py（Linux + msvc-wine）；此脚本只供 Windows 本地验证，
用来在推送前先确认源码能编译、产物是 32 位 PE、导出齐全。

★ 为什么用 Python 而不是 .ps1/.cmd：
    cl.exe 需要传 /Yc"pch.h" 这类**内嵌引号**的参数。
    PowerShell 5.1 的 & $exe @a 会吞掉它（静默只编第一个源文件），
    Start-Process -ArgumentList 会二次转义破坏它，
    手拼 cmd 字符串又会被引号规则吃掉。
    Python 的 subprocess 列表参数直接交给 CreateProcess，
    由 MSVC 自己的 CRT 解析引号，零歧义。

用法：
    python Tools/ci/build_dll_local.py
"""

import os
import struct
import subprocess
import sys

VC = r"C:\Program Files (x86)\Microsoft Visual Studio\2017\Professional\VC\Tools\MSVC\14.16.27023"
SDK = r"C:\Program Files (x86)\Windows Kits\10"
SDKV = "10.0.26100.0"
# 本脚本是 Windows + MSVC 专用（CI 用 compile_dll_wine.py），
# 但路径仍从 __file__ 推导，避免换机器/换 clone 位置时失效。
PROJ = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "Army1_Extend_Dll")

# 顺序与 vcxproj Release|Win32 一致
CL_FLAGS = [
    "/nologo", "/c", "/GS", "/W3", "/Gy", "/Zc:wchar_t", "/Zc:inline",
    "/Zc:forScope", "/Gd", "/O2", "/Oi", "/Oy-", "/fp:precise", "/MT",
    "/EHsc", "/errorReport:prompt", "/utf-8",
    "/D_WINDLL", "/D_UNICODE", "/DUNICODE", "/DNDEBUG",
]
LINK_FLAGS = [
    "/nologo", "/DLL", "/MACHINE:X86", "/OPT:REF", "/OPT:ICF",
    "/INCREMENTAL:NO", "/SUBSYSTEM:WINDOWS",
]
LINK_LIBS = ["kernel32.lib", "user32.lib", "gdi32.lib", "advapi32.lib"]

SOURCES = ["dllmain.cpp", r"src\hooks.cpp", r"src\ini_reader.cpp"]
EXPORTS = [b"ArmyMenCHS_Install", b"ArmyMenCHS_Uninstall", b"InitializeASI"]


def env_setup():
    e = os.environ.copy()
    # ★ C1356 坑：Hostx64\x86\cl.exe 启动时按 PATH 找 mspdbcore.dll，
    #   而该文件只在 Hostx64\x64 下。只加 x86 会报
    #   "fatal error C1356: unable to find mspdbcore.dll"。
    e["PATH"] = os.pathsep.join([
        os.path.join(VC, "bin", "Hostx64", "x86"),
        os.path.join(VC, "bin", "Hostx64", "x64"),
        e.get("PATH", ""),
    ])
    inc = os.path.join(SDK, "Include", SDKV)
    e["INCLUDE"] = ";".join([
        os.path.join(VC, "include"),
        os.path.join(inc, "ucrt"),
        os.path.join(inc, "shared"),
        os.path.join(inc, "um"),
    ])
    lib = os.path.join(SDK, "Lib", SDKV)
    e["LIB"] = ";".join([
        os.path.join(VC, "lib", "x86"),
        os.path.join(lib, "ucrt", "x86"),
        os.path.join(lib, "um", "x86"),
    ])
    return e


def run(cmd, cwd, env):
    print("\n-- " + " ".join(
        os.path.basename(cmd[0]) if i == 0 else c for i, c in enumerate(cmd)))
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.stdout.strip():
        print(r.stdout.strip())
    if r.stderr.strip():
        print("[stderr]", r.stderr.strip())
    if r.returncode != 0:
        print("!! exit=%d" % r.returncode, file=sys.stderr)
        return False
    return True


def clean(build):
    # 清掉上次的中间产物。否则链接可能悄悄用旧 obj，产出残缺 DLL
    # （本项目踩过：只有 pch.obj 被重编，链接器拿了 4 小时前的
    #   dllmain.obj/ini.obj，DLL 里一个导出都没有，且不报任何错）。
    for fn in os.listdir(build):
        if fn.endswith((".obj", ".pch", ".lib")) or \
                (fn.endswith(".dll") and not fn.endswith(".i64")):
            os.remove(os.path.join(build, fn))
            print("   rm", fn)


def main():
    cl = os.path.join(VC, "bin", "Hostx64", "x86", "cl.exe")
    link = os.path.join(VC, "bin", "Hostx64", "x86", "link.exe")
    for p in (cl, link):
        if not os.path.isfile(p):
            print("!! 缺少工具: %s" % p, file=sys.stderr)
            return 1

    env = env_setup()
    build = os.path.join(PROJ, "Release")
    os.makedirs(build, exist_ok=True)
    clean(build)

    pch = os.path.join(build, "Army1_Extend_Dll.pch")

    # 1) 预编译头
    #    ★ /Yc 与 /Yu 的文件名**不带引号**：Python 的 subprocess 会把参数里的
    #      双引号转义成 \" 再交给 CRT，最终 cl 收到 /Yc\"pch.h\" 而匹配不到
    #      #include，报 C2857。pch.h 本就无空格，去掉引号即可。
    if not run([cl] + CL_FLAGS + ["/Ycpch.h", "/Fp" + pch,
                                  "/Fo" + build + os.sep, "pch.cpp"],
               PROJ, env):
        return 1

    # 2) 其余源文件 —— 逐个编译并确认 .obj 真的产出
    objs = [os.path.join(build, "pch.obj")]
    for s in SOURCES:
        sp = os.path.join(PROJ, s)
        if not os.path.isfile(sp):
            print("!! 缺少源文件 %s" % s, file=sys.stderr)
            return 1
        obj = os.path.join(build, s.replace("\\", "_").replace(".cpp", ".obj"))
        if not run([cl] + CL_FLAGS + ["/Yupch.h", "/Fp" + pch,
                                      "/Fo" + obj, s],
                   PROJ, env):
            return 1
        if not os.path.isfile(obj):
            print("!! 未产出 %s（源文件被静默跳过？）" % obj, file=sys.stderr)
            return 1
        objs.append(obj)

    print("\n   objs: " + ", ".join(os.path.basename(o) for o in objs))

    # 3) 链接
    dll = os.path.join(build, "Army1_Extend_Dll.dll")
    if not run([link] + LINK_FLAGS + objs + LINK_LIBS +
               ["/OUT:" + dll, "/IMPLIB:" + os.path.join(build,
                                                        "Army1_Extend_Dll.lib")],
               PROJ, env):
        return 1
    if not os.path.isfile(dll):
        print("!! 未产出 %s" % dll, file=sys.stderr)
        return 1

    # 4) 校验：32 位 PE + 导出齐全
    with open(dll, "rb") as f:
        b = f.read()
    if b[:2] != b"MZ":
        print("!! 不是 PE", file=sys.stderr)
        return 1
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    machine = struct.unpack_from("<H", b, pe + 4)[0]
    print("\n== %s  %d bytes  machine=0x%X" % (dll, len(b), machine))
    if machine != 0x14C:
        print("!! 不是 32 位 PE", file=sys.stderr)
        return 1
    ok = True
    for e in EXPORTS:
        hit = e in b
        print("   %s 导出 %s" % ("[ OK ]" if hit else "[FAIL]", e.decode()))
        ok = ok and hit
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())