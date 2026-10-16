#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""重建 dub_params_archive.json —— 从磁盘成品 + translations + en_raw 反推。

_batch_dub_am4.py 在写存档阶段因 VOICE_CAST[k]["seed"] 不存在而崩溃，
音频已全部落盘（0 FAIL）。此脚本不重跑 TTS，仅重建审计存档。
"""
import json, os, time, wave

MODEL = r"G:\Projects\ArmyMenCHS\models\Qwen3-TTS-12Hz-1.7B-VoiceDesign"
TRANS = r"G:\Projects\ArmyMenCHS\Army4_Voice_CHS\source\vos_translations.json"
SRC   = r"G:\Projects\ArmyMenCHS\Army4_Original\audio\vos"
OUTDIR= r"G:\Projects\ArmyMenCHS\Army4_Voice_CHS\audio\vos"
ENRAW = r"G:\Projects\ArmyMenCHS\Army4_Voice_CHS\source\vos_en_raw_clean.json"
ARCHIVE = r"G:\Projects\ArmyMenCHS\Army4_Voice_CHS\source\dub_params_archive.json"
CAP_FACTOR = 2.0
CAP_PAD = 0.5

import sys
sys.path.insert(0, os.path.dirname(__file__))
import voice_cast as vc

def wav_info(path):
    with wave.open(path, "rb") as w:
        fr = w.getframerate(); n = w.getnframes(); sw = w.getsampwidth()
    return fr, sw * 8, round(n / fr, 3)

en_raw = {d["wav"]: d for d in json.load(open(ENRAW, encoding="utf-8"))}
trans = json.load(open(TRANS, encoding="utf-8"))
src_set = {f for f in os.listdir(SRC) if f.lower().endswith(".wav")}

items = []
tts_total = 0
copied = 0
for fn in sorted(os.listdir(OUTDIR)):
    if not fn.lower().endswith(".wav"):
        continue
    p = os.path.join(OUTDIR, fn)
    fr, bits, dur = wav_info(p)
    if fn in trans and fn in src_set:
        spk = trans[fn].get("speaker", "UnknownVoice")
        vch = trans[fn].get("value_ch", "")
        instruct = vc.build_instruct(spk, vch)
        seed = vc.get_seed(spk)
        src_dur = en_raw.get(fn, {}).get("duration_s", dur)
        cap = int((src_dur * CAP_FACTOR + CAP_PAD) * 12)
        items.append({
            "wav": fn, "type": "tts", "speaker": spk,
            "seed": seed, "instruct": instruct,
            "value_ch_used": vch,
            "cap_tokens": cap, "src_duration_s": round(src_dur, 3),
            "out_sr": fr, "out_bits": bits, "duration_s": dur,
            "gen_seconds": None,  # 进程内计时未持久化
            "worker": None,
        })
        tts_total += 1
    else:
        items.append({
            "wav": fn, "type": "copy", "speaker": None,
            "seed": None, "instruct": None,
            "value_ch_used": None, "cap_tokens": None,
            "src_duration_s": None, "out_sr": fr, "out_bits": bits,
            "duration_s": dur, "gen_seconds": None, "worker": None,
        })
        copied += 1

archive = {
    "meta": {
        "task": "Army Men 4 (World War) 中文配音",
        "model": MODEL,
        "model_repo": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        "license": "Apache-2.0",
        "mode": "VoiceDesign (自然语言声音设计，无克隆)",
        "device": "cpu", "dtype": "bfloat16", "attn_implementation": "sdpa",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_seconds": None,
        "tts_total": tts_total, "copied_total": copied,
        "success": tts_total, "failed": 0,
        "cap_factor": CAP_FACTOR, "cap_pad": CAP_PAD,
        "seed_note": "固定 GLOBAL_SEED；API seed= 实测无效，用 torch.manual_seed()。",
        "format_note": "输出对齐游戏原始 WAV（16bit/11025Hz 或 8bit/22050Hz，单声道）。",
        "python_env": r"G:\Projects\ArmyMenCHS\venv-qwen312",
        "rebuilt": True,
        "character_params": {
            k: {"seed": vc.get_seed(k), "instruct": v["desc"],
                "note": v.get("note", "")}
            for k, v in vc.VOICE_CAST.items()
        },
    },
    "items": sorted(items, key=lambda r: r["wav"]),
}
json.dump(archive, open(ARCHIVE, "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
print(f"重建存档: TTS {tts_total} / 复制 {copied} / 共 {len(items)}")
print(f"  -> {ARCHIVE}")
