# -*- coding: utf-8 -*-
"""校验 Army3_Original 与源目录逐字节一致。"""
import hashlib
import os
import sys

SRC = r"I:\LocalGames\Army Men\Army Men - Toys in Space STEAM"
DST = r"G:\Projects\ArmyMenCHS\Army3_Original"


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


bad = missing = extra = 0
n = 0
for dp, dn, fn in os.walk(DST):
    for f in fn:
        if f in ("MANIFEST.md", "_filehash.csv"):
            continue
        rel = os.path.relpath(os.path.join(dp, f), DST)
        s = os.path.join(SRC, rel)
        n += 1
        if not os.path.isfile(s):
            print("  源缺失: %s" % rel)
            missing += 1
            continue
        if sha(s) != sha(os.path.join(dp, f)):
            print("  不一致: %s" % rel)
            bad += 1

print("比对 %d 个文件：不一致 %d，源缺失 %d" % (n, bad, missing))

# _filehash.csv 自身校验
import csv
rows = list(csv.DictReader(open(os.path.join(DST, "_filehash.csv"),
                                encoding="utf-8")))
print("_filehash.csv 条目: %d" % len(rows))
mismatch = 0
for r in rows:
    p = os.path.join(DST, r["relative"].replace("\\", os.sep))
    if not os.path.isfile(p):
        print("  清单项不存在: %s" % r["relative"])
        mismatch += 1
        continue
    if os.path.getsize(p) != int(r["size"]) or sha(p) != r["sha256"]:
        print("  清单哈希不符: %s" % r["relative"])
        mismatch += 1
print("清单校验不符: %d" % mismatch)

# strings.txt 行数（exe 硬约束）
sp = os.path.join(DST, "strings", "strings.txt")
raw = open(sp, "rb").read()
print()
print("strings/strings.txt: %d B, LF=%d, CRLF=%d, 结尾换行=%s" %
      (len(raw), raw.count(b"\n"), raw.count(b"\r\n"),
       raw.endswith(b"\n")))
src_raw = open(os.path.join(SRC, "strings", "strings.txt"), "rb").read()
print("与源逐字节一致: %s" % (raw == src_raw))

sys.exit(1 if (bad or missing or mismatch) else 0)
