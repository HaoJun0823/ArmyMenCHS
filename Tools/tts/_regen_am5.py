# -*- coding: utf-8 -*-
"""定点重生成：_regen_am5.py  wav1 wav2 ...
用于修掉时长相对源音频超 2 倍的条目（拟声/短句生成拖长）。
时长封顶按 (源时长*1.6 + 0.35)*12，不再套 36 token 下限。
"""
import json
import os
import sys
import wave
from math import gcd

import numpy as np
import torch
import soundfile as sf
from scipy.signal import resample_poly
from qwen_tts import Qwen3TTSModel

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import voice_cast_am5 as vc

MODEL = r"G:\Projects\ArmyMenCHS\models\Qwen3-TTS-12Hz-1.7B-VoiceDesign"
SRC = r"G:\Projects\ArmyMenCHS\Army5_Original\audio\voice"
OUT = r"G:\Projects\ArmyMenCHS\Army5_NEW_CHS\update\audio\voice"
ZH = r"G:\Projects\ArmyMenCHS\Army5_Voice_CHS\source\vos_zh.json"

CAP_FACTOR = 2.2
CAP_PAD = 0.3
CAP_MIN = 14

targets = sys.argv[1:]
data = json.load(open(ZH, encoding="utf-8"))
fmt = {}
for fn in os.listdir(SRC):
    if fn.lower().endswith(".wav"):
        try:
            with wave.open(os.path.join(SRC, fn), "rb") as w:
                fmt[fn] = (w.getframerate(), w.getsampwidth() * 8)
        except Exception:
            fmt[fn] = (22050, 16)

torch.set_num_threads(16)
print("loading...", flush=True)
model = Qwen3TTSModel.from_pretrained(
    MODEL, device_map="cpu", dtype=torch.bfloat16, attn_implementation="sdpa")
print("ready", flush=True)

for f in targets:
    ent = data.get(f) or {}
    zh = (ent.get("zh") or "").strip()
    if not zh:
        print(f"skip {f}: 无中文")
        continue
    spk = ent["speaker"]
    with wave.open(os.path.join(SRC, f), "rb") as w:
        ds = w.getnframes() / w.getframerate()
    cap = max(CAP_MIN, int((ds * CAP_FACTOR + CAP_PAD) * 12))
    instruct = vc.build_instruct(spk, zh)
    torch.manual_seed(vc.get_seed(spk))
    np.random.seed(vc.get_seed(spk))
    wavs, sr = model.generate_voice_design(
        text=zh, language="Chinese", instruct=instruct, max_new_tokens=cap)
    wav = wavs[0].astype(np.float32)
    tsr, tbits = fmt.get(f, (22050, 16))
    if sr != tsr:
        g = gcd(int(sr), int(tsr))
        wav = resample_poly(wav, tsr // g, int(sr) // g).astype(np.float32)
    peak = float(np.max(np.abs(wav))) or 1.0
    if peak > 0.99:
        wav = wav / peak * 0.99
    sf.write(os.path.join(OUT, f), wav, tsr,
             subtype="PCM_U8" if tbits == 8 else "PCM_16")
    print(f"{f:<16} {spk:<10} {len(wav)/tsr:5.2f}s (源 {ds:4.2f}s, cap={cap}) | {zh}",
          flush=True)
print("done")
