# -*- coding: utf-8 -*-
"""
Qwen3-TTS 全量配音 · Army Men 4 (World War) —— 多进程并行
========================================================
与 Army3 (_batch_dub2.py) 同款管线，针对 4 代差异点：
  - TRANS: Army4_Voice_CHS/source/vos_translations.json（250 条 voice）
  - SRC:   Army4_Original/audio/vos（298 个英文基线 wav，含 48 sfx）
  - OUTDIR:Army4_Voice_CHS/audio/vos（ci_build_am4.py 第 6 步读取位置）
  - 遍历 SRC 298：命中翻译表且 value_ch 非空 -> TTS；否则原样复制（sfx + 遗漏）
  - 时长封顶：max_new_tokens = (src_dur*CAP_FACTOR + CAP_PAD)*12，
    12Hz codec，只截断拟声词等病态循环，正常台词靠 EOS 自然结束。
  - seed：torch.manual_seed + np.random.seed（API 的 seed= 实测无效）。

输出对齐游戏原始 WAV 格式（16bit/11025Hz 或 8bit/22050Hz，单声道）。
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
TRANS = r"G:\Projects\ArmyMenCHS\Army4_Voice_CHS\source\vos_translations.json"
SRC = r"G:\Projects\ArmyMenCHS\Army4_Original\audio\vos"
OUTDIR = r"G:\Projects\ArmyMenCHS\Army4_Voice_CHS\audio\vos"
ARCHIVE = r"G:\Projects\ArmyMenCHS\Army4_Voice_CHS\source\dub_params_archive.json"
PROGRESS = r"G:\Projects\ArmyMenCHS\Army4_Voice_CHS\source\_progress_am4.txt"
BAKDIR = r"G:\Projects\ArmyMenCHS\_trash"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# 时长封顶系数：正常台词远低于上限（靠 EOS 结束），仅拟声词等异常循环被截断
CAP_FACTOR = 2.0
CAP_PAD = 0.5

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
    shutil.copy2(TRANS, os.path.join(BAKDIR, "vos_translations_pre_batch_am4.json"))
    fixed = 0
    for wav, zh in TEXT_FIXES.items():
        if wav in data and data[wav].get("value_ch") != zh:
            data[wav]["value_ch"] = zh
            data[wav]["note"] = "TTS 友好改写（拟声/读音）"
            fixed += 1
    if fixed:
        json.dump(data, open(TRANS, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print(f"已应用 {fixed} 处文本修正并写回 JSON")

    fmt = build_fmt()
    fmt_dur = {c["wav"]: c["duration_s"] for c in
               json.load(open(os.path.join(os.path.dirname(TRANS), "vos_en_raw_clean.json"),
                              encoding="utf-8"))}

    # ---- 遍历 SRC：分流 TTS / 复制 ----
    tts_tasks = []
    copied = 0
    missing_trans = []
    src_files = sorted(f for f in os.listdir(SRC) if f.lower().endswith(".wav"))
    for fname in src_files:
        ent = data.get(fname)
        if ent and (ent.get("value_ch") or "").strip():
            spk = ent.get("speaker", "UnknownVoice")
            text = ent["value_ch"].strip()
            src_dur = fmt_dur.get(fname, 3.0)
            cap_tokens = int((src_dur * CAP_FACTOR + CAP_PAD) * 12)
            tts_tasks.append((fname, text, spk,
                              vc.build_instruct(spk, text), vc.get_seed(spk),
                              cap_tokens, src_dur))
        else:
            # sfx 或未翻译：原样复制英文基线
            shutil.copy2(os.path.join(SRC, fname), os.path.join(OUTDIR, fname))
            copied += 1
            if fname not in data:
                missing_trans.append(fname)

    if missing_trans:
        print(f"[WARN] {len(missing_trans)} 个 SRC wav 不在翻译表（已复制原英文）:")
        for m in missing_trans[:20]:
            print("   ", m)

    print(f"TTS 任务 {len(tts_tasks)} 条；原样复制（sfx/遗漏）{copied} 条")

    # ---- 动态决定 worker 数 ----
    free = avail_gb()
    nw = max(1, min(4, int((free - 4.0) // 4.5)))
    os.environ["NWORK"] = str(nw)
    print(f"可用内存 {free:.1f} GB -> 启用 {nw} 个 worker")

    open(PROGRESS, "w", encoding="utf-8").close()

    # ---- 分片 ----
    chunks = [[] for _ in range(nw)]
    for i, t in enumerate(tts_tasks):
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
            "task": "Army Men 4 (World War) 中文配音",
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
            "tts_total": len(tts_tasks),
            "copied_total": copied,
            "success": ok,
            "failed": fail,
            "cap_factor": CAP_FACTOR,
            "cap_pad": CAP_PAD,
            "seed_note": "API 的 seed= 参数实测无效；必须用 torch.manual_seed()。"
                         "每角色固定 seed 以保证音色一致。",
            "format_note": "输出对齐游戏原始 WAV（16bit/11025Hz 或 8bit/22050Hz，单声道）。",
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
    print(f"完成: TTS 成功 {ok} / 失败 {fail} / 共 {len(tts_tasks)}；复制 {copied}")
    print(f"耗时: {time.time()-t0:.0f}s")
    print(f"输出: {OUTDIR}")
    print(f"存档: {ARCHIVE}")


if __name__ == "__main__":
    main()
