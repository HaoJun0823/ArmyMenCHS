# -*- coding: utf-8 -*-
"""把汉化后的 PNG 回包成 title.dat，并做完整性与往返校验。

流程（不改原工作区，全部落在一个临时目录里）：
    1. 复制 Army3_Object_CHS/title 的 manifest.json / palette.bin / raw/ 到临时目录
    2. 把 _am3_title_work/out/*.png 放进临时 png/
    3. 调 am3_dat.py pack 生成 title.dat
    4. 校验：文件数、尺寸未变、对象数、逐个对象重新 unpack 后与输入 PNG 逐像素一致
"""
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys

import numpy as np
from PIL import Image

ROOT = r"G:\Projects\ArmyMenCHS"
SRC_DIR = os.path.join(ROOT, "Army3_Object_CHS", "title")
OUT_PNG = r"I:\LocalGames\Army Men\_am3_title_work\out"
TMP = r"I:\LocalGames\Army Men\_am3_title_work\pack"
DAT_TOOL = os.path.join(ROOT, "Tools", "am3_dat.py")
PY = sys.executable


def main():
    if os.path.exists(TMP):
        shutil.rmtree(TMP)
    os.makedirs(TMP)

    # 1) 复制骨架
    shutil.copy2(os.path.join(SRC_DIR, "manifest.json"), TMP)
    shutil.copy2(os.path.join(SRC_DIR, "palette.bin"), TMP)
    shutil.copytree(os.path.join(SRC_DIR, "raw"), os.path.join(TMP, "raw"))
    png_dir = os.path.join(TMP, "png")
    shutil.copytree(os.path.join(SRC_DIR, "png"), png_dir)

    # 2) 覆盖汉化后的 PNG（尺寸一致性检查）
    man = json.load(open(os.path.join(TMP, "manifest.json"), encoding="utf-8"))
    meta = {o["png"]: o for o in man["objects"] if o.get("png")}
    n = 0
    for f in sorted(os.listdir(OUT_PNG)):
        if not f.endswith(".png"):
            continue
        o = meta.get(f)
        if o is None:
            print("!! manifest 无此对象:", f)
            continue
        a = Image.open(os.path.join(png_dir, f))
        b = Image.open(os.path.join(OUT_PNG, f))
        if a.size != b.size:
            print("!! 尺寸变化 %s: %s -> %s" % (f, a.size, b.size))
            return 2
        if (o["width"], o["height"]) != b.size:
            print("!! 与 manifest 尺寸不符 %s: %s vs %s" % (f, b.size, (o["width"], o["height"])))
            return 2
        shutil.copy2(os.path.join(OUT_PNG, f), os.path.join(png_dir, f))
        n += 1
    print("覆盖 %d 张汉化 PNG（尺寸全部一致）" % n)

    # 3) pack
    out_dat = os.path.join(TMP, "title.dat")
    r = subprocess.run([PY, DAT_TOOL, "pack", TMP, out_dat],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print((r.stdout or r.stderr or "").encode("utf-8", "replace").decode("utf-8", "replace"))
    if r.returncode != 0:
        return 3

    # 4) 结构校验
    buf = open(out_dat, "rb").read()
    print("title.dat: %d bytes  sha256=%s" % (len(buf), hashlib.sha256(buf).hexdigest()[:16]))

    fileid = struct.unpack_from("<I", buf, 0)[0]
    nobj = struct.unpack_from("<I", buf, 1028)[0]
    print("FILEID=0x%08X  nObjects=%d" % (fileid, nobj))
    assert fileid == 0x81920667, "FILEID 不符"
    assert nobj == man["nObjects"], "对象数不符"

    # 5) 逐对象回读，与输入的汉化 PNG 比像素
    sys.path.insert(0, os.path.join(ROOT, "Tools"))
    import am3_dat as D
    pal_rgb = D.palette_rgb(buf[4:4 + 1024])
    entries = []
    for i in range(nobj):
        off = D.HEADER_TABLE_OFF + i * D.ENTRY_SIZE
        entries.append((struct.unpack_from("<I", buf, off)[0],
                        struct.unpack_from("<I", buf, off + 4)[0]))
    bounds = D.object_bounds(buf, entries)
    idx2name = {o["index"]: o["png"] for o in man["objects"]}
    diff = 0
    checked = 0
    for i in range(nobj):
        s, e = bounds[i]
        blob = buf[s:e]
        hdr = D.parse_object_header(blob)
        if not hdr:
            continue
        name = idx2name.get(i)
        if not name or not os.path.isfile(os.path.join(OUT_PNG, name)):
            continue
        g = blob[28:28 + hdr["graphicSize"]]
        img = D.decode_bmp(g, hdr["w"], hdr["h"], pal_rgb, Image).convert("RGB")
        want = Image.open(os.path.join(OUT_PNG, name)).convert("RGB")
        if img.size != want.size:
            print("!! %s 尺寸不符" % name)
            diff += 1
            continue
        if not np.array_equal(np.asarray(img), np.asarray(want)):
            d = int((np.asarray(img) != np.asarray(want)).any(axis=2).sum())
            print("!! %s 像素不一致 (%d px)" % (name, d))
            diff += 1
        checked += 1
    print("回读比对: %d 个对象，%d 个不一致" % (checked, diff))
    return 0 if diff == 0 else 4


if __name__ == "__main__":
    sys.exit(main())
