# -*- coding: utf-8 -*-
"""AM4（玩具兵大战：世界大战）title 贴图汉化构建（生产工具）。

━━ 复用判定（实测，见 docs/13-am4-title-bitmap-chs.md）━━━━━━━━━━━━━━━━━
121 个目标对象里：

  116 个  A4 英文原图与 A3 英文原图**逐字节相同**，尺寸相同，
          且 3 代成品全部颜色 100% 落在 4 代调色板内
          -> 直接从 png_control_army_3/ 复制（复制后校验 sha256）

    5 个  必须从 A4 源图重建：
          · obj_0002_k00080180  4 代删掉了 SELECT SARGE 一行（26 行 vs 27 行）
          · obj_0003_k00080200  4 代把标签页并入面板并新增 2 行延迟标签；
                               3 代对应件是 605x370 的独立标签页
          · obj_0016_k00100600  3 代同 key 件尺寸 355x442 != 456x406
          · obj_0012_k00100400  3 代成品 21px 离板（标题框上边框被锚点带进）
          · obj_0121_k00181082  3 代成品背景被抹字破坏（54x22 极小按钮）

  +2 个  补收：00180281 / 00180282（SELECT 按钮黄/绿两态）。
          它们在 4 代 title.dat 里存在、与 3 代原图逐字节相同、3 代成品
          离板色 = 0，但 4 代的 en 名单漏了它们 -> 不收会出现
          "常态中文、悬停/按下变英文"。

━━ 三个不能违反的约束（违反即报错中止）━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. 输出尺寸必须与原图**完全一致** —— 否则回包触发 graphicSize 长度硬闸
  2. 输出颜色必须 100% 落在 4 代 palette.bin 内 —— 否则回包最近色吸附出噪点
  3. 只允许改动未压缩 BMP 对象（本批 121+2 个全部满足，已实测）

用法：
    python Tools/title/am4_title_build.py --dry-run
    python Tools/title/am4_title_build.py
    python Tools/title/am4_title_build.py --contact <dir>   # 出人眼对照表
"""
import argparse
import hashlib
import json
import os
import shutil
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import am4_title_lines as L                     # noqa: E402
from am3_hzk16 import Hzk16                     # noqa: E402

TITLE = r"G:\Projects\ArmyMenCHS\Army4_Object_CHS\title"
EN = os.path.join(TITLE, "png_control_en")       # 4 代英文原图 = png/ 的同名副本
PNG4 = os.path.join(TITLE, "png")                # 全量 197 个（补收键从这里取）
A3 = os.path.join(TITLE, "png_control_army_3")   # 3 代成品（已按 key 重映射）
OUT = os.path.join(TITLE, "png_control_chs")
PALETTE = os.path.join(TITLE, "palette.bin")
MANIFEST = os.path.join(TITLE, "manifest.json")
WORK = r"I:\LocalGames\Army Men\_am4_title_work"

FONT = Hzk16()

# 补收键（en 名单漏掉的三态按钮状态）
EXTRA_KEYS = ["00180281", "00180282"]

# 文字色（与 am4_title_lines 同源）
COLORS = {
    "FFFBF0": (0xFF, 0xFB, 0xF0),
    "FEE402": (0xFE, 0xE4, 0x02),
    "29DF29": (0x29, 0xDF, 0x29),
    "9CAA7B": (0x9C, 0xAA, 0x7B),
}

# ★ 不做"抗锯齿环色表"：实测环色（(41,58,36) / (74,101,82) / (20,21,18)…）
#   与面板正常底纹是**同一批颜色**（远离文字带的行里也大量出现），
#   列进排除表会让锚点被迫跳到上百行之外，插值反而铺出大片假色带。
#   跳过环区改由 erase() 的 pad_y 保证（文字带上下各 1 行有环，pad_y=3 跨过）。


# ---------------------------------------------------------------- 调色板
_PAL_RGB = None
_PAL_LUT = None


def palette():
    global _PAL_RGB, _PAL_LUT
    if _PAL_RGB is None:
        raw = open(PALETTE, "rb").read()
        if len(raw) != 1024:
            raise SystemExit("!! palette.bin 必须 1024 字节，实际 %d" % len(raw))
        cols = []
        for i in range(256):
            b, g, r, _ = raw[i * 4:i * 4 + 4]
            cols.append((r, g, b))
        _PAL_RGB = cols
        _PAL_LUT = {}
        for i, c in enumerate(cols):
            _PAL_LUT.setdefault(c, i)
    return _PAL_RGB, _PAL_LUT


def snap_to_palette(arr):
    """整图吸附到最近的调色板色（精确命中则原样）。

    ★ 为什么必须做：贴图是 256 色索引图。抹字的线性插值必然产生调色板外
      过渡色；回包时 am3_dat.encode_bmp 会做最近色匹配，那会在纯色背景上
      留下肉眼可见的噪点。这里先吸附，让回包零色差。
    """
    pal, lut = palette()
    pal_a = np.array(pal, dtype=np.int32)
    flat = arr.reshape(-1, 3)
    uniq, inv = np.unique(flat, axis=0, return_inverse=True)
    res = np.empty_like(uniq)
    for i, c in enumerate(uniq):
        t = (int(c[0]), int(c[1]), int(c[2]))
        if t in lut:
            res[i] = c
            continue
        d = np.abs(pal_a - c.astype(np.int32)).sum(axis=1)
        res[i] = pal_a[int(d.argmin())]
    return res[inv].reshape(arr.shape)


def palette_violations(arr):
    """返回不在调色板内的颜色列表 [(rgb, 最近色差)]。"""
    pal, lut = palette()
    pal_a = np.array(pal, dtype=np.int32)
    out = []
    for c in np.unique(arr.reshape(-1, 3), axis=0):
        t = (int(c[0]), int(c[1]), int(c[2]))
        if t in lut:
            continue
        d = int(np.abs(pal_a - c.astype(np.int32)).sum(axis=1).min())
        out.append((t, d))
    return out


# ---------------------------------------------------------------- 字形
def glyph(ch):
    """返回 (宽, 高, 行位掩码, 基线偏移)。"""
    if ch == " ":
        return (7, 1, [0], 0)
    try:
        gb = ch.encode("gbk")
    except UnicodeEncodeError:
        gb = None
    if gb and len(gb) == 2 and gb[0] >= 0x81:
        rows = FONT.bits(ch)
        if rows:
            return (FONT.width, FONT.height, rows, 0)
    # 缺字兜底：空心方框（与 3 代一致）
    return (13, 13, [0b1111111111111] + [0b1000000000001] * 11
            + [0b1111111111111], 0)


def layout(text, tracking=1):
    items = [glyph(c) for c in text]
    w = sum(g[0] for g in items) + tracking * max(0, len(items) - 1)
    rows = [0] * FONT.height
    x = 0
    for gw, gh, grows, yoff in items:
        for i, v in enumerate(grows):
            rows[yoff + i] |= v << (w - x - gw)
        x += gw + tracking
    return w, FONT.height, rows


def render_scaled(text, target_h, tracking=1):
    """按目标高度渲染译文位图。

    ★ 为什么需要缩放：Hzk16 是 13x13 定点阵。多数面板（列表行距 24px、
      标题带 20px+）直接写 13px 最清晰；但 54x22 的 START 按钮内高只有
      14px，写 13px 会压到按钮下沿的高光边（实测 y16 是满宽高光行）。
      这种就用 target_h 缩到合适高度。
    """
    w, h, rows = layout(text, tracking)
    if target_h >= h:
        return w, h, rows
    im = Image.new("L", (w, h), 0)
    px = im.load()
    for yy, r in enumerate(rows):
        for xx in range(w):
            if (r >> (w - 1 - xx)) & 1:
                px[xx, yy] = 255
    nw = max(1, int(round(w * target_h / float(h))))
    im2 = im.resize((nw, target_h), Image.LANCZOS)
    px2 = im2.load()
    out = []
    for yy in range(target_h):
        v = 0
        for xx in range(nw):
            v = (v << 1) | (1 if px2[xx, yy] >= 110 else 0)
        out.append(v)
    return nw, target_h, out


def blit(arr, x, y, w, rows, color):
    H, W = arr.shape[:2]
    for yy, r in enumerate(rows):
        py = y + yy
        if py < 0 or py >= H:
            continue
        for xx in range(w):
            if (r >> (w - 1 - xx)) & 1:
                px = x + xx
                if 0 <= px < W:
                    arr[py, px] = color


# ---------------------------------------------------------------- 抹字
def text_extent(arr, L, pad=7):
    """求该行盒内**文字实际占据**的横向范围（含抗锯齿外溢）。

    ★ 为什么必须收窄：行盒是"同行所有文字的并集"，可能远宽于文字本身。
      实测 00080200 的延迟标签盒 x24..301，而英文实际只到 x307 之前一小段
      —— 但 3 代/本工具的行盒是按"所有连通域并集"给的，宽盒会让纵向插值
      把文字两侧的正常背景一起重铺成横带（实测 2480 px 的假色带）。

    做法：在盒内按行扫描，找出所有含文字色的列，取其最小/最大列，再外扩 pad。
    """
    H, W = arr.shape[:2]
    x1, y1, x2, y2 = L["x1"], L["y1"], L["x2"], L["y2"]
    fgset = set(COLORS.values())
    cols = []
    for x in range(max(0, x1), min(W, x2 + 1)):
        seg = arr[y1:y2 + 1, x]
        for c in np.unique(seg.reshape(-1, 3), axis=0):
            if tuple(int(v) for v in c) in fgset:
                cols.append(x)
                break
    if not cols:
        return None
    return (max(0, min(cols) - pad), min(W - 1, max(cols) + pad))


def erase(arr, L, pad=7, pad_y=3):
    """抹掉一个行盒内的文字：**纵向插值**，只在文字实际占据的横向范围内。

    ★ 为什么必须是纵向，不能横向（这是本次唯一反复踩的坑）：

      这些面板的底色是**横向拉丝条纹**：一行里交替出现
      (24,60,33) / (41,73,41) / (29,38,29) / (20,21,18) / (10,20,10)。
      相邻条纹色的曼哈顿距离就有 40~60，远大于"文字/抗锯齿 vs 背景"的阈值。

      横向做法（无论按锚点色差定掩码，还是两锚点间整段插值）在这种背景上
      都必然出错：
        · 用色差定掩码 -> 整条纹理被误判成文字，填成单色平带（实测
          00080200 y399 整段 x18..104 被压成 (20,21,18)）；
        · 两锚点间整段插值 -> 盒宽 270px 而文字仅 60px，把大片背景重铺。

      纵向插值则天然保纹理：同一列上、下一行属同一竖条纹，颜色本就一致或
      呈固定渐变，插值结果与背景完全同族。

    ★ 横向范围取 text_extent()（文字实际跨度 + pad），**不是整个行盒**。
    ★ pad_y：抗锯齿环也外溢到文字带上下各 1 px。
    """
    H, W = arr.shape[:2]
    x1, y1, x2, y2 = L["x1"], L["y1"], L["x2"], L["y2"]
    fgset = set(COLORS.values())

    ext = text_extent(arr, L, pad)
    if ext is None:
        return arr, 0
    ex1, ex2 = ext

    def clean_row(y):
        """该行能否作为背景锚点。

        判据：跨度内不含**精确文字色**。

        ★ 只查精确文字色，不查"环色表"。
          原因（实测数据）：环色与正常底纹色是**同一批颜色** ——
          例如 (41,58,36) 在远离文字带的行里出现 2224 px，(74,101,82)
          有 450 px，它们本身就是面板底纹的一部分。把它们列进排除表，
          锚点会被迫跳到 100 行之外（实测 ty 落到 y250），插值跨度 120 行，
          反而铺出大片假色带。
          真正需要的是"跳过紧邻文字带的 1~2 行"，这由 pad_y 保证：
          实测文字带上下各 1 行混有抗锯齿色，pad_y=3 正好跨过去。
        """
        if not (0 <= y < H):
            return False
        seg = arr[y, max(0, ex1 - 1):min(W, ex2 + 2)]
        for c in np.unique(seg.reshape(-1, 3), axis=0):
            if tuple(int(v) for v in c) in fgset:
                return False
        return True

    ty = None
    for y in range(y1 - pad_y, -1, -1):
        if clean_row(y):
            ty = y
            break
    by = None
    for y in range(y2 + pad_y, H):
        if clean_row(y):
            by = y
            break
    if ty is None or by is None:
        return arr, 0

    top = arr[ty, ex1:ex2 + 1].astype(np.float32)
    bot = arr[by, ex1:ex2 + 1].astype(np.float32)
    span = float(by - ty)
    n = 0
    for y in range(y1 - pad_y, y2 + pad_y + 1):
        if not (0 <= y < H):
            continue
        t = (y - ty) / span
        arr[y, ex1:ex2 + 1] = np.clip(top * (1 - t) + bot * t + 0.5,
                                      0, 255).astype(np.uint8)
        n += ex2 - ex1 + 1
    return arr, n


# ---------------------------------------------------------------- 主流程
def load_manifest():
    man = json.load(open(MANIFEST, encoding="utf-8"))
    by_key = {}
    for o in man["objects"]:
        by_key[o["key_hex"][2:].upper().zfill(8)] = o
    return man, by_key


def key_of(name):
    return name.split("_k")[1].replace(".png", "").upper()


def src_png(name, by_key):
    """英文源图路径：优先 png_control_en/，缺失则退到 png/（补收键用）。"""
    p = os.path.join(EN, name)
    if os.path.isfile(p):
        return p
    o = by_key.get(key_of(name))
    if o:
        p2 = os.path.join(PNG4, o["png"])
        if os.path.isfile(p2):
            return p2
    return None


def a3_map():
    """png_control_army_3/ 的 key -> 文件名。

    ★ 必须按 key 映射，不能按文件名复制：该目录是 3 代成品按 key 重映射到
      4 代的副本，但**文件名仍是 3 代索引**（例：4 代 obj_0005_k00100080.png
      在 3 代是 obj_0008_k00100080.png）。按文件名复制会张冠李戴。
    """
    out = {}
    for f in os.listdir(A3):
        if f.lower().endswith(".png"):
            out[key_of(f)] = f
    return out


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def load_table(path):
    """译文表：文件名 <TAB> 行号 <TAB> 译文 [<TAB> k=v;k=v]。"""
    plan = {}
    if not path or not os.path.isfile(path):
        return plan
    for ln, raw in enumerate(open(path, encoding="utf-8"), 1):
        s = raw.rstrip("\r\n")
        if not s.strip() or s.lstrip().startswith("#"):
            continue
        parts = s.split("\t")
        if len(parts) < 3:
            print("  跳过（列数不足）第 %d 行: %r" % (ln, s))
            continue
        f, idx, text = parts[0].strip(), int(parts[1]), parts[2]
        opts = {"text": text}
        if len(parts) > 3 and parts[3].strip():
            for kv in parts[3].split(";"):
                if "=" not in kv:
                    continue
                k, v = (x.strip() for x in kv.split("=", 1))
                if k == "color":
                    opts["color"] = COLORS.get(v.upper(), None)
                elif k in ("dx", "dy", "tracking", "gh"):
                    opts[k] = int(v)
                elif k == "align":
                    opts[k] = v
                elif k == "span":
                    opts[k] = [int(x) for x in v.split(",") if x.strip()]
        plan.setdefault(f, {})[idx] = opts
    return plan


def rebuild_one(name, spec, lines_rec, out_path, src_path, check_dir=None):
    """从 A4 源图重建一个对象。返回 (applied, warns)。"""
    src = src_path
    arr = np.asarray(Image.open(src).convert("RGB")).copy()
    orig = arr.copy()                       # 源图快照（用于"新引入颜色"判据）
    H, W = arr.shape[:2]

    applied = []
    for idx in sorted(spec.keys()):
        s = spec[idx]
        if not (1 <= idx <= len(lines_rec["lines"])):
            raise SystemExit("!! %s 行号越界 #%d（共 %d）"
                             % (name, idx, len(lines_rec["lines"])))
        L = lines_rec["lines"][idx - 1]
        # span：同一视觉行被词间隙切成多段（如 MAP / OBJECTIVE）。
        # ★ 必须取**并集盒**统一抹字：分盒抹的话，每段的内边缘紧邻另一段
        #   文字，锚点必然落在文字色上（实测 #18/#19 就是这种），
        #   前置断言会正确地拦下来。
        regions = [L] + [lines_rec["lines"][k - 1] for k in (s.get("span") or [])]
        ux1 = min(r["x1"] for r in regions)
        ux2 = max(r["x2"] for r in regions)
        uy1 = min(r["y1"] for r in regions)
        uy2 = max(r["y2"] for r in regions)
        box = {"x1": ux1, "y1": uy1, "x2": ux2, "y2": uy2, "fg": L["fg"]}
        erase(arr, box)
        text = s["text"]
        if not text:
            applied.append({"idx": idx, "text": "", "box": None})
            continue

        # 字形高度：默认 13（Hzk16 全字格，最清晰）。
        # 仅当行盒/按钮内高不足时才在译文表里用 gh=N 指定缩放。
        gh = s.get("gh") or FONT.height

        tracking = s.get("tracking", 1)
        w, h, rows = render_scaled(text, gh, tracking)
        cy = (uy1 + uy2 + 1) / 2.0
        ty = int(round(cy - h / 2.0))
        align = s.get("align")
        if align == "left":
            tx = ux1
        elif align == "right":
            tx = ux2 + 1 - w
        else:
            tx = int(round((ux1 + ux2 + 1) / 2.0 - w / 2.0))
        tx += s.get("dx", 0)
        ty += s.get("dy", 0)
        color = s.get("color") or tuple(L["fg"])
        blit(arr, tx, ty, w, rows, color)
        applied.append({"idx": idx, "text": text,
                        "box": [tx, ty, w, h], "gh": gh,
                        "src_box": [ux1, uy1, ux2, uy2],
                        "color": list(color),
                        "overflow": max(0, tx + w - 1 - ux2),
                        "top_over": max(0, uy1 - ty)})

    arr = snap_to_palette(arr)
    bad = palette_violations(arr)
    if bad:
        raise SystemExit("!! %s 吸附后仍有离板色 %s" % (name, bad[:5]))

    # ★ 真正的质量判据：文字区域不得引入源图没有的颜色（灰带/补丁痕迹）。
    #   全跨度插值必然产生过渡色，吸附后虽都落在调色板内，但会变成
    #   "源图上不存在的中间色" —— 这正是灰带的数值特征。
    warns = []
    for it in applied:
        if not it.get("src_box"):
            continue
        ux1, uy1, ux2, uy2 = it["src_box"]
        px1 = max(0, ux1 - 5)
        px2 = min(W - 1, ux2 + 5)
        py1 = max(0, uy1 - 2)
        py2 = min(H - 1, uy2 + 2)
        cols_src = set(
            tuple(int(v) for v in c)
            for c in np.unique(orig[py1:py2 + 1, px1:px2 + 1].reshape(-1, 3),
                               axis=0))
        cols_new = set(
            tuple(int(v) for v in c)
            for c in np.unique(arr[py1:py2 + 1, px1:px2 + 1].reshape(-1, 3),
                               axis=0))
        fresh = [c for c in (cols_new - cols_src)
                 if not (c in COLORS.values())]
        if fresh:
            warns.append((it["idx"], len(fresh), fresh[:4]))

    Image.fromarray(arr).save(out_path)

    if check_dir:
        os.makedirs(check_dir, exist_ok=True)
        Z = 6 if W < 120 else (3 if W < 400 else 2)
        a = Image.open(src).convert("RGB")
        b = Image.open(out_path).convert("RGB")
        sa = a.resize((W * Z, H * Z), Image.NEAREST)
        sb = b.resize((W * Z, H * Z), Image.NEAREST)
        c = Image.new("RGB", (sa.width * 2 + 20, sa.height + 22), (18, 18, 22))
        d = ImageDraw.Draw(c)
        d.text((4, 4), "EN   " + name, fill=(255, 220, 120))
        d.text((sa.width + 24, 4), "CHS", fill=(120, 255, 160))
        c.paste(sa, (0, 20))
        c.paste(sb, (sa.width + 20, 20))
        c.save(os.path.join(check_dir, "cmp_" + name))
    return applied, warns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--work", default=WORK)
    ap.add_argument("--table", default=None,
                    help="译文表；默认 <work>/translations_a4.tsv")
    ap.add_argument("--check", default=None, help="人眼对照图输出目录")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default=None)
    args = ap.parse_args()

    table = args.table or os.path.join(args.work, "translations_a4.tsv")
    man, by_key = load_manifest()
    pal, lut = palette()

    # ── 前置闸门 ────────────────────────────────────────────────────────
    print("=" * 78)
    print("前置检查")
    print("=" * 78)
    bad = FONT.selftest()
    if bad:
        print("!! Hzk16 字形自检未通过，中止：")
        for ch, msg in bad:
            print("     %s: %s" % (ch, msg))
        return 2
    print("  Hzk16 自检通过（%dx%d，%d 字形）"
          % (FONT.width, FONT.height, FONT.n_glyph))

    for nm, c in COLORS.items():
        if c not in lut:
            print("!! 文字色 %s (%s) 不在 4 代调色板内，中止" % (nm, c))
            return 2
    print("  4 个文字色全部命中 4 代调色板（索引 %s）"
          % [lut[COLORS[k]] for k in ("FFFBF0", "FEE402", "29DF29", "9CAA7B")])

    en_files = sorted(f for f in os.listdir(EN) if f.endswith(".png"))
    targets = list(en_files)
    for k in EXTRA_KEYS:
        o = by_key.get(k)
        if o is None:
            print("!! 补收键 %s 在 4 代 title.dat 中不存在，中止" % k)
            return 2
        targets.append(o["png"])
    targets = sorted(set(targets))
    print("  目标对象 %d 个（en 名单 %d + 补收 %d）"
          % (len(targets), len(en_files), len(EXTRA_KEYS)))

    a3m = a3_map()
    missing_a3 = [f for f in targets
                  if key_of(f) not in a3m and f not in L.REBUILD]
    if missing_a3:
        print("!! 3 代成品按 key 缺失 %d 个：%s" % (len(missing_a3),
                                                 missing_a3[:8]))
        return 2
    print("  3 代成品按 key 命中：%d 个（按 key 映射，不按文件名）"
          % len([f for f in targets if key_of(f) in a3m]))

    # 尺寸硬闸（覆盖层尺寸必须逐一对上 manifest）
    dim_bad = []
    for f in targets:
        o = by_key[key_of(f)]
        p = src_png(f, by_key)
        if not p:
            dim_bad.append((f, "A4 源缺失"))
            continue
        if Image.open(p).size != (o["width"], o["height"]):
            dim_bad.append((f, Image.open(p).size, (o["width"], o["height"])))
        if o["kind"] != "BMP":
            dim_bad.append((f, "非 BMP: %s" % o["kind"]))
        # 复用件的尺寸也必须对得上（不同尺寸说明 3/4 代版式不同，不能复用）
        if f not in L.REBUILD and key_of(f) in a3m:
            sp = os.path.join(A3, a3m[key_of(f)])
            if Image.open(sp).size != (o["width"], o["height"]):
                dim_bad.append((f, "复用件尺寸 %s != %s"
                                % (Image.open(sp).size,
                                   (o["width"], o["height"]))))
    if dim_bad:
        print("!! 尺寸/类型硬闸未通过：%s" % dim_bad[:6])
        return 2
    print("  尺寸与 kind 硬闸通过（全部 %d 个为未压缩 BMP 且尺寸对得上）"
          % len(targets))

    plan = load_table(table)
    recs = {}
    lp = os.path.join(args.work, "lines_a4.json")
    if os.path.isfile(lp):
        recs = {r["file"]: r for r in
                json.load(open(lp, encoding="utf-8"))}

    miss_tbl = [f for f in L.REBUILD if f not in plan]
    if miss_tbl:
        print("!! 译文表缺 %d 个重建文件：%s" % (len(miss_tbl), miss_tbl))
        return 2
    miss_lines = [f for f in L.REBUILD if f not in recs]
    if miss_lines:
        print("!! lines_a4.json 缺 %d 个文件（先跑 am4_title_lines.py）：%s"
              % (len(miss_lines), miss_lines))
        return 3

    # 用字自检
    need = set()
    for f, p in plan.items():
        if f in L.REBUILD:
            for s in p.values():
                need |= set(s["text"])
    miss_ch = sorted(c for c in need if not FONT.has(c))
    print("  重建用字 %d 个；Hzk16 缺字: %s"
          % (len(need), miss_ch if miss_ch else "无"))
    if miss_ch:
        return 4

    if args.dry_run:
        print()
        print("=" * 78)
        print("DRY RUN —— 计划")
        print("=" * 78)
        print("  直接复用 3 代成品: %d 个（按 key 映射）"
              % (len(targets) - len(L.REBUILD)))
        for f in sorted(set(targets) - set(L.REBUILD))[:12]:
            print("     %-28s <- %s" % (f, a3m[key_of(f)]))
        if len(targets) - len(L.REBUILD) > 12:
            print("     ... 其余 %d 个同类"
                  % (len(targets) - len(L.REBUILD) - 12))
        print("  重建: %d 个" % len(L.REBUILD))
        for f in L.REBUILD:
            print("     %-28s %d 处文字"
                  % (f, len(plan.get(f, {}))))
        print()
        print("  补收（en 名单外的三态按钮）: %s"
              % [by_key[k]["png"] for k in EXTRA_KEYS])
        print("  输出: %s" % args.out)
        print("（dry-run，未写入任何文件）")
        return 0

    os.makedirs(args.out, exist_ok=True)
    report = []
    n_copy = n_rebuild = 0

    for f in sorted(set(targets) - set(L.REBUILD)):
        if args.only and args.only not in f:
            continue
        src = os.path.join(A3, a3m[key_of(f)])       # ★ 按 key 取源
        dst = os.path.join(args.out, f)              # ★ 按 4 代文件名落盘
        shutil.copyfile(src, dst)
        if sha256_file(src) != sha256_file(dst):
            raise SystemExit("!! 复制后哈希不符: %s" % f)
        o = by_key[key_of(f)]
        a = np.asarray(Image.open(dst).convert("RGB"))
        bad = palette_violations(a)
        if bad:
            raise SystemExit("!! %s 复用件含离板色 %s" % (f, bad[:5]))
        if Image.open(dst).size != (o["width"], o["height"]):
            raise SystemExit("!! %s 尺寸不符" % f)
        n_copy += 1
        report.append({"file": f, "mode": "reuse-a3",
                       "src": os.path.basename(src),
                       "sha256": sha256_file(dst)})
        print("  [复用] %-28s <- %s" % (f, os.path.basename(src)))

    for f in L.REBUILD:
        if args.only and args.only not in f:
            continue
        applied, warns = rebuild_one(
            f, plan[f], recs[f], os.path.join(args.out, f),
            src_png(f, by_key), args.check)
        o = by_key[key_of(f)]
        if Image.open(os.path.join(args.out, f)).size != (o["width"], o["height"]):
            raise SystemExit("!! %s 重建后尺寸不符" % f)
        n_rebuild += 1
        warn = ("  !! 引入新色 %s" % warns) if warns else ""
        print("  [重建] %-28s %2d 处%s" % (f, len(applied), warn))
        report.append({"file": f, "mode": "rebuild-a4",
                       "sha256": sha256_file(os.path.join(args.out, f)),
                       "items": applied, "new_colors": warns})

    with open(os.path.join(args.out, "_report.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"targets": len(targets), "reuse": n_copy,
                   "rebuild": n_rebuild, "items": report},
                  fh, ensure_ascii=False, indent=1)
    print()
    print("共写出 %d 个（复用 %d / 重建 %d）-> %s"
          % (n_copy + n_rebuild, n_copy, n_rebuild, args.out))
    print("  -> _report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
