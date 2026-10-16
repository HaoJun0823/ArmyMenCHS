# -*- coding: utf-8 -*-
"""最终校验：尺寸一致 / 调色板合规 / 回包只改了目标对象。"""
import hashlib
import json
import os
import sys

import numpy as np
from PIL import Image

R = r"G:\Projects\ArmyMenCHS"
S = os.path.join(R, "Army4_Object_CHS", "shared")
CHS = os.path.join(S, "png_control_chs")
PNG = os.path.join(S, "png")
GAME = r"I:\LocalGames\Army Men\Army Men - World War GOG"
RT = r"I:\LocalGames\Army Men\_am4_chs_roundtrip"

sys.path.insert(0, os.path.join(R, "Tools"))
import am3_dat as M  # noqa: E402

ok = True


def chk(cond, msg):
    global ok
    if not cond:
        ok = False
    print("  [%s] %s" % ("OK " if cond else "BAD", msg))


# ---------- 1. 尺寸一致 ----------
print("=" * 76)
print("[1] 覆盖层尺寸必须与原图完全一致（否则触发 graphicSize 长度硬闸）")
man = json.load(open(os.path.join(S, "manifest.json"), encoding="utf-8"))
by_index = {o["index"]: o for o in man["objects"]}
files = sorted(f for f in os.listdir(CHS) if f.endswith(".png"))
print("  覆盖层文件 %d 个" % len(files))
bad_dim = 0
for f in files:
    idx = int(f.split("_")[1])
    o = by_index[idx]
    im = Image.open(os.path.join(CHS, f))
    src = Image.open(os.path.join(PNG, f))
    if im.size != src.size or im.size != (o["width"], o["height"]):
        print("     !! %s 尺寸 %s != 原图 %s / manifest %s"
              % (f, im.size, src.size, (o["width"], o["height"])))
        bad_dim += 1
chk(bad_dim == 0, "全部尺寸一致（不一致 %d）" % bad_dim)

# ---------- 2. 覆盖对象必须是未压缩 BMP ----------
print()
print("[2] 覆盖对象编码必须为 BMP（压缩族重编码会写出坏数据）")
nonbmp = [f for f in files
          if by_index[int(f.split("_")[1])]["kind"] != "BMP"]
chk(not nonbmp, "全部为 BMP（非 BMP %d 个）%s" % (len(nonbmp), nonbmp[:4]))

# ---------- 3. 调色板合规 ----------
print()
print("[3] 覆盖层颜色必须都在 4 代调色板内（否则回包会最近色吸附产生噪点）")
raw = open(os.path.join(S, "palette.bin"), "rb").read()
pal = []
for i in range(256):
    b, g, r, _ = raw[i * 4:i * 4 + 4]
    pal.append((r, g, b))
pala = np.array(pal, dtype=np.int32)
worst = 0
notin = 0
for f in files:
    arr = np.asarray(Image.open(os.path.join(CHS, f)).convert("RGB")).reshape(-1, 3)
    uniq = np.unique(arr, axis=0)
    for c in uniq:
        d = int(np.abs(pala - c.astype(np.int32)).sum(axis=1).min())
        if d != 0:
            notin += 1
            worst = max(worst, d)
chk(notin == 0, "全部精确命中调色板（未命中 %d 个色，最大色差 %d）" % (notin, worst))

# ---------- 4. 回包差异只发生在目标对象 ----------
print()
print("[4] 回包产物与原版逐字节比对：差异必须只落在 16 个覆盖对象内")
orig = open(os.path.join(GAME, "shared.dat"), "rb").read()
new = open(os.path.join(RT, "shared.dat"), "rb").read()
chk(len(orig) == len(new), "长度一致：%d == %d" % (len(orig), len(new)))

fid, palette, entries = M.parse_container(orig)
bounds = M.object_bounds(orig, entries)
ov_idx = set(int(f.split("_")[1]) for f in files)
diff_bytes = 0
diff_objs = set()
for i, (k, off) in enumerate(entries):
    s, e = bounds[i]
    if orig[s:e] != new[s:e]:
        diff_objs.add(i)
        diff_bytes += sum(1 for a, b in zip(orig[s:e], new[s:e]) if a != b)
chk(diff_objs == ov_idx,
    "差异对象集合 == 覆盖对象集合（差异 %d 个 / 覆盖 %d 个，差集 %s）"
    % (len(diff_objs), len(ov_idx), sorted(diff_objs ^ ov_idx)[:6]))
chk(diff_bytes > 0, "确实有像素被改写（%d 字节）" % diff_bytes)

# 目录表与调色板必须完全未变
chk(orig[:1028] == new[:1028], "调色板 + FILEID 区域未变")
n = len(entries)
table_off = M.HEADER_TABLE_OFF
chk(orig[table_off:table_off + n * M.ENTRY_SIZE] ==
    new[table_off:table_off + n * M.ENTRY_SIZE], "目录表（key/offset）未变")

print()
print("=" * 76)
print("结论：%s" % ("全部通过" if ok else "存在失败项"))
sys.exit(0 if ok else 1)
