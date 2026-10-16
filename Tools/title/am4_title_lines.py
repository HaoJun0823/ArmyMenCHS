# -*- coding: utf-8 -*-
"""AM4 title 贴图文字行检测（只服务 5 个需重建的对象）。

与 3 代 `am3_title_lines.py` 同一套判据（精确文字色 → 连通域 → 同行聚类
→ 词间隙切分），差异只有两处：

  1. 源目录换成 `Army4_Object_CHS/title/png_control_en`（= 4 代英文原图），
     且只扫 REBUILD 名单里的 5 个文件 —— 其余 118 个直接复用 3 代成品，
     不需要检测。
  2. 文字色白名单**沿用 3 代实测值**：4 色在 4 代调色板里逐字节相同
     （索引 246/167/223/242，见 am4_title_build.py 的前置断言）。

★ 为什么不能用亮度阈值 / 背景估计找文字（3 代踩过，结论沿用）：
  绿字 `#29DF29` 相对绿底亮度差仅约 74；底纹是低对比拉丝噪声。
  改用 4 色精确匹配后误检归零。

输出：
    <WORK>/lines_a4.json     行盒（含实测精确文字色）
    <WORK>/annot_a4/*.png    放大 + 红框编号（人工核对用）

用法：
    python Tools/title/am4_title_lines.py
    python Tools/title/am4_title_lines.py --work <dir>
"""
import argparse
import json
import os
import sys
from collections import Counter, deque

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

TITLE = r"G:\Projects\ArmyMenCHS\Army4_Object_CHS\title"
SRC = os.path.join(TITLE, "png_control_en")
WORK = r"I:\LocalGames\Army Men\_am4_title_work"

# 需重建的 5 个对象（其余 118 个由 am4_title_build.py 直接复制 3 代成品）
REBUILD = [
    "obj_0002_k00080180.png",   # 自定义按键（A4 删了 SELECT SARGE 一行）
    "obj_0003_k00080200.png",   # 多人选项（A4 把标签页并入面板并新增 2 行标签）
    "obj_0012_k00100400.png",   # 另存为（3 代成品有 21px 离板色，在标题框边框）
    "obj_0016_k00100600.png",   # 影片库（3 代同 key 件尺寸 355x442 != 456x406）
    "obj_0121_k00181082.png",   # START 54x22（3 代成品背景被抹字破坏，见下）
]

# ★ 00181082 的额外说明：3 代成品在 y5..y11 出现 (80,97,90)/(90,108,99)/(99,115,107)
#   等灰雾，而 4 代原图该处是 (49,85,49)/(63,138,47) 绿按钮底纹 —— 这是 54x22
#   极小按钮上抹字锚点取样边距不足造成的背景损伤，只能重建，吸附修不回来。

# 实测穷举的文字色（3 代同值，4 代调色板内逐字节相同）
TEXT_COLORS = [(0xFF, 0xFB, 0xF0), (0xFE, 0xE4, 0x02),
               (0x29, 0xDF, 0x29), (0x9C, 0xAA, 0x7B)]
TEXT_COLOR_NAMES = {
    (0xFF, 0xFB, 0xF0): "FFFBF0 白 (标题/按钮常态)",
    (0xFE, 0xE4, 0x02): "FEE402 黄 (按钮选中态)",
    (0x29, 0xDF, 0x29): "29DF29 绿 (按钮按下态)",
    (0x9C, 0xAA, 0x7B): "9CAA7B 暗绿 (未选中标签页)",
}

MIN_PX = 4           # 单字形最小像素
MAX_H = 16           # 单字形高度上限
MAX_W = 26           # 单字形宽度上限
MERGE_GAP = 17       # 同行内允许字间隙（3 代实测：词内 <=16，词块间 >=19）


def components(mask):
    """8 连通域，按单字形尺寸上限过滤（滤掉框线与底纹）。"""
    h, w = mask.shape
    seen = np.zeros((h, w), dtype=bool)
    out = []
    for y0 in range(h):
        row = mask[y0]
        if not row.any():
            continue
        for x0 in np.nonzero(row & ~seen[y0])[0]:
            if seen[y0, x0]:
                continue
            q = deque([(y0, int(x0))])
            seen[y0, x0] = True
            x1 = x2 = int(x0)
            y1 = y2 = y0
            n = 0
            while q:
                y, x = q.popleft()
                n += 1
                x1 = min(x1, x)
                x2 = max(x2, x)
                y1 = min(y1, y)
                y2 = max(y2, y)
                for dy in (-1, 0, 1):
                    ny = y + dy
                    if ny < 0 or ny >= h:
                        continue
                    for dx in (-1, 0, 1):
                        nx = x + dx
                        if nx < 0 or nx >= w:
                            continue
                        if mask[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            q.append((ny, nx))
            if n >= MIN_PX and (y2 - y1 + 1) <= MAX_H and (x2 - x1 + 1) <= MAX_W:
                out.append([y1, y2, x1, x2, n])
    return out


def analyze(path):
    im = Image.open(path).convert("RGB")
    arr = np.asarray(im).astype(np.int16)
    h, w = arr.shape[:2]
    mask = np.zeros((h, w), dtype=bool)
    for c in TEXT_COLORS:
        mask |= ((arr[:, :, 0] == c[0]) & (arr[:, :, 1] == c[1])
                 & (arr[:, :, 2] == c[2]))
    comps = components(mask)

    # 1) 同行聚类：y 重叠 > 50%
    lines = []
    for c in sorted(comps, key=lambda c: (c[0], c[2])):
        for L in lines:
            ov = min(L[1], c[1]) - max(L[0], c[0]) + 1
            if ov > 0.5 * min(L[1] - L[0] + 1, c[1] - c[0] + 1):
                L[0] = min(L[0], c[0])
                L[1] = max(L[1], c[1])
                L[2] = min(L[2], c[2])
                L[3] = max(L[3], c[3])
                L[4].append(c)
                break
        else:
            lines.append([c[0], c[1], c[2], c[3], [c]])

    # 2) 行内按列切分（间隙 > MERGE_GAP）
    segs = []
    for L in lines:
        if not (5 <= L[1] - L[0] + 1 <= MAX_H):
            continue
        cs = sorted(L[4], key=lambda c: c[2])
        seg = [cs[0]]
        for c in cs[1:]:
            if c[2] - seg[-1][3] - 1 > MERGE_GAP:
                segs.append(seg)
                seg = [c]
            else:
                seg.append(c)
        segs.append(seg)

    res = []
    for seg in segs:
        y1 = min(c[0] for c in seg)
        y2 = max(c[1] for c in seg)
        x1 = min(c[2] for c in seg)
        x2 = max(c[3] for c in seg)
        if y2 - y1 + 1 < 5 or x2 - x1 + 1 < 4:
            continue
        cnt = Counter()
        for c in seg:
            sub = arr[c[0]:c[1] + 1, c[2]:c[3] + 1].reshape(-1, 3)
            for p in sub:
                t = (int(p[0]), int(p[1]), int(p[2]))
                if t in TEXT_COLORS:
                    cnt[t] += 1
        fg = cnt.most_common(1)[0][0]
        res.append({"y1": int(y1), "y2": int(y2), "x1": int(x1), "x2": int(x2),
                    "w": int(x2 - x1 + 1), "h": int(y2 - y1 + 1),
                    "fg": list(fg), "npx": int(sum(c[4] for c in seg))})
    res.sort(key=lambda L: (L["y1"], L["x1"]))
    return {"file": os.path.basename(path), "w": int(w), "h": int(h),
            "lines": res}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=WORK)
    ap.add_argument("--only", default=None)
    args = ap.parse_args()

    os.makedirs(args.work, exist_ok=True)
    annot = os.path.join(args.work, "annot_a4")
    os.makedirs(annot, exist_ok=True)
    for f in os.listdir(annot):
        os.remove(os.path.join(annot, f))

    files = [f for f in REBUILD if (not args.only) or (args.only in f)]
    missing = [f for f in files if not os.path.isfile(os.path.join(SRC, f))]
    if missing:
        print("!! 源文件缺失：%s" % missing)
        return 2

    all_res = [analyze(os.path.join(SRC, f)) for f in files]
    with open(os.path.join(args.work, "lines_a4.json"), "w",
              encoding="utf-8") as fh:
        json.dump(all_res, fh, indent=1, ensure_ascii=False)

    total = 0
    print("=" * 78)
    print("AM4 title 文字行检测（%d 个需重建对象）" % len(all_res))
    print("=" * 78)
    for r in all_res:
        print("\n%-28s %dx%d   行数=%d" % (r["file"], r["w"], r["h"],
                                           len(r["lines"])))
        for i, L in enumerate(r["lines"], 1):
            name = TEXT_COLOR_NAMES.get(tuple(L["fg"]), "")
            print("   #%-2d x %3d..%-3d y %3d..%-3d  %3dx%-3d  fg=%02X%02X%02X"
                  " npx=%-4d %s"
                  % (i, L["x1"], L["x2"], L["y1"], L["y2"], L["w"], L["h"],
                     L["fg"][0], L["fg"][1], L["fg"][2], L["npx"], name))
        total += len(r["lines"])

        im = Image.open(os.path.join(SRC, r["file"])).convert("RGB")
        z = 2 if im.width >= 300 else 8
        big = im.resize((im.width * z, im.height * z), Image.NEAREST)
        d = ImageDraw.Draw(big)
        for i, L in enumerate(r["lines"], 1):
            d.rectangle([L["x1"] * z - 2, L["y1"] * z - 2,
                         (L["x2"] + 1) * z + 1, (L["y2"] + 1) * z + 1],
                        outline=(255, 0, 0))
            d.text((L["x1"] * z, max(0, L["y1"] * z - 12)), str(i),
                   fill=(255, 90, 90))
        big.save(os.path.join(annot, r["file"]))

    print()
    print("合计 %d 行；lines_a4.json -> %s" % (total, args.work))
    print("标注图 -> %s（务必目视核对后再跑 build）" % annot)
    return 0


if __name__ == "__main__":
    sys.exit(main())
