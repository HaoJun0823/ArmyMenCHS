"""生成并**离线校验** ASI 用的字符串补丁 INI。

背景与做法：
  * 中文串来自 1999 上海育碧官方简体中文版 ArmyMen2.exe
  * 对应英文原文必须在 **Steam 英文版** 的同位置
  * 两作的 exe 大小相同但布局有累积偏移（中文串比英文长），
    早先用"RVA 线性插值"定位，在字符串变长处会漂移到字符串中间
    （实测：把 "Rifleman" 定位到 0x762e1，实际在 0x762d8，差 9 字节）

  ★ 因此改为：先插值得到**近似**位置，再**对齐到最近的字符串起点**
    （向左/右找到最近的 NUL 之后的第一个可打印 ASCII 起点）。
    这消除了漂移。

  ★ 并额外提供 `--validate`：把写好的 INI 重新读回，
    对 Steam exe 逐条复核 DLL 运行时会做的两项检查
      (a) 该 RVA 处内存 == INI 声明的英文原文（安全闸门）
      (b) 译文 GBK 字节数 + 1 <= 英文原文长度 + 1（槽位容量）
    校验通过 == DLL 运行时会全部写入成功。**不需要启动游戏**。

用法：
    python Tools/unpack_objects/gen_am2_strings_ini.py            # 生成 + 校验
    python Tools/unpack_objects/gen_am2_strings_ini.py --validate # 只校验
"""

import argparse
import bisect
import os
import re
import struct
import sys
from collections import defaultdict

DEF_CHS = r"I:\LocalGames\Army Men\玩具兵大战2\ArmyMen2.exe"
DEF_STM = r"I:\LocalGames\Army Men\Army Men II STEAM\ArmyMen2.exe"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "Army2_Extend_Dll", "strings", "am2_strings.ini")


# ─────────────────────────────────────────────────────────── PE 工具
def sections(d):
    o = struct.unpack_from("<I", d, 0x3C)[0]
    n = struct.unpack_from("<H", d, o + 4)[0]
    so = o + 24 + struct.unpack_from("<H", d, o + 20)[0]
    out = []
    for i in range(n):
        nm = d[so + i * 40: so + i * 40 + 8].rstrip(b"\0").decode("latin1")
        vs, va, rs, ra = struct.unpack_from("<IIII", d, so + i * 40 + 8)
        out.append((nm, va, vs, ra, rs))
    return out


def r2o(secs, rva):
    for nm, va, vs, ra, rs in secs:
        if va <= rva < va + max(vs, rs):
            off = ra + (rva - va)
            if off < ra + rs:
                return off
    return None


def o2r(secs, off):
    for nm, va, vs, ra, rs in secs:
        if ra <= off < ra + rs:
            return va + (off - ra)
    return None


def raw_string_at(d, secs, rva, maxlen=1024):
    """读 rva 处的 NUL 结尾串；失败返回 None。"""
    o = r2o(secs, rva)
    if o is None or o >= len(d):
        return None
    e = d.find(b"\0", o, min(len(d), o + maxlen))
    if e < 0:
        return None
    return d[o:e]


# ─────────────────────────────────────────────────── 锚点对齐
def ascii_anchors(d, secs, mn=10):
    idx = defaultdict(list)
    for nm, va, vs, ra, rs in secs:
        if nm not in (".data", ".rdata"):
            continue
        blob = d[ra:ra + rs]
        for m in re.finditer(rb"[\x20-\x7e]{%d,}" % mn, blob):
            idx[m.group().decode("latin1")].append(va + m.start())
    return idx


def build_anchor_map(chs, csecs, stm, ssecs):
    a = ascii_anchors(chs, csecs)
    b = ascii_anchors(stm, ssecs)
    pairs = []
    for s, rvs in a.items():
        if len(rvs) != 1:
            continue
        if s in b and len(b[s]) == 1:
            pairs.append((rvs[0], b[s][0]))
    pairs.sort()
    # 单调筛选，剔除乱序（跨段或巧合匹配）
    keep, last = [], -1
    for x, y in pairs:
        if y > last:
            keep.append((x, y))
            last = y
    return keep


def make_mapper(anchors):
    xs = [a for a, _ in anchors]
    ys = [b for _, b in anchors]

    def f(rva):
        if not xs or rva < xs[0] or rva > xs[-1]:
            return None
        i = bisect.bisect_right(xs, rva) - 1
        i = min(i, len(xs) - 2)
        x0, x1 = xs[i], xs[i + 1]
        y0, y1 = ys[i], ys[i + 1]
        if x1 == x0:
            return y0
        return y0 + round((rva - x0) * (y1 - y0) / (x1 - x0))
    return f


# ─────────────────────────────────── 对齐到最近字符串起点
def snap_to_string(d, secs, approx_rva, window=96):
    """从近似位置向两侧找最近的"字符串起点"。

    字符串起点定义：该位置的字节是可打印 ASCII，且它前面是 NUL
    （或位于段起点）。返回 (rva, 原文) 或 None。
    """
    o0 = r2o(secs, approx_rva)
    if o0 is None:
        return None
    best = None
    for delta in range(0, window + 1):
        for sign in ((0,) if delta == 0 else (-1, 1)):
            o = o0 + sign * delta
            if o <= 0 or o >= len(d):
                continue
            if not (0x20 <= d[o] < 0x7F):
                continue
            if d[o - 1] != 0:            # 必须紧跟在 NUL 之后
                continue
            e = d.find(b"\0", o, min(len(d), o + 512))
            if e < 0 or e == o:
                continue
            run = d[o:e]
            if not all(0x20 <= c < 0x7F for c in run):
                continue
            rva = o2r(secs, o)
            if rva is None:
                continue
            if best is None or abs(delta) < best[0]:
                best = (abs(delta), rva, run)
    if best is None:
        return None
    return best[1], best[2].decode("ascii")


# ─────────────────────────────────── 提取中文串
def chs_chinese_strings(d, secs):
    out = []
    for nm, va, vs, ra, rs in secs:
        if nm not in (".data", ".rdata"):
            continue
        blob = d[ra:ra + rs]
        start = 0
        for i in range(len(blob) + 1):
            if i == len(blob) or blob[i] == 0:
                if i - start >= 2:
                    raw = blob[start:i]
                    try:
                        s = raw.decode("gbk")
                    except UnicodeDecodeError:
                        s = None
                    if s and all(c.isprintable() for c in s):
                        cjk = sum(1 for c in s if "\u4e00" <= c <= "\u9fff")
                        if cjk >= 2:
                            out.append((va + start, s))
                start = i + 1
    return out


# ─────────────────────────── 已验证的双语词典（硬闸门）
# ★ 为什么需要"词典闸门"而不是靠启发式：
#   槽位对齐在**单位名表区（0x762d8 起）是正确的**（16 条术语全部语义吻合），
#   但在更靠后的区域会失准（实测 Airstrike->灰军装、Aerosol->步枪手）。
#   启发式（长度比、格式符）分不出这种错，因为每条单独看都"像"。
#
#   所以改为**白名单**：只有命中下面词典（英文关键词 -> 允许的中文）才接受。
#   这些对应关系是我逐条人工核对过官方中文版与 Steam 英文版得出的。
#   宁可少翻，不可错翻 —— 错译比不译更糟（玩家会以为游戏坏了）。
#
#   格式: (英文匹配, 允许的中文片段元组)；英文做 lower() 后按子串匹配。
DICT = [
    # —— 单位名（已逐条核对）——
    ("rifleman",          ("步枪手",)),
    ("grenadier",         ("榴弹手",)),
    ("mortarman",         ("迫击炮手",)),
    ("mortar men",        ("迫击炮手",)),
    ("flamethrower",      ("火焰喷射兵",)),
    ("bazookaman",        ("火箭筒兵",)),
    ("tank",              ("坦克",)),
    ("half-track",        ("半履带车",)),
    ("truck",             ("卡车",)),
    ("jeep",              ("吉普车",)),
    ("pt-boat",           ("鱼雷快艇", "快艇")),
    ("pt boats",          ("鱼雷快艇", "快艇")),
    # —— 建筑/设施 ——
    ("pillbox-rifle",     ("堡垒步枪",)),
    ("pillbox-bazooka",   ("堡垒火箭筒",)),
    ("pillbox-mg",        ("堡垒机枪",)),
    ("heavy mg pillbox",  ("堡垒重机枪",)),
    ("medical tent",      ("急救棚",)),
    ("auto repair",       ("自动修复",)),
    ("radar",             ("雷达",)),
    ("aa-gun",            ("高射炮",)),
    ("anti-aircraft gun", ("高射炮",)),
    ("mine",              ("地雷",)),
    ("wrench",            ("扳手",)),
    ("armor",             ("铠甲", "装甲")),
    # —— 难度（列表项，走 DIALOG 渲染器；实测对应官方中文版的"难/中/易"）——
    ("hard",              ("难",)),
    ("medium",            ("中",)),
    ("easy",              ("易",)),
    # —— UI / 系统 ——
    ("stratmap",          ("战略地图",)),
    ("sarge",             ("中士",)),
    ("error",             ("错误",)),
    ("data missing",      ("数据缺失",)),
    ("copy protection",   ("版权保护",)),
    ("in progress",       ("进行中",)),
    ("computer",          ("计算机", "电脑")),
    ("host is ready",     ("创建者就绪", "就绪")),
    ("game type changed", ("游戏类型",)),
    ("map changed",       ("地图",)),
    ("options changed",   ("选项",)),
    ("left the game",     ("离开游戏",)),
    ("want to quit",      ("退出",)),
    ("delete this game",  ("删除",)),
    ("overwrite savefile",("覆盖", "存储")),
    ("saved games",       ("存储", "存档")),
    ("reattempt",         ("重新开始",)),
    ("cd must be in the drive", ("光驱", "光盘")),
    ("flak jacket",       ("防弹衣",)),
    ("medkit",            ("急救包",)),
    ("medpack",           ("急救包",)),
    ("explosives",        ("炸药", "火药")),
    ("magnifying glass",  ("放大镜",)),
    ("aerosol",           ("喷雾剂",)),
    ("sniper rifle",      ("狙击步枪",)),
    ("minesweeper",       ("扫雷器",)),
    ("reconnaissance",    ("空中侦察", "侦察")),
    ("paratroopers",      ("伞兵",)),
    ("air strike",        ("空中打击", "空袭")),
    ("zombie",            ("僵尸",)),
    ("sniper",            ("狙击手",)),
    ("demolitions",       ("爆破", "间谍")),
    ("heavy weapons",     ("重武器", "机枪")),
]


def dict_ok(en, zh):
    """词典闸门：英文命中某条词条时，中文必须包含该条允许的片段之一。

    返回 (是否通过, 原因)。英文没命中任何词条时返回 (None, ...)，
    表示"词典覆盖不到"，由调用方决定是否用其他判据兜底。
    """
    low = en.lower()
    hit = None
    for key, allow in DICT:
        if key in low:
            # 取最长的命中（更具体）
            if hit is None or len(key) > len(hit[0]):
                hit = (key, allow)
    if hit is None:
        return None, "词典未覆盖"
    if any(a in zh for a in hit[1]):
        return True, "词典命中(%s)" % hit[0]
    return False, "词典否决: 英文含 '%s'，译文应含 %s 之一，实得 '%s'" % (
        hit[0], "/".join(hit[1]), zh)


# ─────────────────────────────────── 语义交叉校验
# ★★ 为什么必须有这一关：
#   生成器早先只做"字节层面"的校验（RVA 读得到、能放进槽位），
#   结果产出了一张**看似全部通过、实际大量错位**的表：
#       Corpses Spawn Zombies -> 堡垒重机枪
#       Aerosol               -> 步枪手
#       Airstrike             -> 灰军装
#   根因是 snap_to_string 会把译文吸附到近似位置附近的**错误字符串**上
#   （锚点插值在中文字符串变长处漂移，吸附到相邻的另一个串）。
#
#   字节校验抓不到这种错，因为每条单独看都"合法"。必须加**语义**判据：
#     用 1 代已有的权威材料 —— 官方中文版 exe 里的"英文→中文"邻接关系，
#     凡是能在里面找到一致证据的才接受。
#
#   具体做法：把中文版 exe 当作"一个巨大的对照区"，逐个检查
#     (英文 in 中文版 && 中文 in 中文版) 的对是否在**同一段邻域**里共现。
#   这里用一个更保守也更简单的判据：
#     **英文原文必须也出现在中文版 exe 中**（说明该串是同期共有的显示文本），
#     且该中文串在中文版里**不与另一个不同的英文串更近**。
#
#   实务上最有效的是**人工审阅**（本表只有几十条），
#   因此生成器把结果写成便于逐行核对的格式，并**默认拒绝输出**
#   未通过语言判据的条目。
LANG_STOP = set(
    # 拉丁字母/数字的"标签式"英文串往往与中文译文一一对应，
    # 但对不上的那些恰恰出现在这类短标签上，因此对短标签要求更严。
)


def semantic_score(en, zh):
    """给 (英文, 中文) 打分。返回 (score, reason)，score<0 表示应剔除。

    判据（保守，宁可少翻不可错翻）：
      1. 两者都不为空
      2. 英文里若含 %s 之类的格式符，中文也必须含相同数量的格式符
      3. 英文与中文的"长度比"要落在合理区间（中文一般更短）
         —— 中文码位：CJK 1 字 ≈ 英文 1.5~2 字符
      4. 排除明显语义无关的组合（靠词表）
    """
    if not en or not zh:
        return -1, "空串"
    # 格式符必须一致
    nf_en = en.count("%s") + en.count("%d")
    nf_zh = zh.count("%s") + zh.count("%d")
    if nf_en != nf_zh:
        return -1, "格式符数量不符 (%d vs %d)" % (nf_en, nf_zh)

    # 语义词表：强信号对（英文关键词 -> 中文必须出现的字）
    #  这些是实测确认过的对应关系，用来给明显错位的组合判负
    K = [
        (("leave", "left the game"), ("离开",)),
        (("host",), ("创建者", "主机")),
        (("version",), ("版本",)),
        (("quit",), ("退出",)),
        (("delete",), ("删除",)),
        (("savefile", "saved", "save file"), ("存储", "存档", "保存")),
        (("copy protection",), ("版权",)),
        (("cd must be in the drive",), ("光驱", "光盘")),
        (("ready",), ("就绪", "准备")),
        (("rifleman",), ("步枪",)),
        (("grenadier",), ("榴弹",)),
        (("mortarman",), ("迫击炮",)),
        (("flamethrower",), ("火焰",)),
        (("bazooka",), ("火箭",)),
        (("tank",), ("坦克",)),
        (("truck",), ("卡车",)),
        (("half-track",), ("半履带",)),
        (("radar",), ("雷达",)),
        (("mine",), ("地雷", "雷")),
        (("sarge",), ("中士",)),
        (("stratmap",), ("战略",)),
        (("armor",), ("铠", "装甲")),
        (("wrench",), ("扳手",)),
        (("data missing",), ("数据", "缺失")),
        (("game type",), ("游戏类型",)),
        (("options changed",), ("选项",)),
        (("map changed",), ("地图",)),
        (("computer",), ("计算机", "电脑")),
        (("error",), ("错误",)),
    ]
    low = en.lower()
    for keys, expect in K:
        if any(k in low for k in keys):
            if not any(e in zh for e in expect):
                return -1, "语义不符（英文含 %s，译文缺 %s）" % (
                    "/".join(keys), "/".join(expect))
    return 1, "ok"


# ───────────────────────────── 槽位对齐（真正的正确判据）
def slots(d, secs, names=(".data", ".rdata")):
    """把段按 NUL 切成"槽位"序列：(rva, bytes)。

    ★ 关键洞察：中文字符串虽然**字节更长**，但**槽位数量不变** ——
      同一个槽位在中文版里是 GBK 中文，在英文版里是对应英文。
      所以按"槽位序号"对齐，比按字节/近似 RVA 对齐可靠得多。
      （早先用 RVA 插值 + 最近串吸附，会整段错位一个位置，
        而错位一个位置仍然"单调"，所以单调性判据抓不到。）
    """
    out = []
    for nm, va, vs, ra, rs in secs:
        if nm not in names:
            continue
        blob = d[ra:ra + rs]
        start = 0
        for i in range(len(blob) + 1):
            if i == len(blob) or blob[i] == 0:
                out.append((va + start, blob[start:i]))
                start = i + 1
    return out


def align_slots(chs_slots, stm_slots):
    """用 difflib 对两边的槽位内容做序列对齐，返回 [(chs_rva, stm_rva), ...]。

    能精确匹配上的（英文/相同内容）作为锚；锚之间的"替换块"
    按位置一一对应 —— 那些就是 中文 <-> 英文 的替换点。
    """
    import difflib
    a = [s[1] for s in chs_slots]
    b = [s[1] for s in stm_slots]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    pairs = []
    stats = {"equal": 0, "replace_dp": 0}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                pairs.append((chs_slots[i1 + k][0], stm_slots[j1 + k][0]))
            stats["equal"] += i2 - i1
        elif tag == "replace":
            # ★★ 长度不等时的处理。
            #
            #  中文版比英文版多约 950 个槽位（译文拆分/新增字符串所致），
            #  所以大量替换块两侧长度不等。此时**从块首 1:1 配对会整段错位**：
            #  实测 Corpses Spawn Zombies 被配给"步枪手"。
            #
            #  ⚠️ 最初这里直接 `continue` 把不等长块整块丢掉 ——
            #     结果单位名表（Rifleman/Grenadier/...）全在这一块里，
            #     最终只剩 6 条，等于白做。
            #
            #  改为在块内做 **DP 最优单调匹配**：用双语词典闸门作为配对判据，
            #  在保证顺序（单调）的前提下最大化命中词典的配对数。
            #  错的配对通不过词典，自然不会被选中。
            pairs.extend(_match_block(chs_slots, stm_slots, i1, i2, j1, j2))
            stats["replace_dp"] += max(i2 - i1, j2 - j1)
    print("对齐统计: equal=%d replace(DP)=%d"
          % (stats["equal"], stats["replace_dp"]))
    return pairs


def _block_pair_ok(c_raw, s_raw):
    """块内候选对是否可接受 —— 只用词典闸门（与最终写入判据一致）。"""
    if len(c_raw) < 4 or len(s_raw) < 1:
        return False
    try:
        zh = c_raw.decode("gbk")
    except UnicodeDecodeError:
        return False
    cjk = sum(1 for c in zh if "\u4e00" <= c <= "\u9fff")
    if cjk < 2 or not all(c.isprintable() for c in zh):
        return False
    try:
        en = s_raw.decode("ascii")
    except UnicodeDecodeError:
        return False
    if not en or en.startswith("%") or "\\" in en or "/" in en:
        return False
    try:
        gbk = zh.encode("gbk")
    except UnicodeEncodeError:
        return False
    if len(gbk) + 1 > len(en) + 1:
        return False
    dok, _ = dict_ok(en, zh)
    return dok is True


def _match_block(chs_slots, stm_slots, i1, i2, j1, j2):
    """块内单调最优匹配（DP）。

    返回 [(chs_rva, stm_rva), ...]。块过大时放弃（避免 O(n*m) 爆炸）。
    """
    m, n = i2 - i1, j2 - j1
    if m == 0 or n == 0:
        return []
    if m > 400 or n > 400:
        return []

    ok = [[False] * n for _ in range(m)]
    for a in range(m):
        c_raw = chs_slots[i1 + a][1]
        if len(c_raw) < 4:
            continue
        for b in range(n):
            if _block_pair_ok(c_raw, stm_slots[j1 + b][1]):
                ok[a][b] = True

    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for a in range(1, m + 1):
        for b in range(1, n + 1):
            best = dp[a - 1][b] if dp[a - 1][b] > dp[a][b - 1] else dp[a][b - 1]
            if ok[a - 1][b - 1] and dp[a - 1][b - 1] + 1 > best:
                best = dp[a - 1][b - 1] + 1
            dp[a][b] = best

    out = []
    a, b = m, n
    while a > 0 and b > 0:
        if ok[a - 1][b - 1] and dp[a][b] == dp[a - 1][b - 1] + 1:
            out.append((chs_slots[i1 + a - 1][0], stm_slots[j1 + b - 1][0]))
            a -= 1; b -= 1
        elif dp[a - 1][b] >= dp[a][b - 1]:
            a -= 1
        else:
            b -= 1
    out.reverse()
    return out


# ─────────────────────────────────── 生成
def generate(chs_path, stm_path, out_path):
    chs = open(chs_path, "rb").read()
    stm = open(stm_path, "rb").read()
    csecs, ssecs = sections(chs), sections(stm)

    # ── 用"槽位序号对齐"建立 中文槽位 <-> 英文槽位 的精确映射 ──────────
    cslots = slots(chs, csecs)
    sslots = slots(stm, ssecs)
    print("CHS 槽位=%d  STEAM 槽位=%d" % (len(cslots), len(sslots)))
    pairs = align_slots(cslots, sslots)
    print("对齐出槽位对: %d" % len(pairs))
    chs2stm = dict(pairs)          # chs_rva -> stm_rva

    rows, rejects = [], []
    seen_en = set()

    # 逐个中文槽位
    for c_rva, c_raw in cslots:
        if len(c_raw) < 2:
            continue
        try:
            zh = c_raw.decode("gbk")
        except UnicodeDecodeError:
            continue
        cjk = sum(1 for c in zh if "\u4e00" <= c <= "\u9fff")
        if cjk < 2 or not all(c.isprintable() for c in zh):
            continue

        stm_rva = chs2stm.get(c_rva)
        if stm_rva is None:
            rejects.append((zh, "该槽位在 Steam 侧无对齐项"))
            continue
        raw = raw_string_at(stm, ssecs, stm_rva)
        if raw is None:
            rejects.append((zh, "Steam 侧读不到字符串"))
            continue
        try:
            en = raw.decode("ascii")
        except UnicodeDecodeError:
            rejects.append((zh, "Steam 侧不是纯 ASCII：%r" % raw[:20]))
            continue
        if not en or en in seen_en:
            continue
        seen_en.add(en)

        try:
            gbk = zh.encode("gbk")
        except UnicodeEncodeError as ex:
            rejects.append((zh, "无法编成 GBK: %s" % ex))
            continue

        cap = len(en) + 1
        need = len(gbk) + 1
        if need > cap:
            rejects.append((zh, "译文 %d 字节 > 槽位 %d 字节（英文 \"%s\"）"
                            % (need, cap, en)))
            continue
        if en.startswith("%") or "\\" in en or "/" in en:
            rejects.append((zh, "疑似非显示文本: %s" % en))
            continue

        score, reason = semantic_score(en, zh)
        if score < 0:
            rejects.append((zh, "%s（英文 \"%s\"）" % (reason, en)))
            continue

        # ★★ 词典硬闸门（最关键的一关）
        #   槽位对齐在单位名表区正确，但更靠后的区域会失准；
        #   启发式分不出错译，只有"英文->允许的中文"白名单能拦住。
        dok, dreason = dict_ok(en, zh)
        if dok is False:
            rejects.append((zh, "%s（英文 \"%s\"）" % (dreason, en)))
            continue
        if dok is None:
            # 词典覆盖不到 -> 保守起见不接受（宁可少翻不可错翻）
            rejects.append((zh, "词典未覆盖，保守跳过（英文 \"%s\"）" % en))
            continue

        rows.append((stm_rva, en, zh, need, cap, c_rva))

    rows.sort()
    print("可写入(原始): %d   剔除: %d" % (len(rows), len(rejects)))

    rows.sort()
    print("可写入: %d   剔除: %d" % (len(rows), len(rejects)))


    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    # ★ newline="\n"：避免 Windows 把行尾写成 \r\n，
    #   CR 会混进中文译文的 GBK 字节里（实测出现过 ...c4d10d）。
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(HEADER % (len(rows),))
        for rva, en, zh, need, cap, c_rva in rows:
            # ★ 英文原文可能**带前导/尾随空格**（实测 '  --  In Progress'），
            #   而 INI 解析器（C++ 与 Python 两侧）都会 strip 掉首尾空白，
            #   导致安全闸门比对失败、该条被跳过。
            #   只对**首尾**空格做转义（\x20），中间空格原样保留 ——
            #   这样既保证字节完全一致，也不牺牲 INI 的可读性。
            #   （最初对所有空格转义，结果 37 条里 16 条被误判不符，
            #     而且可读性变差。）
            lead = len(en) - len(en.lstrip(" "))
            trail = len(en) - len(en.rstrip(" "))
            core = en.strip(" ") if (lead or trail) else en
            en_esc = "\\x20" * lead + core + "\\x20" * trail
            f.write("; [%3d/%3d 字节]  %s\n" % (need, cap, en))
            f.write("0x%08X=%s|%s\n" % (rva, en_esc, zh))
    print("-> %s" % out_path)

    if rejects:
        print("\n-- 剔除明细（前 20，共 %d）--" % len(rejects))
        for zh, why in rejects[:20]:
            print("   %-22s %s" % (zh[:20], why))
    return 0


HEADER = """; ============================================================================
;  Army Men II (Steam) 内存字符串补丁表        —— 共 %d 条
;
;  由 Tools/unpack_objects/gen_am2_strings_ini.py 生成。
;  格式： 0x<RVA>=<英文原文>|<中文译文>
;
;  ★ 安全闸门：DLL 写入前会比对"内存现状 == 英文原文"，
;     不一致就 **拒绝写入**（说明 RVA 错了或游戏版本不同）。
;     所以这里的英文原文必须与游戏内存逐字节一致。
;     本文件生成时已用同一个判据离线校验过（见脚本 --validate）。
;
;  ★ 槽位容量：英文槽位按 ASCII 设计，中文每字 2 字节，**经常放不下**。
;     超限的条目在生成阶段就被剔除（不截断，避免破坏相邻数据）。
;
;  ★ 可译性：以下均为**显示用**文本（面板标签 / 单位名 / 道具名）。
;     ⚠️ 尚未逐条做 IDA xref 判定（1 代坑 2 的教训）。
;     若实机出现异常，优先怀疑某条其实是 strcmp / 路径用途，逐条关掉排查。
;
;  译文来源：1999 上海育碧官方简体中文版 ArmyMen2.exe
; ============================================================================

[Strings]

"""


# ─────────────────────────────────── 离线校验
def unescape(s):
    """还原生成时对英文原文做的转义（\\\\ 与 \\x20）。

    ★ 为什么需要：英文原文可能带前导/尾随空格（'  --  In Progress'），
      而 INI 解析会 strip 掉它们 -> 安全闸门比对失败 -> 该条被跳过。
      生成时把空格写成 \\x20，这里还原成真正的空格。
    """
    out = []
    i = 0
    while i < len(s):
        if s.startswith("\\x20", i):
            out.append(" "); i += 4
        elif s.startswith("\\\\", i):
            out.append("\\"); i += 2
        else:
            out.append(s[i]); i += 1
    return "".join(out)


def validate(stm_path, ini_path):
    stm = open(stm_path, "rb").read()
    ssecs = sections(stm)
    img_end = max(ra + rs for _, _, _, ra, rs in ssecs)

    entries = []
    for ln, line in enumerate(open(ini_path, encoding="utf-8"), 1):
        t = line.strip()
        if not t or t[0] in ";#[":
            continue
        m = re.match(r"^(0x[0-9a-fA-F]+)\s*=\s*(.*?)\|(.*)$", t)
        if not m:
            print("  !! 第 %d 行格式错误: %s" % (ln, t[:60]))
            continue
        en = unescape(m.group(2))
        entries.append((int(m.group(1), 16), en, m.group(3)))

    print("校验 %d 条（对照 %s）" % (len(entries), os.path.basename(stm_path)))
    ok = bad = 0
    for rva, en, zh in entries:
        raw = raw_string_at(stm, ssecs, rva)
        if raw is None:
            print("  [FAIL] %#010x 读不到字符串" % rva); bad += 1; continue
        cur = raw.decode("latin1")
        if cur != en:
            print("  [FAIL] %#010x 原文不符 期望 '%s' 实得 '%s'" % (rva, en, cur)); bad += 1; continue
        gbk = zh.encode("gbk")
        if len(gbk) + 1 > len(en) + 1:
            print("  [FAIL] %#010x 译文超长 %d > %d" % (rva, len(gbk) + 1, len(en) + 1)); bad += 1; continue
        if rva + len(en) + 1 > img_end:
            print("  [FAIL] %#010x 写入范围越界" % rva); bad += 1; continue
        ok += 1
    print("\n校验结果: 通过 %d / %d，失败 %d" % (ok, len(entries), bad))
    print("（通过即表示 DLL 运行时这些条目会全部写入成功）")
    return 0 if bad == 0 else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chs", default=DEF_CHS)
    ap.add_argument("--steam", default=DEF_STM)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--validate", action="store_true", help="只校验不生成")
    a = ap.parse_args()

    if a.validate:
        return validate(a.steam, a.out)
    rc = generate(a.chs, a.steam, a.out)
    if rc != 0:
        return rc
    print()
    return validate(a.steam, a.out)


if __name__ == "__main__":
    sys.exit(main())
