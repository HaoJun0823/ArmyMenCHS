# -*- coding: utf-8 -*-
"""Army5 中文配音批量生成（Qwen3-TTS VoiceDesign）—— 多进程
源：Army5_Original/audio/voice（487 wav）
译：Army5_Voice_CHS/source/vos_zh.json（wav -> {speaker, en, zh}）
出：Army5_NEW_CHS/audio/vos（与源同名，格式对齐源 wav）

跳过策略：
  - candidate != voice（音效/空）或 zh 为空 -> 原样复制源 wav
  - 已存在且比脚本新、且非 --force -> 跳过（可断点续跑）
"""
import json
import os
import shutil
import sys
import time
import wave
from math import gcd

import multiprocessing as mp

MODEL = r"G:\Projects\ArmyMenCHS\models\Qwen3-TTS-12Hz-1.7B-VoiceDesign"
SRC = r"G:\Projects\ArmyMenCHS\Army5_Original\audio\voice"
WORK = r"G:\Projects\ArmyMenCHS\Army5_Voice_CHS\source"
ZH = os.path.join(WORK, "vos_zh.json")
OUTDIR = r"G:\Projects\ArmyMenCHS\Army5_NEW_CHS\audio\vos"
ARCHIVE = os.path.join(WORK, "dub_params_archive.json")
PROGRESS = os.path.join(WORK, "_progress.txt")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

CAP_FACTOR = 2.0
CAP_PAD = 0.5
# 下限：极短台词（0.3s 的「啊！」）按公式只给 14 token，会把正常发音截断
CAP_MIN_TOKENS = 36   # 12Hz -> 3.0s


def build_fmt():
    fmt = {}
    for fn in os.listdir(SRC):
        if not fn.lower().endswith(".wav"):
            continue
        try:
            with wave.open(os.path.join(SRC, fn), "rb") as w:
                fmt[fn] = (w.getframerate(), w.getsampwidth() * 8)
        except Exception:
            fmt[fn] = (22050, 16)
    return fmt


def worker(wid, tasks, fmt, outdir, prog_path):
    import numpy as np
    import torch
    import soundfile as sf
    from scipy.signal import resample_poly
    from qwen_tts import Qwen3TTSModel
    import voice_cast_am5 as vc

    torch.set_num_threads(max(1, 32 // max(1, int(os.environ.get("NWORK", "4")))))
    log = open(prog_path, "a", encoding="utf-8", buffering=1)

    def emit(s):
        log.write(s + "\n")

    emit(f"[w{wid}] loading model (bf16)...")
    model = Qwen3TTSModel.from_pretrained(
        MODEL, device_map="cpu", dtype=torch.bfloat16, attn_implementation="sdpa"
    )
    emit(f"[w{wid}] ready, {len(tasks)} tasks")

    out = []
    for i, (fname, text, speaker, instruct, seed, cap_tokens, src_dur) in enumerate(tasks, 1):
        t = time.time()
        try:
            torch.manual_seed(seed)
            np.random.seed(seed)
            wavs, sr = model.generate_voice_design(
                text=text, language="Chinese", instruct=instruct,
                max_new_tokens=cap_tokens,
            )
            wav = wavs[0].astype(np.float32)

            tsr, tbits = fmt.get(fname, (22050, 16))
            if sr != tsr:
                g = gcd(int(sr), int(tsr))
                wav = resample_poly(wav, tsr // g, int(sr) // g).astype(np.float32)

            peak = float(np.max(np.abs(wav))) or 1.0
            if peak > 0.99:
                wav = wav / peak * 0.99

            subtype = "PCM_U8" if tbits == 8 else "PCM_16"
            sf.write(os.path.join(outdir, fname), wav, tsr, subtype=subtype)

            rec = {
                "wav": fname, "speaker": speaker, "seed": seed,
                "instruct": instruct, "value_ch_used": text,
                "cap_tokens": cap_tokens, "src_duration_s": src_dur,
                "out_sr": tsr, "out_bits": tbits,
                "duration_s": round(len(wav) / tsr, 3),
                "gen_seconds": round(time.time() - t, 2),
                "worker": wid,
            }
            out.append(rec)
            emit(f"[w{wid}] {i:3d}/{len(tasks)} {fname:<22} {rec['duration_s']:5.2f}s "
                 f"({rec['gen_seconds']:5.1f}s) | {text[:30]}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            emit(f"[w{wid}] {i:3d}/{len(tasks)} FAIL {fname}: {e}")
            out.append({"wav": fname, "speaker": speaker, "error": str(e), "worker": wid})

    log.close()
    return out


def main():
    import voice_cast_am5 as vc

    os.makedirs(OUTDIR, exist_ok=True)
    data = json.load(open(ZH, encoding="utf-8"))
    fmt = build_fmt()

    tts_tasks, copied, skipped, nomodel = [], 0, 0, []
    for fname in sorted(f for f in os.listdir(SRC) if f.lower().endswith(".wav")):
        ent = data.get(fname) or {}
        zh = (ent.get("zh") or "").strip()
        dst = os.path.join(OUTDIR, fname)
        if not zh:
            nomodel.append(fname)
            if not os.path.exists(dst):
                shutil.copy2(os.path.join(SRC, fname), dst)
                copied += 1
            continue
        spk = ent.get("speaker", "UnknownVoice")
        src_dur = ent.get("duration_s") or 3.0
        cap_tokens = int((src_dur * CAP_FACTOR + CAP_PAD) * 12)
        cap_tokens = max(CAP_MIN_TOKENS, cap_tokens)
        tts_tasks.append((fname, zh, spk, vc.build_instruct(spk, zh),
                          vc.get_seed(spk), cap_tokens, src_dur))

    print(f"TTS 任务 {len(tts_tasks)} | 原样复制(无台词) {copied} | 无台词文件 {len(nomodel)}")

    free_gb = 0
    try:
        import subprocess
        o = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory"], text=True).strip()
        free_gb = int(o) / 1024 / 1024
    except Exception:
        free_gb = 16
    nw = max(1, min(4, int((free_gb - 4.0) // 4.5)))
    os.environ["NWORK"] = str(nw)
    print(f"可用内存 {free_gb:.1f} GB -> {nw} worker")

    open(PROGRESS, "w", encoding="utf-8").close()
    chunks = [[] for _ in range(nw)]
    for i, t in enumerate(tts_tasks):
        chunks[i % nw].append(t)
    chunks = [c for c in chunks if c]

    t0 = time.time()
    ctx = mp.get_context("spawn")
    with ctx.Pool(len(chunks)) as pool:
        results = pool.starmap(
            worker,
            [(i, ch, fmt, OUTDIR, PROGRESS) for i, ch in enumerate(chunks)])
    records = [r for sub in results for r in sub]
    ok = sum(1 for r in records if "error" not in r)
    fail = len(records) - ok

    archive = {
        "meta": {
            "task": "Army Men 5 (Air Tactics) 中文配音",
            "model": MODEL,
            "mode": "VoiceDesign",
            "device": "cpu", "dtype": "bfloat16", "workers": len(chunks),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_seconds": round(time.time() - t0, 1),
            "tts_total": len(tts_tasks), "copied_total": copied,
            "success": ok, "failed": fail,
            "cap_factor": CAP_FACTOR, "cap_pad": CAP_PAD,
            "character_params": {k: {"seed": vc.get_seed(k), "instruct": v["desc"],
                                     "note": v.get("note", "")}
                                 for k, v in vc.VOICE_CAST.items()},
        },
        "items": sorted(records, key=lambda r: r["wav"]),
    }
    json.dump(archive, open(ARCHIVE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"\n{'='*56}")
    print(f"完成: 成功 {ok} / 失败 {fail} / 共 {len(tts_tasks)}；复制 {copied}")
    print(f"耗时 {time.time()-t0:.0f}s")
    print(f"输出 {OUTDIR}")


if __name__ == "__main__":
    main()
