import json, os
root = r"G:\Projects\ArmyMenCHS"
base = os.listdir(os.path.join(root, "Army4_Original", "audio", "vos"))
base_set = {f.lower() for f in base}
trans = json.load(open(os.path.join(root, "Army4_Voice_CHS", "source",
                                    "vos_translations.json"), encoding="utf-8"))
voice_keys_lower = {k.lower() for k in trans
                    if trans[k].get("value_ch", "").strip()}
# baseline 中不在翻译表(有人声)里的 = 无人声音效
sfx = sorted(f for f in base if f.lower() not in voice_keys_lower)
print("baseline 总数:", len(base))
print("translation voice 键数:", len(voice_keys_lower))
print("sfx(无人声)数量:", len(sfx))
for f in sfx:
    print("  ", f)
# 反向校验：翻译表里的键是否都在 baseline（理论上应都在）
missing = sorted(k for k in trans if k.lower() not in base_set)
print("翻译表键但不在 baseline 里的(应为空):", missing)
