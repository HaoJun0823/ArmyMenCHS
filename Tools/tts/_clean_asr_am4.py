# -*- coding: utf-8 -*-
"""清理 Army4 ASR 结果：去重（mp_endgame 的 gbk 失败重复 error 条），
导出 250 条语音清单并按原始顺序切 6 段，供并行翻译。
"""
import json
import os

SRC = r"G:\Projects\ArmyMenCHS\Army4_Voice_CHS\source\vos_en_raw.json"
OUT = r"G:\Projects\ArmyMenCHS\Army4_Voice_CHS\source\vos_en_raw_clean.json"
PARTDIR = r"G:\Projects\ArmyMenCHS\Army4_Voice_CHS\source\_parts"

raw = json.load(open(SRC, encoding="utf-8"))

# 去重：同一 wav 保留有 asr_en 的；error 条丢弃
best = {}
for r in raw:
    w = r.get("wav")
    if not w:
        continue
    if "error" in r and "asr_en" not in r:
        continue  # 纯 error 重复条
    if w not in best or ("asr_en" in r and "asr_en" not in best.get(w, {})):
        best[w] = r

clean = list(best.values())
print(f"去重后 {len(clean)} 条（应=298）")

# 按 wav 原始文件名排序（与游戏加载无关，仅便于分片阅读）
voice = [r for r in clean if r.get("candidate") == "voice"]
sfx = [r for r in clean if r.get("candidate") == "sfx"]
print(f"voice={len(voice)} sfx={len(sfx)}")

json.dump(clean, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

# 切 6 段（按 voice 在 clean 中的顺序）
os.makedirs(PARTDIR, exist_ok=True)
n = 6
chunk = (len(voice) + n - 1) // n
for i in range(n):
    seg = voice[i * chunk:(i + 1) * chunk]
    with open(os.path.join(PARTDIR, f"part_{i+1}.txt"), "w", encoding="utf-8") as f:
        for r in seg:
            f.write(r["wav"] + "\n")
    print(f"part_{i+1}.txt: {len(seg)} 条")
