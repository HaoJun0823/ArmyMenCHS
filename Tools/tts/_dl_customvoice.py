# -*- coding: utf-8 -*-
"""下载 Qwen3-TTS CustomVoice 模型（9 个内置固定音色 + instruct 情绪控制）"""
import os
import sys

PROXY = "http://127.0.0.1:7890"
os.environ["HTTP_PROXY"] = PROXY
os.environ["HTTPS_PROXY"] = PROXY
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "60"
os.environ.pop("HF_ENDPOINT", None)

from huggingface_hub import snapshot_download

REPO = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
LOCAL = r"G:\Projects\ArmyMenCHS\models\Qwen3-TTS-12Hz-1.7B-CustomVoice"

print("downloading", REPO, flush=True)
for attempt in range(1, 5):
    try:
        p = snapshot_download(repo_id=REPO, local_dir=LOCAL, max_workers=3)
        print("[ok]", p, flush=True)
        break
    except Exception as e:
        print(f"attempt {attempt}: {type(e).__name__}: {str(e)[:150]}", flush=True)
        if attempt == 4:
            sys.exit(1)

tot = sum(os.path.getsize(os.path.join(r, f))
          for r, _, fs in os.walk(LOCAL) for f in fs)
print(f"total {tot/1024**3:.2f} GB", flush=True)
