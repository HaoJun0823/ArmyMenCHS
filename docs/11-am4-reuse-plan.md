# 4 代（Army Men: World War）复用方案

> **4 代与 2/3 代同引擎**，因此三条已经跑通的管线可以继续用。
> 本文只写「4 代该怎么做」，原理不在本文重复。
>
> 对象：`ARMYMENWW` 系列（Steam/GOG 版 `amww.exe`）
> 侦察日期：2026-10-16 ｜ 目标：`I:\LocalGames\Army Men\Army Men - World War GOG`

---

## 0. 一句话结论

**4 代是三代里复用度最高的一代** —— 引擎、载体、工具链全部对上，
已有实测证据（见 §1）。**唯一真正待查的是"有没有官方中文母盘"**，
这一项决定工作量是"差异移植"还是"从零翻译 + AI 配音"。

---

## 1. 已实测的 4 代事实（不是推测）

以下全部在 `Army Men - World War GOG` 上实测得到：

| 项 | 实测结果 | 对照 3 代 |
|---|---|---|
| exe | `amww.exe`，757,760 B，**32 位**（machine `0x14C`） | 同（32 位） |
| 导入（注入用） | **`DINPUT.dll!DirectInputCreateA`（按名导入）** | ✅ **完全相同** |
| 另导入 | `DSOUND.dll`（按序号 ord1）、`DDRAW.dll!DirectDrawCreate` | — |
| 界面文本 | **`strings\strings.txt` 存在**，4482 B / 323 行 / 纯 ASCII | ✅ 同机制（3 代为 4420 B / 320 行） |
| `strings.txt` 与 3 代差异 | 相似度 **0.955**，仅 14 处差异块（多为兵种名） | — |
| `title.dat` | FILEID **`0x81920667`**，3,502,576 B，**197** 对象 | ✅ **魔数完全相同**（3 代 203 对象） |
| `shared.dat` | FILEID **`0x81920668`**，2,729,541 B，**969** 对象 | ✅ **魔数完全相同**（3 代 1113 对象） |
| 目录结构 | `01-title/ aai/ audio/ avi/ bitmaps/ data/ rules/ save/ strings/` | ✅ 同 |
| `data` / `rules` | 236 / 75 文件 | ✅ **与 3 代数量完全相同** |
| cnc-ddraw 需求 | `ddraw.dll` + `ddraw.ini` | ✅ 同 |

> ★ **魔数相同是最有价值的发现**：`am3_dat.py` 的解析逻辑可以**直接用于 4 代**，
> 不需要重新逆向格式。这印证了 `00-porting-map.md` §4 里
> "不要假设魔数相同，必须每代重测"的警告 —— 这次重测的结果是"确实相同"。

---

## 2. 三条可复用管线

### 2.1 dat 拆包 / 回包 —— `Tools/am3_dat.py` + `am3_dat_pack.py`

**可复用程度：高**（魔数相同，但对象数不同）

```powershell
# 拆 4 代的 title.dat（FILEID 与 3 代相同，可直接用）
python Tools/am3_dat.py unpack "<4 代目录>/title.dat" Army4_Object_CHS/title

# 改完贴图后回包
python Tools/am3_dat_pack.py --src Army4_Object_CHS/title --out title.dat \
       --expect-size 3502576
```

**为什么能直接用**：4 代 `title.dat` 的 FILEID 是 `0x81920667`、
`shared.dat` 是 `0x81920668`，**与 3 代逐一相同**；
对象块布局（`key/width/height/sprite_flags` + 调色板 + 绝对偏移）也一致。

**4 代必须重测的三件事**：

| 项 | 3 代值 | 4 代值 | 为什么要重测 |
|---|---|---|---|
| `title.dat` 原版大小 | 4,298,896 | **3,502,576** | 回包的 `expect_size` 必须改 |
| `shared.dat` 原版大小 | 2,936,433 | **2,729,541** | 同上 |
| 对象数 | 203 / 1113 | **197 / 969** | 校验器的逐对象断言要重新生成 |

> ★ **判据永远用「逐对象偏移与长度不变」，不是「总大小不变」**（原因见
> [`10-am3-build-and-release.md`](10-am3-build-and-release.md) §4.2）。
> 拆包时先跑一次 `unpack` 生成 `manifest.json`（含 `source_sha256`），
> 它就是 4 代的权威快照。

### 2.2 qwen3-tts 配音生成 —— `Tools/tts/`

**可复用程度：高**（流程与脚本可直接用，台词表要重做）

完整流程：

```
① 取英文原声基线      audio/vos/*.wav  ->  Army4_Original/audio/vos/
② ASR 转写 + 校正     (faster-whisper large-v3) -> vos_en_raw.json
③ 人工中译            -> vos_translations.json
④ 造角色音色参考音    _gen_voice_refs.py  ->  Army4_Voice_CHS/base/
⑤ 全量生成            _batch_dub2.py     ->  Army4_Voice_CHS/audio/vos/
⑥ 进构建载荷          ci_build_am4.py 第 N 步拷进 build_out（**必须**，见下）
```

**4 代需要改的**：

| 项 | 说明 |
|---|---|
| 目录名 | `Army3_Voice_CHS` → `Army4_Voice_CHS`（`_batch_dub2.py` 的 `OUTDIR`） |
| 音色档案 | `voice_cast.py` 的 12 个角色需按 4 代兵种/角色重审 |
| 台词表 | `vos_translations.json` 全量重做（4 代台词不同） |
| 采样率对齐 | 逐文件读游戏原始 wav 的采样率/位深（脚本已自动做） |

**★ 关键约束（3 代踩过）**：配音**必须在组装阶段（`ci_build_am4.py`）拷进
`build_out`**，不能只在打包阶段拷 —— 否则配音不进 `MANIFEST.json`，
校验器的逐条目对照会**静默跳过**，形成"假绿"盲区。

**★ 别用客观指标当判据**：MFCC / 说话人编码器 / yin 基频在
**11025 Hz 游戏音频上均不可靠**（编码器说最一致的，人耳判断相反）。
详见 [`../Tools/README_pipelines.md`](../Tools/README_pipelines.md)。

### 2.3 bmp/png AI 自动汉化 —— `Tools/bmp_png_tool.py` + `Tools/title/`

**可复用程度：高**（流程通用，参数需重测）

| 环节 | 工具 | 4 代注意 |
|---|---|---|
| BMP ↔ PNG 可逆转换 | `Tools/bmp_png_tool.py` | 改 `BASE` 指向 `Army4_NEW_CHS` |
| 差异审计 | `Tools/audit_bmp_am2.py`、`bmp_diff_region.py`、`bmp_side_by_side.py` | 通用 |
| dat 内贴图烧字 | `Tools/title/*.py`（5 个） | 文字色白名单要**重新穷举**（4 代 UI 配色可能不同） |

**★ 复用 `Tools/title/` 时必须重测的**：

1. **文字色白名单**：3 代是 `#FFFBF0`/`#FEE402`/`#29DF29`/`#9CAA7B` 四色。
   4 代若换了 UI 配色，白名单必须重新穷举，否则会**大面积误检**或漏检。
2. **背景是否近似常量**：3 代面板底是 `#315D31` 系绿色、横向无渐变，
   所以"纯色填充 + 原位置重绘"成立。4 代要重新确认。
3. **调色板色数**：3 代单图 ≤ 40 色、全库 252 色。这决定了最近色吸附的误差。

**★ 中文字库可以直接复用 `Army2_CHS/Hzk16`** —— 3 代就是这么做的，
且实机渲染同源。4 代同一引擎，**大概率同样可用**（但需实机确认）。

---

## 3. 4 代开工清单

按顺序做，**第 1 项决定后面所有工作量**：

```
[ ] ① 查是否有官方中文母盘
      有 -> 走"差异移植"（省掉 2.2 的配音与 2.3 的大部分翻译）
      无 -> 从零翻译 + AI 配音（3 代路线，工作量已知：约 171 条配音 + 320 行 UI）
      ❓ 待查

[ ] ② 建资产树 Army4_Original/
      照 Tools/build_army3_assets.py 改（★ 注意它排除 update/ 与 save/，
      并收 audio/vos 作配音对照基线；路径必须镜像源相对路径）

[ ] ③ 测 dat 魔数与对象数
      title.dat=0x81920667 / shared.dat=0x81920668（已测）
      记录原版大小与对象数（已测：3502576/197、2729541/969）

[ ] ④ 确认 ASI 注入可用
      dinput.dll 按名导入（已测）—— 与 2/3 代同一份 asi/dsound.dll 改名
      放一个 log-only 的空 ASI 到 scripts\ 验证能被加载

[ ] ⑤ 测 strings.txt 硬约束
      行数下界 / 单行上限 / 数组容量（3 代是 ≥320、≤510B、容量 320）
      ★ 4 代是 323 行，**容量与下界必须重新确认**（不要猜）

[ ] ⑥ 建 DLL 工程 Army4_Extend_Dll/
      照 Army3_Extend_Dll 复制，重测文字渲染函数地址
      ★ charWidthVA 那个坑：它可能是 atlasOffsetVA 的位移，不是宽度表
        （3 代实证：charWidthVA(0x698DAC) == atlasOffsetVA(0x698D6C) >> 32 WORD）

[ ] ⑦ 抄构建脚本
      ci_build_am3.py / make_patch_am3.py / verify_release_am3.py
      -> *_am4.py，逐项改判据（千万不要"改几个常量就想复用"，见 00 §4）

[ ] ⑧ 反代验收
      注入错误 -> 确认校验器能拦下（3 代做了 7 项，全部拦下）
```

---

## 4. 已知风险与遗留

| 风险 | 说明 |
|---|---|
| **工作区已被 3 代补丁污染** | `Army Men - World War GOG` 目录里已经有 3 代的 `ddraw.dll`/`ddraw.ini`/`dinput.dll`（时间戳 `2026-10-15 18:46:40`，与仓库内文件**逐字节相同**）。建 `Army4_Original` 前**务必先清理或从干净安装重新取基线**，否则会把 3 代的补丁文件当成"4 代原版"入库。 |
| `update/` 污染 | `build_army3_assets.py` 已排除 `update/`（本补丁安装产物）。4 代脚本必须同样排除，否则重跑会用中文补丁内容覆盖英文基线。 |
| `ddraw.ini` 共用 | 2/3 代共用同一份 `ddraw.ini`，只在 3 代实测过。4 代沿用前建议单独验一遍（嫌疑参数 `maxgameticks=120`、`singlecpu=true`）。 |
| `amtisged.dll` 类配置器 | 3 代的启动配置器 UI 仍未汉化。4 代若也有类似组件，同样会漏。 |

---

## 相关文档

| 文档 | 内容 |
|---|---|
| [`00-porting-map.md`](00-porting-map.md) | 移植地图：开工前四项核查、可复用工具、开工顺序 |
| [`10-am3-build-and-release.md`](10-am3-build-and-release.md) | 3 代构建与发布（4 代脚本的模板） |
| [`08-am3-i18n-inventory.md`](08-am3-i18n-inventory.md) | 3 代 i18n 载体侦察（`strings.txt` 三条硬约束） |
| [`09-am3-title-bitmap-chs.md`](09-am3-title-bitmap-chs.md) | 贴图烧字算法与 13 位对齐陷阱 |
| [`../Tools/README_pipelines.md`](../Tools/README_pipelines.md) | `Tools/tts/` 与 `Tools/title/` 使用说明 |
| [`05-am2-porting-guide.md`](05-am2-porting-guide.md) | 2 代视角的移植对照表 |
