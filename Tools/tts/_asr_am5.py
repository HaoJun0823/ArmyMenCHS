# -*- coding: utf-8 -*-
"""Army5 全量 ASR：Army5_Original/audio/voice 下全部 wav -> faster-whisper large-v3。
输出 vos_en_raw.json（含 voice/sfx 判定 + 声学特征 F0/时长/RMS）。
用法：python _asr_am5.py
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
OUT = os.path.join(WORK, "vos_en_raw.json")
PROG = os.path.join(WORK, "_asr_progress.txt")
os.makedirs(WORK, exist_ok=True)


def rs(x, a, b):
    if a == b:
        return x
    n = int(round(len(x) * b / a))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def f0_median(w, sr, fmin=60.0, fmax=400.0):
    """简化自相关基频估计，取有声帧中位数。"""
    try:
        fl = int(0.04 * sr)
        hop = int(0.02 * sr)
        if len(w) < fl * 2:
            return 0.0
        vals = []
        for st in range(0, len(w) - fl, hop):
            fr = w[st:st + fl]
            if np.sqrt(np.mean(fr ** 2)) < 0.008:
                continue
            fr = fr - fr.mean()
            c = np.correlate(fr, fr, mode="full")[fl - 1:]
            lo = int(sr / fmax)
            hi = min(int(sr / fmin), len(c) - 1)
            if hi <= lo:
                continue
            seg = c[lo:hi]
            k = int(np.argmax(seg)) + lo
            if c[k] <= 0:
                continue
            vals.append(sr / k)
        return float(np.median(vals)) if vals else 0.0
    except Exception:
        return 0.0


allwav = sorted(f for f in os.listdir(SRC) if f.lower().endswith(".wav"))
log = open(PROG, "w", encoding="utf-8", buffering=1)


def emit(s):
    print(s, flush=True)
    log.write(s + "\n")


emit(f"源 wav {len(allwav)}")
emit("加载 whisper large-v3 (cpu/int8)...")
t0 = time.time()
m = WhisperModel("large-v3", device="cpu", compute_type="int8", cpu_threads=16)
emit(f"就绪 {time.time()-t0:.1f}s\n")

results = []
t1 = time.time()
for i, fn in enumerate(allwav, 1):
    t = time.time()
    try:
        w, sr = sf.read(os.path.join(SRC, fn), dtype="float32", always_2d=False)
        if w.ndim > 1:
            w = w.mean(axis=-1)
        dur = len(w) / sr
        peak = float(np.max(np.abs(w))) if len(w) else 0.0
        rms = float(np.sqrt(np.mean(w ** 2))) if len(w) else 0.0
        f0 = f0_median(w, sr)
        w16 = rs(w, sr, 16000)

        segs, info = m.transcribe(
            w16, language="en", beam_size=5, temperature=0.0,
            condition_on_previous_text=False, vad_filter=False,
        )
        segs = list(segs)
        text = " ".join(s.text.strip() for s in segs).strip()
        lp = float(np.mean([s.avg_logprob for s in segs])) if segs else -9.0
        nsp = float(np.mean([s.no_speech_prob for s in segs])) if segs else 1.0

        core = re.sub(r"[^A-Za-z]", "", text)
        is_voice = len(core) >= 3 and lp > -1.2 and nsp < 0.6
        if dur < 0.25 or peak < 0.01:
            is_voice = False

        rec = {
            "wav": fn, "duration_s": round(dur, 3),
            "peak": round(peak, 3), "rms": round(rms, 4),
            "f0_median": round(f0, 1),
            "asr_en": text, "avg_logprob": round(lp, 3),
            "no_speech_prob": round(nsp, 3),
            "candidate": "voice" if is_voice else "sfx",
        }
        results.append(rec)
        el = time.time() - t1
        eta = el / i * (len(allwav) - i)
        emit(f"[{i:3d}/{len(allwav)}] {fn:<22} {dur:5.2f}s f0={f0:5.1f} lp={lp:5.2f} "
             f"{rec['candidate']:<6} ETA{eta:4.0f}s | {text[:70]!r}")
    except Exception as e:
        results.append({"wav": fn, "error": str(e), "candidate": "error"})
        emit(f"[{i:3d}/{len(allwav)}] {fn:<22} FAIL {e}")

    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

emit(f"\n完成 {len(results)} 个，耗时 {time.time()-t1:.0f}s")
log.close()
voice = [r for r in results if r.get("candidate") == "voice"]
sfx = [r for r in results if r.get("candidate") == "sfx"]
print(f"\n语音候选 {len(voice)} 个 | 音效/空 {len(sfx)} 个")
