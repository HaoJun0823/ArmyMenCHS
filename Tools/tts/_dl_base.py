# -*- coding: utf-8 -*-
"""下载 Qwen3-TTS Base 模型（用于 voice clone 复用音色）"""
import os
import sys

PROXY = "http://127.0.0.1:7890"
os.environ["HTTP_PROXY"] = PROXY
os.environ["HTTPS_PROXY"] = PROXY
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ.pop("HF_ENDPOINT", None)
os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "60"

import requests
from huggingface_hub import snapshot_download

# 先测代理连通
try:
    r = requests.get("https://huggingface.co/api/models/Qwen/Qwen3-TTS-12Hz-1.7B-Base",
                     proxies={"http": PROXY, "https": PROXY}, timeout=30)
    print("proxy test:", r.status_code, flush=True)
except Exception as e:
    print("proxy test FAILED:", type(e).__name__, e, flush=True)
    sys.exit(1)

REPO = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
LOCAL = r"G:\Projects\ArmyMenCHS\models\Qwen3-TTS-12Hz-1.7B-Base"
print("downloading", REPO, flush=True)

for attempt in range(1, 5):
    try:
        p = snapshot_download(repo_id=REPO, local_dir=LOCAL, max_workers=3)
        print("[ok]", p, flush=True)
        break
    except Exception as e:
        print(f"attempt {attempt} failed: {type(e).__name__}: {str(e)[:200]}", flush=True)
        if attempt == 4:
            sys.exit(1)

tot = sum(os.path.getsize(os.path.join(r, f))
          for r, _, fs in os.walk(LOCAL) for f in fs)
print(f"total {tot/1024**3:.2f} GB", flush=True)
