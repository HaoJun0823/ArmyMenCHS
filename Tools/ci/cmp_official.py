"""
官方汉化包 vs 我们产出：逐文件内容对账。

★ 判定标准（区分"真缺失"和"无害冗余"）：
    - 官方文件在 Steam 原版里存在且字节相同  -> [冗余] 官方只是全量复制，未汉化，无需下发
    - 官方文件在 Steam 原版里不同          -> [缺失] 确实汉化了而我们没覆盖  = 必须修
    - 仅我们有                               -> [多余] 需要复核是否该下发
    - 两边都有但内容不同                     -> [不符] 必须逐个查

用法：
    python Tools/ci/cmp_official.py --official "I:\\...\\玩具兵大战1" \\
                                   [--steam "I:\\...\\Army Men I STEAM"] \\
                                   [--out build_out]

★ 这两个路径**必须显式传入**：官方汉化包与 Steam 安装目录都不在仓库里
  （前者含 copyrighted 素材，后者是用户自己的游戏）。
  不设默认值是有意的 —— 静默用不存在的路径会算出「0 差异」的假阳性。
"""

import os
import sys
import hashlib
import struct

DIRS = ["Audio", "AVI", "Campaigns", "Maps", "Screens", "Stratmap",
        "Alpine", "Bayou", "Desert"]

# 不参与对账：DLL / 配置 / 官方包根本没这些
NOT_ASSET = {"Armymen.exe"}


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def walk(base):
    out = {}
    if not os.path.isdir(base):
        return out
    for root, _, files in os.walk(base):
        for fn in files:
            if fn in NOT_ASSET:
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, base).replace("\\", "/")
            out[rel] = full
    return out


def bmp_mode(p):
    """BMP 位深：游戏只吃 8 位索引色，24 位会翻倍且可能不认。

    注意 biBitCount 本身就是位深，**不要再乘 8**（曾因此误报 174 个"64 位"）。
    """
    try:
        with open(p, "rb") as f:
            b = f.read(34)
        if b[:2] != b"BM":
            return None
        return struct.unpack_from("<H", b, 28)[0]
    except OSError:
        return None


def main():
    a = sys.argv[1:]
    # 同 make_patch.py：root 从 __file__ 推导，不写死绝对路径
    root = (a[a.index("--root") + 1] if "--root" in a else
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))))
    out_name = a[a.index("--out") + 1] if "--out" in a else "build_out"

    # ★ 本工具是**本地对账**脚本，依赖两处本机路径：
    #     官方汉化包 与 Steam 安装目录。
    #   两者都不在仓库里，CI 上必然缺失 —— 所以显式要求传入，
    #   而不是默默拿不存在的路径算出 0 差异假阳性。
    if "--official" in a:
        official = a[a.index("--official") + 1]
    else:
        print("!! 必须传 --official <官方汉化包目录>")
        print("   该目录含 copyrighted 游戏素材，不随仓库分发。")
        return 2
    if "--steam" in a:
        steam = a[a.index("--steam") + 1]
    else:
        print("!! 必须传 --steam <Steam 安装目录>")
        return 2
    if not os.path.isdir(official):
        print("!! 官方汉化包目录不存在: %s" % official)
        return 2
    if not os.path.isdir(steam):
        print("!! Steam 安装目录不存在: %s" % steam)
        return 2
    ours = os.path.join(root, out_name)

    print("官方 : %s" % official)
    print("基底 : %s" % steam)
    print("我们 : %s\n" % ours)

    tally = {"missing": [], "redundant": [], "ours_only": [],
             "mismatch": [], "ok": 0}

    for d in DIRS:
        od = os.path.join(official, d)
        if not os.path.isdir(od):
            continue
        O = walk(od)
        S = walk(os.path.join(steam, d))
        U = walk(os.path.join(ours, d))

        buckets = {"missing": [], "redundant": [], "ours_only": [],
                   "mismatch": []}
        for rel, op in sorted(O.items()):
            up = U.get(rel)
            sp = S.get(rel)
            if up is None:
                # 官方有、我们没有 -> 看 Steam 原版是不是一样的
                if sp and md5(sp) == md5(op):
                    buckets["redundant"].append(rel)
                else:
                    buckets["missing"].append((rel, os.path.getsize(op)))
            elif sp and md5(up) != md5(op):
                buckets["mismatch"].append(rel)
            else:
                tally["ok"] += 1
        for rel in sorted(U.keys()):
            if rel not in O:
                buckets["ours_only"].append(rel)

        n_sum = len(buckets["missing"]) + len(buckets["mismatch"])
        if n_sum == 0 and not buckets["ours_only"]:
            print("=== %-10s OK  (%d 文件)" % (d, len(O)))
        else:
            print("=== %-10s" % d)
        for k in ("missing", "mismatch", "ours_only", "redundant"):
            v = buckets[k]
            if not v:
                continue
            label = {"missing": "缺失(真)", "mismatch": "不一致(需查)",
                     "ours_only": "仅我们有", "redundant": "官方冗余(无害)"}[k]
            print("   %-14s %d" % (label, len(v)))
            for item in v[:8]:
                print("      %s" % (item if isinstance(item, str)
                                    else "%s  (%d B)" % item))
            if len(v) > 8:
                print("      ... 另 %d 个" % (len(v) - 8))
            tally[k].extend(v)

    print("\n===== 汇总 =====")
    print("  一致            %d" % tally["ok"])
    print("  缺失(真)        %d   <- 必须修" % len(tally["missing"]))
    print("  不一致(需查)    %d   <- 必须查" % len(tally["mismatch"]))
    print("  仅我们有        %d   <- 需复核" % len(tally["ours_only"]))
    print("  官方冗余(无害)  %d" % len(tally["redundant"]))

    # BMP 位深体检：游戏只支持 8 位索引色
    print("\n===== BMP 位深体检 =====")
    bad = []
    for rel, p in walk(ours).items():
        if not rel.lower().endswith(".bmp"):
            continue
        bits = bmp_mode(p)
        if bits and bits != 8:
            bad.append((rel, bits))
    if bad:
        for rel, bits in bad[:20]:
            print("  !! %s  %d 位" % (rel, bits))
        print("  共 %d 个非 8 位 BMP" % len(bad))
    else:
        print("  全部为 8 位索引色 OK")

    return 0


if __name__ == "__main__":
    sys.exit(main())