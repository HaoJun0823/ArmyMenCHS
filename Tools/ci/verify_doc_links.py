# -*- coding: utf-8 -*-
"""文档内链有效性检查。

★ 防的问题：改了 md 文件名，其它文档/README 里的相对链接变成死链。
  2 代新增 05/06/07 三篇 + 移植指南，彼此交叉引用，
  一旦改名没人发现就会留下一堆死链。

只检查 Markdown 的**相对路径链接**（`[..](path.md)` 形式），
不检查外链（http/https，避免 CI 依赖网络）。

用法：
    python Tools/ci/verify_doc_links.py
    python Tools/ci/verify_doc_links.py --docs docs --root .
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# [text](target) —— target 不能以 http/https/mailto/# 开头
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
SKIP_PREFIX = ("http://", "https://", "mailto:", "#", "ftp://")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--docs", default=None,
                    help="要扫描的目录（默认扫描仓库根下所有 .md）")
    args = ap.parse_args()

    root = args.root

    # 收集所有 md
    mds = []
    if args.docs:
        base = os.path.join(root, args.docs)
        for dp, _, fns in os.walk(base):
            for fn in fns:
                if fn.lower().endswith(".md"):
                    mds.append(os.path.join(dp, fn))
    else:
        for dp, _, fns in os.walk(root):
            # 跳过依赖目录
            if ".git" in dp.split(os.sep):
                continue
            for fn in fns:
                if fn.lower().endswith(".md"):
                    mds.append(os.path.join(dp, fn))
    mds = [m for m in mds if ".msvc" not in m.split(os.sep)]
    # ★ 跳过本地 Python 虚拟环境（venv311 / venv-qwen312 等）：
    #   它们未入库，CI 上根本不存在，但本机跑时里面有成百上千个 .md /
    #   README，site-packages 里的相对链接（如 onnxruntime 的 ../README.md）
    #   与实际布局对不上，会报一堆与本仓库无关的"死链"。
    #   本地红、CI 绿 —— 与 docs 记录的"假绿镜像"同类，会让人不敢相信本地结果。
    _VENV_DIRS = {"venv", ".venv", "env"}
    mds = [m for m in mds
           if not any(p in _VENV_DIRS or p.startswith(("venv", ".venv"))
                      for p in m.split(os.sep))]

    if not mds:
        print("!! 没找到任何 .md —— 校验器空转，不算通过", file=sys.stderr)
        return 1

    print("=" * 74)
    print("文档内链有效性")
    print("=" * 74)
    print("扫描 %d 个 Markdown 文件\n" % len(mds))

    checked = 0
    broken = []
    for md in mds:
        try:
            text = open(md, "r", encoding="utf-8", errors="replace").read()
        except Exception as e:
            print("!! 读不到 %s: %s" % (md, e), file=sys.stderr)
            broken.append((md, "(读取失败)", ""))
            continue
        for m in LINK.finditer(text):
            target = m.group(1)
            if target.startswith(SKIP_PREFIX):
                continue
            # 去掉锚点
            path_part = target.split("#", 1)[0]
            if not path_part:
                continue
            checked += 1
            # 绝对路径（/ 开头）按仓库根解析；其余按 md 所在目录
            if path_part.startswith("/"):
                full = os.path.join(root, path_part.lstrip("/"))
            else:
                full = os.path.join(os.path.dirname(md), path_part)
            full = os.path.normpath(full)
            if not os.path.exists(full):
                broken.append((os.path.relpath(md, root), target,
                               os.path.relpath(full, root)))

    if broken:
        print("!! %d 个死链：" % len(broken))
        for src, tgt, resolved in broken:
            print("   %-46s -> %-34s (解析为 %s)"
                  % (src[:46], tgt[:34], resolved))
    else:
        print("✓ %d 个相对链接全部有效" % checked)

    print("\n" + "=" * 74)
    print("检查 %d 个链接，死链 %d 个" % (checked, len(broken)))
    if broken:
        print("!! 有问题")
        return 1
    print("全部通过。")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
