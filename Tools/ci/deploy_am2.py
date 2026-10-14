# -*- coding: utf-8 -*-
"""把构建好的补丁部署到本地游戏目录（仅作者本机用，CI 上不跑）。

★ 为什么单独成一个脚本：
    原先这段是 build_all_am2.py 里的 DeployToGame()，随编排脚本一起被删。
    但它是**实测必需**的一步 —— 构建成功不等于游戏加载了补丁，必须
    真拷贝 + 回读校验。与 1 代一致的做法是"部署是独立动作，不属于构建"。

★ 血泪教训（原 DeployToGame 的注释）：
    这段以前**只有 print，没有 copy**，于是每次构建都打印"已自动部署"，
    实际游戏目录还是旧 DLL，白费一轮实机验证（而且旧 DLL 没有诊断日志，
    会误判成"诊断没生效"而不是"文件没换"）。
    现在：真拷贝 + 逐文件 sha256 回读校验 + 失败即非零退出。

用法：
    python Tools/ci/deploy_am2.py
    python Tools/ci/deploy_am2.py --from build_out_am2 --scripts <游戏 scripts 目录>
"""
import argparse
import hashlib
import os
import shutil
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_GAME_SCRIPTS = r"I:\LocalGames\Army Men\Army Men II STEAM\scripts"
DEPLOY_FILES = ["Army2_Extend_Dll.asi", "ArmyMenCHS.ini", "Hzk16"]


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


# PE 里有一个**每次链接都会变**的字段，会让"内容相同"误报成"已变更"：
#     TimeDateStamp（COFF 头 +8）
# 实测（逐字节对比两次构建）：全文件只有 4 字节不同 ——
#     PE 头 +8 的 TimeDateStamp，以及它在 .rdata 里的一份内联副本。
# 处理：把这两处抹平后比较，否则每次构建都报"已更新"，
# 真正的改动反而被淹没在噪声里。
def _norm_pe_hash(p):
    with open(p, "rb") as f:
        d = bytearray(f.read())
    if len(d) < 0x40 or d[:2] != b"MZ":
        return hashlib.sha256(bytes(d)).hexdigest()
    pe = int.from_bytes(d[0x3C:0x40], "little")
    if pe + 0x1C > len(d) or d[pe:pe + 4] != b"PE\0\0":
        return hashlib.sha256(bytes(d)).hexdigest()

    ts = bytes(d[pe + 8:pe + 12])
    nsec = int.from_bytes(d[pe + 6:pe + 8], "little")
    opt_size = int.from_bytes(d[pe + 20:pe + 22], "little")
    d[pe + 8:pe + 12] = b"\0\0\0\0"

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", default="stage_am2",
                    help="补丁包目录（默认 stage_am2）")
    ap.add_argument("--scripts", default=None,
                    help="游戏 scripts 目录（默认环境变量 AM2_GAME_SCRIPTS "
                         "或 %s）" % DEFAULT_GAME_SCRIPTS)
    args = ap.parse_args()

    game_scripts = (args.scripts
                    or os.environ.get("AM2_GAME_SCRIPTS")
                    or DEFAULT_GAME_SCRIPTS)
    src_dir = os.path.join(ROOT, args.src, "scripts")

    print("★ 部署到游戏目录")
    print("      %s" % game_scripts)

    if not os.path.isdir(src_dir):
        print("  [FAIL] 缺少 %s —— 先跑 Tools/ci/make_patch_am2.py"
              % src_dir, file=sys.stderr)
        return 1
    if not os.path.isdir(game_scripts):
        print("  [FAIL] 游戏目录不存在（用 --scripts 覆盖）: %s"
              % game_scripts, file=sys.stderr)
        return 1

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
        print("      InstallAll: 渲染环境自检通过")
        print("      Renderer: 已 hook RVA=0x46930")
        print("      strings: applied=N")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
