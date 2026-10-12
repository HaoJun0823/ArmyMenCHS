"""
由语义配对 CSV 生成 INI（列名: index, en_rva, en_fileoff, english, capacity, chinese, status）

用法：
    python emit_ini2.py <csv> <out.ini> [--block-name NAME] [--section NAME]
"""

import sys
import csv
import os


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return 1
    csv_in, out_path = args[0], args[1]
    block = args[args.index("--block-name") + 1] if "--block-name" in args else "UI Block"

    with open(csv_in, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rows = [r for r in rows if r.get("chinese", "").strip()]
    if not rows:
        print("no translated rows")
        return 1

    base_rva = rows[0]["en_rva"]
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    lines = [
        f"; {block}",
        "; 生成: Tools/exe_scan/emit_ini2.py (语义配对, 以 Steam v1.2 英文为准)",
        "; 译文来源: 中文官方 exe (1998 上海育碧) + 人工补译/校正",
        "; 编码 UTF-8; DLL 运行时转 GBK 写入",
        "",
        "[Meta]",
        f"BaseRVA={base_rva}",
        "Encoding=GBK",
        "Layout=packed4",
        f"Count={len(rows)}",
        "",
        "[Entries]",
        "; 序号 = 中文译文    ; 英文原文 cap=槽容量",
    ]

    for r in rows:
        lines.append(f"{r['index']}={r['chinese']} ; {r['english']} cap={r['capacity']}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"written {out_path}: {len(rows)} entries, base {base_rva}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
