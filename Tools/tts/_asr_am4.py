# -*- coding: utf-8 -*-
"""Army4 全量 ASR：对 Army4_Original/audio/vos 全部 wav 跑 whisper large-v3。
输出 vos_en_raw.json（含 voice/sfx 判定）。
玩法沿用 _asr2.py：language="en", temperature=0.0。
"""
import json
import os
import re
import time

import numpy as np
import soundfile as sf
from faster_whisper import WhisperModel

SRC = r"G:\Projects\ArmyMenCHS\Army4_Original\audio\vos"
OUT = r"G:\Projects\ArmyMenCHS\Army4_Voice_CHS\source\vos_en_raw.json"
PROG = r"G:\Projects\ArmyMenCHS\Army4_Voice_CHS\source\_asr_progress.txt"


def rs(x, a, b):
    if a == b:
        return x
    n = int(round(len(x) * b / a))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


allwav = sorted(f for f in os.listdir(SRC) if f.lower().endswith(".wav"))
log = open(PROG, "w", encoding="utf-8", buffering=1)


def emit(s):
    print(s, flush=True)
    log.write(s + "\n")


emit(f"源 wav {len(allwav)}")
emit("加载 whisper large-v3 (cpu/int8)...")
t0 = time.time()
m = WhisperModel("large-v3", device="cpu", compute_type="int8")
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
        w = rs(w, sr, 16000)

        segs, info = m.transcribe(
            w, language="en", beam_size=5, temperature=0.0,
            condition_on_previous_text=False, vad_filter=False,
        )
        segs = list(segs)
        text = "".join(s.text for s in segs).strip()
        lp = float(np.mean([s.avg_logprob for s in segs])) if segs else -9.0
        nsp = float(np.mean([s.no_speech_prob for s in segs])) if segs else 1.0

        core = re.sub(r"[^A-Za-z]", "", text)
        is_voice = len(core) >= 3 and lp > -1.2 and nsp < 0.6

        rec = {
            "wav": fn, "duration_s": round(dur, 2),
            "asr_en": text, "avg_logprob": round(lp, 3),
            "no_speech_prob": round(nsp, 3),
            "candidate": "voice" if is_voice else "sfx",
        }
        results.append(rec)
        el = time.time() - t1
        eta = el / i * (len(allwav) - i)
        emit(f"[{i:3d}/{len(allwav)}] {fn:<30} {dur:5.2f}s lp={lp:5.2f} "
             f"{rec['candidate']:<6} ETA{eta:4.0f}s | {text[:60]!r}")
    except Exception as e:
        results.append({"wav": fn, "error": str(e), "candidate": "error"})
        emit(f"[{i:3d}/{len(allwav)}] {fn:<30} FAIL {e}")

    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

emit(f"\n完成 {len(results)} 个，耗时 {time.time()-t1:.0f}s")
log.close()
voice = [r for r in results if r.get("candidate") == "voice"]
sfx = [r for r in results if r.get("candidate") == "sfx"]
print(f"\n语音候选 {len(voice)} 个 | 音效 {len(sfx)} 个")
