# -*- coding: utf-8 -*-
"""Army3 title 贴图文字行检测 v4（最终版）。

核心洞察：本作 UI 文字只用**固定几种精确调色板色**，且单图色数 ≤40。
所以不需要任何背景估计 —— 直接按"精确文字色"取掩码，再按
"字形连通域 -> 同行聚类 -> 按词间隙切分"得到行盒。

文字色白名单（实测穷举）：
    FFFBF0  白   按钮常态 / 标题
    FEE402  黄   按钮选中态
    29DF29  绿   按钮按下态
    9CAA7B  暗绿 未选中的标签页
灰色（C6C6C6/ABABAB/717171/E3E3E3）只出现在箭头、单选钮、窗口立体边 —— 无文字，全部排除。

输出:
    _am3_title_work/lines.json          行盒（含颜色、左右边界）
    _am3_title_work/annot/*.png         放大 + 红框编号（核对用）
    _am3_title_work/lines_sheet_*.png   文字条接触表
"""
import json
import os
from collections import Counter, deque

import numpy as np
from PIL import Image, ImageDraw

SRC = r"G:\Projects\ArmyMenCHS\Army3_Object_CHS\title\png_ai"
WORK = r"I:\LocalGames\Army Men\_am3_title_work"

TEXT_COLORS = [(0xFF, 0xFB, 0xF0), (0xFE, 0xE4, 0x02), (0x29, 0xDF, 0x29), (0x9C, 0xAA, 0x7B)]
MIN_PX = 4           # 单字形最小像素
MAX_H = 16           # 单字形高度上限
MAX_W = 26           # 单字形宽度上限
MERGE_GAP = 17       # 同一行内允许的字间隙（实测词内最大 16，词块间最小 19）


def components(mask):
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
            x1 = x2 = int(x0); y1 = y2 = y0; n = 0
            while q:
                y, x = q.popleft()
                n += 1
                x1 = min(x1, x); x2 = max(x2, x)
                y1 = min(y1, y); y2 = max(y2, y)
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
        mask |= ((arr[:, :, 0] == c[0]) & (arr[:, :, 1] == c[1]) & (arr[:, :, 2] == c[2]))
    comps = components(mask)

    # 1) 同一行聚类：y 重叠 > 50%
    lines = []
    for c in sorted(comps, key=lambda c: (c[0], c[2])):
        for L in lines:
            ov = min(L[1], c[1]) - max(L[0], c[0]) + 1
            if ov > 0.5 * min(L[1] - L[0] + 1, c[1] - c[0] + 1):
                L[0] = min(L[0], c[0]); L[1] = max(L[1], c[1])
                L[2] = min(L[2], c[2]); L[3] = max(L[3], c[3])
                L[4].append(c)
                break
        else:
            lines.append([c[0], c[1], c[2], c[3], [c]])

    # 2) 行内按列切分（间隙 > MERGE_GAP）—— 但先按"行高"放宽：间隙 <= 1.2*行高 视作词内
    segs = []
    for L in lines:
        if not (5 <= L[1] - L[0] + 1 <= MAX_H):
            continue
        row_h = L[1] - L[0] + 1
        gap = MERGE_GAP
        cs = sorted(L[4], key=lambda c: c[2])
        seg = [cs[0]]
        for c in cs[1:]:
            if c[2] - seg[-1][3] - 1 > gap:
                segs.append(seg); seg = [c]
            else:
                seg.append(c)
        segs.append(seg)

    res = []
    for seg in segs:
        y1 = min(c[0] for c in seg); y2 = max(c[1] for c in seg)
        x1 = min(c[2] for c in seg); x2 = max(c[3] for c in seg)
        if y2 - y1 + 1 < 5 or x2 - x1 + 1 < 4:
            continue
        # 文字色 = 段内精确色的众数
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
    return {"file": os.path.basename(path), "w": int(w), "h": int(h), "lines": res}


def main():
    os.makedirs(WORK, exist_ok=True)
    annot = os.path.join(WORK, "annot")
    os.makedirs(annot, exist_ok=True)
    for f in os.listdir(annot):
        os.remove(os.path.join(annot, f))
    files = sorted(f for f in os.listdir(SRC) if f.endswith(".png"))
    all_res = [analyze(os.path.join(SRC, f)) for f in files]
    json.dump(all_res, open(os.path.join(WORK, "lines.json"), "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)

    rows = []
    for r in all_res:
        if not r["lines"]:
            continue
        im = Image.open(os.path.join(SRC, r["file"])).convert("RGB")
        z = 3 if im.width >= 300 else 6
        big = im.resize((im.width * z, im.height * z), Image.NEAREST)
        d = ImageDraw.Draw(big)
        for i, L in enumerate(r["lines"], 1):
            d.rectangle([L["x1"] * z - 2, L["y1"] * z - 2,
                         (L["x2"] + 1) * z + 1, (L["y2"] + 1) * z + 1], outline=(255, 0, 0))
            d.text((L["x1"] * z, max(0, L["y1"] * z - 13)), str(i), fill=(255, 90, 90))
        big.save(os.path.join(annot, r["file"]))
        for i, L in enumerate(r["lines"], 1):
            pad = 3
            box = (max(0, L["x1"] - pad), max(0, L["y1"] - pad),
                   min(im.width, L["x2"] + 1 + pad), min(im.height, L["y2"] + 1 + pad))
            crop = im.crop(box)
            zz = 4 if crop.width <= 200 else (3 if crop.width <= 380 else 2)
            rows.append((r["file"], i, L,
                         crop.resize((crop.width * zz, crop.height * zz), Image.NEAREST)))

    PER = 16
    for pi in range(0, len(rows), PER):
        chunk = rows[pi:pi + PER]
        W = max(760, max(c[3].width for c in chunk) + 40)
        H = sum(c[3].height + 20 for c in chunk) + 10
        sheet = Image.new("RGB", (W, H), (28, 28, 34))
        d = ImageDraw.Draw(sheet)
        y = 6
        for fn, idx, L, c in chunk:
            d.text((6, y + 2), "%s #%d  %dx%d at(%d,%d) fg=%02X%02X%02X" % (
                fn, idx, L["w"], L["h"], L["x1"], L["y1"], *L["fg"]), fill=(255, 220, 120))
            sheet.paste(c, (10, y + 16))
            y += c.height + 20
        sheet.save(os.path.join(WORK, "lines_sheet_%02d.png" % (pi // PER)))

    print("objects:", len(all_res), " with lines:", sum(1 for r in all_res if r["lines"]))
    print("lines:", sum(len(r["lines"]) for r in all_res))
    print("sheets:", (len(rows) + PER - 1) // PER)


if __name__ == "__main__":
    main()
