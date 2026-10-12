"""
校验翻译数据是否超出 exe 槽容量。

对每个条目：
  需要字节 = GBK(译文)长度 + 1(NUL)
  若 需要 > 容量 => 会覆盖下一项，必须处理

用法：
    python check_capacity.py <translation.ini>
"""

import sys
import re
import os


def gbk_len(s):
    try:
        return len(s.encode("gbk"))
    except Exception as e:
        return -1


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    path = sys.argv[1]

    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    entries = []
    in_entries = False
    for ln in lines:
        st = ln.strip()
        if st.startswith("[Entries]"):
            in_entries = True
            continue
        if st.startswith("["):
            in_entries = False
            continue
        if not in_entries or not st or st.startswith(";"):
            continue
        m = re.match(r"^(\d+)=(.*)$", st)
        if not m:
            continue
        idx = int(m.group(1))
        rest = m.group(2)
        # 分离注释 "; ..."
        if " ; " in rest:
            val, comment = rest.split(" ; ", 1)
        else:
            val, comment = rest, ""
        cap = None
        cm = re.search(r"cap=(\d+)", comment)
        if cm:
            cap = int(cm.group(1))
        en = comment.split(" [")[0].split(" cap=")[0].strip()
        entries.append((idx, val.strip(), en, cap))

    print(f"{'#':>3}  {'EN':<20} {'ZH':<16} {'need':>5} {'cap':>5}  status")
    print("-" * 68)
    over = []
    bad_gbk = []
    for idx, zh, en, cap in entries:
        n = gbk_len(zh)
        if n < 0:
            bad_gbk.append((idx, zh, en))
            print(f"{idx:>3}  {en:<20} {zh:<16} {'?':>5} "
                  f"{str(cap):>5}  GBK编码失败")
            continue
        need = n + 1
        if cap is None:
            print(f"{idx:>3}  {en:<20} {zh:<16} {need:>5} {'?':>5}  无容量信息")
            continue
        if need > cap:
            over.append((idx, en, zh, need, cap))
            print(f"{idx:>3}  {en:<20} {zh:<16} {need:>5} {cap:>5}  "
                  f"*** 超限 ***")
        else:
            print(f"{idx:>3}  {en:<20} {zh:<16} {need:>5} {cap:>5}  ok")

    print()
    print(f"总计 {len(entries)} 条")
    print(f"  超限   : {len(over)}")
    print(f"  GBK失败: {len(bad_gbk)}")
    if over:
        print("\n超限明细（必须缩短译文，否则会覆盖下一项）：")
        for idx, en, zh, need, cap in over:
            room = cap - 1
            max_cn = room // 2
            print(f"  #{idx} {en} -> '{zh}' 需{need}B > 容量{cap}B "
                  f"(最多 {max_cn} 个汉字)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
