# -*- coding: utf-8 -*-
"""小样测试：_smoke_am5.py —— 每个角色挑 1 条，验证 TTS 管线与音色。
输出到 Army5_Voice_CHS/source/_smoke/
"""
import os
import sys
import time
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
OUT = r"G:\Projects\ArmyMenCHS\Army5_Voice_CHS\source\_smoke"
os.makedirs(OUT, exist_ok=True)

CASES = [
    ("Sarge", "sar010c.wav", "总部，我是中士。我们在那栋房子里发现了一处巨大的棕军基地。"),
    ("Sam", "sam002c.wav", "上尉，情报显示霍克中士就在沙箱附近。"),
    ("Captain", "cap019f.wav", "叫我布莱德……桥梁建筑师！"),
    ("Grimm", "col041c.wav", "胜利属于我们！"),
    ("Plastro", "pla005a.wav", "很快我们就能造出一支空战部队的大军！"),
    ("BlueSpy", "blu001f.wav", "别开枪！我给你们情报！"),
]

fmt = {}
for fn in os.listdir(SRC):
    if fn.lower().endswith(".wav"):
        try:
            with wave.open(os.path.join(SRC, fn), "rb") as w:
                fmt[fn] = (w.getframerate(), w.getsampwidth() * 8)
        except Exception:
            fmt[fn] = (22050, 16)

torch.set_num_threads(16)
print("loading model...", flush=True)
t0 = time.time()
model = Qwen3TTSModel.from_pretrained(
    MODEL, device_map="cpu", dtype=torch.bfloat16, attn_implementation="sdpa")
print(f"ready {time.time()-t0:.1f}s", flush=True)

for spk, fn, zh in CASES:
    instruct = vc.build_instruct(spk, zh)
    torch.manual_seed(vc.get_seed(spk))
    np.random.seed(vc.get_seed(spk))
    t = time.time()
    wavs, sr = model.generate_voice_design(
        text=zh, language="Chinese", instruct=instruct, max_new_tokens=480)
    wav = wavs[0].astype(np.float32)
    tsr, tbits = fmt.get(fn, (22050, 16))
    if sr != tsr:
        g = gcd(int(sr), int(tsr))
        wav = resample_poly(wav, tsr // g, int(sr) // g).astype(np.float32)
    peak = float(np.max(np.abs(wav))) or 1.0
    if peak > 0.99:
        wav = wav / peak * 0.99
    p = os.path.join(OUT, f"{spk}_{os.path.splitext(fn)[0]}.wav")
    sf.write(p, wav, tsr, subtype="PCM_U8" if tbits == 8 else "PCM_16")
    print(f"{spk:10} {len(wav)/tsr:5.2f}s ({time.time()-t:.1f}s) -> {os.path.basename(p)}"
          f" | {instruct[:40]}", flush=True)

print("\ndone")
