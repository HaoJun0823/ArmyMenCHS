# -*- coding: utf-8 -*-
"""校验 Army4_Original 与源目录逐字节一致。

校验项（4 代实测值，非照抄 3 代）:
  1. 全量 sha256 与源目录一致
  2. _filehash.csv 自校验
  3. strings/strings.txt 行数（4 代 = 323；下界闸门 320，见 MANIFEST）
  4. 入库口径核查：不含 save/update/EULA.txt，且 audio/vos 未被误排

★ 校验器必须自证（见 docs/05-am2-porting-guide.md 3.2）:
    报出实际检查条目数；空转即失败。
"""
import csv
import hashlib
import os
import sys

SRC = r"I:\LocalGames\Army Men\Army Men - World War GOG"
DST = r"G:\Projects\ArmyMenCHS\Army4_Original"

# 4 代实测：出厂 strings.txt = 323 行（3 代为 320）
EXPECTED_STRINGS_LINES = 323
# 3 代 #C1 约束的下界（两代 exe 内均为 cmp ..., 320）
STRINGS_FLOOR = 320
# 目标目录内允许存在的非资产元文件
META = ("MANIFEST.md", "_filehash.csv")


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


errors = []


def check(ok, msg):
    if not ok:
        errors.append(msg)
    print("  [%s] %s" % ("OK " if ok else "BAD", msg))


print("=" * 74)
print("Army4_Original 校验")
print("=" * 74)

# ---------- 1. 逐文件 sha256 ----------
print("\n[1] 与源逐字节比对")
bad = missing = n = 0
for dp, dn, fn in os.walk(DST):
    for f in fn:
        if f in META:
            continue
        rel = os.path.relpath(os.path.join(dp, f), DST)
        s = os.path.join(SRC, rel)
        n += 1
        if not os.path.isfile(s):
            print("      源缺失: %s" % rel)
            missing += 1
            continue
        if sha(s) != sha(os.path.join(dp, f)):
            print("      不一致: %s" % rel)
            bad += 1
check(n > 0, "检查了 %d 个文件（空转即失败）" % n)
check(bad == 0, "不一致 %d 个" % bad)
check(missing == 0, "源缺失 %d 个" % missing)

# ---------- 2. _filehash.csv 自校验 ----------
print("\n[2] _filehash.csv 自校验")
rows = list(csv.DictReader(open(os.path.join(DST, "_filehash.csv"),
                                encoding="utf-8")))
mismatch = 0
for r in rows:
    p = os.path.join(DST, r["relative"].replace("\\", os.sep))
    if not os.path.isfile(p):
        print("      清单项不存在: %s" % r["relative"])
        mismatch += 1
        continue
    if os.path.getsize(p) != int(r["size"]) or sha(p) != r["sha256"]:
        print("      清单哈希不符: %s" % r["relative"])
        mismatch += 1
check(len(rows) > 0, "清单条目 %d 条（空转即失败）" % len(rows))
check(mismatch == 0, "清单校验不符 %d 条" % mismatch)
# 清单必须覆盖全部资产（除 meta）
check(len(rows) == n, "清单条目数 %d == 实际资产数 %d" % (len(rows), n))

# ---------- 3. strings.txt 行数（硬约束） ----------
print("\n[3] strings/strings.txt")
sp = os.path.join(DST, "strings", "strings.txt")
spp = os.path.join(SRC, "strings", "strings.txt")
raw = open(sp, "rb").read()
src_raw = open(spp, "rb").read()
lf = raw.count(b"\n")
crlf = raw.count(b"\r\n")
nonascii = sum(1 for c in raw if c > 127)
maxline = max(len(l) for l in raw.split(b"\n"))
print("      %d B, LF=%d, CRLF=%d, 非 ASCII 字节=%d, 最长行=%d, 结尾换行=%s"
      % (len(raw), lf, crlf, nonascii, maxline, raw.endswith(b"\n")))
check(raw == src_raw, "与源逐字节一致")
check(lf == EXPECTED_STRINGS_LINES,
      "行数 %d == 期望 %d" % (lf, EXPECTED_STRINGS_LINES))
check(lf >= STRINGS_FLOOR,
      "行数 %d >= 下界闸门 %d（C1）" % (lf, STRINGS_FLOOR))
check(maxline < 510, "最长行 %d < 510（fgets 上限，C2）" % maxline)

# ---------- 4. 入库口径 ----------
print("\n[4] 入库口径核查")
for forbidden in ("save", "update"):
    exists = os.path.isdir(os.path.join(DST, forbidden))
    check(not exists, "不含 %s/ 目录" % forbidden)
check(not os.path.isfile(os.path.join(DST, "EULA.txt")),
      "不含 EULA.txt（GOG 安装器文档）")
check(not os.path.isfile(os.path.join(DST, "amww.exe")),
      "不含主程序 exe（硬约束：不改 exe）")
vos = os.path.join(DST, "audio", "vos")
n_vos = len([f for f in os.listdir(vos)]) if os.path.isdir(vos) else 0
check(n_vos == 298, "audio/vos 台词 %d 个 == 期望 298" % n_vos)
n_bmp = sum(1 for dp, dn, fn in os.walk(DST) for f in fn
            if f.lower().endswith(".bmp"))
n_txt = sum(1 for dp, dn, fn in os.walk(DST) for f in fn
            if f.lower().endswith(".txt"))
# 源目录共 159 个 .txt（含根目录 EULA.txt）；EULA.txt 是 GOG 安装器文档已排除 → 158
check(n_bmp == 146, "BMP %d 个 == 期望 146" % n_bmp)
check(n_txt == 158, "TXT %d 个 == 期望 158（源 159 - 排除 EULA.txt 1）" % n_txt)

print("\n" + "=" * 74)
if errors:
    print("失败：%d 项" % len(errors))
    for e in errors:
        print("  - %s" % e)
    sys.exit(1)
print("全部通过。")
sys.exit(0)
