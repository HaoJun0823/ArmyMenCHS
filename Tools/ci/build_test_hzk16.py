"""编译并运行 Hzk16 离线自测。

这是本补丁**唯一能在不启动游戏的情况下自证**的部分：
验证 C++ 字库实现与"官方公式 + 真实文件"一致（含偏移量逐条对照）。

用法：
    python Tools/ci/build_test_hzk16.py
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_dll_local_am2 import (pick_vc, pick_sdk, env_setup, SDK,  # noqa
                                 CL_FLAGS, PROJ)

DEFAULT_FONT = r"I:\LocalGames\Army Men\玩具兵大战2\Hzk16"


def run(cmd, cwd, env, label=""):
    print("\n-- %s" % (label or os.path.basename(cmd[0])))
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.stdout:
        print(r.stdout, end="")
    if r.stderr.strip():
        print("[stderr]", r.stderr.strip())
    return r.returncode


def main():
    vc = pick_vc()
    sdkv = pick_sdk()
    if not vc or not sdkv:
        print("!! 缺工具链", file=sys.stderr)
        return 1
    env = env_setup(vc, sdkv)
    cl = os.path.join(vc, "bin", "Hostx64", "x86", "cl.exe")
    link = os.path.join(vc, "bin", "Hostx64", "x86", "link.exe")

    out = os.path.join(PROJ, "Release")
    os.makedirs(out, exist_ok=True)

    # 只编 hzk16.cpp + log.cpp + 测试主程序。
    # ★ /MD 而不是 /MT：测试程序是控制台程序，用动态 CRT 便于直接跑；
    #   与 DLL 的 /MT 无冲突（各编各的）。
    flags = ["/nologo", "/c", "/W3", "/O2", "/EHsc", "/utf-8", "/MD",
             "/I" + PROJ, "/I" + os.path.join(PROJ, "src")]

    srcs = [
        (os.path.join(PROJ, "test", "test_hzk16.cpp"), "test_hzk16.obj"),
        (os.path.join(PROJ, "src", "hzk16.cpp"), "t_hzk16.obj"),
        (os.path.join(PROJ, "src", "log.cpp"), "t_log.obj"),
    ]
    objs = []
    for src, obj in srcs:
        rc = run([cl] + flags + ["/Fo" + os.path.join(out, obj), src],
                 PROJ, env, "cl " + os.path.basename(src))
        if rc != 0:
            return 1
        objs.append(os.path.join(out, obj))

    exe = os.path.join(out, "test_hzk16.exe")
    rc = run([link, "/nologo", "/INCREMENTAL:NO", "/SUBSYSTEM:CONSOLE"]
             + objs + ["kernel32.lib", "user32.lib", "/OUT:" + exe],
             PROJ, env, "link test_hzk16.exe")
    if rc != 0:
        return 1

    font = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FONT
    print("\n" + "=" * 70)
    rc = run([exe, font], PROJ, env, "运行自测")
    print("=" * 70)
    return rc


if __name__ == "__main__":
    sys.exit(main())
