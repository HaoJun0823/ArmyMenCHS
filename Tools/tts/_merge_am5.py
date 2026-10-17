# -*- coding: utf-8 -*-
"""合并 ASR 分片 + 官方字幕(COM.txt) 生成 Army5 英文台词总表 vos_en_all.json。

优先用 COM.txt 的官方台词文本（比 ASR 准确），缺失时回退 ASR。
同时给出每个 wav 的说话人（来自 COM.txt）与声学特征。
"""
import glob
import json
import os
import re
from collections import defaultdict

WORK = r"G:\Projects\ArmyMenCHS\Army5_Voice_CHS\source"
SRC = r"G:\Projects\ArmyMenCHS\Army5_Original\audio\voice"
DATA = r"G:\Projects\ArmyMenCHS\Army5_Original\data"
OUT = os.path.join(WORK, "vos_en_all.json")

PREFIX_SPK = {
    "sam": "Sam", "cap": "Captain", "capt": "Captain",
    "sar": "Sarge", "col": "Grimm", "pla": "Plastro",
    "blu": "BlueSpy", "gry": "GreySpy",
}


def load_com():
    """Com.txt: 说话人|wav|台词。同一 wav 多条时取最长台词。"""
    com = {}
    for p in glob.glob(os.path.join(DATA, "*", "COM.txt")):
        for ln in open(p, encoding="latin-1"):
            ln = ln.rstrip("\r\n")
            if ln.count("|") < 2 or ln.startswith("//"):
                continue
            spk, wav, txt = ln.split("|", 2)
            spk = spk.strip()
            spk = {"Bluespy": "BlueSpy", "Blue Spy": "BlueSpy",
                   "Grey Spy": "GreySpy"}.get(spk, spk)
            k = wav.lower()
            if k not in com or len(txt.strip()) > len(com[k][1]):
                com[k] = (spk, txt.strip())
    return com


def load_asr():
    m = {}
    for p in sorted(glob.glob(os.path.join(WORK, "vos_en_raw_shard*.json"))):
        for r in json.load(open(p, encoding="utf-8")):
            m[r["wav"].lower()] = r
    return m


def main():
    com = load_com()
    asr = load_asr()
    files = sorted(f for f in os.listdir(SRC) if f.lower().endswith(".wav"))
    print(f"wav {len(files)} | COM 覆盖 {len(com)} | ASR 覆盖 {len(asr)}")

    out = []
    for fn in files:
        k = fn.lower()
        a = asr.get(k, {})
        spk, com_txt = com.get(k, (None, ""))
        if not spk:
            m = re.match(r"([A-Za-z]+)", fn)
            pre = m.group(1).lower() if m else ""
            spk = PREFIX_SPK.get(pre)
            if not spk:
                if pre.startswith("tro") and re.search(r"(stub|crowd)", fn, re.I):
                    spk = "GreenTrooper"
                elif pre.startswith("tro"):
                    spk = "GreenTrooper"
                elif pre.startswith("death"):
                    spk = "Screamer"
                else:
                    spk = "UnknownVoice"
        txt = com_txt or (a.get("asr_en") or "").strip()
        out.append({
            "wav": fn,
            "speaker": spk,
            "en": txt,
            "en_source": "com" if com_txt else ("asr" if a.get("asr_en") else "none"),
            "asr_en": (a.get("asr_en") or "").strip(),
            "duration_s": a.get("duration_s"),
            "f0_median": a.get("f0_median"),
            "peak": a.get("peak"),
            "rms": a.get("rms"),
            "candidate": a.get("candidate", "unknown"),
        })
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 统计
    from collections import Counter
    c = Counter(r["speaker"] for r in out)
    print("\n说话人分布:")
    for s, n in c.most_common():
        print(f"  {s:14} {n:4}")
    srcs = Counter(r["en_source"] for r in out)
    print("\n文本来源:", dict(srcs))
    empty = [r["wav"] for r in out if not r["en"]]
    print(f"\n无文本 {len(empty)}: {empty}")


if __name__ == "__main__":
    main()
