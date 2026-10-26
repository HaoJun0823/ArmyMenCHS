"""
独立校验 build_out 产出是否可发布。

与 ci_build.py 分离：构建脚本自己说"成功"不算，这里再核一遍。

检查项：
  1. DLL 存在，且是 **32 位 PE**（machine == 0x14C）—— 游戏是 i386
  2. DLL 导出 ArmyMenCHS_Install / ArmyMenCHS_Uninstall
  3. ArmyMenCHS.ini 存在，且声明的 strings 文件都在
  4. 三个 objects.dat 存在、非空，**且能重新解析**（魔数 + key 数量 + 块头合法）
  5. objects.dat 的 key 集合与 Steam 原版一致（差异移植不应改 key 集合）
  6. 载荷目录齐全：Audio / AVI / Campaigns / Maps / Screens
  7. **包根必备文件**：dsound.dll（ASI Loader）/ LICENSE / License.txt /
     安装说明.txt（须 UTF-8 BOM，否则记事本显示乱码）
  8. LICENSE 内容体检：不得残留其它项目名（Saints Row / Volition 等），
     必须含本项目主许可（HJNCSA-1.0 / Apache-2.0 基础许可）与游戏版权方声明

★ 第 7/8 项是硬门禁：dsound.dll 缺失时游戏不会加载 scripts/ 下的 .asi，
  汉化会**完全失效**且没有任何报错 —— 必须在 CI 阶段拦下。

用法：
    python3 Tools/ci/verify_release.py stage [--root G:\\Projects\\ArmyMenCHS]

★ 目标目录可以是 build_out（中间目录，平铺）或 stage（最终产物，按安装布局）。
  本脚本用 resolve() 同时兼容两者。
"""

import os
import sys
import json
import struct

TERRAINS = ("Alpine", "Bayou", "Desert")
FILEID = 132415161
HEADER_SIZE = 4 + 1024 + 4

# ── 关于 DLL 体积指纹 ─────────────────────────────────────────────────────
# 这里**曾经**有一个 DLL_EXPECTED_SIZE 硬门禁（精确等于某个字节数）。
# 已移除：它是「工具链 × 源码」的联合指纹，任何无关改动都会让它变红，
# 却不指向真正的产物缺陷。现在只校验「32 位 PE + 导出齐全」这两条
# 与功能直接相关的事实。



def sha256(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def read_pe_machine(p):
    with open(p, "rb") as f:
        b = f.read()
    if b[:2] != b"MZ":
        return None
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    if b[pe:pe + 4] != b"PE\0\0":
        return None
    return struct.unpack_from("<H", b, pe + 4)[0]


def check_objects(path, expect_keys=None):
    """返回 (ok, msg)。解析 objects.dat 并逐块校验头部。"""
    if not os.path.isfile(path):
        return False, "文件不存在"
    with open(path, "rb") as f:
        b = f.read()
    fid = struct.unpack_from("<I", b, 0)[0]
    if fid != FILEID:
        return False, f"魔数错误 0x{fid:X}"
    n = struct.unpack_from("<I", b, 1028)[0]
    if n <= 0 or n > 65536:
        return False, f"nObjects 异常 {n}"

    entries = []
    for i in range(n):
        p = HEADER_SIZE + i * 8
        if p + 8 > len(b):
            return False, f"目录表越界 @ {i}"
        k, off = struct.unpack_from("<II", b, p)
        entries.append((k, off))

    order = sorted(range(n), key=lambda i: entries[i][1])
    bad = 0
    keys = set()
    for pos, i in enumerate(order):
        s = entries[i][1]
        e = entries[order[pos + 1]][1] if pos + 1 < len(order) else len(b)
        blob = b[s:e]
        keys.add(entries[i][0])
        if len(blob) < 28:
            bad += 1
            continue
        k, w, h, _ = struct.unpack_from("<iiii", blob, 0)
        if k != entries[i][0] or w <= 0 or h <= 0 or w > 4096 or h > 4096:
            bad += 1
    if bad:
        return False, f"{bad}/{n} 个块头部非法"

    if expect_keys is not None and keys != expect_keys:
        return False, (f"key 集合与 Steam 不一致 "
                       f"(少了 {len(expect_keys - keys)}, 多了 {len(keys - expect_keys)})")
    return True, f"{n} objects, 头部全部合法"


def resolve(out, *cands):
    """在 out 下按候选路径查找，返回第一个命中的绝对路径。

    为什么需要：校验目标有两种布局
      · build_out —— 中间目录，内容是平铺的（Audio/、strings/、DLL）
      · stage     —— 最终产物，内容按安装布局分布（update/、scripts/、包根）
    同一个脚本要能校验两者，所以逐个候选探测。
    """
    for c in cands:
        p = os.path.join(out, c.replace("/", os.sep))
        if os.path.exists(p):
            return p
    return os.path.join(out, cands[0].replace("/", os.sep))


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    out = args[0]
    root = args[args.index("--root") + 1] if "--root" in args else \
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))

    print(f"校验: {out}")
    print()
    ok = True

    # 1/2. DLL —— build_out 里叫 .dll，落包时改名 .asi
    dll = resolve(out, "Army1_Extend_Dll.dll", "scripts/Army1_Extend_Dll.asi")
    if not os.path.isfile(dll):
        print("  [FAIL] DLL 缺失")
        ok = False
    else:
        m = read_pe_machine(dll)
        sz = os.path.getsize(dll)
        if m != 0x14C:
            print(f"  [FAIL] DLL 不是 32 位 (machine=0x{m:X}, 应为 0x14C)")
            ok = False
        else:
            print(f"  [ OK ] DLL 32 位 PE, {sz} bytes")
            with open(dll, "rb") as f:
                b = f.read()
            for name in (b"ArmyMenCHS_Install", b"ArmyMenCHS_Uninstall"):
                if name in b:
                    print(f"  [ OK ] 导出 {name.decode()}")
                else:
                    print(f"  [FAIL] 缺少导出 {name.decode()}")
                    ok = False

    # 3. ini + strings
    ini = resolve(out, "ArmyMenCHS.ini", "scripts/ArmyMenCHS.ini")
    if not os.path.isfile(ini):
        print("  [FAIL] ArmyMenCHS.ini 缺失")
        ok = False
    else:
        with open(ini, "r", encoding="utf-8") as f:
            txt = f.read()
        print("  [ OK ] ArmyMenCHS.ini")
        # 提取 Files= 行
        files_line = None
        for ln in txt.splitlines():
            if ln.strip().startswith("Files="):
                files_line = ln.split("=", 1)[1].strip()
        if files_line:
            for one in files_line.split(","):
                one = one.strip()
                p = resolve(out, "strings/" + one, "scripts/strings/" + one)
                if os.path.isfile(p):
                    n = sum(1 for l in open(p, encoding="utf-8")
                            if "=" in l and not l.strip().startswith((";", "[")))
                    print(f"  [ OK ] strings/{one} ({n} 条)")
                else:
                    print(f"  [FAIL] strings/{one} 缺失")
                    ok = False

    # 4/5. objects.dat
    steam_terrain = os.path.join(root, "Army1_Original", "terrain")
    for t in TERRAINS:
        p = resolve(out, t + "/objects.dat", "update/" + t + "/objects.dat")
        base = os.path.join(steam_terrain, t, "objects.dat")
        expect = None
        if os.path.isfile(base):
            with open(base, "rb") as f:
                bb = f.read()
            nn = struct.unpack_from("<I", bb, 1028)[0]
            expect = set()
            for i in range(nn):
                pp = HEADER_SIZE + i * 8
                k, _ = struct.unpack_from("<II", bb, pp)
                expect.add(k)
        good, msg = check_objects(p, expect)
        tag = " OK " if good else "FAIL"
        print(f"  [{tag}] {t}/objects.dat: {msg}")
        if not good:
            ok = False

    # 6. 载荷目录
    for d in ("Audio", "AVI", "Campaigns", "Maps", "Screens"):
        p = resolve(out, d, "update/" + d)
        if os.path.isdir(p):
            n = sum(len(f) for _, _, f in os.walk(p))
            print(f"  [ OK ] {d}/ ({n} 文件)")
        else:
            print(f"  [WARN] {d}/ 不存在")
            # Maps/Screens 必存在
            if d in ("Maps", "Screens"):
                ok = False

    # 7. 包根必备文件
    #    这些缺任何一个都会直接影响用户：dsound.dll 缺失则汉化完全不加载；
    #    LICENSE / 必读说明 是分发义务。
    print()
    print("包根文件:")
    ROOT_FILES = [
        ("dsound.dll", 100_000, "ASI Loader；缺失则 scripts\\*.asi 不会被加载",
         False),
        ("LICENSE", 1000, "项目主许可（含游戏版权声明）", False),
        ("License.txt", 1000, "LICENSES/*.txt 合并正文", False),
        # 必读说明是中文，**必须**带 BOM，否则记事本显示乱码。
        # License.txt 是英文许可正文（第三方声明 + Apache-2.0 全文），不需要 BOM。
        # S11 统一命名：原「安装说明.txt」已更名为「必读说明.txt」。
        ("必读说明.txt", 500, "必读说明（须为 UTF-8 BOM）", True),
        # S12/S13：两份 AI 辅助文件，中文正文同样需 BOM。
        ("如果不会安装，请把该文件发给AI，让AI教你.txt", 500,
         "AI 安装助手入口（须为 UTF-8 BOM）", True),
        ("将此文件交给AI，让AI协助完善本项目.txt", 500,
         "AI 贡献助手入口（须为 UTF-8 BOM）", True),
    ]
    for name, min_size, why, need_bom in ROOT_FILES:
        p = os.path.join(out, name)
        if not os.path.isfile(p):
            print(f"  [FAIL] 缺少 {name} —— {why}")
            ok = False
            continue
        sz = os.path.getsize(p)
        if sz < min_size:
            print(f"  [FAIL] {name} 仅 {sz} 字节（应 >= {min_size}）—— {why}")
            ok = False
            continue
        extra = ""
        if need_bom:
            with open(p, "rb") as f:
                head = f.read(3)
            if head != b"\xef\xbb\xbf":
                print(f"  [FAIL] {name} 缺 UTF-8 BOM —— 记事本会显示乱码")
                ok = False
                continue
            extra = " (UTF-8 BOM)"
        print(f"  [ OK ] {name}  {sz} bytes{extra}")

    # 8. LICENSE 内容体检：不能是 SR_GAME_CHINESE 的模板残留
    lic = os.path.join(out, "LICENSE")
    if os.path.isfile(lic):
        with open(lic, "r", encoding="utf-8") as f:
            txt = f.read()
        for bad, desc in (("Saints Row", "错误引用了其它项目（Saints Row）"),
                          ("Volition", "错误引用了其它项目（Volition）")):
            if bad in txt:
                print(f"  [FAIL] LICENSE {desc}")
                ok = False
        # 主许可已由 GPL-3.0 更换为 HJNCSA-1.0（非商业源码可得许可，
        # 基座为 Apache 2.0）。体检项随之更新：确认换的是本项目的新许可，
        # 而不是残留的旧模板或其它仓库的 LICENSE。
        for need in ("Non-Commercial Source-Available License",
                     "Apache License 2.0", "3DO Company"):
            if need not in txt:
                print(f"  [FAIL] LICENSE 缺少必要声明: {need}")
                ok = False
        print(f"  [ OK ] LICENSE 内容体检通过")

    print()
    print("✓ 全部通过" if ok else "✗ 校验失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
