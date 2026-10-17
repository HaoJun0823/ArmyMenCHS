# -*- coding: utf-8 -*-
"""Army5 ASR 分片：_asr_am5_shard.py <shard_idx> <shard_total>
各分片只处理自己的份额，写 vos_en_raw_shard<N>.json，互不覆盖。
"""
import json
import os
import re
import sys
import time

import numpy as np
import soundfile as sf
from faster_whisper import WhisperModel

SRC = r"G:\Projects\ArmyMenCHS\Army5_Original\audio\voice"
WORK = r"G:\Projects\ArmyMenCHS\Army5_Voice_CHS\source"
os.makedirs(WORK, exist_ok=True)

IDX = int(sys.argv[1])
TOT = int(sys.argv[2])
OUT = os.path.join(WORK, f"vos_en_raw_shard{IDX}.json")
PROG = os.path.join(WORK, f"_asr_progress_{IDX}.txt")


def rs(x, a, b):
    if a == b:
        return x
    n = int(round(len(x) * b / a))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def f0_median(w, sr, fmin=60.0, fmax=400.0):
    try:
        fl, hop = int(0.04 * sr), int(0.02 * sr)
        if len(w) < fl * 2:
            return 0.0
        vals = []
        for st in range(0, len(w) - fl, hop):
            fr = w[st:st + fl]
            if np.sqrt(np.mean(fr ** 2)) < 0.008:
                continue
            fr = fr - fr.mean()
            c = np.correlate(fr, fr, mode="full")[fl - 1:]
            lo, hi = int(sr / fmax), min(int(sr / fmin), len(c) - 1)
            if hi <= lo:
                continue
            k = int(np.argmax(c[lo:hi])) + lo
            if c[k] <= 0:
                continue
            vals.append(sr / k)
        return float(np.median(vals)) if vals else 0.0
    except Exception:
        return 0.0


allwav = sorted(f for f in os.listdir(SRC) if f.lower().endswith(".wav"))
mine = allwav[IDX::TOT]
log = open(PROG, "w", encoding="utf-8", buffering=1)


def emit(s):
    log.write(s + "\n")


emit(f"shard {IDX}/{TOT}: {len(mine)}/{len(allwav)}")
m = WhisperModel("large-v3", device="cpu", compute_type="int8", cpu_threads=10)
emit("model ready")

results = []
t1 = time.time()
for i, fn in enumerate(mine, 1):
    try:
        w, sr = sf.read(os.path.join(SRC, fn), dtype="float32", always_2d=False)
        if w.ndim > 1:
            w = w.mean(axis=-1)
        dur = len(w) / sr
        peak = float(np.max(np.abs(w))) if len(w) else 0.0
        rms = float(np.sqrt(np.mean(w ** 2))) if len(w) else 0.0
        f0 = f0_median(w, sr)
        segs, _ = m.transcribe(rs(w, sr, 16000), language="en", beam_size=5,
                               temperature=0.0, condition_on_previous_text=False,
                               vad_filter=False)
        segs = list(segs)
        text = " ".join(s.text.strip() for s in segs).strip()
        lp = float(np.mean([s.avg_logprob for s in segs])) if segs else -9.0
        nsp = float(np.mean([s.no_speech_prob for s in segs])) if segs else 1.0
        core = re.sub(r"[^A-Za-z]", "", text)
        is_voice = len(core) >= 3 and lp > -1.2 and nsp < 0.6
        if dur < 0.25 or peak < 0.01:
            is_voice = False
        results.append({
            "wav": fn, "duration_s": round(dur, 3), "peak": round(peak, 3),
            "rms": round(rms, 4), "f0_median": round(f0, 1), "asr_en": text,
            "avg_logprob": round(lp, 3), "no_speech_prob": round(nsp, 3),
            "candidate": "voice" if is_voice else "sfx",
        })
        el = time.time() - t1
        emit(f"[{i:3d}/{len(mine)}] {fn:<22} {dur:5.2f}s f0={f0:5.1f} {text[:70]!r} "
             f"ETA{el/i*(len(mine)-i):4.0f}s")
    except Exception as e:
        results.append({"wav": fn, "error": str(e), "candidate": "error"})
        emit(f"[{i:3d}/{len(mine)}] {fn:<22} FAIL {e}")
    if i % 5 == 0 or i == len(mine):
        json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
emit(f"done {len(results)} in {time.time()-t1:.0f}s")
