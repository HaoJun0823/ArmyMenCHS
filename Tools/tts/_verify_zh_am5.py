# -*- coding: utf-8 -*-
"""中文配音回检：用 whisper 对生成的中文 wav 做 ASR，与原文算字级相似度。
输出 _verify_zh.json。抽样或全量用 --all。
"""
import json
import os
import re
import sys

import numpy as np
import soundfile as sf
from faster_whisper import WhisperModel

OUT = r"G:\Projects\ArmyMenCHS\Army5_NEW_CHS\audio\vos"
WORK = r"G:\Projects\ArmyMenCHS\Army5_Voice_CHS\source"
ZH = os.path.join(WORK, "vos_zh.json")
RES = os.path.join(WORK, "_verify_zh.json")


def rs(x, a, b):
    if a == b:
        return x
    n = int(round(len(x) * b / a))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def norm(s):
    return re.sub(r"[^\u4e00-\u9fff0-9a-zA-Z]", "", s or "")


def ratio(a, b):
    """字级 F1（按字集合多寡近似），简单且够用。"""
    A, B = norm(a), norm(b)
    if not A or not B:
        return 0.0
    from collections import Counter
    ca, cb = Counter(A), Counter(B)
    inter = sum((ca & cb).values())
    return 2 * inter / (len(A) + len(B))


def main():
    zh = json.load(open(ZH, encoding="utf-8"))
    items = [(w, e) for w, e in sorted(zh.items()) if (e.get("zh") or "").strip()]
    if "--all" not in sys.argv:
        import random
        random.seed(11)
        items = random.sample(items, min(60, len(items)))

    m = WhisperModel("large-v3", device="cpu", compute_type="int8", cpu_threads=16)
    out = []
    for i, (w, e) in enumerate(items, 1):
        wav, sr = sf.read(os.path.join(OUT, w), dtype="float32")
        if wav.ndim > 1:
            wav = wav.mean(axis=-1)
        segs, _ = m.transcribe(rs(wav, sr, 16000), language="zh",
                               beam_size=5, temperature=0.0, vad_filter=False)
        hyp = "".join(s.text for s in segs).strip()
        r = ratio(e["zh"], hyp)
        out.append({"wav": w, "speaker": e["speaker"], "ref": e["zh"],
                    "asr_zh": hyp, "sim": round(r, 3)})
        print(f"[{i:3d}/{len(items)}] {w:<16} {r:5.2f} | {e['zh'][:28]} => {hyp[:28]}",
              flush=True)

    json.dump(out, open(RES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    sims = sorted(x["sim"] for x in out)
    n = len(sims)
    print(f"\n样本 {n}  中位 {sims[n//2]:.3f}  P10 {sims[max(0,n//10)]:.3f}  "
          f"<0.5 的 {sum(1 for s in sims if s<0.5)} 条")
    print("最低 10 条:")
    for x in sorted(out, key=lambda y: y["sim"])[:10]:
        print(f"  {x['wav']:<16} {x['sim']:.2f} | ref={x['ref'][:26]} | asr={x['asr_zh'][:26]}")


if __name__ == "__main__":
    main()
