# -*- coding: utf-8 -*-
"""为 6 段生成带英文+角色提示的待译清单（供并行子代理纯文本翻译）。"""
import json, os

CLEAN = r"G:\Projects\ArmyMenCHS\Army4_Voice_CHS\source\vos_en_raw_clean.json"
PARTDIR = r"G:\Projects\ArmyMenCHS\Army4_Voice_CHS\source\_parts"
SRC = json.load(open(CLEAN, encoding="utf-8"))
by_wav = {r["wav"]: r for r in SRC}

# 角色提示规则（与 3 代 cast + 文件名线索一致）
def hint(w):
    wl = w.lower()
    if any(k in wl for k in ["hq", "cmd", "gamehq"]): return "HQ_Command(总部/指挥官)"
    if "civilian" in wl: return "Civilian(平民; *_Ann_*=Civilian_Ann, *_Tanya_*=Civilian_Tanya)"
    if "guard" in wl: return "Guard(守卫)"
    if "mp_" in wl or wl.startswith("mp"): return "Multiplayer(多人模式)"
    if any(k in wl for k in ["green", "lgreenman"]): return "GreenArmy_Grunt(绿军)"
    if any(k in wl for k in ["tan", "tantroop"]): return "TanArmy(棕军)"
    if any(k in wl for k in ["hardplastic", "boatpilot", "ptboat"]): return "SpaceHQ(盟友单位/太空总部)"
    if "sarge" in wl: return "Sarge(中士)"
    return "按文本语境判断: Sarge/GreenArmy_Grunt/Civilian/UnknownVoice"

for i in range(1, 7):
    p = os.path.join(PARTDIR, f"part_{i}.txt")
    names = [l.strip() for l in open(p, encoding="utf-8") if l.strip()]
    out = []
    for w in names:
        r = by_wav.get(w, {})
        en = r.get("asr_en", "").strip()
        out.append(f"{w}\t{hint(w)}\t{en}")
    with open(os.path.join(PARTDIR, f"part_{i}_en.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print(f"part_{i}_en.txt: {len(out)} 行")
