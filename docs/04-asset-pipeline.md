# 资产提取与差异移植流程

> 覆盖：从中文母盘提取资产、判定哪些需要本地化、差异移植打包、
> 与官方包/Steam 基线对账。2/3/4 代可复用整套方法论。

---

## 1. 为什么用"差异移植"而不是整包替换

**先看 1 代的教训**：原补丁（2018 年发布）直接整包替换了 `objects.dat`，
结果把 1998 版的一个地形缺陷一起带进了中文版
（详见 [`02-pitfalls.md`](02-pitfalls.md) 坑 3）。

差异移植的做法：

```
Steam v1.2 原版 objects.dat（基底，保留所有上游修复）
        │
        │  只覆盖"N 个确实含中文的块"
        ▼
最终 objects.dat
        │
        ├─ 汉化块   → 与 1998 中文盘逐字节一致
        ├─ cat 17   → Steam 美术 + 剥离多余掩膜（bug 修复）
        └─ 其余     → Steam v1.2 原样
```

1 代的最终数字：

| 内容 | 块数 | 来源 |
|---|---|---|
| 汉化块（cat 18/44/45/46/47） | 37 | **与 1998 中文盘逐字节一致（37/37）** |
| cat 17 建筑块 | 4 | Steam 美术 + 剥离掩膜 |
| 其余 | 1633 | Steam v1.2 原样 |

**与 1998 母盘的差异精确为 4 块** —— 正是 bug 修复。这就是目标状态。

---

## 2. 第一步：全量对账，找出真正需要本地化的文件

不要凭感觉判断"哪些文件含中文"。逐文件 sha256 比对。

```powershell
# 中文母盘 vs Steam 基线，逐文件 sha256
# 1 代用 _filehash.csv（全量哈希表）
```

1 代的实测结果（`Army1_CHS/MANIFEST.md`）：

### texture —— 需本地化 147 项

| 位置 | 总数 | 与 Steam 不同 | 判据 |
|---|---|---|---|
| `ui\Screens\Briefs\` | 138 | **135** | 抽帧确认中文简报文 |
| `ui\Screens\`（根） | 43 | **12** | `alp_load`/`bay_load`/`des_load`/`multihost`/`Title_legal` 等 |
| `ui\Screens\{blue,green,grey,tan}` | 127 | **0** | 纯按钮底图，无文字 |
| `ui\Stratmap\` | 20 | **0** | 战略图，两侧一致 |
| `maps\Maps\*.BMP` | 41 | **27** | 中文烧入标注 |

### data —— 需本地化 4 项

| 文件 | 与 Steam | 说明 |
|---|---|---|
| `text\campaigns\Campaign.cpn` | 不同 | 28 关 MISSION TITLE 全中文 |
| `terrain\Alpine\objects.dat` | 不同 | +1108 B，key 集合一致 |
| `terrain\Bayou\objects.dat` | 不同 | 字节数相同但 hash 不同 |
| `terrain\Desert\objects.dat` | 不同 | 同上 |
| `BootCamp.cpn` / `final_pal.bmp` / `explosions.axs` / `AiDefault.aai` | **相同** | 无需处理 |

### audio —— 3 项

`voices.ast`（配音文本表，GBK 可读）、`voices.asd`、`sounds.asd`。
`streams.asd` 相同（音乐流未本地化）。

### video —— 真汉化 10 / 未汉化 6

| 文件 | 判定 |
|---|---|
| `intro.smk` / `IntroSml.smk` | 含中文 |
| `lose1~4.smk` / `lose1~4Sml.smk` | 含中文 |
| `credits*.smk` / `logo20*.smk` | **未汉化**，sha 与 Steam 相同 |
| `final.smk` / `FinalSml.smk` | **未汉化**，是同片不同码率 |

> ★ **视频不能只看 sha。** 中文母盘的 `.smk` 普遍比 Steam 小
> （低码率重编码）。`final.smk` 就是"同片不同码率"而非汉化版 ——
> 已用逐帧抽图纠正过这个误判。
>
> **可移植经验**：视频类资产必须**抽帧目视**才能下结论。

---

## 3. 第二步：判定"是否真的是本地化"

sha 不同 **≠** 需要覆盖。可能是：

- 重编码（视频）
- 调色板差异（objects.dat）
- 修正了一些无关的东西

对 `objects.dat` 这类容器，要**逐块**比对而不是逐文件。

### 1 代的逐块分析结果

```
Alpine: 差异恰好 41 个 key
        cat 17: 4 个  ← 经确认无中文，只有多余掩膜
        cat 18: 16 个
        cat 44: 6 个
        cat 45: 5 个
        cat 46: 5 个
        cat 47: 5 个
```

进一步目视确认：

| 分类 | 是否含中文 | 证据 |
|---|---|---|
| cat 44-47 | ✅ **是** | 迷你地图边框：`兵力型`/`车辆型`/`武器型`、`主基地X1回`/`后勤中转站`、`遥控`/`军械库`/`弹药库`、`发射控制台` vs `VEHICLE`/`TRUCK`/`CANNON` |
| cat 18 | ✅ **是** | `AIRBASE X1`/`HOME REPAIR B1`/`DISPENSARY B1`、`MOTOR POLE`/`ARMORY`、`RIFLE SHOP`、`SEND TO` |
| cat 17 | ❌ **否** | 同一栋木屋的完好/损坏态，视觉完全一致，只有掩膜差异 |

**这个判定直接决定了分类列表**：覆盖 `{18, 44, 45, 46, 47}`，排除 `17`。

### 调色板差异

1 代的两个版本调色板**只差 index 248**：

| | 值 |
|---|---|
| 1998 中文盘 | 蓝 `(89, 132, 212)` |
| Steam v1.2 | 暗红 `(120, 36, 76)` |

产物使用 Steam 调色板，实测中文渲染正常。
（该色位的原始用途**未查明**，见 `01-technical-archive.md` 第 7 节。）

---

## 4. 第三步：提取差异块

```powershell
# 从中文母盘的 objects.dat 提取指定分类的块
python Tools\unpack_objects\build_object_chs.py --categories 18 44 45 46 47
```

产出 `Army1_Object_CHS/<Terrain>/`：

```
Army1_Object_CHS/Alpine/
├─ raw/                37 个解包后的对象块（按 key 命名）
└─ manifest.json       块清单（key / 大小 / 来源）
```

### ★ 幂等性要求（重要）

这个脚本**必须连跑两次结果一致**。

1 代最初的实现有 bug：先清空 `raw/` 缓存，第二次运行时把
"文件读不到"误判成"与 Steam 不同"，37 个块被错误扩成 273 个。

**修复原则**：比较基准**始终从中文母盘的原始 objects 读取**，
不依赖可能被自己清空的中间缓存。

```python
# ✓ 对的：基准是不变的原始文件
chs_objs = load_objects(Army1_CHS/terrain/<T>/objects.dat)
for obj in chs_objs:
    if chs_objs[obj] != steam_objs[obj]:
        include(obj)
```

> **移植经验**：用增量缓存做比较逻辑时，
> "缓存缺失"和"内容不同"**必须分开处理**，不能共用一条判断分支。

---

## 5. 第四步：差异打包

```powershell
python Tools\unpack_objects\pack_diff.py `
    <steam objects.dat> `
    Army1_Object_CHS/<Terrain> `
    out.dat `
    --categories 18 44 45 46 47 `
    --strip-mask 567552 567553 585952 585953
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `base` | Steam 原版 `objects.dat`（基底） |
| `overlay_dir` | `Army1_Object_CHS/<Terrain>`（含 `raw/` 与 `manifest.json`） |
| `--keys` | 显式指定要覆盖的 key |
| `--categories` | 按分类批量覆盖 |
| `--palette` | 是否同时用 overlay 的调色板（**默认否**，保留 base 的） |
| `--strip-mask` | 剥离碰撞掩膜的 key 列表 |

### `--strip-mask` 的行为

只把 `maskSize` 写成 0 并丢弃掩膜字节，
**不动 graphic / shadow / hotspot / linkspot / maskRect / flags**。

所以**不损失任何汉化像素** —— 这正是它安全的原因。

实现（`pack_diff.py` 的 `strip_mask()`）：

```python
# 顺序解析块头，走到 maskSize 位置
p = 24
gsize = read_i32(p); p += 4 + gsize      # 跳过 graphic
ssize = read_i32(p); p += 4 + ssize      # 跳过 shadow
msize = read_i32(p); p += 4
if msize == 0: return blob, False        # 本就没有
if p + msize + 16 != len(blob): return blob, False   # 结构不符，拒绝改
# 置 0 并移除掩膜字节
out = bytearray(blob[:p]); pack_into("<i", out, p-4, 0)
out += blob[p + msize:]
```

注意最后两个检查：**结构不符合预期就拒绝修改**，
而不是硬改 —— 避免在格式假设错误时静默破坏文件。

### ★ 执行顺序：先覆盖，后剥离

`--strip-mask` 的剥离步骤必须跑在**覆盖之后**。

1 代的实际数据：

```
Alpine strip: requested 4, actually stripped 2
```

为什么是 2 不是 4？因为：

| key | 基底（Steam）状态 | 剥离是否生效 |
|---|---|---|
| 567552 (n328 d0) | `maskSize 5264` | ✅ 剥离 |
| 567553 (n328 d1) | `maskSize 0` | ⏭ 本就无掩膜 |
| 585952 (n903 d0) | `maskSize 5824` | ✅ 剥离 |
| 585953 (n903 d1) | `maskSize 0` | ⏭ 本就无掩膜 |

**Steam 只删了 d1 的掩膜，d0 的还在。** 所以单纯"不覆盖 cat 17"
并不足以修复 bug —— 必须主动剥离。这个发现纠正了一个最初的错误假设。

---

## 6. 第五步：对账验证

### 6.1 与官方汉化包对账

```powershell
python Tools\ci\cmp_official.py `
  --official "I:\...\玩具兵大战1" `
  --steam    "I:\...\Army Men I STEAM"
```

1 代的结果：

| 分类 | 数量 | 判定 |
|---|---|---|
| 一致 | 215 | ✓ |
| **缺失（真）** | **0** | ✓ |
| 不一致（需查） | 3 | 逐个查清 |
| 官方冗余（无害） | 264 | 官方全量复制，无需下发 |

### ★ 关键概念："官方包里的文件" ≠ "需要汉化的文件"

官方包做了**全量复制** —— 把 264 个与 Steam 完全相同（未汉化）的文件
也一起打包了。实测确认它们在 Steam 里**本来就存在且字节相同**，无需下发。

判定逻辑：

```python
if up is None:                        # 官方有、我们没有
    if steam_file and md5(steam_file) == md5(official_file):
        redundant.append(rel)         # 官方冗余，无害
    else:
        missing.append(rel)           # 真缺失，必须补
```

### 6.2 结构完整性校验

```powershell
python Tools\unpack_objects\verify_objects.py <objects.dat>
```

期望：

```
块边界精确匹配 : 1674 / 1674
异常块         : 0
```

这个校验确认：目录表的 key 与 offset 一一对应，每个块的
`graphicSize`/`shadowSize`/`maskSize` 都能走到正确的边界。

---

## 7. 视频与音频资产

### 视频（`.smk`）

Smacker 格式。**不能用 sha 判断是否汉化** —— 中文盘的通常是低码率重编码。

正确流程：

1. 用 ffmpeg 或 Smacker 工具抽关键帧
2. 目视对比同画面的文字
3. 记录判定依据（1 代写进了 `MANIFEST.md`）

1 代的结论：`intro`/`lose1-4` 及其小版含中文；
`credits`/`logo20`/`final` **未汉化**。

### 音频（`.asd` / `.ast`）

`.ast` 是文本表（1 代的 `voices.ast` 含 GBK 可读的配音文本），
`.asd` 是音频数据。

1 代判定：`voices.asd`、`sounds.asd` 是中文配音；`streams.asd` 是音乐流，未本地化。

> **移植注意**：2/3/4 代的音频如果也有中文配音，
> 这些资源体积大（1 代 20.8 MB），且**必须随包分发**（无法运行时补丁）。

---

## 8. 地图与文本资产

`.txt`（任务脚本）、`.rul`（多人规则）、`.cpn`（战役定义）是**纯文本**，
游戏按字节解析。

### ★ 换行符保护

`.gitattributes` 必须把它们标为 `-text`：

```gitattributes
*.txt      -text
*.rul      -text
*.cpn      -text
*.aai      -text
```

否则 `core.autocrlf=true` 会让检出时 LF→CRLF，
**每行多 1 字节，后续所有偏移错位**，症状是"地图加载崩溃"。

实测证据（`AiDefault.aai`）：磁盘 28473 B（CRLF=896），
git blob 27577 B（CRLF=0）—— 少了 896 字节。

### 地图文件类型（1 代）

| 类型 | 数量 | 说明 |
|---|---|---|
| `.AMM` | 18 | 关卡几何，两版**字节相同** |
| `.ATL` | 18 | 图集，两版**字节相同** |
| `.BMP` | 41 | 地图底图，27 个含中文标注 |
| `.rul` | 20 | 多人任务脚本，含目标文字 |
| `.txt` | 52 | 帧/配置数据 |

> `.AMM`/`.ATL` 两版相同，说明**地形缺陷不在关卡数据里**，
> 而在 `objects.dat` 的资源块 —— 这个观察帮助定位了「羊肠河」bug 的根因。

---

## 9. 资产流程清单

```
[ ] 全量 sha256 对账（中文母盘 vs Steam 基线）
[ ] 逐文件分类：相同 / 不同
[ ] 对"不同"的文件逐个判定：真汉化 / 重编码 / 无关差异
[ ] 视频：抽帧目视，不能只看 sha
[ ] objects.dat：逐块（按 key）比对，不能只看文件
[ ] 确认哪些分类含中文（目视像素）
[ ] 识别"旧汉化包缺少的新版修复" ← 最容易被忽略
[ ] 提取差异块，验证幂等性（连跑两次）
[ ] 差异打包（先覆盖，后剥离掩膜）
[ ] 结构校验：块边界 N/N
[ ] 与官方包对账：真缺失 = 0
[ ] 确认 .gitattributes 保护了文本类资产
```

---

## 相关文档

| 文档 | 内容 |
|---|---|
| [`00-porting-map.md`](00-porting-map.md) | 移植地图（先读这个） |
| [`01-technical-archive.md`](01-technical-archive.md) | objects.dat 二进制格式 |
| [`02-pitfalls.md`](02-pitfalls.md) | 踩坑清单 |
| [`03-build-and-release.md`](03-build-and-release.md) | 构建与发布 |
| [`../Army1_CHS/MANIFEST.md`](../Army1_CHS/MANIFEST.md) | 1 代中文母盘资产清单 |
| [`../Tools/README.md`](../Tools/README.md) | objects.dat 格式与官方打包器 |
