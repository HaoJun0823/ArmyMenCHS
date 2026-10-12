"""
把 build_out 打包为可分发的 zip（ASCII 名，GitHub 附件不支持中文）。

用法：
    python3 Tools/ci/pack_release.py build_out stage
    -> stage/ArmyMen-CHS-Patch-<UTC日期-时间>.zip
"""

import os
import sys
import zipfile
from datetime import datetime, timezone


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return 1
    src, dst_dir = args[0], args[1]

    if not os.path.isdir(src):
        print(f"!! 源目录不存在: {src}", file=sys.stderr)
        return 1

    os.makedirs(dst_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = f"ArmyMen-CHS-Patch-{stamp}.zip"
    out = os.path.join(dst_dir, name)

    n = 0
    total = 0
    # ZIP_DEFLATED 压缩；大文件（smk 已压缩）收益有限但无妨
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _, files in os.walk(src):
            for fn in sorted(files):
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, src).replace("\\", "/")
                z.write(full, rel)
                n += 1
                total += os.path.getsize(full)

    sz = os.path.getsize(out)
    print(f"{out}")
    print(f"  {n} 文件 / {total/1024/1024:.1f} MB (未压缩)")
    print(f"  zip: {sz/1024/1024:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
