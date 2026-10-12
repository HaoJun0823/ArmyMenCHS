"""
在中文 exe 里找出"中文串聚集区"，作为 UI 串块候选。

原理：真正的 UI 文本块是连续多个 C 串（紧凑排列 + 4 字节对齐）。
随机数据里的 GBK 巧合不会连续成串。

用法：
    python find_blocks.py <chs.exe> [--min-run N] [--min-len M]

输出每个候选块：起始 file offset、连续串数、前若干条内容。
"""

import sys


def is_gbk_lead(b):
    return 0xB0 <= b <= 0xF7


def is_gbk_trail(b):
    return 0xA1 <= b <= 0xFE


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    path = args[0]
    min_run = int(args[args.index("--min-run") + 1]) if "--min-run" in args else 3
    min_len = int(args[args.index("--min-len") + 1]) if "--min-len" in args else 2

    with open(path, "rb") as f:
        buf = f.read()

    # 扫描所有 "C 串 + padding 到 4" 的槽，从每个可能位置开始，
    # 找出连续 >= min_run 个有效 GBK 中文串的区域
    n = len(buf)
    i = 0
    blocks = []
    while i < n - 4:
        # 尝试从 i 开始读一个 C 串
        if buf[i] == 0:
            i += 1
            continue
        # 读串
        j = i
        raw = bytearray()
        ok = True
        while j < n and buf[j] != 0:
            raw.append(buf[j])
            j += 1
            if j - i > 200:
                ok = False
                break
        if not ok or j >= n:
            i += 1
            continue
        # 判定是否为合法 GBK 中文串
        try:
            s = raw.decode("gbk")
        except Exception:
            i += 1
            continue
        # 至少 min_len 个汉字，且不含控制字符
        cn = sum(1 for c in s if '\u4e00' <= c <= '\u9fff')
        if cn < min_len:
            i += 1
            continue
        if any(ord(c) < 32 for c in s):
            i += 1
            continue

        # 找到起点，向后连续读多个槽
        entries = []
        p = i
        while len(entries) < 200:
            q = p
            r = bytearray()
            while q < n and buf[q] != 0:
                r.append(buf[q])
                q += 1
            if q >= n:
                break
            try:
                t = r.decode("gbk")
            except Exception:
                break
            # 下一槽应对齐到 4
            nxt = q + 1
            nxt += (4 - (nxt % 4)) % 4
            entries.append((p, t, nxt - p))
            p = nxt
            # 若下一个字节是 0（空槽），停止
            if p < n and buf[p] == 0:
                # 允许一个空槽后继续？简单起见停止
                break
        if len(entries) >= min_run:
            blocks.append((i, entries))
            i = entries[-1][0] + entries[-1][2]
        else:
            i += 1

    print(f"候选块: {len(blocks)} 个 (min_run={min_run})")
    print()
    for idx, (start, ents) in enumerate(blocks):
        print(f"--- 块 #{idx}  off=0x{start:08X}  {len(ents)} 项 ---")
        for off, t, cap in ents[:8]:
            print(f"    0x{off:08X} cap={cap:3d}  {t}")
        if len(ents) > 8:
            print(f"    ... 共 {len(ents)} 项")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
