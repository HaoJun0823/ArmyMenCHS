# -*- coding: utf-8 -*-
"""
扫描全部译文，找出 TTS 不友好的模式：
1. 重复单字喊叫（冲，冲，冲 / 啊啊啊 / 不——）——模型缺音素上下文，易吞音或机械重复
2. 纯拟声/无实义（嗬！/ 呃…… / 啵嗒！）
3. 省略号过长、破折号拖音
"""
import json
import re

P = r"G:\Projects\ArmyMenCHS\Army3_Original\audio\vos\vos_translations.json"
d = json.load(open(P, encoding="utf-8"))

def is_char_repeat(s):
    """检测 2 字以内小单元的重复，如 冲，冲，冲 / 啊啊啊 / 不——"""
    core = re.sub(r"[，,！!。.、~\s—\-]+", "", s)
    if len(core) == 0:
        return False
    # 整个串由 <=2 种字符构成，且总长>=2
    if len(set(core)) <= 2 and len(core) >= 2:
        return True
    return False

buckets = {"重复单字": [], "纯语气拟声": [], "超长重复串": []}

for f, v in d.items():
    zh = (v.get("value_ch") or "").strip()
    en = (v.get("value_en") or "").strip()
    spk = v.get("speaker", "?")
    if not zh:
        continue

    core = re.sub(r"[，,！!。.、~—\-\s]+", "", zh)

    if len(core) >= 2 and len(set(core)) <= 2:
        buckets["重复单字"].append((f, spk, en, zh))
    elif len(core) == 1 and zh.strip("，,！!。.、~— "):
        buckets["纯语气拟声"].append((f, spk, en, zh))
    elif len(core) >= 6 and len(set(core)) <= 3:
        buckets["超长重复串"].append((f, spk, en, zh))

for k, items in buckets.items():
    print(f"\n{'='*70}\n### {k}  ({len(items)} 条)\n{'='*70}")
    for f, spk, en, zh in items:
        print(f"[{spk}] {f}")
        print(f"   EN: {en}")
        print(f"   ZH: {zh}")

print(f"\n\n总计需处理: {sum(len(v) for v in buckets.values())} 条 / {len(d)} 条")
