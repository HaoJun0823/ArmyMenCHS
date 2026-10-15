# -*- coding: utf-8 -*-
"""
生成每个角色的【基础音色参考音】(voice reference)
=================================================
用途：作为 Base 模型克隆的音色基准，冻结音色，解决跨台词不一致问题。

依据实测：
  VoiceDesign 直出      MFCC 相似度 0.9565
  VoiceDesign + Clone   MFCC 相似度 0.9785  <- 采用

设计：
  - 每个角色读一段【指定的中文文本】（含足够音素覆盖，约 5-8 秒，
    官方建议参考音 3 秒以上，过短会克隆不稳）
  - 参考文本要能体现该角色的音色特征（用中性语气，不带极端情绪，
    因为参考音要复用到各种情绪场景）
  - 全局 seed = 19970823（用户生日，便于复现）

输出：<仓库>/Army3_Voice_CHS/base/<角色>.wav
      以及 voice_refs.json 记录每段参考音的文本/参数（可追溯）

★ 输出目录是 base/ 而不是 source/：base/ 存"音色基准音 + 参数记录"，
  source/ 存"ASR 原文 + 译文表"等中间数据。dub_plan.py 从 base/ 读取
  参考音（BASE_DIR），所以生成必须落在 base/，否则克隆取不到参考音。
"""
import json
import os
import sys
import time

import numpy as np
import torch
import soundfile as sf
from qwen_tts import Qwen3TTSModel

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VOICE_MODEL = r"G:\Projects\ArmyMenCHS\models\Qwen3-TTS-12Hz-1.7B-VoiceDesign"
# ★ 必须是 base\（dub_plan.py 的 BASE_DIR 从这里读参考音）
OUTDIR = r"G:\Projects\ArmyMenCHS\Army3_Voice_CHS\base"
REFS_JSON = os.path.join(OUTDIR, "voice_refs.json")
GLOBAL_SEED = 19970823
SR_OUT = 22050          # 与游戏 8bit 档一致，参考音用较高规格便于克隆

os.makedirs(OUTDIR, exist_ok=True)

# ============ 各角色参考音：音色描述 + 朗读文本 ============
# 文本设计原则：
#   - 中性平实的语句，覆盖常用音素
#   - 长度 5-9 秒
#   - 不含极端情绪（参考音要复用到所有场景）
#   - 让该角色的音色特征充分暴露（如 Sarge 的粗犷、Tina 的清脆）
CAST = {
    "Sarge": {
        "desc": "中年男性军官，嗓音低沉沙哑，粗犷有力，音量足。威严果断",
        "text": "士兵们，听好了。这里是战场，不是游乐场。"
                "我们今天的任务很简单，拿下那座基地，把敌人清干净。"
                "动作要快，队形别乱。跟上我。",
        "note": "主角，台词最多（71+条）",
    },
    "GreenArmy_Grunt": {
        "desc": "年轻男性小兵，音色偏亮偏薄，带点青涩紧张，语速偏快",
        "text": "长官，我我我……我准备好了。"
                "弹药检查过了，装备也带齐了。"
                "就是，那个，我们真的要现在冲进去吗？",
        "note": "Sarge 下属小兵",
    },
    "TanArmy": {
        "desc": "男性敌兵，嗓音粗野油滑，带嘲讽嚣张的痞气，语速偏慢",
        "text": "瞧瞧这是谁来了。绿皮小子，你们还真敢往这儿闯。"
                "行啊，那就别怪我不客气了。今天谁也别想活着出去。",
        "note": "黄军反派",
    },
    "HQ_Command": {
        "desc": "男性总部指挥官，中年，嗓音沉稳清晰，字正腔圆的无线电播报腔",
        "text": "中士，这里是总部。我们已经确认了目标区域的位置。"
                "你的任务是带领小队进入并控制关键节点。"
                "保持通讯畅通，有情况随时汇报。总部完毕。",
        "note": "总部（男声）",
    },
    "SpaceHQ": {
        "desc": "女性总部通讯官，音色清亮冷静，专业干练的无线电播报腔",
        "text": "指挥官，这里是太空总部。扫描显示目标区域出现异常能量波动。"
                "建议立即派遣小队前往侦察。我们会持续提供情报支援。总部完毕。",
        "note": "★ 太空总部（女声，用户明确要求）",
    },
    "Tina": {
        "desc": "年轻女性战士，音色清脆利落，中气足，果敢干练",
        "text": "我是蒂娜。别担心，我不是来添乱的。"
                "那些外星人封锁了通道，我需要有人帮我关掉力场发生器。"
                "掩护我，我们就能一起出去。",
        "note": "女英雄",
    },
    "Civilian_Ann": {
        "desc": "年轻女性平民，嗓音柔细偏高，声音清亮干净",
        "text": "求求你们，救救我们吧。那些东西到处都是，"
                "我们根本不知道该往哪儿跑。我真的好害怕。",
        "note": "女平民 Ann",
    },
    "Civilian_Tanya": {
        "desc": "女性平民，嗓音偏低沉沙哑",
        "text": "救命啊，谁来帮帮我们。它们把路全堵死了，"
                "我们被困在这儿出不去了。快想想办法吧。",
        "note": "女平民 Tanya",
    },
    "Civilian": {
        "desc": "成年男性平民，普通男声，音色偏粗实",
        "text": "哎，这到底是怎么回事啊。那些怪物是从哪儿冒出来的。"
                "我们就是普通老百姓，可不想掺和这种事。快跑吧。",
        "note": "★ 男性平民（用户修正）",
    },
    "Guard": {
        "desc": "男性哨兵，嗓音粗短有力，警觉凶狠",
        "text": "站住。什么人。这里是禁区，没有通行证不许靠近。"
                "再往前走一步，我就不客气了。",
        "note": "守卫",
    },
    "UnknownVoice": {
        "desc": "成年男性，平淡自然的生活化语气，放松随意",
        "text": "行吧，这样也行。反正事情都办完了，"
                "剩下的明天再说。今天就先到这儿吧。",
        "note": "杂项/通用",
    },
    "Multiplayer": {
        "desc": "成年男性播报员，音色清晰中性有力，播报式干脆利落",
        "text": "蓝旗已被夺取。红旗正在推进。"
                "比赛还剩两分钟，双方比分接近。请各位玩家继续努力。",
        "note": "多人模式旗帜播报",
    },
}

print("=" * 68)
print(f"生成基础音色参考音　共 {len(CAST)} 个角色")
print(f"模型: {os.path.basename(VOICE_MODEL)}")
print(f"seed: {GLOBAL_SEED}")
print("=" * 68)

t0 = time.time()
model = Qwen3TTSModel.from_pretrained(
    VOICE_MODEL, device_map="cpu", dtype=torch.bfloat16, attn_implementation="sdpa"
)
print(f"模型就绪 {time.time()-t0:.1f}s\n")

records = []
for i, (spk, cfg) in enumerate(CAST.items(), 1):
    out = os.path.join(OUTDIR, f"{spk}.wav")
    t = time.time()
    try:
        torch.manual_seed(GLOBAL_SEED)
        np.random.seed(GLOBAL_SEED)
        instruct = cfg["desc"] + "。语速自然平稳。"
        wavs, sr = model.generate_voice_design(
            text=cfg["text"], language="Chinese", instruct=instruct
        )
        w = wavs[0].astype(np.float32)
        peak = float(np.max(np.abs(w))) or 1.0
        if peak > 0.99:
            w = w / peak * 0.99
        sf.write(out, w, sr, subtype="PCM_16")

        dur = len(w) / sr
        rec = {
            "speaker": spk,
            "file": f"{spk}.wav",
            "ref_text": cfg["text"],
            "instruct": instruct,
            "seed": GLOBAL_SEED,
            "seed_method": "torch.manual_seed",
            "sample_rate": sr,
            "duration_s": round(dur, 2),
            "note": cfg.get("note", ""),
            "gen_seconds": round(time.time() - t, 1),
        }
        records.append(rec)
        print(f"[{i:2d}/{len(CAST)}] {spk:<18} {dur:5.2f}s  ({time.time()-t:4.1f}s)  -> {spk}.wav")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[{i:2d}/{len(CAST)}] {spk:<18} FAIL {e}")

meta = {
    "purpose": "角色基础音色参考音，供 Base 模型克隆复用，保证跨台词音色一致",
    "model": VOICE_MODEL,
    "model_repo": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
    "mode": "VoiceDesign",
    "device": "cpu",
    "dtype": "bfloat16",
    "global_seed": GLOBAL_SEED,
    "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    "total_seconds": round(time.time() - t0, 1),
    "reuse": "用 Base 模型 create_voice_clone_prompt(ref_audio=<file>, ref_text=<ref_text>) 复现音色",
    "items": records,
}
json.dump(meta, open(REFS_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

print(f"\n{'='*68}")
print(f"完成 {len(records)}/{len(CAST)}　耗时 {time.time()-t0:.0f}s")
print(f"输出: {OUTDIR}")
print(f"存档: {REFS_JSON}")
print("=" * 68)
