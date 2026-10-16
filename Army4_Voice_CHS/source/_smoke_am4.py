# -*- coding: utf-8 -*-
"""Smoke test: load VoiceDesign model and synthesize 2 lines (1 normal + 1 onomatopoeia)."""
import os, sys, wave, time, numpy as np, torch, soundfile as sf
from scipy.signal import resample_poly
from math import gcd
sys.path.insert(0, r"G:\Projects\ArmyMenCHS\Tools\tts")
from qwen_tts import Qwen3TTSModel
import voice_cast as vc

MODEL = r"G:\Projects\ArmyMenCHS\models\Qwen3-TTS-12Hz-1.7B-VoiceDesign"
SRC = r"G:\Projects\ArmyMenCHS\Army4_Original\audio\vos"
OUT = r"G:\Projects\ArmyMenCHS\Army4_Voice_CHS\audio\vos"

def fmt(fn):
    with wave.open(os.path.join(SRC, fn), "rb") as w:
        return w.getframerate(), w.getsampwidth()*8

print("loading model...")
t0=time.time()
model = Qwen3TTSModel.from_pretrained(MODEL, device_map="cpu", dtype=torch.bfloat16, attn_implementation="sdpa")
print(f"loaded in {time.time()-t0:.1f}s")

tests = [
    ("00_103_C.wav", "列兵，我要跟你赛一场吉普车。", "Sarge"),
    ("Aah2.wav", "呃！", "GreenArmy_Grunt"),  # sfx/onomatopoeia path -> but we TTS it here as test
]
for fn, text, spk in tests:
    tsr, tbits = fmt(fn)
    seed = vc.get_seed(spk)
    torch.manual_seed(seed); np.random.seed(seed)
    cap = int((3.0*2.0+0.5)*12)
    t=time.time()
    wavs, sr = model.generate_voice_design(text=text, language="Chinese",
                                           instruct=vc.build_instruct(spk, text),
                                           max_new_tokens=cap)
    wav = wavs[0].astype(np.float32)
    if sr != tsr:
        g=gcd(int(sr),int(tsr)); wav=resample_poly(wav, tsr//g, int(sr)//g).astype(np.float32)
    peak=float(np.max(np.abs(wav))) or 1.0
    if peak>0.99: wav=wav/peak*0.99
    subtype="PCM_U8" if tbits==8 else "PCM_16"
    sf.write(os.path.join(OUT, "_smoke_"+fn), wav, tsr, subtype=subtype)
    print(f"{fn}: gen {time.time()-t:.1f}s sr {sr}->{tsr} bits {tbits} dur {len(wav)/tsr:.2f}s")
print("SMOKE OK")
