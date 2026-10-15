# -*- coding: utf-8 -*-
"""独立复核 3 代汉化补丁产物（stage_am3）—— 不复用组装期的判断。

★ 设计原则（承接 2 代 verify_release_am2.py 的教训清单）：
  1. 报出**实际检查的条目数**
  2. **空转即失败**（一条都没查到 => 非零退出），防"校验器自己失效成假绿"
  3. 尽量让判据能**区分正误**（不是"文件存在就 OK"）
  4. 校验**最终产物**（stage_am3 里的 zip），不是中间目录

★ 为什么要独立校验、而不是信任 make_patch 的打印：
  补丁最常见的两种"装了但没效果"的失效模式都不会报错：
    (a) 代理 DLL 名字不对 -> 游戏拿不到 DirectInputCreateA，
        补丁完全不加载，且**没有任何提示**
    (b) ASI 没落成 .asi 后缀 -> Ultimate ASI Loader 不扫描，同样静默失效
  所以这里对 zip **内部**逐项断言，而不是看磁盘上的源文件。

检查项：
    A. zip 存在、可打开、CRC 全对
    B. 包根必备：dinput.dll / ddraw.dll / ddraw.ini
    B2. 包根说明与许可：LICENSE / License.txt / 必读说明.txt(BOM+CRLF) /
        两份 AI 辅助文件；License.txt 必须含随包分发的三方声明
        （cnc-ddraw / qwen3-tts），且项目主许可正文在内
    C. scripts/：Army3_Extend_Dll.asi + Hzk16
    C2. update/audio/vos/：中文配音 wav 数量（qwen3-tts 生成）
    D. update/：01-title / bitmaps / strings / title.dat / shared.dat
    E. update/ 里**没有**任何可执行文件（硬约束：不改游戏文件）
    F. dinput.dll 含具名导出 DirectInputCreateA（代理真的能命中）
    G. .asi 是 32 位 PE(0x14C) 且导出 ArmyMenTIS_Install / ArmyMenTIS_Uninstall
    H. Hzk16 魔数 'RSE\\x1a'、宽高 13x13（与 ASI 的硬校验一致）
    I. strings/strings.txt：320 行、CRLF、GBK 可解码
    J. title.dat / shared.dat：FILEID / 对象数与权威值一致、目录表可解析、
       **每个对象 blob 落在其 offset 区间内且长度 >= 28+graphicSize**
       （即回包没有丢尾部数据 —— 这正是 am3_dat.py pack 的老毛病）
    K. 与 build_out_am3/MANIFEST.json 逐条 sha256 对照（载荷未在打包期被改动）
        —— 配音 171 个 wav 也在清单内，故同样被逐条核对

用法：
    python Tools/ci/verify_release_am3.py stage_am3
"""

import glob
import hashlib
import json
import os
import struct
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "Tools"))

# 权威值（与 ci_build_am3.py 的 DAT_JOBS 一致；两处都写死是刻意的 ——
# 校验器的判据不该从被校验的对象里读出来）
DAT_SPECS = {
    "update/title.dat": {"fileid": 0x81920667, "nObjects": 203, "size": 4298896},
    "update/shared.dat": {"fileid": 0x81920668, "nObjects": 1113, "size": 2936433},
}

REQUIRED_ROOT = ["dinput.dll", "ddraw.dll", "ddraw.ini"]

# ── 包根说明与许可（统一标准 S11/S12/S13，与 1/2 代同一套命名）──────────
REQUIRED_ROOT_DOCS = ["LICENSE", "License.txt", "必读说明.txt"]
AI_FILES = [
    "如果不会安装，请把该文件发给AI，让AI教你.txt",
    "将此文件交给AI，让AI协助完善本项目.txt",
]
# ★ 三方声明必须随包分发：cnc-ddraw(MIT) 与 qwen3-tts(Apache-2.0) 分发的
#   是二进制/产物，许可要求附版权声明；UAL 是 MIT 同理。
#   ★ 只查 .txt 正文里出现这些标识，不查"文件多大" —— 空壳声明没意义。
LICENSE_REQUIRED_MARKS = [
    ("MIT License", "LICENSES/cnc-ddraw.txt 的 MIT 正文"),
    ("github.com/FunkyFr3sh", "cnc-ddraw 版权行"),
    ("Apache License", "LICENSES/qwen3-tts.txt 的 Apache-2.0 正文"),
    ("== ASILoader.txt", "随包分发的 Ultimate ASI Loader 声明"),
]

# ── 中文配音（qwen3-tts 生成，随 update\ 覆盖游戏英文原声）──────────────
#   ★ 数量下限写死：配音丢失的表现是"游戏照常跑但全是英文语音"，
#     不会报错、不会崩 —— 典型静默失效，只能靠数量断言拦。
AUDIO_PREFIX = "update/audio/vos/"
AUDIO_EXPECT_FILES = 171

REQUIRED_SCRIPTS = ["scripts/Army3_Extend_Dll.asi", "scripts/Hzk16"]
REQUIRED_UPDATE = [
    "update/title.dat", "update/shared.dat",
    "update/strings/strings.txt",
    "update/01-title/01_000_00_screen.bmp",
]
FORBIDDEN_UPDATE_EXT = {".exe", ".dll", ".asi", ".sys", ".ocx"}

# 解包记录（= 原版 dat 的权威快照）：用于断言产物**每个对象的偏移与长度
# 都与原版逐一相同**。这是"回包无损"的真正判据 —— 仅比总大小是不够的：
# 若在文件**中部**丢 24 字节、又在别处多 24 字节，总大小可以不变，但
# 其后所有对象都会错位。
#
# ★ 为什么不从产物自身推断：判据必须来自**被校验对象之外**的独立来源。
#   manifest.json 是 am3_dat.py unpack 原版 dat 时写下的，且带 source_sha256，
#   与产物无关。
UNPACK_MANIFESTS = {
    "update/title.dat": ("Army3_Object_CHS/title/manifest.json", "title.dat"),
    "update/shared.dat": ("Army3_Object_CHS/shared/manifest.json", "shared.dat"),
}

HZK_MAGIC = b"RSE\x1a"

fails = []
warns = []
checks = 0


def check(cond, label, detail=""):
    global checks
    checks += 1
    if cond:
        print("  [OK]   %s%s" % (label, ("  " + detail) if detail else ""))
    else:
        print("  [FAIL] %s%s" % (label, ("  " + detail) if detail else ""))
        fails.append(label)


def warn(label, detail=""):
    print("  [WARN] %s%s" % (label, ("  " + detail) if detail else ""))
    warns.append(label)


def pe_machine(b):
    if len(b) < 0x40:
        return None
    e_lfanew = struct.unpack_from("<I", b, 0x3C)[0]
    if e_lfanew + 6 > len(b):
        return None
    if b[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        return None
    return struct.unpack_from("<H", b, e_lfanew + 4)[0]


def parse_dat(b):
    """极简 3 代 dat 目录表解析（独立实现，不 import am3_dat —— 校验器不该
    用被校验对象的代码来判定它自己）。"""
    if len(b) < 1032:
        return None
    fileid = struct.unpack_from("<I", b, 0)[0]
    n = struct.unpack_from("<I", b, 1028)[0]
    if n == 0 or n > 200000:
        return None
    table_off = 1032
    if table_off + n * 8 > len(b):
        return None
    entries = []
    for i in range(n):
        key = struct.unpack_from("<I", b, table_off + i * 8)[0]
        off = struct.unpack_from("<I", b, table_off + i * 8 + 4)[0]
        entries.append((key, off))
    return fileid, entries


def main():
    if len(sys.argv) < 2:
        print("用法: python Tools/ci/verify_release_am3.py <stage_am3>", file=sys.stderr)
        return 1
    stage = os.path.abspath(sys.argv[1])
    zips = sorted(glob.glob(os.path.join(stage, "*.zip")))
    if not zips:
        print("!! %s 下没有 zip" % stage, file=sys.stderr)
        return 1
    zpath = zips[0]
    print("=" * 74)
    print("3 代汉化补丁产物校验")
    print("=" * 74)
    print("zip : %s  (%.2f MB)"
          % (zpath, os.path.getsize(zpath) / 1048576))
    print()

    z = zipfile.ZipFile(zpath)
    names = z.namelist()
    blobs = {}

    # ── A. zip 完整性 ──────────────────────────────────────────────────
    print("A. zip 完整性")
    check(z.testzip() is None, "CRC 全部正确")
    check(len(names) > 0, "条目非空", "%d 条目" % len(names))

    # ── B/C/D. 结构 ────────────────────────────────────────────────────
    print()
    print("B. 包根必备文件（代理 DLL / cnc-ddraw）")
    for n in REQUIRED_ROOT:
        check(n in names, "包根 %s" % n)

    # ── B2. 包根说明与许可 ─────────────────────────────────────────────
    print()
    print("B2. 包根说明与许可（S11/S12/S13）")
    for n in REQUIRED_ROOT_DOCS:
        check(n in names, "包根 %s" % n)
    for n in AI_FILES:
        check(n in names, "包根 %s" % n)

    readme = "必读说明.txt"
    if readme in names:
        rb = z.read(readme)
        check(rb[:3] == b"\xef\xbb\xbf", "必读说明.txt 带 UTF-8 BOM",
              "（记事本靠 BOM 判编码，缺了中文显示乱码）")
        check(b"\r\n" in rb, "必读说明.txt 为 CRLF 换行")
        check(len(rb) >= 500, "必读说明.txt 内容非空壳",
              "%d B" % len(rb))
    if "License.txt" in names:
        lt = z.read("License.txt").decode("utf-8", errors="replace")
        for mark, label in LICENSE_REQUIRED_MARKS:
            check(mark in lt, "License.txt 含 %s" % label)
        check("GNU GENERAL PUBLIC LICENSE" in lt.upper()
              or "GPL" in lt, "License.txt 含项目主许可（GPLv3）正文")
        print("       License.txt %d B" % len(z.read("License.txt")))

    print()
    print("C. scripts\\ 运行期文件")
    for n in REQUIRED_SCRIPTS:
        check(n in names, "%s" % n)

    # ── C2. 中文配音 ───────────────────────────────────────────────────
    print()
    print("C2. update\\audio\\vos\\ 中文配音（qwen3-tts 生成）")
    n_wav = [x for x in names
             if x.startswith(AUDIO_PREFIX) and x.lower().endswith(".wav")]
    check(len(n_wav) >= AUDIO_EXPECT_FILES,
          "配音 wav 数量 >= %d" % AUDIO_EXPECT_FILES,
          "%d 个（配音丢失的表现是游戏照常跑但语音全英文，不会报错）"
          % len(n_wav))
    # 抽查若干必须存在的关键台词：号手/HQ/平民三类各取一，
    #   防"数量够了但全是同一批文件重复"这类构造错误。
    for probe in ("Aah.wav", "Sarge_Eatplastic.wav", "HQ_Goodwork.wav",
                  "Tina_ImTina.wav"):
        check(AUDIO_PREFIX + probe in names, "配音含 %s" % probe)
    tot_audio = sum(z.getinfo(x).file_size for x in n_wav)
    check(tot_audio > 10000000, "配音总体积 > 10 MB",
          "%.2f MB" % (tot_audio / 1048576))

    print()
    print("D. update\\ 载荷")
    for n in REQUIRED_UPDATE:
        check(n in names, "%s" % n)
    n_01 = [x for x in names if x.startswith("update/01-title/")]
    n_bm = [x for x in names if x.startswith("update/bitmaps/")]
    n_st = [x for x in names if x.startswith("update/strings/")]
    check(len(n_01) >= 1, "update/01-title/ 非空", "%d 文件" % len(n_01))
    check(len(n_bm) >= 50, "update/bitmaps/ 齐全", "%d 文件" % len(n_bm))
    check(len(n_st) >= 1, "update/strings/ 非空", "%d 文件" % len(n_st))

    # ── E. update/ 不得含可执行文件 ────────────────────────────────────
    print()
    print("E. update\\ 不得含可执行文件（硬约束：不改游戏文件）")
    bad = [n for n in names
           if n.startswith("update/")
           and os.path.splitext(n)[1].lower() in FORBIDDEN_UPDATE_EXT]
    check(not bad, "无可执行文件", "" if not bad else "混入 %s" % bad[:5])

    # ── F. 代理 DLL 具名导出 ───────────────────────────────────────────
    print()
    print("F. 代理 dinput.dll 必须含具名导出 DirectInputCreateA")
    blobs["dinput.dll"] = z.read("dinput.dll")
    m = pe_machine(blobs["dinput.dll"])
    check(m == 0x14C, "dinput.dll 是 32 位 PE", "machine=0x%X" % (m or 0))
    check(b"DirectInputCreateA" in blobs["dinput.dll"],
          "导出名 DirectInputCreateA 存在",
          "（游戏按名字导入，缺失则补丁完全不加载且无报错）")

    # ── G. ASI 位数与导出 ──────────────────────────────────────────────
    print()
    print("G. scripts\\Army3_Extend_Dll.asi 位数与导出")
    asi = z.read("scripts/Army3_Extend_Dll.asi")
    blobs["scripts/Army3_Extend_Dll.asi"] = asi
    m = pe_machine(asi)
    check(m == 0x14C, "ASI 是 32 位 PE", "machine=0x%X" % (m or 0))
    for exp in (b"ArmyMenTIS_Install", b"ArmyMenTIS_Uninstall"):
        check(exp in asi, "导出 %s" % exp.decode())
    # ★ 前缀碰撞自证：ArmyMenTIS_Install 是 ArmyMenTIS_Uninstall 的前缀吗？
    #   不是（Install vs Uninstall 在第 11 字节就分叉），但若将来把导出名改成
    #   一个包含另一个的形式（如 xxx / xxxEx），子串断言会双双"通过"却是错的。
    #   这里显式核一遍二者互不为前缀，让该断言真有区分力。
    check(not b"ArmyMenTIS_Install".startswith(b"ArmyMenTIS_Uninstall")
          and not b"ArmyMenTIS_Uninstall".startswith(b"ArmyMenTIS_Install"),
          "两个导出名互不为前缀（子串断言具备区分力）")
    print("       ASI 大小 %d B" % len(asi))

    # ── H. Hzk16 字库 ──────────────────────────────────────────────────
    print()
    print("H. scripts\\Hzk16 魔数与几何")
    hzk = z.read("scripts/Hzk16")
    blobs["scripts/Hzk16"] = hzk
    check(hzk[:4] == HZK_MAGIC, "魔数 RSE\\x1a",
          "实际 %r" % hzk[:4])
    # ★ 字段偏移必须按 ASI 源码（src/hzk16.cpp 的 Hzk16Font::Load）来，
    #   不能想当然：宽/高在 **0x14/0x16**（WORD），不是 0x2C/0x30。
    #   0x48 是 DWORD（数据起始 0x694C）、0x50 是 WORD(26 B/字形)、
    #   0x52 是 WORD(6768 字形数)。2 代曾把 0x50/0x52 当 DWORD 读，
    #   读成 0x1A70001A，几何校验失败、字库被误判不可用。
    if len(hzk) > 0x1C:
        w, h = struct.unpack_from("<HH", hzk, 0x14)
        check((w, h) == (13, 13), "字形 13x13（ASI 硬校验值）",
              "实际 %dx%d" % (w, h))
        lo, hi = struct.unpack_from("<HH", hzk, 0x18)[0], \
            struct.unpack_from("<HH", hzk, 0x1C)[0]
        check((lo, hi) == (0xA1B0, 0xFEF7), "GBK 覆盖范围 A1B0-FEF7",
              "实际 %04X-%04X" % (lo, hi))
    if len(hzk) > 0x54:
        data_start = struct.unpack_from("<I", hzk, 0x48)[0]
        bpg, nglyph = struct.unpack_from("<HH", hzk, 0x50)
        check(bpg == 26, "每字形 26 B", "实际 %d" % bpg)
        check(nglyph == 6768, "字形数 6768", "实际 %d" % nglyph)
        check(data_start == 0x694C, "数据起始 0x694C",
              "实际 0x%X" % data_start)
    check(len(hzk) == 202966, "字库大小 202966 B", "实际 %d" % len(hzk))
    print("       Hzk16 大小 %d B" % len(hzk))

    # ── I. strings.txt 三条硬约束（来自 exe 反编译）────────────────────
    print()
    print("I. update\\strings\\strings.txt（exe 硬约束）")
    st = z.read("update/strings/strings.txt")
    blobs["update/strings/strings.txt"] = st
    n_lines = st.count(b"\n")
    n_crlf = st.count(b"\r\n")
    check(n_lines >= 320, "行数 >= 320（低于则游戏拒绝启动）",
          "%d 行" % n_lines)
    check(n_crlf == n_lines, "全部为 CRLF",
          "CRLF=%d / LF=%d" % (n_crlf, n_lines))
    check(b"\xef\xbb\xbf" != st[:3], "无 UTF-8 BOM（游戏按字节读）")
    try:
        st.decode("gbk")
        check(True, "GBK 可完整解码")
    except UnicodeDecodeError as e:
        check(False, "GBK 可完整解码", str(e))
    maxlen = max(len(x) for x in st.split(b"\r\n"))
    check(maxlen <= 510, "无超长行（fgets 上限 510）", "最长 %d B" % maxlen)
    nonascii = sum(1 for c in st if c > 0x7F)
    check(nonascii > 0, "确实含非 ASCII 字节（是中文译文而非英文原样）",
          "%d 个" % nonascii)

    # ── J. 两条 dat 结构 + 尾部完整性 ──────────────────────────────────
    print()
    print("J. update\\title.dat / shared.dat 结构与尾部完整性")
    for rel, spec in sorted(DAT_SPECS.items()):
        b = z.read(rel)
        blobs[rel] = b
        check(len(b) == spec["size"], "%s 大小 %d" % (rel, spec["size"]),
              "实际 %d" % len(b))
        parsed = parse_dat(b)
        if not parsed:
            check(False, "%s 目录表可解析" % rel)
            continue
        fileid, entries = parsed
        check(fileid == spec["fileid"], "%s FILEID 0x%08X"
              % (rel, spec["fileid"]), "实际 0x%08X" % fileid)
        check(len(entries) == spec["nObjects"],
              "%s 对象数 %d" % (rel, spec["nObjects"]),
              "实际 %d" % len(entries))
        # 目录表 offset 必须落在数据区内
        data_start = 1032 + len(entries) * 8
        offs = [o for _, o in entries]
        check(max(offs) < len(b), "%s 偏移不越界" % rel)
        # ★ 每个对象的 blob 必须容得下它的载荷：
        #     - 任何对象都至少要有 28 字节头
        #     - graphicSize > 0 时须有 28+graphicSize <= blob
        #     - graphicSize == 0 **是合法的**，但只对压缩族（RLE/WRLE/TRLE/
        #       SRLE/DRLE）：压缩流的长度由 blob 长度隐含，头部不记长度。
        #       实测 shared.dat 有 31 个 SRLE 对象 graphicSize==0
        #       —— **原版就是如此**，不是回包损坏。
        #   （这一条判据最初写成 g<=0 即失败，把原版的正常状态误判成损坏。
        #     校验器必须先在**原版**上通过，才有资格判产物。）
        order = sorted(range(len(entries)), key=lambda i: entries[i][1])
        bad = []
        n_zero_rle = 0
        for pos, i in enumerate(order):
            s = entries[i][1]
            e = entries[order[pos + 1]][1] if pos + 1 < len(order) else len(b)
            blen = e - s
            if blen < 28:
                bad.append((i, "blob 仅 %d B < 28" % blen))
                continue
            flags = struct.unpack_from("<i", b, s + 12)[0]
            g = struct.unpack_from("<i", b, s + 24)[0]
            compressed = bool(flags & 0x3E)      # RLE|DRLE|WRLE|TRLE|SRLE
            if g == 0:
                n_zero_rle += 1
                if not compressed:
                    bad.append((i, "graphicSize=0 但非压缩族 (flags=0x%X)" % flags))
                continue
            if g < 0 or 28 + g > blen:
                bad.append((i, "28+graphicSize=%d > blob=%d" % (28 + g, blen)))
        check(not bad,
              "%s 每个对象 blob 载荷自洽（尾部未被截断）" % rel,
              "" if not bad else "异常前几例 %s" % bad[:5])
        print("       %s: graphicSize==0 的压缩对象 %d 个（原版即如此）"
              % (os.path.basename(rel), n_zero_rle))
        # 偏移必须两两不同，且排序后**无缝铺满**数据区（无空洞、无重叠）。
        #   ★ 不能按 index 顺序判递增 —— 目录表的条目顺序不等于物理顺序
        #     （实测 title/shared 的 entry[i].offset 就不是单调的）。
        #   ★ 原本这里写的是"数据连续到文件尾"，那句恒真（末对象的 e 就是
        #     len(b)，怎么算都成立），属于"看着在查、其实永远通过"的死判据
        #     （docs/07 记录的假绿失效方式之一）。改为真的查覆盖性。
        sorted_offs = sorted(offs)
        contiguous = (sorted_offs[0] == data_start)
        for k in range(len(sorted_offs) - 1):
            if sorted_offs[k] == sorted_offs[k + 1]:
                contiguous = False
                break
        check(len(set(offs)) == len(offs),
              "%s 对象偏移两两不同（无重复指向）" % rel)
        check(contiguous,
              "%s 首个对象紧接目录表" % rel,
              "min=%d data_start=%d" % (sorted_offs[0], data_start))

        # ★★ 核心判据：产物的**每个对象偏移与长度**必须与解包记录逐一相同。
        #    这才是"回包无损"的真正证明。仅比总大小抓不到"中部丢 24 B、
        #    别处多 24 B"这类总长不变的错位（J 的 28+gsize<=blob 也抓不到：
        #    对象 blob 本来是 28+gsize+24，砍掉 24 后仍满足 28+gsize<=blob）。
        man_rel, dat_name = UNPACK_MANIFESTS[rel]
        man_p = os.path.join(ROOT, man_rel.replace("/", os.sep))
        if not os.path.isfile(man_p):
            warn("%s 找不到解包记录 %s，跳过偏移逐一对照"
                 % (rel, man_rel))
        else:
            um = json.load(open(man_p, encoding="utf-8"))
            uobjs = sorted(um["objects"], key=lambda o: o["index"])
            # 先自证解包记录确实对应**原版**：它的 source_sha256 长度应与
            # 官方 dat 大小一致，且条数与产物一致。
            check(len(uobjs) == len(entries),
                  "%s 解包记录条数与产物一致" % rel,
                  "%d vs %d" % (len(uobjs), len(entries)))
            check(um.get("source_size") == spec["size"],
                  "%s 解包记录 source_size 为原版权威大小" % rel,
                  "%s" % um.get("source_size"))
            drift = []
            # 偏移与长度逐一对照：长度由"与下一个对象的偏移差"算出，
            # 因此这一条同时覆盖 offset 与 size 两个字段。
            order_map = {i: p for p, i in enumerate(order)}
            for i, u in enumerate(uobjs):
                if u["orig_offset"] != entries[i][1]:
                    drift.append((i, "offset", u["orig_offset"], entries[i][1]))
                    continue
                s = entries[i][1]
                p = order_map[i]
                e = entries[order[p + 1]][1] if p + 1 < len(order) else len(b)
                if u["size"] != (e - s):
                    drift.append((i, "size", u["size"], e - s))
            check(not drift,
                  "%s 每个对象偏移与长度与原版逐一相同（无损回包）" % rel,
                  "" if not drift else "漂移 %d 处，前几例 %s"
                  % (len(drift), drift[:4]))
            if not drift:
                print("       已逐一核对 %d 个对象的偏移与长度" % len(uobjs))

    # ── K. 与 build_out_am3/MANIFEST.json 对照 ─────────────────────────
    print()
    print("K. 载荷与 build_out_am3/MANIFEST.json 逐条对照")
    man_path = os.path.join(os.path.dirname(stage), "build_out_am3", "MANIFEST.json")
    if not os.path.isfile(man_path):
        warn("找不到 build_out_am3/MANIFEST.json，跳过载荷一致性对照",
             "（本地单独跑校验时正常；CI 上应能取到）")
    else:
        man = json.load(open(man_path, "r", encoding="utf-8"))
        rows = man["files"]
        check(len(rows) > 0, "MANIFEST 非空", "%d 条" % len(rows))
        mismatch = []
        missing = []
        for r in rows:
            rel = "update/" + r["path"]
            if rel not in names:
                missing.append(rel)
                continue
            data = z.read(rel)
            if len(data) != r["size"] or \
                    hashlib.sha256(data).hexdigest() != r["sha256"]:
                mismatch.append(rel)
        check(not missing, "MANIFEST 条项目标都在 zip 内",
              "" if not missing else "缺 %d 条，例 %s" % (len(missing), missing[:3]))
        check(not mismatch, "MANIFEST 条目 sha256 全部一致",
              "" if not mismatch else "%d 条不符，例 %s"
              % (len(mismatch), mismatch[:3]))
        print("       对照 %d 条载荷" % len(rows))

    z.close()

    # ── 结果 ───────────────────────────────────────────────────────────
    print()
    print("=" * 74)
    print("共 %d 项检查，失败 %d，警告 %d" % (checks, len(fails), len(warns)))
    if checks == 0:
        print("!! 一项都没检查 —— 校验器空转，不算通过", file=sys.stderr)
        return 1
    if fails:
        print("!! 失败项：")
        for f in fails:
            print("   - %s" % f)
        return 1
    print("全部通过。")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
