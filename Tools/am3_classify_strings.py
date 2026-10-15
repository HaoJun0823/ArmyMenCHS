# -*- coding: utf-8 -*-
"""AM3 .txt 引号字面量精确分类，供文档引用。"""
import os
import re
import collections

B = r"I:\LocalGames\Army Men\Army Men - Toys in Space STEAM"

QUOTED = re.compile(r'"([^"\r\n]{1,400})"')
HAS_WORD = re.compile(r"[A-Za-z]{2,}")
# 句子特征：含空格且至少两个词，或含句末标点
SENT = re.compile(r"[A-Za-z]{2,}[\s]+[A-Za-z]{2,}")


def cls(s):
    t = s.strip()
    if not t:
        return "empty"
    if t.lower().endswith(".wav"):
        return "wav"
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_\-@\.]{0,60}", t):
        return "ident"          # 资源名/变量名：无空格单一 token
    if re.search(r"\.(bmp|amm|atl|dat|ani|aai|txt)$", t, re.I):
        return "assetfile"
    if SENT.search(t) or (len(t) > 3 and " " in t):
        return "text"           # 含空格 -> 疑似 UI 文本
    return "other"


cnt = collections.Counter()
uniq = collections.defaultdict(set)
texts = collections.Counter()
where = collections.defaultdict(set)

nfiles = 0
for dp, dn, fn in os.walk(B):
    for f in fn:
        if not f.lower().endswith(".txt"):
            continue
        p = os.path.join(dp, f)
        if os.path.relpath(p, B).split(os.sep)[0].lower() == "save":
            continue
        nfiles += 1
        rel = os.path.relpath(p, B)
        d = open(p, "rb").read().decode("latin1")
        for m in QUOTED.finditer(d):
            s = m.group(1)
            k = cls(s)
            cnt[k] += 1
            uniq[k].add(s.strip())
            if k == "text":
                texts[s.strip()] += 1
                where[s.strip()].add(rel)

print("扫描 .txt: %d" % nfiles)
print()
print("%-12s %8s %8s" % ("类别", "出现次数", "唯一"))
for k in ("text", "ident", "wav", "assetfile", "other", "empty"):
    print("%-12s %8d %8d" % (k, cnt[k], len(uniq[k])))
print("%-12s %8d %8d" % ("合计", sum(cnt.values()),
                         sum(len(v) for v in uniq.values())))
print()
print("UI 文本跨文件复用条数: %d" %
      sum(1 for s in where if len(where[s]) > 1))
print()
print("== text 类全量（%d 唯一 / %d 次）==" % (len(texts), sum(texts.values())))
for s, c in texts.most_common():
    print("  x%-3d %s" % (c, s[:110]))
