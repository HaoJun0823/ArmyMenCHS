# -*- coding: utf-8 -*-
"""3 代 dat **无损回包**（title.dat / shared.dat）。

★ 为什么不能直接用 Tools/am3_dat.py 的 pack 命令：

   `am3_dat.py pack` 对"Png 被改动"的对象只写出
       struct.pack("<iiii", ...) + 8 + graphicSize(4)  =  28 字节头 + 新像素
   而 3 代 dat 里每个对象 blob 的真实结构是

       28 字节头 + graphicSize 字节像素 + **24 字节尾**

   那 24 字节尾部被 pack 丢掉了。实测代价（用真数据跑）：

       title.dat   4298896 -> 4295848   （127 个对象各丢 24 B）
       shared.dat  2936433 -> 2936049   （ 16 个对象各丢 24 B）

   文件变短意味着**其后每个对象的偏移全部前移**，目录表里的 offset 与
   实际数据不再一致。这条路没有实机验证过。

   ⚠ 而且 `shared` 里 88 个对象的尾部**非 0**（不是填充），丢掉就是内容损坏。

★ 本工具的算法（已用真数据验证）：

       未改动的 PNG  -> 直接写 raw/*.bin（逐字节无损，含头、尾）
       改动的 PNG    -> raw[:28] + 重编码像素 + raw[28+graphicSize:]
                        （头与尾原样保留，只换像素段）

   因此不变量全部成立（实测断言通过）：

       产物与原始 dat **等长**
       每个对象的 orig_offset **不变**
       未改动对象区域与原始 dat **逐字节相同**
       改动对象仅像素段不同（头 28 B 与尾部完全一致）

★ 硬闸（违反即报错中止，不静默继续）：

   1. 改动的对象必须是未压缩 BMP。RLE 族（WRLE/TRLE/SRLE）的重编码与
      flags 不符，写出就是坏数据；shared 里 31 个 SRLE 对象没有 PNG，
      本工具不会去碰它们。
   2. 重编码后的长度必须**恰好等于**原 graphicSize。长度不同会让该对象
      及其后所有对象的偏移移动 —— 那正是我们要避免的事。
   3. 对象 blob 长度必须 >= 28 + graphicSize，否则 manifest/graphicSize
      与实际 raw 不一致（说明 raw 被换过），不能继续。

用法：

    # 基本：回包到指定输出
    python Tools/am3_dat_pack.py Army3_Object_CHS/title out/title.dat

    # 带中文控件覆盖层（覆盖层优先于 png/）
    python Tools/am3_dat_pack.py Army3_Object_CHS/title out/title.dat \
        --overlay Army3_Object_CHS/title/png_control_chs

    # 断言产物与原版 dat 等长 + 对象偏移与目录表完全一致（CI 用）
    python Tools/am3_dat_pack.py Army3_Object_CHS/title out/title.dat \
        --overlay ... --expect-size 4298896

退出码：0 成功；非 0 失败（且**不**留下半成品 —— 只在全部校验通过后落盘）。
"""

import argparse
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import am3_dat as M  # noqa: E402

HEADER_SIZE = 28          # key,w,h,flags / hotspot / linkspot / graphicSize
TAIL_MIN = 0              # 尾部长度不做假设，按 raw 实际长度取


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def pick_source_png(in_dir, overlay_dir, name):
    """返回该对象要用的 PNG 路径与来源标记。

    覆盖层优先：png_control_chs 是中文控件，落在与 png/ 相同的文件名上。
    """
    if overlay_dir:
        p = os.path.join(overlay_dir, name)
        if os.path.isfile(p):
            return p, "overlay"
    p = os.path.join(in_dir, "png", name)
    if os.path.isfile(p):
        return p, "png"
    return None, None


def build(in_dir, overlay_dir=None, expect_size=None, verbose=True):
    """按无损算法构造 dat 字节流。返回 (data, stats)。"""
    man_path = os.path.join(in_dir, "manifest.json")
    if not os.path.isfile(man_path):
        raise SystemExit("!! 缺少 %s（先用 am3_dat.py unpack 生成）" % man_path)
    man = json.load(open(man_path, "r", encoding="utf-8"))

    objects = sorted(man["objects"], key=lambda o: o["index"])
    n_obj = len(objects)

    # 目录表声明与 manifest 必须自洽，否则后面所有偏移假设都不成立
    if man.get("nObjects") != n_obj:
        raise SystemExit("!! manifest.nObjects=%s 与实际 %d 条不符"
                         % (man.get("nObjects"), n_obj))
    if man.get("headerTableOff") != M.HEADER_TABLE_OFF:
        raise SystemExit("!! manifest.headerTableOff=%s，本工具假定 %d"
                         % (man.get("headerTableOff"), M.HEADER_TABLE_OFF))

    palette = open(os.path.join(in_dir, "palette.bin"), "rb").read()
    if len(palette) != 1024:
        raise SystemExit("!! palette.bin 必须 1024 字节，实际 %d" % len(palette))
    pal_rgb = M.palette_rgb(palette)
    lut = M.build_palette_lookup(pal_rgb)
    raw_dir = os.path.join(in_dir, "raw")

    stats = {
        "objects": n_obj,
        "verbatim": 0,          # 未改动：raw 原样回填
        "reencoded": 0,         # 改动：重编码像素
        "overlay_used": 0,      # 命中了覆盖层的对象数
        "overlay_changed": 0,   # 覆盖层里内容与原 PNG 不同的对象数
        "tail_nonzero": 0,      # 尾部非 0 的对象数（这些绝不能被丢）
        "rle_objects": 0,       # 压缩族对象（一律走 raw）
    }

    blobs = {}
    changed = []
    for o in objects:
        raw_path = os.path.join(raw_dir, o["raw"])
        if not os.path.isfile(raw_path):
            raise SystemExit("!! 缺少 %s" % raw_path)
        raw = open(raw_path, "rb").read()

        g = o["graphicSize"]
        if g is None or g < 0:
            raise SystemExit("!! %s 的 graphicSize 无效: %r" % (o["raw"], g))
        if len(raw) < HEADER_SIZE + g:
            raise SystemExit(
                "!! %s 长度 %d < 28+graphicSize(%d)=%d —— raw 与 manifest 不一致"
                % (o["raw"], len(raw), g, HEADER_SIZE + g))
        tail = raw[HEADER_SIZE + g:]
        if any(tail):
            stats["tail_nonzero"] += 1
        if o.get("kind") not in (None, "BMP"):
            stats["rle_objects"] += 1

        # ── 决定是否用 PNG 重编码 ──────────────────────────────────────
        use_png = False
        src_png = None
        if o.get("png"):
            src_png, origin = pick_source_png(in_dir, overlay_dir, o["png"])
            if src_png is not None:
                if origin == "overlay":
                    stats["overlay_used"] += 1
                    if sha256_file(src_png) != o.get("png_sha256_at_unpack"):
                        stats["overlay_changed"] += 1
                cur = sha256_file(src_png)
                if o.get("png_sha256_at_unpack") and \
                        cur != o["png_sha256_at_unpack"]:
                    use_png = True
                elif not o.get("raw"):
                    use_png = True

        if not use_png:
            blobs[o["index"]] = raw
            stats["verbatim"] += 1
            continue

        # ── 硬闸 1：只允许未压缩 BMP 重编码 ────────────────────────────
        if o.get("kind") != "BMP":
            raise SystemExit(
                "!! 对象 %s 是 %s（压缩族）却被改动 —— 重编码与 flags 不符，"
                "拒绝写出坏数据。请只改动未压缩 BMP 对象。"
                % (o.get("png") or o["raw"], o.get("kind")))

        from PIL import Image
        idx = M.encode_bmp(Image.open(src_png), pal_rgb, lut)

        # ── 硬闸 2：重编码长度必须与原 graphicSize 相同 ────────────────
        if len(idx) != g:
            raise SystemExit(
                "!! %s 重编码后 %d 字节 != 原 graphicSize %d —— 长度变化会让"
                "该对象及其后所有对象的偏移移动。请检查 PNG 尺寸/格式。"
                % (o["png"], len(idx), g))

        blobs[o["index"]] = raw[:HEADER_SIZE] + idx + tail
        changed.append(o["index"])
        stats["reencoded"] += 1

    # ── 排版：offset 必须与 manifest 记录的 orig_offset 逐一相同 ───────
    #    这是"不移动任何对象"的可执行断言 —— 长度不变则偏移必然不变，
    #    这里再独立核一遍，防上游引入长度漂移。
    data_start = M.HEADER_TABLE_OFF + n_obj * M.ENTRY_SIZE
    phys = sorted(objects, key=lambda o: o["orig_offset"])
    new_off = {}
    cur = data_start
    for o in phys:
        new_off[o["index"]] = cur
        cur += len(blobs[o["index"]])

    moved = [(o["raw"], o["orig_offset"], new_off[o["index"]])
             for o in objects if new_off[o["index"]] != o["orig_offset"]]
    if moved:
        raise SystemExit(
            "!! %d 个对象偏移发生移动（前 3 例：%s）—— 拒绝写出。"
            % (len(moved), moved[:3]))

    out = bytearray()
    out += struct.pack("<I", int(man["fileid"], 16))
    out += palette
    out += struct.pack("<I", n_obj)
    for o in objects:
        out += struct.pack("<II", o["key"], new_off[o["index"]])
    for o in phys:
        out += blobs[o["index"]]
    data = bytes(out)

    stats["size"] = len(data)
    stats["sha256"] = hashlib.sha256(data).hexdigest()
    stats["changed_indices"] = changed

    # 目录表 offset 与实际数据边界再解析一遍（自证产出的 dat 可被读回）
    try:
        fid2, pal2, entries2 = M.parse_container(data)
    except Exception as e:                      # noqa: BLE001
        raise SystemExit("!! 产物无法被 am3_dat.parse_container 解析: %s" % e)
    if fid2 != int(man["fileid"], 16) or pal2 != palette or len(entries2) != n_obj:
        raise SystemExit("!! 产物回读与 manifest 不一致（fileid/调色板/对象数）")

    stats["expect_size"] = expect_size
    stats["size_matches_expect"] = (expect_size is None
                                    or expect_size == len(data))
    if verbose:
        print("pack(无损) %s -> %d bytes, %d objects"
              % (os.path.basename(in_dir.rstrip("\\/")), len(data), n_obj))
        print("  原样回填 %d / 重编码 %d   （覆盖层命中 %d，其中内容不同 %d）"
              % (stats["verbatim"], stats["reencoded"],
                 stats["overlay_used"], stats["overlay_changed"]))
        print("  压缩族对象 %d（一律走 raw）；尾部非 0 的对象 %d（已保留）"
              % (stats["rle_objects"], stats["tail_nonzero"]))
        print("  对象偏移全部未移动  OK")
    return data, stats


def main():
    ap = argparse.ArgumentParser(
        description="3 代 dat 无损回包（保留对象头与 24 字节尾）")
    ap.add_argument("in_dir", help="解包目录（含 manifest.json/palette.bin/raw/png）")
    ap.add_argument("out_path", help="输出的 .dat 路径")
    ap.add_argument("--overlay", default=None,
                    help="PNG 覆盖层目录（内容优先于 png/，如 title/png_control_chs）")
    ap.add_argument("--expect-size", type=int, default=None,
                    help="断言产物字节数（CI 上填原版 dat 大小）")
    args = ap.parse_args()

    if not os.path.isdir(args.in_dir):
        print("!! 目录不存在: %s" % args.in_dir, file=sys.stderr)
        return 1
    if args.overlay and not os.path.isdir(args.overlay):
        print("!! 覆盖层目录不存在: %s" % args.overlay, file=sys.stderr)
        return 1

    data, stats = build(args.in_dir, args.overlay, args.expect_size)

    if not stats["size_matches_expect"]:
        print("!! 产物 %d 字节 != --expect-size %d"
              % (stats["size"], stats["expect_size"]), file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(os.path.abspath(args.out_path)), exist_ok=True)
    with open(args.out_path, "wb") as f:
        f.write(data)
    print("  -> %s  (%d bytes, sha256=%s)"
          % (args.out_path, len(data), stats["sha256"][:16]))
    if stats["expect_size"] is not None:
        print("  --expect-size %d 断言通过" % stats["expect_size"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
