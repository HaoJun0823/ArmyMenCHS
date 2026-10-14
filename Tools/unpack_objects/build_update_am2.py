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

# ── 源目录默认值 ──────────────────────────────────────────────────────────
#   ★ 默认指向**仓库内**的资产树（Army2_CHS / Army2_Original），使 CI 与
#     本地跑出同一份产物。作者本机的原始母盘可通过 --chs/--steam 显式指定。
#   早先默认写死 I:\LocalGames\... —— CI 上必然失败，而本地因为文件存在
#   完全看不出问题（"本地能跑、CI 炸"的典型）。
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEF_CHS = os.path.join(ROOT, "Army2_CHS")
DEF_STEAM = os.path.join(ROOT, "Army2_Original")
DEF_OUT = "build_out_am2"

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
#   ★ 不要往这里加 "hzk16"：字库由 ci_build_am2.py 取
#     Army2_CHS/Hzk16，最终只落在 stage\scripts\Hzk16 一处。
#     早先它同时出现在 update\Hzk16 / scripts\Hzk16 / Army2_NEW_CHS\Hzk16
#     三处，纯属重复（同一份 200 KB 文件打三遍）。
PAYLOAD_NAMES = {}

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
    """返回 {相对路径(casefold, 反斜杠): 绝对路径}

    ★★★ 关于这里的 casefold（2026-10 修正）★★★
      本函数原先用 `.lower()` 作字典键，而该键**同时被用作输出文件名**
      （见下方 `dst = os.path.join(update_dir, rel)`），后果是：

        · 99 个 audio/vos/*.wav 的文件名被改写成全小写，
          例：`0201TanTrooper.wav` -> `0201tantrooper.wav`
          （中文母盘原样是混合大小写）

      Windows 文件系统不区分大小写，游戏照常能读，所以本地一直没暴露。
      但这是**保真度缺陷**，而且会把偏差固化进 Linux 上产出的发布包。

      修法：键仍用 casefold（保证 CHS/Steam 两棵树能按"同一文件"配对比较），
      但**记住第一次出现的真实相对路径**，输出时用真实路径。
      即把 walk 的返回值从 {k: abs} 改为 {k: (real_rel, abs)}。

      碰撞检查：两个资产树内各目录均不存在"仅大小写不同"的同名文件
      （已实测 0 处），所以配对不会出错。
    """
    out = {}
    for dp, dn, fn in os.walk(root):
        for f in fn:
            if f.lower().endswith(IDA_SUFFIX):
                continue
            p = os.path.join(dp, f)
            real = os.path.relpath(p, root)
            out[real.lower()] = (real, p)
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

    # walk 返回 {casefold 键: (真实相对路径, 绝对路径)}。
    # 比较/配对用 casefold 键（同一文件在 CHS 与 Steam 里的键一致），
    # 但**输出文件名必须用真实相对路径**，否则会把混合大小写的文件名
    # 改写成全小写（见 walk() 的说明）。
    A_t = walk(chs_root)
    B_t = walk(steam_root)
    A = {k: v[1] for k, v in A_t.items()}
    B = {k: v[1] for k, v in B_t.items()}
    REAL_A = {k: v[0] for k, v in A_t.items()}   # 真实相对路径（保留大小写）
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
    #   payload 项 = (casefold 键, 来源绝对路径, 理由, 真实相对路径)
    #   · 前两个用于比较与读取
    #   · 第 4 个用于**写出文件名**（保留原始大小写）
    payload = []
    skipped = []            # (rel, 理由)

    def real_rel(k):
        """casefold 键 -> 真实相对路径（保留大小写）"""
        return REAL_A.get(k, k)

    # 1) 差异文件
    for rel in diff:
        k = norm_key(rel)
        if k.lower() in EXCLUDE:
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
        payload.append((rel, A[rel], reason, real_rel(rel)))

    # 2) 仅 CHS 有的：同样走白名单
    for rel in only_chs:
        reason = payload_reason(rel)
        if reason is not None:
            payload.append((rel, A[rel], reason, real_rel(rel)))
        else:
            skipped.append((rel, "仅中文版有的非汉化文件（附带程序/快捷方式等）"))

    # ── 统计 ────────────────────────────────────────────────────────────
    print("\n== 下发清单（%d 项）==" % len(payload))
    bycat = {}
    total = 0
    for rel, src, reason, _real in payload:
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
    for rel, src, reason, real in payload:
        # ★ 用真实相对路径（保留大小写）作为落盘名，避免把
        #   0201TanTrooper.wav 之类改写成全小写（见 walk() 说明）。
        dst = os.path.join(update_dir, real)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        # 确认复制成功（不信任"复制了几个文件"这种统计）
        if sha256(dst) != sha256(src):
            print("!! 复制后校验失败: %s" % real, file=sys.stderr)
            return 1
        manifest.append({
            "path": norm_key(real),
            "size": os.path.getsize(src),
            "sha256": sha256(src),
            "reason": reason,
        })
    # ★ 用 casefold 键索引，这样"母盘叫 0201TanTrooper.wav、NEW_CHS 叫
    #   0201tantrooper.wav"能被识别为**同一个文件**。
    #   早先用原样大小写作键，导致同一文件在表里出现两条（表 433 条、
    #   磁盘只有 325 个文件）—— 幂等性自检把它抓了出来。
    by_key = {m["path"].lower(): m for m in manifest}

    # ── 人工覆盖层：Army2_NEW_CHS 优先于中文母盘 ─────────────────────────
    #   为什么需要这一步（实机踩过的坑）：
    #     汉化流程是 Army2_CHS(母盘) -> build_out -> stage。
    #     而**手工修图**的成果放在 Army2_NEW_CHS —— 上面这条链根本不读它，
    #     所以手工汉化的 BMP 永远进不了补丁包（补丁里下发的是母盘原图）。
    #   规则：
    #     · 只接受**白名单内**的资产（复用 payload_reason，保持 fail-closed）
    #     · 同名以 NEW_CHS 的内容为准（手工成果赢）
    #     · 大小写不同视为同名（Windows 语义）
    #   ★ 但必须**再排除**两类不该进 update\ 的东西（第一版就踩了）：
    #       1) scripts/ —— 那是补丁包的目录（放 .asi / ini），
    #          它属于 stage_am2 根，不属于游戏资产树。
    #          NEW_CHS 里有一份 scripts/Hzk16，放进来会变成
    #          update\scripts\Hzk16 这种错位置。
    #       2) 字库 Hzk16/hzk16 —— 由 make_patch_am2.py 单独放进
    #          stage\scripts\Hzk16（DLL 在那找）。它是无扩展名文件，
    #          会被 PAYLOAD_NAMES 的 "hzk16" 命中而误入 update\ 根。
    #          三份副本（Hzk16/hzk16/scripts\Hzk16）纯属重复。
    OVERLAY_SKIP_TOP = {"scripts"}
    OVERLAY_SKIP_NAMES = {"hzk16"}

    print("\n== 人工覆盖层（Army2_NEW_CHS）==")
    if not os.path.isdir(new_chs):
        print("   (无 Army2_NEW_CHS，跳过)")
    else:
        # ★ 大小写安全：update\ 里可能已有"仅大小写不同"的同名文件
        #   （母盘是 0201TanTrooper.wav，而 NEW_CHS 里可能是
        #     0201tantrooper.wav）。Windows 不区分大小写，直接写会覆盖同名；
        #   但 **Linux 上会凭空多出一个重复文件**，把补丁撑大且可能出现
        #   两个同名不同大小写的资源。
        #   做法：以磁盘上**已存在的真实名字**为准来写。
        existing_cf = {}
        for dp, _dn, fns in os.walk(update_dir):
            for fn in fns:
                full = os.path.join(dp, fn)
                rel = os.path.relpath(full, update_dir).replace(os.sep, "/")
                existing_cf[rel.lower()] = rel

        n_over = n_same = n_skip = 0
        for rel, (real, src) in sorted(walk(new_chs).items()):
            key = norm_key(real)
            top = key.split("/")[0].lower()
            base = os.path.basename(key).lower()
            if top in OVERLAY_SKIP_TOP or base in OVERLAY_SKIP_NAMES:
                n_skip += 1
                continue
            reason = payload_reason(real)
            if reason is None:
                n_skip += 1
                continue
            # 落盘名：优先沿用磁盘上已有的真实大小写，避免 Linux 下重复
            out_rel = existing_cf.get(key.lower(), real)
            dst = os.path.join(update_dir, out_rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
            if sha256(dst) != sha256(src):
                print("!! 覆盖后校验失败: %s" % out_rel, file=sys.stderr)
                return 1
            h = sha256(src)
            prev = by_key.get(key.lower())
            if prev is None:
                n_over += 1
                print("   + %-46s （新增）" % key)
            elif prev["sha256"] != h:
                n_over += 1
                print("   * %-46s （覆盖母盘版）" % key)
            else:
                n_same += 1
            by_key[key.lower()] = {
                "path": norm_key(out_rel),
                "size": os.path.getsize(src),
                "sha256": h,
                "reason": "人工汉化覆盖（Army2_NEW_CHS 优先）",
            }
        print("   覆盖/新增 %d 项，与母盘相同 %d 项，非资产/不该入包跳过 %d 项"
              % (n_over, n_same, n_skip))
        manifest = sorted(by_key.values(), key=lambda m: m["path"])

    # 覆盖层可能改动了内容，重新统计体积
    total = sum(m["size"] for m in manifest)
    # 清单（供审阅 + 校验）
    #   ★ newline="\n" 不能省：Windows 上文本模式默认把 \n 写成 \r\n，
    #     而 .gitattributes 声明 *.json/*.md 为 `text eol=lf`，
    #     于是"工作区 CRLF / 索引 LF"来回转换 —— 表现为
    #     "CRLF will be replaced by LF" 警告，且提交后工作区文件被判定为
    #     已修改（哈希漂移）。显式写 LF，让工作区与索引逐字节一致。
    import json
    with open(os.path.join(out_root, "MANIFEST.json"), "w", encoding="utf-8",
              newline="\n") as f:
        json.dump({"game": "Army Men II", "count": len(manifest),
                   "files": manifest}, f, ensure_ascii=False, indent=1)

    # 人类可读清单
    with open(os.path.join(out_root, "MANIFEST.md"), "w", encoding="utf-8",
              newline="\n") as f:
        f.write("# Army Men II 汉化 update 资产清单\n\n")
        f.write("共 %d 个文件，%.2f MB\n\n" % (len(manifest), total / 1048576))
        f.write("| 路径 | 字节 | 理由 |\n|---|---|---|\n")
        for m in sorted(manifest, key=lambda m: m["path"]):
            f.write("| `%s` | %d | %s |\n" % (m["path"], m["size"], m["reason"]))

    # ── 不再往 Army2_NEW_CHS 回写清单 ─────────────────────────────────
    #   ★ 这里以前把 build_out 的 MANIFEST.json/MD 复制到 Army2_NEW_CHS，
    #     但两者**内容不同**：NEW_CHS 还包含 3 部电影、scripts/ 等
    #     （由 Tools/build_new_chs_am2.py 从 update/ + stage/scripts 组装）。
    #     结果 NEW_CHS 里的清单描述的是 build_out —— 条目数 325 vs
    #     磁盘 347，自相矛盾（verify_assets_am2.py 抓到过）。
    #   现在各写各的：build_out 的清单在 build_out，
    #   NEW_CHS 的清单由 build_new_chs_am2.py 自己生成。
    print("\n清单 -> %s" % os.path.join(out_root, "MANIFEST.md"))
    print("update -> %s" % update_dir)

    # ── 幂等性自检：重跑一次算出的清单应与刚才一致 ──────────────────────
    #    ★ 直接从**中文母盘原始文件**重新计算，不依赖任何可能被清掉的中间缓存
    #      （1 代坑 5：把"缓存缺失"误判成"内容不同"，37 块被扩成 273 块）
    #    ★ 覆盖层也要算进来，否则"人工覆盖"的条目会被误判成不一致。
    print("\n== 幂等性自检 ==")
    #   ★ 用 casefold 键比较：母盘与 NEW_CHS 可能存在"仅大小写不同"的
    #     同一文件，若用原样大小写做键会误报不一致（已实测踩过）。
    #   ★ 同时以**磁盘实际内容**为最终依据 —— 清单必须是磁盘的忠实快照。
    sig1 = sorted((m["path"].lower(), m["sha256"]) for m in manifest)
    recomputed = {}
    for rel in sorted(set(diff) | set(only_chs)):
        k = norm_key(rel)
        if k.lower() in EXCLUDE or rel.lower().endswith(IDA_SUFFIX):
            continue
        if classify(rel) == "smk" and args.no_movies:
            continue
        if payload_reason(rel) is None:
            continue
        # 与上面写盘时一致：用真实相对路径（保留大小写）构造签名
        recomputed[norm_key(real_rel(rel)).lower()] = sha256(A[rel])
    # 覆盖层：NEW_CHS 里白名单内的资产覆盖同名项（与上面写盘用同一套排除）
    if os.path.isdir(new_chs):
        cf_now = {}
        for dp, _dn, fns in os.walk(update_dir):
            for fn in fns:
                full = os.path.join(dp, fn)
                r = os.path.relpath(full, update_dir).replace(os.sep, "/")
                cf_now[r.lower()] = r
        for rel, (real, src) in walk(new_chs).items():
            key = norm_key(real)
            top = key.split("/")[0].lower()
            base = os.path.basename(key).lower()
            if top in OVERLAY_SKIP_TOP or base in OVERLAY_SKIP_NAMES:
                continue
            if payload_reason(real) is None:
                continue
            recomputed[norm_key(cf_now.get(key.lower(), real)).lower()] = sha256(src)
    sig2 = sorted(recomputed.items())
    if sig1 == sig2:
        print("  OK  两次计算结果一致（%d 项）" % len(sig1))
    else:
        print("  !!  不一致：%d vs %d" % (len(sig1), len(sig2)), file=sys.stderr)
        for x in sorted(set(sig1) ^ set(sig2)):
            print("     %s" % x[0], file=sys.stderr)
        return 1

    # ── 最终一致性：清单条数必须等于磁盘文件数 ─────────────────────────
    #   这是"表里 433 条、磁盘 325 个"那个 bug 的直接防线。
    on_disk = []
    for dp, _dn, fns in os.walk(update_dir):
        for fn in fns:
            full = os.path.join(dp, fn)
            on_disk.append(os.path.relpath(full, update_dir).replace(os.sep, "/"))
    if len(on_disk) != len(manifest):
        print("  !! 清单 %d 条，磁盘 %d 个文件 —— 不一致"
              % (len(manifest), len(on_disk)), file=sys.stderr)
        return 1
    dset = sorted(x.lower() for x in on_disk)
    mset = sorted(m["path"].lower() for m in manifest)
    if dset != mset:
        only_d = sorted(set(dset) - set(mset))[:5]
        only_m = sorted(set(mset) - set(dset))[:5]
        print("  !! 清单与磁盘文件集不符：磁盘多 %s / 清单多 %s"
              % (only_d, only_m), file=sys.stderr)
        return 1
    print("  OK  清单与磁盘一致（%d 个文件）" % len(on_disk))

    return 0


if __name__ == "__main__":
    sys.exit(main())
