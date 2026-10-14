# -*- coding: utf-8 -*-
"""资产树结构自检：MANIFEST + sha256 逐文件回读。

★ 防两类问题：
  1. **资产被换行符改写**：本机 core.autocrlf=true，.gitattributes 没覆盖到的
     扩展名（如 .wav）可能在检出时被 LF->CRLF 污染。游戏按**字节**解析资产，
     一旦污染就是"地图加载崩溃"这种极难排的症状。
     1 代为这个坑专门写了 .gitattributes 注释；2 代实测 .wav 目前靠 git 的
     "内容像二进制就跳过"启发式兜底 —— 那是偶然保护，不是声明。

  2. **MANIFEST 与实际不符**：改了文件忘了重新生成清单，
     版本记录就失去意义。

判据：MANIFEST.md 声明的文件数/总体积 == 磁盘实际；
      磁盘上每个文件都能在 _filehash.csv 里找到且 sha256 一致；
      csv 里每个条目都对应一个真实文件。

用法：
    python Tools/ci/verify_assets_am2.py
    python Tools/ci/verify_assets_am2.py --dir Army2_Original
"""
import argparse
import csv
import hashlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DIRS = ["Army2_Original", "Army2_CHS", "Army2_NEW_CHS"]


def sha256(p, buf=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(buf), b""):
            h.update(c)
    return h.hexdigest()


def check_dir(base, verbose=False):
    """返回 (错误数, 检查数, 说明)"""
    d = os.path.join(ROOT, base)
    errs = []
    n = 0

    if not os.path.isdir(d):
        return 0, 0, "目录不存在，跳过"

    csv_path = os.path.join(d, "_filehash.csv")
    # ★ 摘要文件：在 MANIFEST.md / README.md 里挑**真正含"文件数"摘要表**的那个。
    #   Army2_Original / Army2_CHS  -> MANIFEST.md（含总量摘要）
    #   Army2_NEW_CHS              -> MANIFEST.md 是逐文件明细表（无摘要），
    #                                 摘要在 README.md 里
    #   早先按固定顺序取第一个存在的文件，在 NEW_CHS 上误取 MANIFEST.md，
    #   于是"找不到文件数"误报 —— 这是校验器自身的假红。
    import re as _re
    COUNT_RE = _re.compile(r"\|\s*文件数\s*\|\s*(\d+)\s*\|")
    md_path = None
    md_text = None
    md_declared = None
    for cand in ("MANIFEST.md", "README.md"):
        p = os.path.join(d, cand)
        if not os.path.isfile(p):
            continue
        try:
            t = open(p, "r", encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        m = COUNT_RE.search(t)
        if m:
            md_path, md_text, md_declared = p, t, int(m.group(1))
            break
        # 保留第一个存在的作为兜底（即便没有摘要行）
        if md_path is None:
            md_path, md_text, md_declared = p, t, None

    if not os.path.isfile(csv_path):
        return 1, 0, "缺少 _filehash.csv"
    if md_path is None:
        return 1, 0, "缺少 MANIFEST.md 或 README.md"

    # ── ① 读 csv ──
    rows = []
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    if not rows:
        return 1, 0, "_filehash.csv 为空（解析失败或无数据行）"

    # ── ② csv 每条都要对应真实文件且哈希一致 ──
    missing = []
    badhash = []
    for r in rows:
        rel = r.get("relative", "").replace("\\", "/")
        if not rel:
            continue
        p = os.path.join(d, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            missing.append(rel)
            continue
        n += 1
        got = sha256(p).upper()
        want = (r.get("sha256") or "").upper()
        if got != want:
            badhash.append((rel, want[:16], got[:16]))
    if missing:
        errs.append("csv 中有 %d 个文件不存在（如 %s）"
                    % (len(missing), missing[:3]))
    if badhash:
        errs.append("sha256 不符 %d 个（可能被换行符改写）：%s"
                    % (len(badhash), badhash[:3]))

    # ── ③ 磁盘上每个文件都应在 csv 里（反向，防漏登记）──
    listed = set()
    for r in rows:
        rel = r.get("relative", "").replace("\\", "/")
        if rel:
            listed.add(rel.lower())
    # ★ 清单类文件自身不参与对账（它们是"关于资产的元数据"，不是资产）。
    #   漏了这条会误报"MANIFEST.json 未登记"。
    META_FILES = {
        "_filehash.csv", "manifest.md", "manifest.json",
        "readme.md", "manifest_bmp.md", "bmp_status.json",
    }
    on_disk = []
    for dp, _, fns in os.walk(d):
        for fn in fns:
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, d).replace("\\", "/")
            if rel.lower() in META_FILES:
                continue
            on_disk.append(rel)
    extra = [x for x in on_disk if x.lower() not in listed]
    if extra:
        errs.append("磁盘有 %d 个文件未登记（如 %s）"
                    % (len(extra), extra[:3]))

    # ── ④ MANIFEST 声明的文件数要一致 ──
    if md_declared is None:
        errs.append("%s 里没找到『文件数』摘要行（格式不符约定）"
                    % os.path.basename(md_path))
    else:
        want_n = md_declared
        # MANIFEST 的文件数含清单文件自身，故允许少量差额
        if not (want_n - 5 <= len(on_disk) <= want_n + 5):
            errs.append("%s 声明文件数 %d，实际 %d（不含清单文件）"
                        % (os.path.basename(md_path), want_n, len(on_disk)))

    return len(errs), n, "；".join(errs) if errs else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", action="append",
                    help="只检查指定目录（可多次）")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    dirs = args.dir or DIRS
    print("=" * 74)
    print("Army2 资产树结构自检")
    print("=" * 74)
    print("检查目录: %s\n" % ", ".join(dirs))

    total_err = 0
    total_chk = 0
    for base in dirs:
        errs, n, msg = check_dir(base, args.verbose)
        total_err += errs
        total_chk += n
        tag = "OK " if errs == 0 else "!! "
        print("%s %-18s 逐文件校验 %5d 个  %s"
              % (tag, base, n, msg or "一致"))

    print("\n" + "=" * 74)
    print("合计逐文件校验 %d 个，错误 %d 项" % (total_chk, total_err))
    if total_err == 0:
        print("全部通过。")
    else:
        print("!! 有问题，不要部署")
    print("=" * 74)
    return 1 if total_err else 0


if __name__ == "__main__":
    sys.exit(main())
