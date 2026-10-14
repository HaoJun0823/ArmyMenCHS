"""Army Men II 汉化补丁：一键完整构建 + 校验。

依次执行，任一步失败立即停止（不做静默容错）：
    ① build_update_am2.py        资产差异对账 -> build_out_am2/update
    ② build_dll_local_am2.py     编译 ASI（并断言 32 位 PE + 3 个导出）
    ③ build_test_hzk16.py        字库离线自测（13x13 几何 + 偏移量对照）
    ④ gen_am2_strings_ini.py     生成译文表（含词典硬闸门 + 逐条校验）
    ⑤ make_patch_am2.py          组装 stage_am2
    ⑥ verify_release_am2.py      独立校验产物

用法：
    python Tools/ci/build_all_am2.py
    python Tools/ci/build_all_am2.py --skip-movies    # 不打包 129 MB 电影
"""

import hashlib
import os
import shutil
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS = os.path.join(ROOT, "Tools")
PY = sys.executable

STEPS = [
    ("① 资产对账与差异打包", [PY, os.path.join(TOOLS, "unpack_objects", "build_update_am2.py")]),
    ("①b 生成 rules 汉化文本", [PY, os.path.join(TOOLS, "unpack_objects", "gen_rules_chs_am2.py")]),
    ("①c 补回被移除的多人地图", [PY, os.path.join(TOOLS, "unpack_objects", "add_lost_mp_am2.py")]),
    ("② 编译 ASI 模块",      [PY, os.path.join(TOOLS, "ci", "build_dll_local_am2.py")]),
    ("③ 字库离线自测",       [PY, os.path.join(TOOLS, "ci", "build_test_hzk16.py")]),
    # ★ ③b 判据性测试：用全角 ASCII（ＡＢＣ１２）与一二三的形状指纹验证
    #   字形偏移公式。加这一步的理由 —— 同一个问题被误判过两次：
    #     第 1 轮：我目视把噪声点阵当成工整字形（误判为"公式正确"）
    #     第 2 轮：子代理推导"缺 dataStart"（误判为"公式错误"）
    #   两次都是判据太弱（汉字"看着都像字"；"墨迹量 8..110"随便一段都满足）。
    #   本测试用不可混淆的形状指纹，并**自证区分力**（全偏移扫描，
    #   误通过率 0.717%），从根上堵住这两种误判。
    ("③b 校验字形偏移公式",   [PY, os.path.join(TOOLS, "ci", "verify_hzk_offset.py")]),
    ("④ 校验 hook 签名",     [PY, os.path.join(TOOLS, "ci", "verify_hook_sigs.py")]),
    ("④b 校验全局量 VA",     [PY, os.path.join(TOOLS, "ci", "verify_globals.py")]),
    ("④c 校验 stub 边界",    [PY, os.path.join(TOOLS, "ci", "verify_stub_boundary.py")]),
    ("④d 校验代码补丁",    [PY, os.path.join(TOOLS, "ci", "verify_codepatch.py")]),
    ("⑤ 生成译文表",         [PY, os.path.join(TOOLS, "unpack_objects", "gen_am2_strings_ini.py")]),
    ("⑤b 补录难度三项",      [PY, os.path.join(TOOLS, "unpack_objects", "add_difficulty_am2.py")]),
    ("⑤c 补录人工译文",      [PY, os.path.join(TOOLS, "unpack_objects", "add_manual_strings_am2.py")]),
    ("⑤d 补录单位名称",      [PY, os.path.join(TOOLS, "unpack_objects", "add_unit_names_am2.py")]),
    ("⑤e 补录通讯消息",      [PY, os.path.join(TOOLS, "unpack_objects", "add_messages_am2.py")]),
    ("⑥ 组装 stage",         [PY, os.path.join(TOOLS, "ci", "make_patch_am2.py")]),
    ("⑦ 独立校验产物",       [PY, os.path.join(TOOLS, "ci", "verify_release_am2.py")]),
]


def main():
    skip_movies = "--skip-movies" in sys.argv
    print("=" * 72)
    print("Army Men II 汉化补丁 —— 完整构建" + ("（不含电影）" if skip_movies else ""))
    print("=" * 72)

    results = []
    for title, cmd in STEPS:
        if skip_movies and "build_update_am2.py" in " ".join(cmd):
            cmd = cmd + ["--no-movies"]
        print("\n" + "─" * 72)
        print("%s" % title)
        print("─" * 72)
        r = subprocess.run(cmd, cwd=ROOT)
        results.append((title, r.returncode))
        if r.returncode != 0:
            print("\n!! 步骤失败，停止：%s (exit=%d)" % (title, r.returncode),
                  file=sys.stderr)
            break

    print("\n" + "=" * 72)
    print("结果汇总")
    print("=" * 72)
    for title, rc in results:
        print("  %-24s %s" % (title, "OK" if rc == 0 else "失败 (%d)" % rc))

    allok = all(rc == 0 for _, rc in results) and len(results) == len(STEPS)
    if allok:
        stage = os.path.join(ROOT, "stage_am2")
        total = n = 0
        for dp, dn, fn in os.walk(stage):
            for x in fn:
                total += os.path.getsize(os.path.join(dp, x))
                n += 1
        print("\n产物: %s" % stage)
        print("      %d 文件, %.2f MB" % (n, total / 1048576))

        # ── 真正部署 ────────────────────────────────────────────────────
        # ★ 血泪教训：这段以前**只有 print，没有 copy**。
        #   结果每次构建都打印"已自动部署"，实际游戏目录还是旧 DLL，
        #   白白浪费一轮实机验证（而且旧 DLL 没有诊断日志，
        #   我会误判成"诊断没生效"而不是"文件没换"）。
        #   现在：真拷贝 + 逐文件 sha256 回读校验 + 失败即非零退出。
        if not DeployToGame(stage):
            return 1
    return 0 if allok else 1


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


# PE 里有一个**每次链接都会变**的字段，会让"内容相同"误报成"已变更"：
#     TimeDateStamp（COFF 头 +8）
# 实测（_diff_pe.py 逐字节对比两次构建）：全文件只有 4 字节不同 ——
#     PE 头 +8 的 TimeDateStamp，以及它在 .rdata 里的一份副本
#     （文件偏移 0x2E7F4 / RVA 0x2F5F4，编译器把它内联进了某个常量）
# CheckSum 恒为 0，不用管。
#
# 处理：把 PE 头里的时间戳清零后比较；.rdata 那份副本按其**特征**
# （与原时间戳相同的 4 字节序列）一并抹平。这样"是否需要部署"才准，
# 否则每次构建都报"已更新"，真正的改动反而被淹没在噪声里。
def _norm_pe_hash(p):
    with open(p, "rb") as f:
        d = bytearray(f.read())
    if len(d) < 0x40 or d[:2] != b"MZ":
        return hashlib.sha256(bytes(d)).hexdigest()
    pe = int.from_bytes(d[0x3C:0x40], "little")
    if pe + 0x1C > len(d) or d[pe:pe + 4] != b"PE\0\0":
        return hashlib.sha256(bytes(d)).hexdigest()

    ts = bytes(d[pe + 8:pe + 12])          # 原时间戳
    nsec = int.from_bytes(d[pe + 6:pe + 8], "little")
    opt_size = int.from_bytes(d[pe + 20:pe + 22], "little")
    d[pe + 8:pe + 12] = b"\0\0\0\0"        # ① PE 头里的

    # ② .rdata 里内联的那份副本：按段范围扫描相同 4 字节序列
    for i in range(nsec):
        o = pe + 24 + opt_size + i * 40
        if o + 40 > len(d):
            break
        nm = bytes(d[o:o + 8]).rstrip(b"\0").decode("latin1", "ignore")
        vs, va, rs, ra = struct.unpack_from("<IIII", d, o + 8)
        if nm != ".rdata":
            continue
        end = min(len(d), ra + rs)
        j = ra
        while j + 4 <= end:
            if bytes(d[j:j + 4]) == ts:
                d[j:j + 4] = b"\0\0\0\0"
            j += 1
    return hashlib.sha256(bytes(d)).hexdigest()


# 部署目标：stage_am2/scripts/* -> 游戏 scripts/
# 只部署"运行期需要的 3 个文件"，避免把整个 stage 铺进游戏目录。
DEPLOY_FILES = ["Army2_Extend_Dll.asi", "ArmyMenCHS.ini", "Hzk16"]


def DeployToGame(stage):
    game_scripts = os.environ.get(
        "AM2_GAME_SCRIPTS",
        r"I:\LocalGames\Army Men\Army Men II STEAM\scripts")
    src_dir = os.path.join(stage, "scripts")

    print("\n★ 部署到游戏目录")
    print("      %s" % game_scripts)

    if not os.path.isdir(src_dir):
        print("  [FAIL] 缺少 %s" % src_dir, file=sys.stderr)
        return False
    if not os.path.isdir(game_scripts):
        print("  [FAIL] 游戏目录不存在（用 AM2_GAME_SCRIPTS 覆盖）: %s"
              % game_scripts, file=sys.stderr)
        return False

    ok = True
    for fn in DEPLOY_FILES:
        s = os.path.join(src_dir, fn)
        d = os.path.join(game_scripts, fn)
        if not os.path.isfile(s):
            print("  [FAIL] 源缺失: %s" % fn, file=sys.stderr)
            ok = False
            continue
        sh = sha256_file(s)
        dh = sha256_file(d) if os.path.isfile(d) else ""
        # .asi/.dll 用"抹平 PE 易变字段"的哈希判断是否真的需要更新
        need = (sh != dh)
        if need and fn.lower().endswith((".asi", ".dll")):
            need = (_norm_pe_hash(s) != _norm_pe_hash(d))
        if not need:
            print("  =  %-24s 已是最新（内容一致）" % fn)
            continue
        shutil.copyfile(s, d)
        # ★ 回读校验：不能只信"我调了 copyfile"
        after = sha256_file(d)
        if after != sh:
            print("  [FAIL] %s 回读校验不符" % fn, file=sys.stderr)
            ok = False
        else:
            print("  -> %-24s 已更新  %s" % (fn, sh[:12]))

    if ok:
        print("\n  直接启动游戏即可：")
        print("      I:\\LocalGames\\Army Men\\Army Men II STEAM\\ArmyMen2.exe")
        print("  日志（scripts\\ArmyMen2CHS.log）应能看到：")
        print("      InstallAll: 渲染环境自检通过   ← 含 rc/enabled/dispW 等新字段")
        print("      diag#1 kind=... rc=(..) clip=on(..)   ← 有界诊断")
    return ok


if __name__ == "__main__":
    sys.exit(main())
