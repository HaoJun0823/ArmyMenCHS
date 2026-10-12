"""
对比两个 .cpn / .rul / .txt 脚本的"结构"差异（关键字与字段，忽略具体文本）。

用途：Steam v1.2 与中文 v1.0 是不同游戏版本，脚本格式可能有差异。
       整体替换中文版脚本可能导致新版解析器不认识旧字段。

用法：
    python diff_script.py <旧文件> <新文件> [--encoding gbk] [--limit N]
"""

import sys
import re
import collections


def load(path, enc):
    with open(path, "rb") as f:
        return f.read().decode(enc, "replace")


def keys_of(text):
    """提取每行的首个关键字（大写词），统计出现次数。"""
    cnt = collections.Counter()
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)", s)
        if m:
            cnt[m.group(1).upper()] += 1
    return cnt


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return 1
    a, b = args[0], args[1]
    enc = "gbk"
    if "--encoding" in args:
        enc = args[args.index("--encoding") + 1]
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 40

    ta, tb = load(a, enc), load(b, enc)
    ka, kb = keys_of(ta), keys_of(tb)

    allk = sorted(set(ka) | set(kb))
    print(f"old: {a}  ({len(ta.splitlines())} 行)")
    print(f"new: {b}  ({len(tb.splitlines())} 行)")
    print()
    print(f"{'关键字':<20} {'old':>6} {'new':>6}  差异")
    print("-" * 50)
    only_old, only_new, cntdiff = [], [], []
    for k in allk:
        va, vb = ka.get(k, 0), kb.get(k, 0)
        if va == vb:
            continue
        mark = ""
        if va > 0 and vb == 0:
            mark = "★ 仅旧版有"
            only_old.append(k)
        elif vb > 0 and va == 0:
            mark = "★ 仅新版有"
            only_new.append(k)
        else:
            mark = f"数量差 {vb - va:+d}"
            cntdiff.append((k, va, vb))
        print(f"{k:<20} {va:>6} {vb:>6}  {mark}")

    if not (only_old or only_new or cntdiff):
        print("(结构与关键字完全一致)")

    print()
    if only_old:
        print(f"仅旧版有的关键字 ({len(only_old)}): {', '.join(only_old)}")
    if only_new:
        print(f"仅新版有的关键字 ({len(only_new)}): {', '.join(only_new)}")

    # 展示仅旧版有的关键字所在行，便于判断是否为已废弃字段
    if only_old:
        print()
        print("仅旧版有的关键字示例行:")
        shown = 0
        for ln in ta.splitlines():
            s = ln.strip()
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)", s)
            if m and m.group(1).upper() in only_old:
                print(f"  {s[:100]}")
                shown += 1
                if shown >= limit:
                    break
    return 0


if __name__ == "__main__":
    sys.exit(main())
