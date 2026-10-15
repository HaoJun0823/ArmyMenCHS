# -*- coding: utf-8 -*-
"""
Qwen3-TTS 全量配音 v2 —— 多进程并行
====================================
关键参数（用户要求：每角色参数一致，可追溯）
  - 每角色【固定 seed】：保证同一角色跨台词音色稳定
    实测依据：固定 seed MFCC 相似度 0.95 vs 随机 seed 0.85
  - 每角色【固定 instruct 基底】+ 按台词内容追加情绪
  - bf16：实测与 fp32 输出质量一致（ASR 匹配度同为 0.944），
    内存 4.35GB(bf16) vs 8GB(fp32)，速度快约 40%
  - 输出对齐游戏原始 WAV 格式（16bit/11025Hz 等）

并行策略：按可用内存动态决定 worker 数，每进程独立加载模型。
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
TRANS = r"G:\Projects\ArmyMenCHS\Army3_Original\audio\vos\vos_translations.json"
# 英文原声基线（游戏目录）。用途：逐文件读取原始采样率/位深，输出对齐游戏格式。
SRC = r"I:\LocalGames\Army Men\Army Men - Toys in Space STEAM\audio\vos"
# ★ 输出必须落在 Army3_Voice_CHS/audio/vos —— 即 ci_build_am3.py 第 5 步
#   读取的位置（AUDIO_SRC_DEFAULT）。早期这里误写成 Army3_CHS_Voice（不存在
#   的目录），生成结果会落在仓库外，导致打包拿不到新配音。
OUTDIR = r"G:\Projects\ArmyMenCHS\Army3_Voice_CHS\audio\vos"
ARCHIVE = r"G:\Projects\ArmyMenCHS\Army3_Voice_CHS\source\dub_params_archive.json"
PROGRESS = r"G:\Projects\ArmyMenCHS\Army3_Voice_CHS\source\_progress.txt"
BAKDIR = r"G:\Projects\ArmyMenCHS\_trash"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# ---- 文本修正（v3：含拟声补足，统一从 voice_cast 读取）----
# 拟声修正 + 其他修正合并；拟声修正优先
TEXT_FIXES = {}


def build_fmt():
    fmt = {}
    for fn in os.listdir(SRC):
        if not fn.lower().endswith(".wav"):
            continue
        try:
            with wave.open(os.path.join(SRC, fn), "rb") as w:
                fmt[fn] = (w.getframerate(), w.getsampwidth() * 8)
        except Exception:
            pass
    return fmt


def worker(wid, tasks, fmt, outdir, prog_path):
    import numpy as np
    import torch
    import soundfile as sf
    from scipy.signal import resample_poly
    from qwen_tts import Qwen3TTSModel
    import voice_cast as vc

    # 32 线程 / N 进程，避免过度订阅
    torch.set_num_threads(max(1, 32 // max(1, int(os.environ.get("NWORK", "4")))))

    log = open(prog_path, "a", encoding="utf-8", buffering=1)

    def emit(s):
        log.write(s + "\n")

    emit(f"[w{wid}] 加载模型 (bf16)...")
    model = Qwen3TTSModel.from_pretrained(
        MODEL, device_map="cpu", dtype=torch.bfloat16, attn_implementation="sdpa"
    )
    emit(f"[w{wid}] 就绪，分配 {len(tasks)} 条")

    out = []
    for i, (fname, text, speaker, instruct, seed) in enumerate(tasks, 1):
        t = time.time()
        try:
            torch.manual_seed(seed)
            np.random.seed(seed)
            wavs, sr = model.generate_voice_design(
                text=text, language="Chinese", instruct=instruct
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
                "out_sr": tsr, "out_bits": tbits,
                "duration_s": round(len(wav) / tsr, 3),
                "gen_seconds": round(time.time() - t, 1),
                "worker": wid,
            }
            out.append(rec)
            emit(f"[w{wid}] {i:3d}/{len(tasks)} {fname:<30} {rec['duration_s']:5.2f}s "
                 f"({rec['gen_seconds']:4.1f}s)")
        except Exception as e:
            import traceback
            traceback.print_exc()
            emit(f"[w{wid}] {i:3d}/{len(tasks)} FAIL {fname}: {e}")
            out.append({"wav": fname, "speaker": speaker, "error": str(e), "worker": wid})

    log.close()
    return out


def avail_gb():
    import subprocess
    o = subprocess.check_output(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory"],
        text=True).strip()
    return int(o) / 1024 / 1024


def main():
    import voice_cast as vc

    # 合并文本修正：普通修正 + 拟声补足（拟声优先）
    global TEXT_FIXES
    TEXT_FIXES = dict(getattr(vc, "TEXT_FIXES", {}))
    TEXT_FIXES.update(getattr(vc, "ONOMATOPOEIA_FIXES", {}))

    os.makedirs(OUTDIR, exist_ok=True)
    os.makedirs(BAKDIR, exist_ok=True)

    data = json.load(open(TRANS, encoding="utf-8"))

    # ---- 应用文本修正并写回 JSON，保证 JSON 与音频一致 ----
    shutil.copy2(TRANS, os.path.join(BAKDIR, "vos_translations_pre_batch.json"))
    fixed = 0
    for wav, zh in TEXT_FIXES.items():
        if wav in data and data[wav].get("value_ch") != zh:
            data[wav]["value_ch"] = zh
            data[wav]["note"] = "TTS 友好改写（重复单字）"
            fixed += 1
    if fixed:
        json.dump(data, open(TRANS, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print(f"已应用 {fixed} 处文本修正并写回 JSON")

    fmt = build_fmt()

    # ---- 构造任务 ----
    tasks = []
    for fname, v in sorted(data.items()):
        text = (v.get("value_ch") or "").strip()
        if not text:
            continue
        spk = v.get("speaker", "UnknownVoice")
        tasks.append((fname, text, spk, vc.build_instruct(spk, text), vc.get_seed(spk)))

    # ---- 动态决定 worker 数 ----
    free = avail_gb()
    nw = max(1, min(4, int((free - 4.0) // 4.5)))
    os.environ["NWORK"] = str(nw)
    print(f"可用内存 {free:.1f} GB -> 启用 {nw} 个 worker")
    print(f"任务总数 {len(tasks)}")

    open(PROGRESS, "w", encoding="utf-8").close()

    # ---- 分片 ----
    chunks = [[] for _ in range(nw)]
    for i, t in enumerate(tasks):
        chunks[i % nw].append(t)
    chunks = [c for c in chunks if c]

    t0 = time.time()
    ctx = mp.get_context("spawn")
    with ctx.Pool(len(chunks)) as pool:
        results = pool.starmap(
            worker,
            [(i, ch, fmt, OUTDIR, PROGRESS) for i, ch in enumerate(chunks)],
        )

    records = [r for sub in results for r in sub]
    ok = sum(1 for r in records if "error" not in r)
    fail = len(records) - ok

    archive = {
        "meta": {
            "task": "Army Men 3 (Toys in Space) 中文配音",
            "model": MODEL,
            "model_repo": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
            "license": "Apache-2.0",
            "mode": "VoiceDesign (自然语言声音设计，无克隆)",
            "device": "cpu",
            "dtype": "bfloat16",
            "attn_implementation": "sdpa",
            "workers": len(chunks),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_seconds": round(time.time() - t0, 1),
            "success": ok,
            "failed": fail,
            "seed_note": "API 的 seed= 参数实测无效；必须用 torch.manual_seed()。"
                         "每角色固定 seed 以保证音色一致。",
            "format_note": "输出对齐游戏原始 WAV（16bit/11025Hz 或 8bit/22050Hz，单声道）。",
            "dtype_note": "bf16 与 fp32 输出质量实测一致（ASR 匹配度同为 0.944）。",
            "python_env": r"G:\Projects\ArmyMenCHS\venv-qwen312",
            "text_fixes": TEXT_FIXES,
            "character_params": {
                k: {"seed": v["seed"], "instruct": v["desc"], "note": v.get("note", "")}
                for k, v in vc.VOICE_CAST.items()
            },
        },
        "items": sorted(records, key=lambda r: r["wav"]),
    }
    json.dump(archive, open(ARCHIVE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    print(f"\n{'='*58}")
    print(f"完成: 成功 {ok} / 失败 {fail} / 共 {len(records)}")
    print(f"耗时: {time.time()-t0:.0f}s")
    print(f"输出: {OUTDIR}")
    print(f"存档: {ARCHIVE}")


if __name__ == "__main__":
    main()
