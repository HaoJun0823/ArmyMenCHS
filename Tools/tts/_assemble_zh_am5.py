# -*- coding: utf-8 -*-
"""合并译文分片 -> vos_zh.json（wav -> {speaker, en, zh, duration_s}）

输入：
  _zh_part1.py / _zh_part2.py / _zh_part3.py   手工译文（键为小写 wav）
  vos_en_all.json                              _merge_am5.py 产出（说话人 + 英文 + 时长）
输出：
  vos_zh.json                                  配音批次直接读它
"""
import importlib.util
import json
import os
import sys

WORK = r"G:\Projects\ArmyMenCHS\Army5_Voice_CHS\source"
EN_ALL = os.path.join(WORK, "vos_en_all.json")
OUT = os.path.join(WORK, "vos_zh.json")


def load_zh():
    zh = {}
    for i in (1, 2, 3, 4):
        p = os.path.join(WORK, f"_zh_part{i}.py")
        if not os.path.exists(p):
            continue
        spec = importlib.util.spec_from_file_location(f"zp{i}", p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        part = getattr(m, "ZH", {})
        dup = set(zh) & set(k.lower() for k in part)
        if dup:
            print(f"[WARN] part{i} 与前面重复 {len(dup)} 条: {sorted(dup)[:5]}")
        zh.update({k.lower(): v for k, v in part.items()})
        print(f"part{i}: {len(part)} 条")
    return zh


def main():
    zh = load_zh()
    rows = json.load(open(EN_ALL, encoding="utf-8"))
    out, missing = {}, []
    for r in rows:
        k = r["wav"].lower()
        t = zh.get(k, "").strip()
        out[r["wav"]] = {
            "speaker": r["speaker"],
            "en": r.get("en", ""),
            "zh": t,
            "duration_s": r.get("duration_s"),
            "en_source": r.get("en_source"),
        }
        if not t:
            missing.append(r)

    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"\n总 {len(rows)} 条，已译 {len(rows)-len(missing)}，未译 {len(missing)}")
    if missing:
        from collections import Counter
        print("未译按说话人:", dict(Counter(m["speaker"] for m in missing)))
        print("\n未译清单（wav | speaker | en）:")
        for m in missing:
            print(f"  {m['wav']:<22} {m['speaker']:<12} {(m.get('en') or '')[:70]}")


if __name__ == "__main__":
    main()
