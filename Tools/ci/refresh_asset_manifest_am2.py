# -*- coding: utf-8 -*-
"""重算 Army2_Original / Army2_CHS 的 _filehash.csv 与 MANIFEST.md 汇总。

用途：当资产树里的文件被**有意**恢复/替换后（例如 rules/*_desc.txt 从
被污染的中文恢复成英文原文），清单必须同步，否则 verify_assets_am2.py
会报"sha256 不符"（那是正确的报警，但会挡住构建）。

用法：
    python Tools/ci/refresh_asset_manifest_am2.py --dir Army2_Original
    python Tools/ci/refresh_asset_manifest_am2.py --dir Army2_Original --dir Army2_CHS
"""
import argparse
import csv
import hashlib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest().lower()


def refresh(base):
    root = os.path.join(ROOT, base)
    csvp = os.path.join(root, "_filehash.csv")
    mdp = os.path.join(root, "MANIFEST.md")
    if not os.path.isfile(csvp):
        print("!! 缺 %s" % csvp, file=sys.stderr)
        return 1

    rows = []
    with open(csvp, "r", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            rel = (r.get("relative") or "").replace("\\", os.sep)
            if not rel:
                continue
            p = os.path.join(root, rel)
            if os.path.isfile(p):
                r["size"] = str(os.path.getsize(p))
                r["sha256"] = sha256(p)
            rows.append(r)

    with open(csvp, "w", encoding="utf-8", newline="\n") as f:
        f.write('"relative","size","sha256"\n')
        for r in rows:
            f.write('"%s","%s","%s"\n' % (r["relative"], r["size"], r["sha256"]))
    print("  [%s] _filehash.csv 已按实际重算 %d 行" % (base, len(rows)))

    if not os.path.isfile(mdp):
        print("  [%s] 无 MANIFEST.md，跳过汇总刷新" % base)
        return 0

    tot = sum(int(r["size"]) for r in rows)
    big = max(rows, key=lambda r: int(r["size"]))
    ext = {}
    for r in rows:
        e = os.path.splitext(r["relative"])[1].lower() or "(无扩展名)"
        a = ext.setdefault(e, [0, 0])
        a[0] += 1
        a[1] += int(r["size"])

    md = open(mdp, encoding="utf-8").read()
    md = re.sub(r"\| 文件数 \| \d+ \|", "| 文件数 | %d |" % len(rows), md)
    md = re.sub(r"\| 总体积 \| [\d.]+ MB \|",
                "| 总体积 | %.1f MB |" % (tot / 1048576), md)
    md = re.sub(r"\| 单文件最大 \| [\d.]+ MB \(`[^`]*`\) \|",
                "| 单文件最大 | %.1f MB (`%s`) |"
                % (int(big["size"]) / 1048576,
                   big["relative"].replace("\\", "/")), md)

    lines = ["| 扩展名 | 文件数 | 体积 (MB) |", "|---|---|---|"]
    for e in sorted(ext, key=lambda k: -ext[k][1]):
        c, sz = ext[e]
        lines.append("| `%s` | %d | %.1f |" % (e, c, sz / 1048576))
    md = re.sub(
        r"\| 扩展名 \| 文件数 \| 体积 \(MB\) \|\n\|---\|---\|---\|\n(?:\|[^\n]*\|\n)+",
        "\n".join(lines) + "\n", md)
    open(mdp, "w", encoding="utf-8", newline="\n").write(md)
    print("  [%s] MANIFEST.md 已重算：%d 文件 / %.1f MB"
          % (base, len(rows), tot / 1048576))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", action="append", required=True)
    args = ap.parse_args()
    rc = 0
    for b in args.dir:
        rc |= refresh(b)
    return rc


if __name__ == "__main__":
    sys.exit(main())
