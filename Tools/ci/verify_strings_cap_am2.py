# -*- coding: utf-8 -*-
"""译文表容量自检（不需要 exe）。

★ 防的问题：中文字节数超过英文槽容量，覆盖相邻字符串。
  DLL 侧的规则是 `cap = len(英文原文) + 1`（含 NUL）。
  中文 GBK 每字 2 字节，超限即越界写入相邻槽。

  本地构建时 gen_am2_strings_ini.py 会做**更强**的闸门
  （与 exe 里的英文原文逐条比对，RVA 错就拒绝写入）。
  CI 上没有 exe，退化为容量算术校验 —— 仍然能挡住最常见的超限错误。

★ 已知例外：`Jeeps -> 吉普车` 需 7 B > cap 6，改用 `吉普`。
  例外表与原因见脚本 EXCEPTIONS。

用法：
    python Tools/ci/verify_strings_cap_am2.py
    python Tools/ci/verify_strings_cap_am2.py --ini <路径>
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_INI = os.path.join(ROOT, "Army2_Extend_Dll", "strings",
                           "am2_strings.ini")

# 经人工确认的例外：RVA -> (中文, 原因)
EXCEPTIONS = {
    0x86C6C: ("吉普", "Jeeps 的 cap=6，『吉普车』需 7 B，改用 2 字"),
}


def parse_ini(path):
    """返回 [(rva:int, en:str, zh:str, 行号:int)]"""
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for ln, raw in enumerate(f, 1):
            line = raw.rstrip("\n")
            if not line or line.lstrip().startswith((";", "#")):
                continue
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            if not key.lower().startswith("0x"):
                continue
            try:
                rva = int(key, 16)
            except ValueError:
                continue
            # 值格式：英文|中文（英文可能为空）
            if "|" in val:
                en, zh = val.split("|", 1)
            else:
                en, zh = "", val
            out.append((rva, en.strip(), zh.strip(), ln))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ini", default=DEFAULT_INI)
    args = ap.parse_args()

    if not os.path.isfile(args.ini):
        print("!! INI 不存在: %s" % args.ini, file=sys.stderr)
        return 1

    rows = parse_ini(args.ini)
    print("=" * 74)
    print("译文表容量自检（CI 级：不读 exe）")
    print("=" * 74)
    print("INI: %s" % args.ini)

    # ★ 空转即失败（本项目校验器失效过 4 次，都是"什么都没查却报通过"）
    if not rows:
        print("!! 没解析出任何条目 —— 校验器空转，不算通过", file=sys.stderr)
        return 1
    print("解析出 %d 条译文\n" % len(rows))

    fail = 0
    over = []
    for rva, en, zh, ln in rows:
        # cap = len(英文) + 1；英文为空时无从判断，跳过容量判定
        if not en:
            continue
        cap = len(en.encode("gbk", errors="replace")) + 1
        need = len(zh.encode("gbk", errors="replace")) + 1
        if need > cap:
            if rva in EXCEPTIONS:
                exp_zh, why = EXCEPTIONS[rva]
                if zh == exp_zh:
                    print("  ≈ RVA %#06x 超限但属已登记例外：%s -> %s（%s）"
                          % (rva, en, zh, why))
                    continue
            over.append((rva, en, zh, need, cap, ln))
            fail += 1

    if over:
        print("\n!! %d 条超出槽容量：" % len(over))
        for rva, en, zh, need, cap, ln in over:
            print("   行 %-5d RVA %#06x  %-28s -> %-16s 需 %d B，槽 %d B"
                  % (ln, rva, en[:28], zh[:16], need, cap))
        print("\n   解法：换更短译名，或在脚本里登记 EXCEPTIONS 并注明原因。")

    # ── 附带检查：键唯一性（重复键会静默互相覆盖）──
    seen = {}
    dup = []
    for rva, en, zh, ln in rows:
        if rva in seen and seen[rva][0] != zh:
            dup.append((rva, seen[rva][0], zh))
        seen[rva] = (zh, ln)
    if dup:
        print("\n!! %d 个 RVA 有冲突译法：" % len(dup))
        for rva, a, b in dup:
            print("   RVA %#06x: %r vs %r" % (rva, a, b))
        fail += len(dup)

    # ── 附带检查：格式串占位符必须一致（%s/%d 等）──
    import re
    ph = re.compile(r"%[-+ #0]*\d*(?:\.\d+)?[diouxXeEfgGcs]")
    ph_fail = 0
    for rva, en, zh, ln in rows:
        if not en:
            continue
        e_n, z_n = len(ph.findall(en)), len(ph.findall(zh))
        if e_n != z_n:
            print("!! 行 %-5d RVA %#06x 占位符数量不一致：%s (%d) -> %s (%d)"
                  % (ln, rva, en[:30], e_n, zh[:30], z_n))
            ph_fail += 1
    if ph_fail:
        print("\n   占位符不匹配会导致 printf 读到栈上垃圾 -> 崩溃或乱码。")
        fail += ph_fail

    print("\n" + "=" * 74)
    print("检查 %d 条，失败 %d 项" % (len(rows), fail))
    if fail == 0:
        print("全部通过。")
    else:
        print("!! 有问题")
    print("=" * 74)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
