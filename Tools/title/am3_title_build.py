# -*- coding: utf-8 -*-
"""Army3 贴图汉化：按译文表批量生成。

译文表（UTF-8，TAB 分隔，# 与空行忽略）：
    文件名 <TAB> 行号 <TAB> 译文 <TAB> 可选参数
参数（分号分隔的 k=v）：
    color=RRGGBB    覆盖文字颜色（默认沿用原文精确色）
    outline=RRGGBB  指定描边色；outline=none 关闭描边
    align=left|center
    dx=N / dy=N     微调偏移
    tracking=N      字距（默认 1）
"""
import argparse
import json
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import am3_title_render as R

SRC = R.SRC
WORK = R.WORK


def _color(v):
    if v.lower() in ("none", "0", "off"):
        return None
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))


def load_table(path):
    plan = {}
    for ln, raw in enumerate(open(path, encoding="utf-8"), 1):
        s = raw.rstrip("\r\n")
        if not s.strip() or s.lstrip().startswith("#"):
            continue
        parts = s.split("\t")
        if len(parts) < 3:
            print("跳过（列数不足）第 %d 行: %r" % (ln, s))
            continue
        f, idx, text = parts[0].strip(), int(parts[1]), parts[2]
        opts = {"text": text}
        if len(parts) > 3 and parts[3].strip():
            for kv in parts[3].split(";"):
                if "=" not in kv:
                    continue
                k, v = (x.strip() for x in kv.split("=", 1))
                if k in ("color", "outline"):
                    opts[k] = _color(v)
                elif k in ("dx", "dy", "tracking"):
                    opts[k] = int(v)
                elif k == "span":
                    opts[k] = [int(x) for x in v.split(",") if x.strip()]
                elif k == "align":
                    opts[k] = v
                elif k == "outline_none":
                    opts["outline"] = None
        plan.setdefault(f, {})[idx] = opts
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--contact", default=None)
    args = ap.parse_args()

    # ★ 前置自检：字形取位错了会让每个字的左边被切掉，且肉眼易漏。
    bad = R.FONT.selftest()
    if bad:
        print("!! Hzk16 字形自检未通过（取位/对齐有误），中止构建：")
        for ch, msg in bad:
            print("     %s: %s" % (ch, msg))
        return 2
    print("Hzk16 字形自检通过（%dx%d，%d 字形）" %
          (R.FONT.width, R.FONT.height, R.FONT.n_glyph))

    plan = load_table(args.table)
    recs = {r["file"]: r for r in json.load(open(os.path.join(WORK, "lines.json"), encoding="utf-8"))}
    os.makedirs(args.out, exist_ok=True)

    report = []
    for f, p in sorted(plan.items()):
        src = os.path.join(SRC, f)
        if not os.path.isfile(src):
            print("!! 缺文件", f)
            continue
        rec = recs.get(f)
        if rec is None:
            print("!! lines.json 无记录", f)
            continue
        for idx in p:
            if not (1 <= idx <= len(rec["lines"])):
                print("!! %s 行号越界: #%d (共 %d)" % (f, idx, len(rec["lines"])))
        out = os.path.join(args.out, f)
        applied, residues = R.process(src, p, rec, out)
        for idx, text, box in applied:
            report.append({"file": f, "idx": idx, "text": text, "box": box})
        warn = ("  !! 残留 %s" % residues) if residues else ""
        print("%-26s %d 处%s" % (f, len(applied), warn))
    print("共写出 %d 个文件, %d 处文字" % (len(plan), len(report)))
    json.dump(report, open(os.path.join(WORK, "applied.json"), "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)

    if args.contact:
        os.makedirs(args.contact, exist_ok=True)
        for old in os.listdir(args.contact):
            os.remove(os.path.join(args.contact, old))
        files = sorted(plan.keys())
        PER = 6
        for pi in range(0, len(files), PER):
            chunk = files[pi:pi + PER]
            tiles = []
            for f in chunk:
                a = Image.open(os.path.join(SRC, f)).convert("RGB")
                b = Image.open(os.path.join(args.out, f)).convert("RGB")
                z = min(3.0, 620 / max(a.width, 1))
                if z < 1:
                    z = 1
                a2 = a.resize((int(a.width * z), int(a.height * z)), Image.NEAREST)
                b2 = b.resize(a2.size, Image.NEAREST)
                tiles.append((f, a2, b2))
            W = max(t[1].width for t in tiles) * 2 + 30
            H = sum(t[1].height + 26 for t in tiles) + 10
            sheet = Image.new("RGB", (W, H), (28, 28, 34))
            d = ImageDraw.Draw(sheet)
            y = 6
            for f, a, b in tiles:
                d.text((6, y + 2), f + "   [原文]", fill=(255, 220, 120))
                d.text((a.width + 20, y + 2), "[译文]", fill=(120, 255, 160))
                sheet.paste(a, (6, y + 18))
                sheet.paste(b, (a.width + 20, y + 18))
                y += a.height + 26
            sheet.save(os.path.join(args.contact, "cmp_%02d.png" % (pi // PER)))
        print("对比表 ->", args.contact)


if __name__ == "__main__":
    main()
