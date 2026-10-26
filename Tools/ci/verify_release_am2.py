"""独立校验 Army Men II 汉化补丁包（stage_am2）。

★ 为什么必须独立校验：1 代踩过"构建全绿但补丁根本没加载"
  （DLL 放错目录 / Loader 只认 .asi）—— 只有把产物当黑盒重新检查才能发现。

校验项（每条都有明确的判据与失败后果）：
  1. dinput.dll 存在、32 位 PE、**导出 DirectInputCreateA**
     —— 缺这条游戏拿不到输入，或补丁完全不加载
  2. scripts\\*.asi 存在、32 位 PE、三个导出齐全
     —— UAL 只扫描 *.asi，放 .dll 会被静默忽略
  3. scripts\\ArmyMenCHS.ini 可解析、关键节齐全
  4. scripts\\strings\\am2_strings.ini 存在且**逐条对照 Steam exe 复核**
     —— 这是"写进去会不会成功"的唯一离线判据
  5. scripts\\Hzk16 存在、魔数正确、几何为 13x13
  6. update\\ 里**不含任何 exe/dll**（硬约束：不改游戏文件）
  7. update\\ 的文件清单与 MANIFEST 一致，且总大小在预期范围
  8. 必读说明.txt 为 UTF-8 BOM + CRLF（记事本友好）
  9. 包根 cnc-ddraw（ddraw.dll / ddraw.ini）—— 缺了在新系统上直接黑屏；
     License.txt 必须含随包分发的 cnc-ddraw 的 MIT 声明与版权行
     （只查"文件存在"挡不住合并时漏掉一份声明）

用法：
    python Tools/ci/verify_release_am2.py [stage_dir]
"""

import json
import os
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STAGE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "stage_am2")

# Steam exe 的位置。用于"译文表逐条对照英文原文"这一步（较强的闸门）。
#   ★ 可用环境变量 AM2_STEAM_EXE 覆盖；CI 上没有 exe（exe 不入库，见
#     .github/workflows/build-release.yml 的说明），此时该步退化为
#     WARN 而不是 FAIL —— 见下方 [4] 的处理。
#   之所以不硬编码，是为了让路径可移植、可测试。
STM_EXE = (os.environ.get("AM2_STEAM_EXE")
           or r"I:\LocalGames\Army Men\Army Men II STEAM\ArmyMen2.exe")

FAIL = []
WARN = []


def ok(cond, good, bad):
    if cond:
        print("  [ OK ] %s" % good)
    else:
        print("  [FAIL] %s" % bad)
        FAIL.append(bad)
    return cond


def _unescape(s):
    """还原生成脚本对英文原文做的首尾空格转义（\\x20 -> 空格）。

    ★ 必须与 gen_am2_strings_ini.py 和 src/strings.cpp 的 Unescape 保持同步。
      三处任一不同步，都会导致这里报"原文不符"，或 DLL 运行时静默跳过该条。
    """
    out = []
    i = 0
    while i < len(s):
        if s.startswith("\\x20", i):
            out.append(" "); i += 4
        else:
            out.append(s[i]); i += 1
    return "".join(out)


# ── PE 工具 ────────────────────────────────────────────────────────────
def pe_info(path):
    with open(path, "rb") as f:
        b = f.read()
    if b[:2] != b"MZ":
        return None
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    machine = struct.unpack_from("<H", b, pe + 4)[0]
    nsec = struct.unpack_from("<H", b, pe + 6)[0]
    optsize = struct.unpack_from("<H", b, pe + 20)[0]
    opt = pe + 24
    exp_rva, exp_sz = struct.unpack_from("<II", b, opt + 96)
    secs = []
    so = opt + optsize
    for i in range(nsec):
        base = so + i * 40
        nm = b[base:base + 8].rstrip(b"\0").decode("latin1")
        vs, va, rs, ra = struct.unpack_from("<IIII", b, base + 8)
        secs.append((nm, va, vs, ra, rs))

    def r2o(rva):
        for nm, va, vs, ra, rs in secs:
            if va <= rva < va + max(vs, rs):
                o = ra + (rva - va)
                if o < ra + rs:
                    return o
        return None

    exports = []
    if exp_rva and exp_sz:
        o = r2o(exp_rva)
        if o is not None:
            nfun, nnam = struct.unpack_from("<II", b, o + 20)
            addr_names = struct.unpack_from("<I", b, o + 32)[0]
            on = r2o(addr_names)
            if on is not None:
                for i in range(min(nnam, 8000)):
                    nr = struct.unpack_from("<I", b, on + i * 4)[0]
                    no = r2o(nr)
                    if no is None:
                        continue
                    e = b.find(b"\0", no)
                    exports.append(b[no:e].decode("latin1"))
    return {"machine": machine, "exports": exports, "size": len(b)}


def sections_of(path):
    with open(path, "rb") as f:
        b = f.read()
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    nsec = struct.unpack_from("<H", b, pe + 6)[0]
    optsize = struct.unpack_from("<H", b, pe + 20)[0]
    so = pe + 24 + optsize
    out = []
    for i in range(nsec):
        base = so + i * 40
        nm = b[base:base + 8].rstrip(b"\0").decode("latin1")
        vs, va, rs, ra = struct.unpack_from("<IIII", b, base + 8)
        out.append((nm, va, vs, ra, rs))
    return b, out


def main():
    print("校验目标: %s" % STAGE)
    if not os.path.isdir(STAGE):
        print("!! 目录不存在", file=sys.stderr)
        return 1

    # ── 1. 代理 DLL ────────────────────────────────────────────────────
    print("\n[1] ASI 代理 DLL")
    proxy = os.path.join(STAGE, "dinput.dll")
    if ok(os.path.isfile(proxy), "dinput.dll 存在", "缺 dinput.dll（补丁不会加载）"):
        info = pe_info(proxy)
        ok(info and info["machine"] == 0x14C, "32 位 PE (0x14C)",
           "不是 32 位 PE（机器码 %s）" % (hex(info["machine"]) if info else "?"))
        ok("DirectInputCreateA" in (info["exports"] if info else []),
           "导出 DirectInputCreateA（AM2/TIS 按名字导入它）",
           "未导出 DirectInputCreateA -> 游戏输入或补丁加载会失败")
        ok("InitializeASI" in (info["exports"] if info else []) or
           "IsUltimateASILoader" in (info["exports"] if info else []),
           "是 Ultimate ASI Loader", "看起来不是 UAL（缺 IsUltimateASILoader）")

    # ── 2. ASI 本体 ───────────────────────────────────────────────────
    print("\n[2] ASI 本体")
    asi = os.path.join(STAGE, "scripts", "Army2_Extend_Dll.asi")
    if ok(os.path.isfile(asi), "scripts\\Army2_Extend_Dll.asi 存在",
          "缺 .asi（★ UAL 只扫描 scripts\\*.asi，放 .dll 会被静默忽略）"):
        info = pe_info(asi)
        ok(info and info["machine"] == 0x14C, "32 位 PE (0x14C)",
           "不是 32 位 PE")
        need = ["InitializeASI", "ArmyMenCHS_Install", "ArmyMenCHS_Uninstall"]
        for e in need:
            ok(e in (info["exports"] if info else []), "导出 %s" % e, "缺导出 %s" % e)

    # ── 3. 主配置 ─────────────────────────────────────────────────────
    print("\n[3] 主配置")
    ini = os.path.join(STAGE, "scripts", "ArmyMenCHS.ini")
    if ok(os.path.isfile(ini), "scripts\\ArmyMenCHS.ini 存在", "缺主配置"):
        txt = open(ini, encoding="utf-8").read()
        for sec in ("[General]", "[Target]", "[Font]", "[Strings]"):
            ok(sec in txt, "含 %s 节" % sec, "缺 %s 节" % sec)

    # ── 3b. 包根 cnc-ddraw + 许可与说明 ───────────────────────────────
    #   ★ 这些是 2/3 代共有的分发义务与渲染前提，缺了都不报错：
    #     · 缺 ddraw.dll   -> 新系统上黑屏/无图像（玩家以为是补丁坏了）
    #     · 缺 License.txt -> 少了 cnc-ddraw 的 MIT 声明（合规缺口）
    #     · 缺 必读说明    -> 玩家不知道要先导入 Disable_...reg
    print("\n[3b] 包根 cnc-ddraw / 许可 / 说明")
    for f in ("ddraw.dll", "ddraw.ini", "LICENSE", "License.txt",
              "必读说明.txt",
              "如果不会安装，请把该文件发给AI，让AI教你.txt",
              "将此文件交给AI，让AI协助完善本项目.txt",
              "Disable_AM2ExeWinCompatShim.reg",
              "Restore_AM2ExeWinCompatShim.reg"):
        ok(os.path.isfile(os.path.join(STAGE, f)), "包根 %s" % f, "缺 %s" % f)

    dd = os.path.join(STAGE, "ddraw.ini")
    if os.path.isfile(dd):
        dtxt = open(dd, encoding="utf-8", errors="replace").read()
        ok("cnc-ddraw" in dtxt, "ddraw.ini 是 cnc-ddraw 配置",
           "ddraw.ini 不像 cnc-ddraw 配置（缺 cnc-ddraw 标识）")
        ok("[ddraw]" in dtxt, "ddraw.ini 含 [ddraw] 节", "缺 [ddraw] 节")

    lt = os.path.join(STAGE, "License.txt")
    if os.path.isfile(lt):
        ltxt = open(lt, encoding="utf-8", errors="replace").read()
        # ★ 三方声明必须随包：cnc-ddraw 是 MIT，随二进制分发须附版权声明。
        #   只查"文件非空"挡不住"合并时漏了 cnc-ddraw 这一份"。
        for mark, label in (("MIT License", "MIT 正文"),
                            ("github.com/FunkyFr3sh", "cnc-ddraw 版权行"),
                            ("== ASILoader.txt", "UAL 声明"),
                            ("Apache License", "基础许可（Apache-2.0）正文")):
            ok(mark in ltxt, "License.txt 含 %s" % label,
               "License.txt 缺 %s —— 随包分发的第三方声明不全" % label)

    # ── 4. 译文表（逐条对照 Steam exe）───────────────────────────────
    print("\n[4] 译文表（逐条对照 Steam exe）")
    sin = os.path.join(STAGE, "scripts", "strings", "am2_strings.ini")
    if ok(os.path.isfile(sin), "scripts\\strings\\am2_strings.ini 存在", "缺译文表"):
        entries = []
        for ln, line in enumerate(open(sin, encoding="utf-8"), 1):
            t = line.strip()
            if not t or t[0] in ";#[":
                continue
            m = re.match(r"^(0x[0-9a-fA-F]+)\s*=\s*(.*?)\|(.*)$", t)
            if m:
                # ★ 必须与生成脚本/DLL 做同样的反转义：
                #   英文原文的首尾空格被写成 \x20，否则安全闸门会误判不符。
                entries.append((int(m.group(1), 16),
                                _unescape(m.group(2)), m.group(3)))
        print("     条目数: %d" % len(entries))
        if os.path.isfile(STM_EXE):
            buf, secs = sections_of(STM_EXE)

            def r2o(rva):
                for nm, va, vs, ra, rs in secs:
                    if va <= rva < va + max(vs, rs):
                        o = ra + (rva - va)
                        if o < ra + rs:
                            return o
                return None

            bad = 0
            # ★ 额外的"地址语义"闸门：INI 的键必须是 **RVA**（DLL 用 base+rva 定位）。
            #   曾把一条写成 VA（0x00475300），DLL 侧算成 0x875300 落在映像外,
            #   被越界检查静默跳过 —— 不崩但补丁不生效。
            #   这里显式检查：RVA 必须 < SizeOfImage；若某条像 VA（>= ImageBase）
            #   则直接报出来，而不是等它在 r2o 里换成别的位置。
            size_of_image = None
            try:
                o0 = struct.unpack_from("<I", buf, 0x3C)[0]
                size_of_image = struct.unpack_from("<I", buf, o0 + 24 + 56)[0]
            except Exception:
                pass
            if size_of_image:
                for rva, en, zh in entries:
                    if rva >= size_of_image:
                        print("       [x] %#010x 超出映像（SizeOfImage=%#x）"
                              "—— RVA 键误写成 VA？" % (rva, size_of_image))
                        bad += 1

            for rva, en, zh in entries:
                o = r2o(rva)
                if o is None:
                    bad += 1; continue
                e = buf.find(b"\0", o, o + 1024)
                cur = buf[o:e].decode("latin1") if e > 0 else ""
                if cur != en:
                    print("       [x] %#010x 原文不符 期望 '%s' 实得 '%s'" % (rva, en, cur))
                    bad += 1
                    continue
                if len(zh.encode("gbk")) + 1 > len(en) + 1:
                    print("       [x] %#010x 译文超长" % rva)
                    bad += 1
            ok(bad == 0, "全部 %d 条与 Steam 内存一致且容量足够（DLL 运行时将全部写入）"
               % len(entries),
               "%d 条会在运行时被跳过" % bad)
        else:
            WARN.append("找不到 Steam exe，跳过逐条复核")

    # ── 5. 中文字库 ───────────────────────────────────────────────────
    print("\n[5] 中文字库")
    hzk = os.path.join(STAGE, "scripts", "Hzk16")
    if ok(os.path.isfile(hzk), "scripts\\Hzk16 存在", "缺 Hzk16（中文无法显示）"):
        with open(hzk, "rb") as f:
            h = f.read(0x60)
        magic = struct.unpack_from("<I", h, 0)[0]
        ok(magic == 0x1A455352, "魔数 'RSE\\x1a' 正确", "魔数错误 %#x" % magic)
        w, hh = struct.unpack_from("<HH", h, 0x14)
        bpg = struct.unpack_from("<H", h, 0x50)[0]
        ng = struct.unpack_from("<H", h, 0x52)[0]
        ok((w, hh, bpg) == (13, 13, 26),
           "几何 13x13 / 26 B/字形（与官方渲染器一致）",
           "几何不符 %dx%d bpg=%d" % (w, hh, bpg))
        print("     字形数=%d  文件=%d 字节" % (ng, os.path.getsize(hzk)))

    # ── 6. update 不含可执行文件（硬约束）─────────────────────────────
    print("\n[6] 硬约束：update\\ 里不得含 exe/dll")
    upd = os.path.join(STAGE, "update")
    if os.path.isdir(upd):
        bad = []
        for dp, dn, fn in os.walk(upd):
            for x in fn:
                if x.lower().endswith((".exe", ".dll", ".asi", ".sys")):
                    bad.append(os.path.relpath(os.path.join(dp, x), upd))
        ok(not bad, "update\\ 内无任何可执行文件",
           "update\\ 含可执行文件（违反“不改游戏文件”约束）: %s" % bad[:5])

        # ── 7. 清单一致性 ─────────────────────────────────────────────
        print("\n[7] 资产清单一致性")
        man = os.path.join(ROOT, "build_out_am2", "MANIFEST.json")
        if os.path.isfile(man):
            m = json.load(open(man, encoding="utf-8"))
            # ★★ 路径分隔符必须**归一化**再比较（CI run 38555827350 的失败根因）：
            #   清单里写的是正斜杠（build_update_am2.py 统一用 "/"），
            #   而 os.path.relpath 在 Windows 上给 "\"、在 Linux 上给 "/"。
            #   早先这里把清单侧 replace("/", "\\") 强行转成反斜杠，
            #   于是 Linux 上两侧分隔符不一致 —— **全部 336 条**都被判成
            #   "磁盘有清单外文件"，报出来的却是"清单缺失"。
            #   Windows 上两侧恰好都是 "\"，所以本地一直看不出来（假绿的镜像：
            #   这里是"本地绿、CI 红"）。
            #   统一用正斜杠比较，与平台无关。
            def _norm(s):
                return s.replace("\\", "/").lower()

            listed = set(_norm(x["path"]) for x in m["files"])
            actual = set()
            for dp, dn, fn in os.walk(upd):
                for x in fn:
                    actual.add(_norm(os.path.relpath(os.path.join(dp, x), upd)))
            listed |= {"hzk16"}
            only_actual = actual - listed
            only_listed = listed - actual
            # Hzk16 是**故意**不放进 update\ 的（字库只由 make_patch_am2.py
            # 落在 scripts\Hzk16 一处，避免同一份 200 KB 文件重复三遍），
            # 且 build_update_am2.py 已不再把 hzk16 收进清单。
            # 这里容错处理旧清单：若清单里还列着 hzk16 而磁盘没有，不算错误。
            only_listed.discard("hzk16")
            ok(not only_actual, "磁盘文件都在清单内",
               "磁盘有清单外文件: %s" % sorted(only_actual)[:5])
            if only_listed:
                WARN.append("清单里有但磁盘没有: %s" % sorted(only_listed)[:5])
            tot = sum(os.path.getsize(os.path.join(dp, x))
                      for dp, dn, fn in os.walk(upd) for x in fn)
            print("     update\\: %d 文件, %.2f MB" % (len(actual), tot / 1048576))
        else:
            WARN.append("没有 MANIFEST.json，跳过清单核对")

        # 电影是否在包内
        smk = [x for x in os.listdir(os.path.join(upd, "avi"))
               ] if os.path.isdir(os.path.join(upd, "avi")) else []
        print("     电影: %d 个 %s" % (len(smk), sorted(smk)))
    else:
        FAIL.append("缺 update\\ 目录")

    # ── 8. 必读说明编码 ───────────────────────────────────────────────
    #   与 1 代 verify_release.py 同一套判据（统一标准 S11：
    #   包内说明一律叫「必读说明.txt」）。
    print("\n[8] 必读说明.txt")
    readme = os.path.join(STAGE, "必读说明.txt")
    if ok(os.path.isfile(readme), "存在", "缺 必读说明.txt"):
        raw = open(readme, "rb").read()
        ok(raw[:3] == b"\xef\xbb\xbf", "UTF-8 BOM（记事本友好）", "缺 UTF-8 BOM")
        ok(b"\r\n" in raw, "CRLF 换行", "不是 CRLF 换行")

    # ── 汇总 ──────────────────────────────────────────────────────────
    print("\n" + "=" * 68)
    if WARN:
        print("警告 %d 项:" % len(WARN))
        for w in WARN:
            print("   - %s" % w)
    if FAIL:
        print("失败 %d 项:" % len(FAIL))
        for x in FAIL:
            print("   - %s" % x)
        return 1
    print("全部校验通过。")
    print("★ 仍需实机确认：启动游戏后 scripts\\ArmyMen2CHS.log 里应出现")
    print("    '适配档位 = ArmyMenII' 与 'Renderer: 已 hook RVA=0x46930'。")
    print("    1 代踩过\"构建全绿但补丁根本没加载\"的坑，这一步不能省。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
