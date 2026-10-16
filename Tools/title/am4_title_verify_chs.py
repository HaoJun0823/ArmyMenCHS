# -*- coding: utf-8 -*-
"""AM4 title 覆盖层校验：尺寸 / 编码 / 调色板 / 覆盖集合 / 回包往返。

四条硬闸（任一不过即失败退出）：
  1. 尺寸逐一对上 manifest 的 width/height（否则回包触发 graphicSize 长度闸）
  2. 覆盖对象全是未压缩 BMP（压缩族重编码会写出坏数据）
  3. 覆盖层颜色 100% 精确命中 4 代 palette.bin（否则回包最近色吸附出噪点）
  4. 回包产物与原始 title.dat 的差异**只**落在覆盖对象内；目录表与调色板未变

用法：
    python Tools/title/am4_verify_chs.py
    python Tools/title/am4_verify_chs.py --no-repack    # 跳过回包（只查前 3 条）
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image

R = r"G:\Projects\ArmyMenCHS"
TITLE = os.path.join(R, "Army4_Object_CHS", "title")
CHS = os.path.join(TITLE, "png_control_chs")
EN = os.path.join(TITLE, "png_control_en")
A3 = os.path.join(TITLE, "png_control_army_3")
GAME = r"I:\LocalGames\Army Men\Army Men - World War GOG"
RT = r"I:\LocalGames\Army Men\_am4_title_work\roundtrip"

sys.path.insert(0, os.path.join(R, "Tools"))
import am3_dat as M  # noqa: E402

# 对象 blob 头长度：28 字节（key,w,h,flags / hotspot / linkspot / graphicSize）
HEADER_SIZE = 28

ok = True


def chk(cond, msg):
    global ok
    if not cond:
        ok = False
    print("  [%s] %s" % ("OK " if cond else "BAD", msg))


def key_of(name):
    return name.split("_k")[1].replace(".png", "").upper()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-repack", action="store_true")
    args = ap.parse_args()

    man = json.load(open(os.path.join(TITLE, "manifest.json"), encoding="utf-8"))
    by_key = {o["key_hex"][2:].upper().zfill(8): o for o in man["objects"]}
    by_idx = {o["index"]: o for o in man["objects"]}

    files = sorted(f for f in os.listdir(CHS) if f.endswith(".png"))
    en_files = sorted(f for f in os.listdir(EN) if f.endswith(".png"))

    # ---------- 1. 覆盖集合 ----------
    print("=" * 76)
    print("[1] 覆盖集合")
    print("=" * 76)
    chk(len(files) >= len(en_files),
        "覆盖层 %d 个 >= en 名单 %d 个" % (len(files), len(en_files)))
    missing = sorted(set(en_files) - set(files))
    chk(not missing, "en 名单全部被覆盖（缺 %d 个）%s"
        % (len(missing), missing[:5]))
    extra = sorted(set(files) - set(en_files))
    print("     补收（en 名单之外）：%s" % (extra if extra else "无"))

    # ---------- 2. 尺寸 + 编码 ----------
    print()
    print("=" * 76)
    print("[2] 尺寸与编码")
    print("=" * 76)
    bad_dim, bad_kind = [], []
    for f in files:
        o = by_key.get(key_of(f))
        if o is None:
            bad_dim.append((f, "manifest 中不存在该 key"))
            continue
        if Image.open(os.path.join(CHS, f)).size != (o["width"], o["height"]):
            bad_dim.append((f, Image.open(os.path.join(CHS, f)).size,
                            (o["width"], o["height"])))
        if o["kind"] != "BMP":
            bad_kind.append((f, o["kind"]))
    chk(not bad_dim, "尺寸逐一对上 manifest（不符 %d 个）%s"
        % (len(bad_dim), bad_dim[:4]))
    chk(not bad_kind, "全部为未压缩 BMP（非 BMP %d 个）%s"
        % (len(bad_kind), bad_kind[:4]))

    # ---------- 3. 调色板纯度 ----------
    print()
    print("=" * 76)
    print("[3] 调色板纯度")
    print("=" * 76)
    raw = open(os.path.join(TITLE, "palette.bin"), "rb").read()
    pal = np.array([(raw[i * 4 + 2], raw[i * 4 + 1], raw[i * 4])
                    for i in range(256)], dtype=np.int32)
    palset = set(map(tuple, pal.tolist()))
    notin, worst = 0, 0
    for f in files:
        a = np.asarray(Image.open(os.path.join(CHS, f)).convert("RGB"))
        for c in np.unique(a.reshape(-1, 3), axis=0):
            t = tuple(int(v) for v in c)
            if t in palset:
                continue
            notin += 1
            worst = max(worst, int(np.abs(pal - c.astype(np.int32)).sum(axis=1).min()))
    chk(notin == 0, "全部精确命中 4 代调色板（未命中 %d 个色，最大色差 %d）"
        % (notin, worst))

    # ---------- 4. 复用件的来源核验 ----------
    print()
    print("=" * 76)
    print("[4] 复用件的来源核验（按 key 映射到 3 代成品，须逐字节相同）")
    print("=" * 76)
    a3m = {key_of(f): f for f in os.listdir(A3) if f.endswith(".png")}
    import hashlib

    def sha(p):
        return hashlib.sha256(open(p, "rb").read()).hexdigest()

    rep = os.path.join(CHS, "_report.json")
    reuse, rebuild = [], []
    if os.path.isfile(rep):
        r = json.load(open(rep, encoding="utf-8"))
        reuse = [it["file"] for it in r["items"] if it["mode"] == "reuse-a3"]
        rebuild = [it["file"] for it in r["items"] if it["mode"] == "rebuild-a4"]
    mism = []
    for f in reuse:
        k = key_of(f)
        if k not in a3m or sha(os.path.join(CHS, f)) != sha(os.path.join(A3, a3m[k])):
            mism.append(f)
    chk(not mism, "复用件与 3 代成品逐字节相同（不符 %d 个）%s"
        % (len(mism), mism[:4]))
    print("     复用 %d 个 / 重建 %d 个" % (len(reuse), len(rebuild)))

    # ---------- 5. 回包往返 ----------
    if args.no_repack:
        print()
        print("（--no-repack：跳过回包往返校验）")
        print()
        print("=" * 76)
        print("结论：%s" % ("全部通过" if ok else "存在失败项"))
        return 0 if ok else 1

    print()
    print("=" * 76)
    print("[5] 回包往返（title.dat）")
    print("=" * 76)
    os.makedirs(RT, exist_ok=True)
    out_dat = os.path.join(RT, "title.dat")
    cmd = [sys.executable, os.path.join(R, "Tools", "am3_dat_pack.py"),
           TITLE, out_dat, "--overlay", CHS]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if p.returncode != 0:
        print(p.stdout[-3000:])
        print(p.stderr[-2000:])
        chk(False, "回包命令失败（exit %d）" % p.returncode)
        print()
        print("结论：存在失败项")
        return 1

    orig = open(os.path.join(GAME, "title.dat"), "rb").read()
    new = open(out_dat, "rb").read()
    chk(len(orig) == len(new), "产物与原版等长：%d == %d" % (len(orig), len(new)))

    fid, palette, entries = M.parse_container(orig)
    bounds = M.object_bounds(orig, entries)
    ov_idx = set(int(f.split("_")[1]) for f in files)
    diff_objs, diff_bytes = set(), 0
    for i in range(len(entries)):
        s, e = bounds[i]
        if orig[s:e] != new[s:e]:
            diff_objs.add(i)
            diff_bytes += sum(1 for a, b in zip(orig[s:e], new[s:e]) if a != b)
    # ★ 排除"覆盖层之外就已存在的差异"：本仓库 title/png/ 里
    #   obj_0000_k00080000.png（标题画 640x480）是上一轮人工汉化的产物，
    #   它在 title.dat 里的对应对象与出厂版本就不同，与本覆盖层无关。
    preexisting = set(diff_objs) - ov_idx
    unexpected = ov_idx - diff_objs - preexisting
    chk(not unexpected,
        "覆盖对象全部被改写（未生效 %d 个）%s" % (len(unexpected),
                                              sorted(unexpected)[:6]))
    chk(preexisting <= {0},
        "差异只多出预期的既有改动（额外 %s）" % sorted(preexisting))
    print("     差异对象 %d 个 = 覆盖 %d 个 + 既有改动 %s"
          % (len(diff_objs), len(ov_idx), sorted(preexisting)))
    chk(diff_bytes > 0, "确实有像素被改写（%d 字节）" % diff_bytes)
    chk(orig[:1028] == new[:1028], "调色板 + FILEID 区域未变")
    n = len(entries)
    chk(orig[M.HEADER_TABLE_OFF:M.HEADER_TABLE_OFF + n * M.ENTRY_SIZE] ==
        new[M.HEADER_TABLE_OFF:M.HEADER_TABLE_OFF + n * M.ENTRY_SIZE],
        "目录表（key/offset）未变")

    # 逐对象回读：覆盖对象的像素必须与 CHS 覆盖层一致
    print()
    print("  逐对象回读比对（覆盖对象解码后须与覆盖层 PNG 逐像素一致）")
    bad_rt = []
    for f in files:
        o = by_key[key_of(f)]
        i = o["index"]
        s, e = bounds[i]
        idx = M.decode_bmp(new[s + HEADER_SIZE:s + HEADER_SIZE + o["graphicSize"]],
                           o["width"], o["height"],
                           M.palette_rgb(palette), Image)
        want = Image.open(os.path.join(CHS, f)).convert("RGB")
        if np.any(np.asarray(idx.convert("RGB")) != np.asarray(want)):
            bad_rt.append(f)
    chk(not bad_rt, "往返一致（不一致 %d 个）%s" % (len(bad_rt), bad_rt[:4]))

    print()
    print("=" * 76)
    print("结论：%s" % ("全部通过" if ok else "存在失败项"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
