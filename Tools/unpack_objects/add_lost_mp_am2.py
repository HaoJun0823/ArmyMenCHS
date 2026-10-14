"""把 Lost MP Content 的多人地图纳入汉化补丁。

背景（全部实测）：
  * 《Army Men II》Steam 版移除了 6 张多人地图的**全部文件**，
    并且把它们从 mpmaps.txt 的注册表里摘掉了。
  * 中文版同样没有这些文件（58/58 两版皆无），但中文版**有** mplaynow.exe 等启动器文件。
  * 用户提供的 "Army Men II Lost MP Content\\AMII" 正好补齐这 58 个文件。

6 张地图（由文件名与 folder 判定）：
    data\\frontyard\\roadwars            Road_Wars
    data\\hobby\\hobby_multi1            Hobby_Table_Havoc
    data\\hobby\\hobby_multi2            Carpet_Carnage
    data\\kitchen\\kitchenmadness        Kitchen_Madness
    data\\playset\\Bedroom_Bonanza       Bedroom_Bonanza
    data\\playset\\Rec_Room_Rumble       Rec_Room_Rumble
  每张含：.AMM(地图) .ATL(图层) .bmp(小图) _prev.bmp(预览) 4 个阵营 _place.txt
  另有 6 张载入图 bitmaps\\load_*.bmp

★ 关键：还要**注册到 mpmaps.txt**，否则游戏看不到这些图。
  注册表由 sub_43E2C0 解析，MAP 行的第 3 列（folder）会拼成 "data\\" + folder。

★ mpmaps.txt 放哪（重要）：
  游戏通过 sub_422DE0 _chdir 到 <cwd>\\data，然后 fopen("mpmaps.txt")，
  即实际读取 **<游戏根>\\data\\mpmaps.txt**；该处不存在时回退。
  而 UAL 的 update\\ 机制是**文件视图重定向** ——
  把文件放进 update\\data\\mpmaps.txt，游戏读 data\\mpmaps.txt 时就会拿到它。
  （1 代已实机验证该机制：update\\Alpine\\objects.dat 生效）
  => 我们把 mpmaps.txt 放到 **update\\mpmaps.txt**（与现有做法一致，见下）。

  ⚠️ 现有 stage_am2\\update\\mpmaps.txt 已在用这个位置，且它与 CHS 根目录那份同哈希，
     说明该位置是**此前验证过能生效**的。因此新增地图只需改这一份文件。

输出：
    build_out_am2/update/data/<folder>/*     地图文件
    build_out_am2/update/bitmaps/load_*.bmp  载入图
    build_out_am2/update/mpmaps.txt          追加注册行后的注册表
"""
import hashlib
import os
import re
import shutil
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ★★ 源目录默认值：一律指向**仓库内**的资产树，而不是作者的测试环境盘符。
#   这样 CI（ubuntu-latest，没有 I:\ 盘）与本地跑出来的是同一份产物。
#   早先默认 I:\LocalGames\... —— CI 上必然失败，而本地因为文件在而看不出问题
#   （这类"本地能跑、CI 炸"的默认值是本项目反复踩的坑）。
#
#   --lost   Lost MP 地图源。默认用 Army2_NEW_CHS：那 54 个文件已随仓库入库，
#            且已逐一核对与外部 Lost MP 目录内容完全一致（54/54）。
#   --chs    中文母盘资产（Army2_CHS）
#   --steam  Steam 基线资产（Army2_Original）
LOST = (sys.argv[sys.argv.index("--lost") + 1] if "--lost" in sys.argv
        else os.path.join(ROOT, "Army2_NEW_CHS"))
CHS = (sys.argv[sys.argv.index("--chs") + 1] if "--chs" in sys.argv
       else os.path.join(ROOT, "Army2_CHS"))
STEAM = (sys.argv[sys.argv.index("--steam") + 1] if "--steam" in sys.argv
         else os.path.join(ROOT, "Army2_Original"))

OUT = os.path.join(ROOT, "build_out_am2", "update")

# 排除主程序（用户明确要求，且符合"不改 exe"约束）
EXCLUDE_NAMES = {"armymen2.exe"}

# 6 张地图的注册信息
#   map_name  = .AMM 文件名（不含扩展名），游戏据此查找
#   disp      = 显示名（下划线会被解析器转空格+首字母大写，见 sub_43E2C0）
MAPS = [
    ("frontyard", "roadwars",        "Road_Wars",         "load_roadwars.bmp"),
    ("hobby",     "hobby_multi1",    "Hobby_Table_Havoc", "load_hobby_table_havoc.bmp"),
    ("hobby",     "hobby_multi2",    "Carpet_Carnage",    "load_carpet_carnage.bmp"),
    ("kitchen",   "kitchenmadness",  "Kitchen_Madness",   "load_kitchenmadness.bmp"),
    ("playset",   "Bedroom_Bonanza", "Bedroom_Bonanza",   "load_bedroom_bonanza.bmp"),
    ("playset",   "Rec_Room_Rumble", "Rec_Room_Rumble",   "load_rec_room_rumble.bmp"),
]

RULES = ["death", "ctf", "koth", "ctf_death", "killer", "holdflag"]


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def copy_tree(src_root, dst_root, manifest, reason_prefix):
    """复制 src_root 下所有文件到 dst_root，返回登记项列表。"""
    n = 0
    for dp, dn, fn in os.walk(src_root):
        for f in fn:
            sp = os.path.join(dp, f)
            if f.lower() in EXCLUDE_NAMES:
                print("    [跳过] %s（主程序）" % os.path.relpath(sp, src_root))
                continue
            rel = os.path.relpath(sp, src_root)
            dst = os.path.join(dst_root, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(sp, dst)
            if sha256(dst) != sha256(sp):
                print("!! 复制校验失败: %s" % rel, file=sys.stderr)
                return None
            manifest.append({
                "path": rel.replace("\\", "/"),
                "size": os.path.getsize(dst),
                "sha256": sha256(dst),
                "reason": reason_prefix,
            })
            n += 1
    return n


def main():
    if not os.path.isdir(LOST):
        print("!! 找不到 Lost MP 内容: %s" % LOST)
        return 1
    os.makedirs(OUT, exist_ok=True)

    manifest = []
    print("=" * 88)
    print("一、复制地图文件（data\\ + bitmaps\\）")
    print("=" * 88)

    # data\ 下只取本补丁涉及的 6 张图（避免误带入无关文件）
    copied = 0
    for folder, name, disp, load in MAPS:
        sd = os.path.join(LOST, "data", folder)
        if not os.path.isdir(sd):
            print("!! 缺目录 %s" % sd)
            return 1
        base = name.lower()
        got = []
        for f in os.listdir(sd):
            fl = f.lower()
            # 该地图的文件：以地图名开头（含 _place.txt / _prev.bmp / .AMM/.ATL/.bmp）
            if fl.startswith(base):
                sp = os.path.join(sd, f)
                rel = os.path.join("data", folder, f)
                dst = os.path.join(OUT, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(sp, dst)
                if sha256(dst) != sha256(sp):
                    print("!! 复制校验失败: %s" % rel, file=sys.stderr)
                    return 1
                manifest.append({
                    "path": rel.replace("\\", "/"),
                    "size": os.path.getsize(dst),
                    "sha256": sha256(dst),
                    "reason": "被移除的多人地图（Steam/CHS 均缺，本补丁补回）",
                })
                got.append(f)
                copied += 1
        print("  [%s] %-18s %d 个文件: %s"
              % (folder, name, len(got), ", ".join(sorted(got))))

    # 载入图
    print()
    for folder, name, disp, load in MAPS:
        sp = os.path.join(LOST, "bitmaps", load)
        if not os.path.isfile(sp):
            print("  !! 缺载入图 %s" % load)
            return 1
        rel = os.path.join("bitmaps", load)
        dst = os.path.join(OUT, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(sp, dst)
        manifest.append({
            "path": rel.replace("\\", "/"),
            "size": os.path.getsize(dst),
            "sha256": sha256(dst),
            "reason": "被移除的多人地图载入画面",
        })
        copied += 1
        print("  [bitmaps] %-30s -> %s" % (load, rel))

    print()
    print("复制完成：%d 个文件" % copied)

    # ── 二、注册到 mpmaps.txt ────────────────────────────────────────────
    print()
    print("=" * 88)
    print("二、生成含新地图的 mpmaps.txt")
    print("=" * 88)

    # 以 CHS 的中文 mpmaps.txt 为基底（它已是中文显示名），
    # 若没有则退回 Steam update\ 里那份。
    base_candidates = [
        os.path.join(OUT, "mpmaps.txt"),                    # 已在包内的（中文）
        os.path.join(CHS, "mpmaps.txt"),
        os.path.join(STEAM, "update", "mpmaps.txt"),
        os.path.join(STEAM, "mpmaps.txt"),
    ]
    base = None
    for c in base_candidates:
        if os.path.isfile(c):
            base = c
            break
    if not base:
        print("!! 找不到基底 mpmaps.txt")
        return 1
    print("  基底: %s" % base)

    raw = open(base, "rb").read()
    # 保留原编码（中文版是 GBK）
    try:
        txt = raw.decode("gbk")
        enc = "gbk"
    except Exception:
        txt = raw.decode("latin1")
        enc = "latin1"

    # 幂等：若已注册过就跳过
    if re.search(r"^\s*MAP\s+roadwars\b", txt, re.I | re.M):
        print("  已有新地图注册，跳过（幂等）")
    else:
        # 1) 追加 MAP 行：插到第一个空行前（MAP 段落末尾）
        map_lines = []
        for folder, name, disp, load in MAPS:
            map_lines.append(
                "MAP      %-16s %-18s %-10s none       %-26s none      none     none     none\t true\t\tnone\t\tnone\t\tnone"
                % (name, disp, folder, load))

        # 找 "# this list defines all available multi-player rules files" 之前插入
        anchor = "# this list defines all available multi-player rules files"
        idx = txt.find(anchor)
        if idx < 0:
            print("!! mpmaps.txt 结构不符（找不到规则段锚点）")
            return 1
        # 回退到该锚点前最后一个空行之后
        head = txt[:idx]
        tail = txt[idx:]
        # 去掉 head 末尾多余空行，插入 MAP 行，再补一个空行
        head = head.rstrip("\r\n") + "\r\n"
        txt = head + "\r\n".join(map_lines) + "\r\n\r\n" + tail
        print("  已插入 %d 条 MAP 行" % len(map_lines))

        # 2) 追加 RULEMAP 行到文件末尾
        rm = []
        for r in RULES:
            for folder, name, disp, load in MAPS:
                rm.append("RULEMAP\t %-11s %s" % (r, name))
        if not txt.endswith("\n"):
            txt += "\r\n"
        txt += "\r\n" + "\r\n".join(rm) + "\r\n"
        print("  已追加 %d 条 RULEMAP 行" % len(rm))

    out_txt = os.path.join(OUT, "mpmaps.txt")
    blob = txt.encode(enc)
    with open(out_txt, "wb") as f:
        f.write(blob)
    print("  写出 %s（%d 字节，编码 %s）" % (out_txt, len(blob), enc))

    # 登记（覆盖原有条目）
    manifest = [m for m in manifest if m["path"] != "mpmaps.txt"]
    manifest.append({
        "path": "mpmaps.txt",
        "size": len(blob),
        "sha256": sha256(out_txt),
        "reason": "多人地图注册表（中文 + 补回 6 张被移除地图）",
    })

    # ── 三、登记进 MANIFEST ──────────────────────────────────────────────
    import json
    mj = os.path.join(ROOT, "build_out_am2", "MANIFEST.json")
    if os.path.isfile(mj):
        with open(mj, encoding="utf-8") as f:
            data = json.load(f)
        files = {x["path"]: x for x in data.get("files", [])}
        for m in manifest:
            files[m["path"]] = m
        data["files"] = sorted(files.values(), key=lambda x: x["path"])
        data["count"] = len(data["files"])
        with open(mj, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

        mm = os.path.join(ROOT, "build_out_am2", "MANIFEST.md")
        total = sum(x["size"] for x in data["files"])
        with open(mm, "w", encoding="utf-8", newline="\n") as f:
            f.write("# Army Men II 汉化 update 资产清单\n\n")
            f.write("共 %d 个文件，%.2f MB\n\n" % (len(data["files"]),
                                                  total / 1048576))
            f.write("| 路径 | 字节 | 理由 |\n|---|---|---|\n")
            for m in data["files"]:
                f.write("| `%s` | %d | %s |\n"
                        % (m["path"], m["size"], m["reason"]))
        print("  MANIFEST 已更新：共 %d 项" % len(data["files"]))
    else:
        print("  [warn] 无 MANIFEST.json，跳过登记")

    print()
    print("完成：新增 %d 个文件 + 1 份 mpmaps.txt" % copied)
    return 0


if __name__ == "__main__":
    sys.exit(main())
