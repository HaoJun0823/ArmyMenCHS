# -*- coding: utf-8 -*-
"""
配音方案 v5（已验证）—— 单参考音克隆 + 逐句 instruct 注入
============================================================
【方案对比实测】
  方案                                     音色一致度    情绪
  VoiceDesign 直出                          0.9565      ✅
  多情绪参考音 -> 克隆                        0.8159      ✅   ✗ 音色漂移
  单参考音克隆 + instruct 注入（本方案）       0.9911      ✅   ★ 最优

  * Sarge 全情绪谱（中性/命令/愤怒/悲痛）= 0.9765
  * 例外：极端惨叫（啊啊啊——）会漂移到 0.75

【实现要点】
  qwen_tts 高层 generate_voice_clone() 未暴露 instruct 参数；
  但底层 Qwen3TTSForConditionalGeneration.generate() 同时接受
  instruct_ids 与 voice_clone_prompt（modeling_qwen3_tts.py:2022-2080）。
  -> 绕过高层，直接调底层，实现「音色锁定 + 情绪可控」。

【惨叫的处理】
  惨叫类台词改用 VoiceDesign 直出（有情绪），或接受轻微音色漂移。
  这类台词数量少且本身是极端发声，音色差异影响较小。
"""
import json
import os

BASE_DIR = r"G:\Projects\ArmyMenCHS\Army3_Voice_CHS\base"
SOURCE = r"G:\Projects\ArmyMenCHS\Army3_Voice_CHS\source"

GLOBAL_SEED = 19970823          # 用户生日
BASE_MODEL = r"G:\Projects\ArmyMenCHS\models\Qwen3-TTS-12Hz-1.7B-Base"
VD_MODEL = r"G:\Projects\ArmyMenCHS\models\Qwen3-TTS-12Hz-1.7B-VoiceDesign"

# ============ 情绪规则（用于生成 instruct 文本）============
# 顺序重要：具体情绪优先
EMOTION_RULES = [
    # 惨叫：走 VoiceDesign 直出（见下方 EXCEPTIONS）
    (("啊啊啊", "啊啊啊啊"),
     "发出长长的凄厉惨叫。", "vd"),
    # 痛呼
    (("哎哟", "呃啊", "唔", "痛"),
     "短促地闷哼一声，自然不夸张。", "clone"),
    # 惊恐呼喊
    (("救命", "救我", "救救", "害怕", "怪物", "天哪"),
     "极度惊恐，声音高亢急促地呼喊。", "clone"),
    # 战斗号令
    (("冲锋", "进攻", "冲啊", "攻击", "开火", "干掉", "杀啊", "上膛", "准备战斗"),
     "威严果断，用命令语气下达指令，音量提高。", "clone"),
    # 愤怒
    (("该死", "混蛋", "教训", "嚣张", "报仇"),
     "极度愤怒，粗声吼叫。", "clone"),
    # 大笑
    (("哈哈", "笑"),
     "爽朗地大笑。", "clone"),
    # 悲痛
    (("阵亡", "牺牲", "可怜", "完了", "不幸", "死"),
     "低沉悲痛，语速缓慢。", "clone"),
    # 播报（HQ/SpaceHQ/Multiplayer 专用语气）
    (("总部", "完毕", "报告", "坐标", "扫描"),
     "冷静克制的无线电播报腔。", "clone"),
    # 紧迫
    (("快", "马上", "立刻", "赶紧", "来不及"),
     "语气急迫，语速偏快。", "clone"),
]


def match_rule(text: str):
    """返回 (instruct后缀, 生成方式)"""
    for keys, emo, mode in EMOTION_RULES:
        if any(k in text for k in keys):
            return emo, mode
    return "", "clone"


def build_instruct(text: str) -> str:
    emo, _ = match_rule(text)
    return emo


def gen_mode(text: str) -> str:
    _, mode = match_rule(text)
    return mode


if __name__ == "__main__":
    data = json.load(open(os.path.join(SOURCE, "vos_translations.json"), encoding="utf-8"))
    import collections
    mode_cnt = collections.Counter()
    emo_cnt = collections.Counter()
    for f, v in data.items():
        zh = v.get("value_ch", "")
        emo, mode = match_rule(zh)
        mode_cnt[mode] += 1
        emo_cnt[emo or "(中性)"] += 1
    print(f"共 {len(data)} 条")
    print("\n生成方式分布:")
    for k, n in mode_cnt.most_common():
        print(f"  {k:<8} {n}")
    print("\n情绪分布:")
    for k, n in emo_cnt.most_common():
        print(f"  {k[:28]:<30} {n}")
