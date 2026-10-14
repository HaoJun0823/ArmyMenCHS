"""在 Windows 本地用真实 MSVC 2017 (v141) 编译 32 位 Army2_Extend_Dll.dll。

与 1 代的 build_dll_local.py 结构一致，关键约束也相同：
  * 用 Python subprocess 而不是 PowerShell —— cl.exe 需要 /Yc"pch.h" 这类
    **内嵌引号**参数，PowerShell 会静默吞掉它们（见 1 代 02-pitfalls.md 坑 6.1）
  * 编译前 clean 掉旧中间产物 —— 否则链接器可能复用陈旧 .obj，
    产出"零导出且不报错"的 DLL（1 代真实踩过）
  * 链接后必须断言：32 位 PE + 三个导出齐全

★ C1356 坑：Hostx64\\x86\\cl.exe 启动时按 PATH 找 mspdbcore.dll，
  而该文件只在 Hostx64\\x64 下。只加 x86 会报
  "fatal error C1356: unable to find mspdbcore.dll"。

用法：
    python Tools/ci/build_dll_local_am2.py
"""

import os
import struct
import subprocess
import sys

# ── 工具链（本机实测存在 v141）────────────────────────────────────────────
VC_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft Visual Studio\2017\Professional\VC\Tools\MSVC\14.16.27023",
    r"C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Tools\MSVC\14.16.27023",
    r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\MSVC\14.16.27023",
]
SDK = r"C:\Program Files (x86)\Windows Kits\10"
SDK_CANDIDATES = ["10.0.26100.0", "10.0.19041.0"]

PROJ = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "Army2_Extend_Dll")

CL_FLAGS = [
    "/nologo", "/c", "/GS", "/W3", "/Gy", "/Zc:wchar_t", "/Zc:inline",
    "/Zc:forScope", "/Gd", "/O2", "/Oi", "/Oy-", "/fp:precise", "/MT",
    "/EHsc", "/errorReport:prompt", "/utf-8",
    "/D_WINDLL", "/D_UNICODE", "/DUNICODE", "/DNDEBUG",
    # 源码与头文件放在 src\，需要显式加包含路径
    "/Isrc", "/I.",
]
LINK_FLAGS = [
    "/nologo", "/DLL", "/MACHINE:X86", "/OPT:REF", "/OPT:ICF",
    "/INCREMENTAL:NO", "/SUBSYSTEM:WINDOWS",
]
LINK_LIBS = ["kernel32.lib", "user32.lib", "gdi32.lib", "advapi32.lib"]

SOURCES = [
    "dllmain.cpp",
    r"src\hooks.cpp",
    r"src\target.cpp",
    r"src\renderer.cpp",
    r"src\hzk16.cpp",
    r"src\strings.cpp",
    r"src\codepatch.cpp",
    r"src\log.cpp",
]
EXPORTS = [b"InitializeASI", b"ArmyMenCHS_Install", b"ArmyMenCHS_Uninstall"]
DLL_NAME = "Army2_Extend_Dll"


def pick_vc():
    for p in VC_CANDIDATES:
        if os.path.isfile(os.path.join(p, "bin", "Hostx64", "x86", "cl.exe")):
            return p
    return None


def pick_sdk():
    for v in SDK_CANDIDATES:
        if os.path.isdir(os.path.join(SDK, "Include", v)):
            return v
    return None


def env_setup(vc, sdkv):
    e = os.environ.copy()
    e["PATH"] = os.pathsep.join([
        os.path.join(vc, "bin", "Hostx64", "x86"),
        os.path.join(vc, "bin", "Hostx64", "x64"),
        e.get("PATH", ""),
    ])
    inc = os.path.join(SDK, "Include", sdkv)
    e["INCLUDE"] = ";".join([
        os.path.join(vc, "include"),
        os.path.join(inc, "ucrt"),
        os.path.join(inc, "shared"),
        os.path.join(inc, "um"),
    ])
    lib = os.path.join(SDK, "Lib", sdkv)
    e["LIB"] = ";".join([
        os.path.join(vc, "lib", "x86"),
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
    for fn in os.listdir(build):
        if fn.endswith((".obj", ".pch", ".lib", ".exp", ".ilk")) or \
                (fn.endswith(".dll") and not fn.endswith(".i64")):
            os.remove(os.path.join(build, fn))
            print("   rm", fn)


def main():
    vc = pick_vc()
    sdkv = pick_sdk()
    if not vc:
        print("!! 找不到 v141 (MSVC 14.16) 工具链", file=sys.stderr)
        for p in VC_CANDIDATES:
            print("   试过:", p, file=sys.stderr)
        return 1
    if not sdkv:
        print("!! 找不到 Windows SDK", file=sys.stderr)
        return 1
    print("VC  =", vc)
    print("SDK =", sdkv)

    cl = os.path.join(vc, "bin", "Hostx64", "x86", "cl.exe")
    link = os.path.join(vc, "bin", "Hostx64", "x86", "link.exe")
    env = env_setup(vc, sdkv)

    build = os.path.join(PROJ, "Release")
    os.makedirs(build, exist_ok=True)
    clean(build)

    pch = os.path.join(build, DLL_NAME + ".pch")

    # 1) 预编译头
    #    ★ /Yc 与 /Yu 的文件名**不带引号**：Python subprocess 会把参数里的
    #      双引号转义成 \" 交给 CRT，最终 cl 收到 /Yc\"pch.h\" 而匹配不到
    #      #include，报 C2857。pch.h 无空格，去掉引号即可。
    if not run([cl] + CL_FLAGS + ["/Ycpch.h", "/Fp" + pch, "/Fo" + build + os.sep,
                                  "pch.cpp"], PROJ, env):
        return 1

    # 2) 其余源文件
    objs = [os.path.join(build, "pch.obj")]
    for s in SOURCES:
        sp = os.path.join(PROJ, s)
        if not os.path.isfile(sp):
            print("!! 缺少源文件 %s" % s, file=sys.stderr)
            return 1
        obj = os.path.join(build, s.replace("\\", "_").replace(".cpp", ".obj"))
        if not run([cl] + CL_FLAGS + ["/Yupch.h", "/Fp" + pch, "/Fo" + obj, s],
                   PROJ, env):
            return 1
        if not os.path.isfile(obj):
            print("!! 未产出 %s（源文件被静默跳过？）" % obj, file=sys.stderr)
            return 1
        objs.append(obj)
    print("\n   objs: " + ", ".join(os.path.basename(o) for o in objs))

    # 3) 链接
    dll = os.path.join(build, DLL_NAME + ".dll")
    if not run([link] + LINK_FLAGS + objs + LINK_LIBS +
               ["/OUT:" + dll, "/IMPLIB:" + os.path.join(build, DLL_NAME + ".lib")],
               PROJ, env):
        return 1
    if not os.path.isfile(dll):
        print("!! 未产出 %s" % dll, file=sys.stderr)
        return 1

    # 4) 校验：32 位 PE + 导出齐全 + 大小合理
    with open(dll, "rb") as f:
        b = f.read()
    if b[:2] != b"MZ":
        print("!! 不是 PE", file=sys.stderr)
        return 1
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    machine = struct.unpack_from("<H", b, pe + 4)[0]
    print("\n== %s  %d bytes  machine=0x%X" % (dll, len(b), machine))
    ok = True
    if machine != 0x14C:
        print("!! 不是 32 位 PE（0x14C）", file=sys.stderr)
        ok = False
    if len(b) < 20000:
        print("!! DLL 体积异常小（疑似链接了陈旧/空的 obj）", file=sys.stderr)
        ok = False
    for e in EXPORTS:
        hit = e in b
        print("   %s 导出 %s" % ("[ OK ]" if hit else "[FAIL]", e.decode()))
        ok = ok and hit
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
