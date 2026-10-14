"""构建《玩具兵大战2》汉化 update 资产包。

输入（本机私有路径，不进仓库）：
    中文母盘  = I:\\LocalGames\\Army Men\\玩具兵大战2
    Steam 基线 = I:\\LocalGames\\Army Men\\Army Men II STEAM

输出：
    Army2_NEW_CHS/        差异资产清单 + 逐文件复制（供人工审阅 / git 跟踪）
    build_out_am2/update/ 可直接落包的 update 目录

设计原则（承接 1 代 04-asset-pipeline.md）：
  * **不做整包替换**，只放"确实含中文"的文件
  * 逐文件 sha256 对账，差异必须逐个人工定性（汉化 / 重编码 / 无关改动）
  * 同一份输入连跑两次结果必须一致（幂等）

判据来源（全部实测，见 ArmyMen2-汉化可行性-逆向侦察报告.md）：
  * .txt      含 showpda/showfailure/showmessage 中文
  * .bmp      中文烧字（目视确认：任务简报地图 / 教程文 / 载入画面）
  * .wav      真中文配音（互相关 ≈0，排除重采样）
  * shared.dat / title.dat  中文 UI 精灵（目视确认）
  * .smk      画面逐像素相同，仅音轨为中文配音
  * kitchen.amm / heal.wav  **排除**（地图属性编辑 / 音频重编码，非汉化）

用法：
    python Tools/unpack_objects/build_update_am2.py
    python Tools/unpack_objects/build_update_am2.py --chs <dir> --steam <dir> --out <dir>
"""

import argparse
import hashlib
import os
import shutil
import struct
import sys

# ── 默认本机路径（CI 必须显式传参）────────────────────────────────────────
DEF_CHS = r"I:\LocalGames\Army Men\玩具兵大战2"
DEF_STEAM = r"I:\LocalGames\Army Men\Army Men II STEAM"
DEF_OUT = "build_out_am2"

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# IDA 工作文件不该被视为游戏资产
IDA_SUFFIX = (".id0", ".id1", ".id2", ".id3", ".nam", ".til", ".i64")

# ── 下发白名单（★ fail-closed：不在白名单里的一律不下发）────────────────
#   设计教训：最初用"未知类型 -> 放行"的兜底逻辑，结果把 armymen2.exe
#   也打进了 update 包 —— 直接违反"永不修改 exe"的硬约束。
#   改为白名单后，任何新出现的文件类型都会落到 skipped 并显式报告，
#   逼人工定性，而不是静默下发。
#
#   .exe / .dll 永久排除：本项目的核心约束就是"不改游戏文件"。
PAYLOAD_EXT = {
    ".bmp": "含中文烧字",
    ".txt": "含中文文本",
    ".wav": "中文配音",
    ".dat": "含中文 UI 精灵（shared/title）",
    ".smk": "含中文配音音轨",
}

# 无扩展名但确属汉化必需的文件（按文件名精确匹配，小写）
PAYLOAD_NAMES = {
    "hzk16": "中文字库（渲染器数据源）",
}

# 明确排除：差异已定性为"非汉化"
#   data\kitchen\kitchen.amm : 23 字节 0x0f<->0x00，地图属性编辑，与文字无关
#   audio\heal.wav           : ±1 LSB 重编码，采样参数完全相同，听感无差别
#   options.cfg              : 运行时会重新生成的玩家配置，覆盖它无意义
EXCLUDE = {
    "data/kitchen/kitchen.amm",
    "audio/heal.wav",
    "options.cfg",
}

# Steam 侧独有的文件（我们不需要，也不该下发）
# 由 diff 自动得出，无需列举。


def sha256(path, bufsize=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(bufsize), b""):
            h.update(chunk)
    return h.hexdigest()


def walk(root):
    """返回 {相对路径(小写, 反斜杠): 绝对路径}"""
    out = {}
    for dp, dn, fn in os.walk(root):
        for f in fn:
            if f.lower().endswith(IDA_SUFFIX):
                continue
            p = os.path.join(dp, f)
            out[os.path.relpath(p, root).lower()] = p
    return out


def norm_key(rel):
    return rel.replace("\\", "/")


def classify(rel):
    """把相对路径归类，用于清单分组与日志。"""
    ext = os.path.splitext(rel.lower())[1]
    return ext.lstrip(".") or "other"


def payload_reason(rel):
    """返回下发理由；不在白名单则返回 None（fail-closed）。

    ★ 这里**不做"未知类型放行"的兜底**。任何未列出的类型都必须显式报告，
      由人工定性后再加入白名单 —— 避免把 exe/dll 这类文件静默打进包。
    """
    low = rel.lower()
    ext = os.path.splitext(low)[1]
    # 先按扩展名白名单
    if ext in PAYLOAD_EXT:
        return PAYLOAD_EXT[ext]
    # 再按精确文件名（无扩展名或特例）
    base = os.path.basename(low)
    if base in PAYLOAD_NAMES:
        return PAYLOAD_NAMES[base]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chs", default=DEF_CHS, help="中文母盘目录")
    ap.add_argument("--steam", default=DEF_STEAM, help="Steam 基线目录")
    ap.add_argument("--out", default=DEF_OUT, help="输出根目录名（相对仓库根）")
    ap.add_argument("--no-movies", action="store_true",
                    help="不下发 3 个 .smk（省 129 MB，代价是电影仍为英文配音）")
    args = ap.parse_args()

    chs_root = args.chs
    steam_root = args.steam
    out_root = args.out if os.path.isabs(args.out) else os.path.join(ROOT, args.out)
    new_chs = os.path.join(ROOT, "Army2_NEW_CHS")

    for p, n in ((chs_root, "中文母盘"), (steam_root, "Steam 基线")):
        if not os.path.isdir(p):
            print("!! %s 不存在: %s" % (n, p), file=sys.stderr)
            return 1

    print("中文母盘  : %s" % chs_root)
    print("Steam 基线: %s" % steam_root)
    print("输出      : %s" % out_root)
    print()

    A = walk(chs_root)
    B = walk(steam_root)
    print("CHS 文件=%d  STEAM 文件=%d" % (len(A), len(B)))

    # ── 分类：三个集合 ──────────────────────────────────────────────────
    only_chs = sorted(set(A) - set(B))
    only_steam = sorted(set(B) - set(A))
    both = sorted(set(A) & set(B))

    same, diff = [], []
    for rel in both:
        if sha256(A[rel]) == sha256(B[rel]):
            same.append(rel)
        else:
            diff.append(rel)

    print("仅 CHS=%d  仅 STEAM=%d  相同=%d  不同=%d"
          % (len(only_chs), len(only_steam), len(same), len(diff)))

    # ── 决定下发集合（白名单，fail-closed）──────────────────────────────
    payload = []            # (rel, 来源绝对路径, 理由)
    skipped = []            # (rel, 理由)

    # 1) 差异文件
    for rel in diff:
        k = norm_key(rel)
        if k in EXCLUDE:
            skipped.append((rel, "已定性为非汉化/无意义差异"))
            continue
        if rel.lower().endswith(IDA_SUFFIX):
            skipped.append((rel, "IDA 工作文件"))
            continue
        cat = classify(rel)
        if cat == "smk" and args.no_movies:
            skipped.append((rel, "--no-movies 跳过"))
            continue
        reason = payload_reason(rel)
        if reason is None:
            # ★ 关键：未知类型显式报告，绝不静默下发
            skipped.append((rel, "不在下发白名单（需人工定性）"))
            continue
        payload.append((rel, A[rel], reason))

    # 2) 仅 CHS 有的：同样走白名单
    for rel in only_chs:
        reason = payload_reason(rel)
        if reason is not None:
            payload.append((rel, A[rel], reason))
        else:
            skipped.append((rel, "仅中文版有的非汉化文件（附带程序/快捷方式等）"))

    # ── 统计 ────────────────────────────────────────────────────────────
    print("\n== 下发清单（%d 项）==" % len(payload))
    bycat = {}
    total = 0
    for rel, src, reason in payload:
        bycat.setdefault(classify(rel), []).append(rel)
        total += os.path.getsize(src)
    for cat in sorted(bycat):
        sz = sum(os.path.getsize(A[r]) for r in bycat[cat])
        print("  %-6s %3d 个  %10.2f MB" % (cat, len(bycat[cat]), sz / 1048576))
    print("  合计        %3d 个  %10.2f MB" % (len(payload), total / 1048576))

    print("\n== 跳过（%d 项）==" % len(skipped))
    sk_by = {}
    for rel, why in skipped:
        sk_by.setdefault(why, []).append(rel)
    for why in sorted(sk_by):
        print("  %-46s %d 项" % (why, len(sk_by[why])))
        if "白名单" in why:
            for r in sk_by[why]:
                print("        - %s" % r)

    # ── 写盘 ────────────────────────────────────────────────────────────
    update_dir = os.path.join(out_root, "update")
    if os.path.isdir(out_root):
        shutil.rmtree(out_root)
    os.makedirs(update_dir)

    manifest = []
    for rel, src, reason in payload:
        dst = os.path.join(update_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        # 确认复制成功（不信任"复制了几个文件"这种统计）
        if sha256(dst) != sha256(src):
            print("!! 复制后校验失败: %s" % rel, file=sys.stderr)
            return 1
        manifest.append({
            "path": norm_key(rel),
            "size": os.path.getsize(src),
            "sha256": sha256(src),
            "reason": reason,
        })

    # 清单（供审阅 + 校验）
    import json
    with open(os.path.join(out_root, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump({"game": "Army Men II", "count": len(manifest),
                   "files": manifest}, f, ensure_ascii=False, indent=1)

    # 人类可读清单
    with open(os.path.join(out_root, "MANIFEST.md"), "w", encoding="utf-8") as f:
        f.write("# Army Men II 汉化 update 资产清单\n\n")
        f.write("共 %d 个文件，%.2f MB\n\n" % (len(manifest), total / 1048576))
        f.write("| 路径 | 字节 | 理由 |\n|---|---|---|\n")
        for m in sorted(manifest, key=lambda m: m["path"]):
            f.write("| `%s` | %d | %s |\n" % (m["path"], m["size"], m["reason"]))

    # ── 同时把清单复制一份到 Army2_NEW_CHS（供 git 跟踪/审阅）────────────
    os.makedirs(new_chs, exist_ok=True)
    shutil.copyfile(os.path.join(out_root, "MANIFEST.json"),
                    os.path.join(new_chs, "MANIFEST.json"))
    shutil.copyfile(os.path.join(out_root, "MANIFEST.md"),
                    os.path.join(new_chs, "MANIFEST.md"))
    print("\n清单 -> %s" % os.path.join(out_root, "MANIFEST.md"))
    print("update -> %s" % update_dir)

    # ── 幂等性自检：重跑一次算出的清单应与刚才一致 ──────────────────────
    #    ★ 直接从**中文母盘原始文件**重新计算，不依赖任何可能被清掉的中间缓存
    #      （1 代坑 5：把"缓存缺失"误判成"内容不同"，37 块被扩成 273 块）
    print("\n== 幂等性自检 ==")
    sig1 = sorted((m["path"], m["sha256"]) for m in manifest)
    sig2 = []
    for rel in sorted(set(diff) | set(only_chs)):
        k = norm_key(rel)
        if k in EXCLUDE or rel.lower().endswith(IDA_SUFFIX):
            continue
        if classify(rel) == "smk" and args.no_movies:
            continue
        if payload_reason(rel) is None:
            continue
        sig2.append((k, sha256(A[rel])))
    sig2.sort()
    if sig1 == sig2:
        print("  OK  两次计算结果一致（%d 项）" % len(sig1))
    else:
        print("  !!  不一致：%d vs %d" % (len(sig1), len(sig2)), file=sys.stderr)
        for x in sorted(set(sig1) ^ set(sig2)):
            print("     %s" % x[0], file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
