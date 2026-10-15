# -*- coding: utf-8 -*-
"""经本地代理直连 HuggingFace 下载权重（禁用 xet，走普通 HTTP）"""
import os

os.environ["HTTP_PROXY"] = "http://127.0.0.1:7890"
os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7890"
os.environ.pop("HF_ENDPOINT", None)      # 用官方源
os.environ["HF_HUB_DISABLE_XET"] = "1"   # 关键：禁用 xet，走普通下载

from huggingface_hub import snapshot_download

REPO = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
LOCAL = r"G:\Projects\ArmyMenCHS\models\Qwen3-TTS-12Hz-1.7B-VoiceDesign"

print("repo    :", REPO)
print("local   :", LOCAL)
print("proxy   :", os.environ.get("HTTPS_PROXY"))
print("endpoint:", os.environ.get("HF_ENDPOINT", "(official)"))

path = snapshot_download(repo_id=REPO, local_dir=LOCAL, max_workers=4)
print("[ok] downloaded to:", path)

total = 0
for root, dirs, files in os.walk(LOCAL):
    for f in files:
        total += os.path.getsize(os.path.join(root, f))
print(f"total size: {total/1024**3:.2f} GB")
