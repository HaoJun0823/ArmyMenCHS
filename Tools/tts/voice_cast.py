# -*- coding: utf-8 -*-
"""
角色音色档案 v5 (Voice Cast) —— Qwen3-TTS VoiceDesign
=====================================================
v5 修订依据（用户第 4 轮反馈 + 实测诊断）：
  1. 拟声类"诡异"的元凶是【生成失控】：Civilians_aahhh1 生成 15.84s
     （源 1.22s、文本仅 4 字）-> 13 倍失控。修复在批量脚本里加时长上限。
  2. 纯拟声会让模型忽略音色描述（Tanya 设定低沉却出 649Hz 尖啸）
     -> 惨叫指令去掉推动音高的"声音高亢"，改为温和表述
  3. M80s 读音问题 -> ASR 实测「艾姆八零」可被正确识别为 M80
  4. GreenUnits_ahieee3「嗬啊！」诡异 -> 换用常见字的自然发声词
  5. Aah4「唔……」被误判为痛呼（唔 是"思考/应声"，非疼痛）-> 移出痛呼规则

★ 关于指标 ★
  实测发现 MFCC / 说话人编码器 / yin 基频 在 11025Hz 低质音频上均不可靠
  （编码器称 HQ 最一致 0.9796，但用户听觉判断相反）。故不再以指标做判据，
  一律以用户试听为准。
"""

GLOBAL_SEED = 19970823   # 用户生日，便于复现


VOICE_CAST = {
    "Sarge": {
        "desc": "中年男性军官，嗓音低沉沙哑，粗犷有力，音量足。威严果断",
        "note": "用户已认可",
    },
    "GreenArmy_Grunt": {
        "desc": "年轻男性小兵，音色偏亮偏薄，带点青涩紧张，语速偏快",
        "note": "Sarge 下属",
    },
    "TanArmy": {
        "desc": "男性敌兵，嗓音粗野油滑，带嘲讽嚣张的痞气，语速偏慢",
        "note": "黄军反派",
    },
    "HQ_Command": {
        "desc": "男性总部指挥官，中年，嗓音沉稳清晰，字正腔圆的无线电播报腔",
        "note": "总部（男）",
    },
    "SpaceHQ": {
        "desc": "女性总部通讯官，音色清亮冷静，专业干练的无线电播报腔",
        "note": "太空总部（女声）",
    },
    "Tina": {
        "desc": "年轻女性战士，音色清脆利落，中气足，果敢干练",
        "note": "女英雄",
    },
    "Civilian_Ann": {
        "desc": "年轻女性平民，嗓音柔细偏高，声音清亮干净",
        "note": "女性平民 Ann",
    },
    "Civilian_Tanya": {
        "desc": "女性平民，嗓音偏低沉沙哑",
        "note": "女性平民 Tanya",
    },
    "Civilian": {
        "desc": "成年男性平民，普通男声，音色偏粗实",
        "note": "男性",
    },
    "Guard": {
        "desc": "男性哨兵，嗓音粗短有力，警觉凶狠",
        "note": "守卫",
    },
    "UnknownVoice": {
        "desc": "成年男性，平淡自然的生活化语气，放松随意",
        "note": "杂项",
    },
    "Multiplayer": {
        "desc": "成年男性播报员，音色清晰中性有力，播报式干脆利落",
        "note": "多人模式旗帜播报",
    },
}

# ============ 情绪规则 v5 ============
# 顺序重要：具体优先于泛化
EMOTION_RULES = [
    # 惨叫：去掉"声音高亢"（会把纯拟声推向尖啸音区）
    (("啊啊啊", "啊啊啊啊"),
     "发出惊恐的尖叫。"),
    # 痛呼：移出"唔"（唔 是应声/思考，非疼痛）
    (("哎哟", "呃啊", "痛"),
     "短促地闷哼一声，自然不夸张。"),
    # 惊恐呼喊
    (("救命", "救我", "救救", "害怕", "怪物", "天哪"),
     "极度惊恐地呼喊。"),
    # 战斗号令
    (("冲锋", "进攻", "冲啊", "攻击", "开火", "干掉", "杀啊", "给我上", "冲上去"),
     "情绪高昂，用力喊出，声音清晰有力。"),
    # 大笑
    (("哈哈", "笑"),
     "爽朗地大笑。"),
    # 悲伤
    (("阵亡", "牺牲", "可怜", "完了", "不幸", "死"),
     "语气沉重低落，语速放慢。"),
]


def build_instruct(speaker: str, text: str) -> str:
    base = VOICE_CAST.get(speaker, VOICE_CAST["UnknownVoice"])["desc"]
    extra = ""
    for keys, emo in EMOTION_RULES:
        if any(k in text for k in keys):
            extra = emo
            break
    return f"{base}。{extra}" if extra else f"{base}。"


def get_seed(speaker: str = None) -> int:
    return GLOBAL_SEED


# ============ 拟声修正 ============
ONOMATOPOEIA_FIXES = {
    # 惨叫：保留长形态
    "Civilians_Ann_Civilian_Ahhhhhh3.wav":   "啊啊啊啊——！",
    "Civilians_Tanya_Civilian_Ahhhhhh3.wav": "啊啊啊——！",
    # Aah*：用户认可的回退版
    "Aah2.wav": "呃！",
    "Aah3.wav": "哦！",
    # 补足音节，避免单字长度失控
    "GreenUnits_arrrgh2.wav": "呃啊！",
    "GreenUnits_arrrgh3.wav": "呃啊！",
    # v5: 「嗬啊！」诡异 -> 换常见字的自然发声
    "GreenUnits_ahieee3.wav": "嘿哟！",
    "TanUnits_Fire1.wav":     "哇哦！",
}

# ============ 其他文本修正 ============
TEXT_FIXES = {
    "Civilians_helpMe1.wav": "快救救我们！",
    "TanUnits_ready4.wav":   "来吧！",
    # v5: M80s 读音修正（ASR 实测「艾姆八零」= M80 可识别）
    "M80s.wav": "艾姆八零！",
}
