# -*- coding: utf-8 -*-
"""Army5 (Air Tactics / 空中战术) 角色音色档案 —— Qwen3-TTS VoiceDesign
角色来源：Army5_Original/data/*/COM.txt 的 `说话人|wav|台词` 三列表。
说话人枚举：Sam / Sarge / Captain / Grimm / Plastro / Blue Spy / Grey Spy
其余 Tro*（士兵群戏）、Death*（惨叫）、bullet*（弹丸撞击，非人声）、null 需按内容定。
"""
GLOBAL_SEED = 19970823

VOICE_CAST = {
    # 无线电萨姆：全程无线电引导，冷静专业
    "Sam": {
        "desc": "成年男性无线电报务员，嗓音沉稳清晰，标准的电台播报腔，专业冷静",
        "note": "玩家的无线电引导员",
    },
    # 中士 Sarge：霍克中士，老练军官
    "Sarge": {
        "desc": "中年男性军官，嗓音低沉沙哑，粗犷有力，音量足。威严果断",
        "note": "用户已认可（沿用 4 代）",
    },
    # 布莱德上尉：本作主角，直升机飞行员
    "Captain": {
        "desc": "青年男性直升机飞行员，音色明亮有力，干脆利落，带军人式的爽朗",
        "note": "主角 Blade（布莱德上尉）",
    },
    # 格里姆上校
    "Grimm": {
        "desc": "中年男性高级军官，嗓音浑厚低沉，语调从容老练，带指挥官的威压",
        "note": "绿军上校",
    },
    # 普拉斯特将军：大反派
    "Plastro": {
        "desc": "男性反派首领，嗓音阴冷油滑，拖长腔调，透着傲慢与威胁",
        "note": "棕军将军（4 代称 TanArmy，本作语义为反派首领）",
    },
    # 蓝军间谍
    "BlueSpy": {
        "desc": "成年男性间谍，压低嗓音说话，语气戒备，略带奸诈",
        "note": "蓝军间谍",
    },
    # 灰军间谍
    "GreySpy": {
        "desc": "成年男性间谍，嗓音沙哑低沉，鬼祟小心的耳语感",
        "note": "灰军间谍",
    },
    # 普通绿军士兵（Tro* 群戏）
    "GreenTrooper": {
        "desc": "年轻男性小兵，音色偏亮偏薄，带点青涩紧张，语速偏快",
        "note": "沿用 4 代 GreenArmy_Grunt",
    },
    # 惨叫 / 死亡（Death*、部分 Tro*）
    "Screamer": {
        "desc": "成年男性士兵，嗓音粗实，情绪激烈的呼喊",
        "note": "惨叫/受击类",
    },
    "UnknownVoice": {
        "desc": "成年男性，平淡自然的生活化语气，放松随意",
        "note": "杂项",
    },
}

# 情绪规则：顺序敏感，具体优先
EMOTION_RULES = [
    (("啊啊啊", "啊啊啊啊"), "发出惊恐的尖叫。"),
    (("哎哟", "呃啊", "痛"), "短促地闷哼一声，自然不夸张。"),
    (("救命", "救我", "救救", "害怕", "怪物", "天哪"), "极度惊恐地呼喊。"),
    (("冲锋", "进攻", "冲啊", "攻击", "开火", "干掉", "杀啊", "给我上", "冲上去"), "情绪高昂，用力喊出，声音清晰有力。"),
    (("哈哈", "笑"), "爽朗地大笑。"),
    (("阵亡", "牺牲", "可怜", "完了", "不幸", "死"), "语气沉重低落，语速放慢。"),
]


def build_instruct(speaker, text):
    base = VOICE_CAST.get(speaker, VOICE_CAST["UnknownVoice"])["desc"]
    extra = ""
    for keys, emo in EMOTION_RULES:
        if any(k in text for k in keys):
            extra = emo
            break
    return f"{base}。{extra}" if extra else f"{base}。"


def get_seed(speaker=None):
    return GLOBAL_SEED
