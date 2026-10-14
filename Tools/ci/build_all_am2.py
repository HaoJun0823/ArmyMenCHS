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

import os
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
        print("\n★ 已自动部署到 Steam 目录，直接启动游戏即可：")
        print("      I:\\LocalGames\\Army Men\\Army Men II STEAM\\ArmyMen2.exe")
        print("  预期日志（scripts\\ArmyMen2CHS.log）：")
        print("      Detect: 选中 'ArmyMenII'  校验=n 个 hook 目标签名全部一致")
        print("      Renderer: hook #1 RVA=0x46930 kind=0   ← 左对齐（面板）")
        print("      Renderer: hook #2 RVA=0x46ab0 kind=1   ← 对话框")
        print("      Renderer: hook #3 RVA=0x46c50 kind=2   ← 居中")
        print("      InstallAll: 渲染器 hook 成功 3 个，失败 0 个")
        print("      strings: applied=40")
        print("      codepatch[解锁多人游戏]: 已应用 @0x44d8fa  EB -> 74")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
