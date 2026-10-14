"""生成 A 批汉化文件：rules\\*_desc.txt（6 个帮助/规则说明）。

★ 与 B 批的本质区别（重要）：
  B 批文本在 exe 的字符串表里 -> 用 INI + 运行时内存补丁
  A 批文本**不在 exe 里**（全文搜过，0 命中）
      -> 是磁盘上的独立文件，按 "%s.txt" 命名规则加载
      -> 只能**直接产出汉化后的 .txt 文件**放进 update 包

★ 官方中文版这些文件也**完全是英文**（36/36 字节相同）
  => 属于新增翻译，不是"漏提取"。

★ 行数与换行（关键约束）：
  原文 CRLF，且按渲染宽度硬换行。中文更紧凑，但**必须保持相同行数**，
  否则文本框的竖向排版会变。本脚本逐行对齐、宽度上限取原行估算宽度。

宽度估算（与原行同一套算法，便于比较）：
  中文（>127）按 13px，ASCII 按 7px。译文行宽必须 <= 原行宽。

用法：
    python Tools/unpack_objects/gen_rules_chs_am2.py
输出：
    build_out_am2/update/rules/<name>.txt   （GBK + CRLF）
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_RULES = (sys.argv[sys.argv.index("--rules") + 1] if "--rules" in sys.argv
             else r"I:\LocalGames\Army Men\Army Men II STEAM\rules")
OUT_RULES = os.path.join(ROOT, "build_out_am2", "update", "rules")

# 逐行译文；行数必须与原文件一致（脚本会断言）
TRANS = {
    "death_desc.txt": [
        "击毙敌方中士得 100 分。",
        "误伤友军致死扣 100 分。",
        "最先达到目标分数的玩家或队伍获胜。",
    ],
    "killer_desc.txt": [
        "当你的中士持有黑旗时，击毙敌方中士得 250 分。",
        "这是唯一的得分方式。",
        "旗帜若 2 分钟无人持有，将自动返回基地。",
        "误伤友军致死扣 100 分。",
        "最先达到目标分数的玩家或队伍获胜。",
    ],
    "ctf_desc.txt": [
        "将敌方旗帜带回己方基地得 250 分。",
        "旗帜若 2 分钟无人持有，将自动返回基地。",
        "误伤友军致死扣 100 分。",
        "最先达到目标分数的玩家或队伍获胜。",
    ],
    "ctf_death_desc.txt": [
        "将敌方旗帜带回己方基地得 200 分。",
        "击毙敌方中士得 50 分。",
        "旗帜若 2 分钟无人持有，将自动返回基地。",
        "误伤友军致死扣 100 分。",
        "最先达到目标分数的玩家或队伍获胜。",
    ],
    # 原文 6 行（含末尾空行）：
    #   [0] Sarge scores 10 pts for every 3 seconds he holds the   (w=364)
    #   [1] black flag.                                            (w=77)
    #   [2..4] 三句通用规则
    #   [5] 空行（文件末尾的双 CRLF）
    # 中文更紧凑，第 0/1 行可合一 —— 但必须保持**行数一致**，
    # 否则文本框竖向排版会变。故第 1 行留空。
    "holdflag_desc.txt": [
        "中士每持有黑旗 3 秒得 10 分。",
        "",
        "旗帜若 2 分钟无人持有，将自动返回基地。",
        "误伤友军致死扣 100 分。",
        "最先达到目标分数的玩家或队伍获胜。",
        "",
    ],
    "koth_desc.txt": [
        "当中士是山顶上唯一的中士时，",
        "他成为山丘之王。山丘之王每在山上",
        "停留 3 秒得 10 分。当前的山丘之王",
        "由彩色旗帜标示。",
        "误伤友军致死扣 100 分。",
        "最先达到目标分数的玩家或队伍获胜。",
    ],
}


def width(s):
    """与原行同一套估算：中文 13px/字，ASCII 7px/字符。"""
    return sum(13 if ord(c) > 127 else 7 for c in s)


def read_lines(path):
    raw = open(path, "rb").read()
    txt = raw.decode("latin1")
    # 保留结构：按 CRLF 切，末尾空元素是文件末尾换行
    parts = txt.split("\r\n")
    if parts and parts[-1] == "":
        parts = parts[:-1]
    return parts


def update_manifest(written_files):
    """把 rules 汉化文件登记进 MANIFEST。

    ★ 为什么需要：MANIFEST 由 build_update_am2.py 依据"两版差异"生成，
      而这些 .txt 在**两版里完全相同**（官方也没翻），不属于差异文件，
      因此不会被它收录。但 ⑦ 独立校验会检查"磁盘文件必须都在清单内"，
      所以这里主动补登记，保持清单与实际内容一致。
    """
    import hashlib
    import json

    mj = os.path.join(ROOT, "build_out_am2", "MANIFEST.json")
    if not os.path.isfile(mj):
        print("[warn] 没有 MANIFEST.json，跳过登记")
        return

    with open(mj, encoding="utf-8") as f:
        data = json.load(f)

    files = data.get("files", [])
    have = {x["path"] for x in files}

    def sha256(p):
        h = hashlib.sha256()
        with open(p, "rb") as fp:
            for b in iter(lambda: fp.read(65536), b""):
                h.update(b)
        return h.hexdigest()

    added = 0
    for rel, abspath in written_files:
        key = rel.replace("\\", "/")
        if key in have:
            continue
        files.append({
            "path": key,
            "size": os.path.getsize(abspath),
            "sha256": sha256(abspath),
            "reason": "帮助/规则文本（两版均为英文，本项目新增翻译）",
        })
        added += 1

    data["files"] = files
    data["count"] = len(files)
    with open(mj, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    # 同步人类可读清单
    mm = os.path.join(ROOT, "build_out_am2", "MANIFEST.md")
    if os.path.isfile(mm):
        total = sum(x["size"] for x in files)
        with open(mm, "w", encoding="utf-8", newline="\n") as f:
            f.write("# Army Men II 汉化 update 资产清单\n\n")
            f.write("共 %d 个文件，%.2f MB\n\n" % (len(files), total / 1048576))
            f.write("| 路径 | 字节 | 理由 |\n|---|---|---|\n")
            for m in sorted(files, key=lambda m: m["path"]):
                f.write("| `%s` | %d | %s |\n"
                        % (m["path"], m["size"], m["reason"]))

    if added:
        print("[ OK ] MANIFEST 登记 %d 个 rules 文件（共 %d 项）" % (added, len(files)))


def main():
    if not os.path.isdir(SRC_RULES):
        print("!! 找不到源 rules 目录: %s" % SRC_RULES)
        return 1
    os.makedirs(OUT_RULES, exist_ok=True)

    fail = 0
    written = 0
    written_files = []
    for fn, zh_lines in TRANS.items():
        sp = os.path.join(SRC_RULES, fn)
        if not os.path.isfile(sp):
            print("[FAIL] 缺源文件 %s" % fn)
            fail += 1
            continue
        en_lines = read_lines(sp)

        # ★ 行数必须一致（否则版式变化）
        if len(en_lines) != len(zh_lines):
            print("[FAIL] %s 行数不符：原文 %d / 译文 %d"
                  % (fn, len(en_lines), len(zh_lines)))
            fail += 1
            continue

        # ★ 逐行宽度核对
        bad = []
        for i, (e, z) in enumerate(zip(en_lines, zh_lines)):
            we, wz = width(e), width(z)
            if wz > we:
                bad.append((i + 1, e, z, we, wz))
        if bad:
            print("[FAIL] %s 有 %d 行超宽：" % (fn, len(bad)))
            for ln, e, z, we, wz in bad:
                print("        第 %d 行 %d > %d : %r -> %r" % (ln, wz, we, e, z))
            fail += 1
            continue

        # 写出 GBK + CRLF（游戏用 GBK 查 Hzk16）
        out = "\r\n".join(zh_lines) + "\r\n"
        try:
            blob = out.encode("gbk")
        except Exception as ex:
            print("[FAIL] %s 无法编码 GBK: %s" % (fn, ex))
            fail += 1
            continue
        op = os.path.join(OUT_RULES, fn)
        with open(op, "wb") as f:
            f.write(blob)
        written += 1
        written_files.append((os.path.join("rules", fn), op))
        print("[ OK ] %-22s %2d 行  %4d 字节 -> %s"
              % (fn, len(zh_lines), len(blob), os.path.relpath(op, ROOT)))

    if written_files:
        update_manifest(written_files)

    print()
    print("写出 %d 个文件，失败 %d 个" % (written, fail))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
