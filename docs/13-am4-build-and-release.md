# Army Men: World War (系列第 5 代 / 施工第 4 批) 构建与发布流程

> ★ 编号说明（全文通用）：本文大量出现的「4 代」指的是**汉化施工批次**
> （目录号 `Army4_*`），不是游戏系列的发行序号。
> 本作《世界大战 / World War》是系列**第 5 代**；系列第 4 代是
> 《空中战术 / Air Tactics》，对应目录 `Army5_*`（见
> [`15-am5-reverse-findings.md`](15-am5-reverse-findings.md)）。
> 面向玩家的 `必读说明_*.txt` 一律按**系列序号**称呼，不按目录号。
>
> 4 代的构建、校验、打包、CI。与 1 代 [`03-build-and-release.md`](03-build-and-release.md)、
> 2 代 [`07-am2-build-and-release.md`](07-am2-build-and-release.md)、
> 3 代 [`10-am3-build-and-release.md`](10-am3-build-and-release.md) **同构**，
> 差异集中在 §1 与 §4。
>
> 4 代的复用方案见 [`11-am4-reuse-plan.md`](11-am4-reuse-plan.md)，
> exe 逆向实测见 [`12-am4-reverse-findings.md`](12-am4-reverse-findings.md)。

---

## 0. 一句话结论

**4 代的 CI 三段式与全部载荷（含中文配音）均已就绪，本地全绿。**
中文配音已生成 250 条（qwen3-tts），位于 `Army4_Voice_CHS/audio/vos/`；
CI 不按数量硬校验（配音条数随音效甄别浮动，且缺失会静默回退英文原声），
只校验文件名是英文原声子集、体积下限、抽样探针。

| 环节 | 状态 |
|---|---|
| `compile_dll_wine.py --proj Army4_Extend_Dll` | ✅ 配置就位（源码清单与 vcxproj 逐项一致） |
| `ci_build_am4.py`（含 dat 回包） | ✅ 全绿（含 250 条配音拷入） |
| `make_patch_am4.py` | ✅ 全绿 |
| `verify_release_am4.py` | ✅ **82 项检查，失败 0** |
| 对抗性验证（14 项注入错误） | ✅ **全部拦下**，恢复后回绿 |
| 中文配音 | ✅ **已生成 250 条**（qwen3-tts，见 §4） |

---

## 1. 与 1/2/3 代的差异

| 项 | 1 代 | 2 代 | 3 代 | 4 代 |
|---|---|---|---|---|
| 注入代理 | `dsound.dll` | `dinput.dll` | `dinput.dll` | **`dinput.dll`**（同 2/3） |
| 构建入口 | `ci_build.py` | `ci_build_am2.py` | `ci_build_am3.py` | `ci_build_am4.py` |
| 打补丁包 | `make_patch.py` | `make_patch_am2.py` | `make_patch_am3.py` | `make_patch_am4.py` |
| 产物校验 | `verify_release.py` | `verify_release_am2.py` | `verify_release_am3.py` | `verify_release_am4.py` |
| 产物目录 | `build_out` / `stage` | `build_out_am2` / `stage_am2` | `build_out_am3` / `stage_am3` | `build_out_am4` / `stage_am4` |
| 载荷目录 | `Army1_NEW_CHS/` | `Army2_NEW_CHS/` | `Army3_NEW_CHS/` + `Army3_Voice_CHS/` | `Army4_NEW_CHS/` + `Army4_Voice_CHS/` |
| 界面文本 | INI 内存补丁 | INI 内存补丁 | 游戏自带 `strings.txt` | **同 3 代** |
| cnc-ddraw | 不需要 | ✅ 包根 | ✅ 包根 | ✅ 包根 |
| ASI 导出名 | — | — | `ArmyMenTIS_*` | **`ArmyMenWW_*`** |
| 中文配音 | 官方母盘 | 官方母盘 | qwen3-tts 171 | **qwen3-tts 250** |
| 校验项数 | 4 | 7 | 76 | **82** |

> ★ 3 代与 4 代的**唯一结构性差异**在 dat：4 代的 `shared.dat` **也有**
> 中文覆盖层（3 代 `shared` 是 `None`）。其余都是权威值不同。

---

## 2. 三条权威值（4 代实测，**不可沿用 3 代**）

| 文件 | FILEID | 原版大小 | 对象数 |
|---|---|---|---|
| `title.dat` | `0x81920667` | 3,502,576 B | 197 |
| `shared.dat` | `0x81920668` | 2,729,541 B | 969 |

> **FILEID 与 3 代逐一相同**（3 代 203 / 1113 对象），所以 `Tools/am3_dat.py`
> 的解析逻辑与 `Tools/am3_dat_pack.py` 的无损回包**可以直接复用** ——
> 但大小与对象数的断言必须按上表重写。
>
> 写死两处（`ci_build_am4.py` 的 `DAT_JOBS.expect_size` 与
> `verify_release_am4.py` 的 `DAT_SPECS`）是刻意的：校验器的判据
> **不该从被校验对象里读出来**（原理见 [`10`](10-am3-build-and-release.md) §4.1）。

已用原盘 sha256 反查确认 `Army4_Object_CHS/*/manifest.json` 的
`source_sha256` 就是这两份官方 dat，故 manifest 可作为独立权威快照。

---

## 3. 构建：与 1/2/3 代同构的三段式

```powershell
cd G:\Projects\ArmyMenCHS

# ① 编译 ASI（本地用 MSVC 2017 x86；CI 用 msvc-wine）
python Tools\ci\compile_dll_wine.py --proj Army4_Extend_Dll

# ② 载荷 + dat 回包 + 字库 + cnc-ddraw + 配音 -> build_out_am4
python Tools\ci\ci_build_am4.py --out build_out_am4 --verify

# ③ 打补丁包 -> stage_am4
python Tools\ci\make_patch_am4.py --out stage_am4

# ④ 独立校验产物
python Tools\ci\verify_release_am4.py stage_am4
```

### 单向数据流

```
Army4_NEW_CHS/            （人工维护，权威载荷：01-title/bitmaps/data/rules/strings）
Army4_Voice_CHS/audio/    （人工维护，中文配音；250 条 qwen3-tts 已生成）
Army4_Object_CHS/         （title/shared 解包 + 中文覆盖层）
        │  ci_build_am4.py（含 dat 回包）
        ▼
build_out_am4/            （游戏原生布局 + dll + Hzk16 + audio + title.dat/shared.dat）
        │  make_patch_am4.py 分流到 scripts\ 与 update\
        ▼
stage_am4/                （玩家实际拿到的包）
```

**方向必须单向**：任何脚本都不得回写 `Army4_NEW_CHS/` 与 `Army4_Voice_CHS/`。

### 4 代新增的一条硬闸（3 代没有）

`ci_build_am4.py` 第 5 步断言
**配音文件名必须是 `Army4_Original/audio/vos/` 的子集**，并校验总体积下限。

理由：游戏按**原名**加载 `update\audio\vos\*.wav`，名字对不上等于没配，
表现是"游戏照常跑但该句仍是英文"，**不报错、不崩**。3 代只核了数量，
挡不住"文件名整体写错"这一类——文件名子集断言正是为此。

> ★ 数量不硬校验：4 代英文原声 298 个含 48 个无人声音效（环境/枪械/多人模式音）
> 不配中文，实际配音 250 个；且缺失配音会静默回退英文原声，不会报错，
> 数错个数反而会让 CI 误红。质量闸门改为"文件名子集 + 体积下限 + 抽样探针"。

---

## 4. 中文配音（已完成）

4 代英文原声 `Army4_Original/audio/vos/` 共 **298** 个 wav，其中 48 个为
**无人声音效**（环境/枪械/多人模式音），不配中文配音。

中文配音已生成 **250 条**（qwen3-tts），位于 `Army4_Voice_CHS/audio/vos/`，
总体积 ~23.8 MB，文件名均为英文原声真人配音条目的子集（一一对应，
游戏按原名加载）。48 个无人声音效未被摘除——它们仍留在
`Army4_Original/audio/vos/`，游戏对缺失的配音会静默回退英文原声。

**生成流程**见 [`11-am4-reuse-plan.md`](11-am4-reuse-plan.md) §2.2：

```
① 英文原声基线   audio/vos/*.wav -> Army4_Original/audio/vos/   （已做）
② ASR 转写 + 校正 (faster-whisper large-v3) -> vos_en_raw.json    （已做）
③ 人工中译        -> vos_translations.json                        （已做）
④ 造角色音色参考音 _gen_voice_refs.py -> Army4_Voice_CHS/base/     （已做）
⑤ 全量生成        _batch_dub2.py      -> Army4_Voice_CHS/audio/vos/（已做，250 条）
```

> ★ 音效甄别：48 个无人声音效（环境/枪械/多人模式音）已从中文配音集合摘除，
> 游戏对它们回退英文原声。因此配音条数为 250 而非 298，CI **不按数量硬校验**。

> ★ 别用客观指标当判据：MFCC / 说话人编码器 / yin 基频在
> **11025 Hz 游戏音频上均不可靠**（见 [`../Tools/README_pipelines.md`](../Tools/README_pipelines.md)）。

---

## 5. 校验器设计：82 项，按节

`verify_release_am4.py` 的检查分节（与 1/2/3 代同一套编号习惯）：

| 节 | 内容 |
|---|---|
| A | zip 完整性 |
| B/C/D | 结构（必须存在的文件与目录） |
| **B2** | **包根说明与许可**（`LICENSE` / `License.txt` / `必读说明.txt` / 2 个 AI 辅助 txt） |
| **C2** | **中文配音**（抽样探针 + 总体积下限；不数数量，缺失会静默回退英文原声） |
| E | `update/` 不得含可执行文件 |
| F | 代理 DLL 具名导出（`dinput.dll` 必须导出 `DirectInputCreateA`） |
| G | ASI 位数与导出（**`ArmyMenWW_*`**，且不得残留 `ArmyMenTIS_*`） |
| H | Hzk16 字库（存在 + 几何参数） |
| **I** | **`strings.txt` 硬约束**（`>=320` 行、CRLF、GBK、无 BOM） |
| **J** | **两条 dat 结构 + 尾部完整性**（逐对象偏移/长度） |
| K | 与 `build_out_am4/MANIFEST.json` 逐条目对照 |

### 5.1 比 3 代多出来的断言（都是本轮踩过的坑）

| 断言 | 防的是什么 |
|---|---|
| `必读说明.txt` 必须含「世界大战」 | 复制 3 代说明忘了改标题 |
| `必读说明.txt` 不得含「太空玩具」 | 同上（残留 3 代字样） |
| ASI 不得残留 `ArmyMenTIS_Install` | 复制 3 代 DLL 工程忘了改导出名 |
| 配音文件名须是英文原声子集 | 游戏按原名加载，名字错了静默失效 |
| C2 探针名取自 **4 代**英文原声 | 照抄 3 代的 `Tina_ImTina` / `HQ_Goodwork` 等 4 代**不存在**，会让断言永远红 |

### 5.2 对抗性验证（先证明能发现错误）

本地对产物注入 14 种错误，**全部被拦下**，恢复原样后回绿：

| 注入的错误 | 结果 |
|---|---|
| 删 `必读说明.txt` | ✅ 拦下（B2） |
| 删 `License.txt` | ✅ 拦下（B2） |
| `License.txt` 剥掉 cnc-ddraw 声明 | ✅ 拦下（B2） |
| 删 1 个配音 wav | ✅ 拦下（C2） |
| 删包根 `ddraw.dll` | ✅ 拦下（B） |
| 代理 `dinput.dll` 换掉导出名 | ✅ 拦下（F） |
| ASI 落错后缀（`.dll`） | ✅ 拦下（C） |
| ASI 换成 3 代产物 | ✅ 拦下（G） |
| `strings.txt` 截到 100 行 | ✅ 拦下（I） |
| `title.dat` 中部砍 24 字节 | ✅ 拦下（J，总长变化的错位） |
| `title.dat` 砍尾部 24 字节 | ✅ 拦下（J） |
| `必读说明.txt` 去掉 BOM | ✅ 拦下（B2） |
| `必读说明.txt` 混入 3 代标题 | ✅ 拦下（B2） |
| `update/` 混入可执行文件 | ✅ 拦下（E） |

复现：`python Tools/ci/_am4_adversarial_test.py`（依赖已构建的 `stage_am4`）。

---

## 6. 产物布局

```
stage_am4/                      ~409 文件 / 112.8 MB（含 87.8 MB 临时配音测试集）
├── scripts/
│   ├── Army4_Extend_Dll.asi    ← build_out 里叫 .dll，落包时改名
│   └── Hzk16                   202,966 B 中文字库
├── update/                     游戏原生目录布局
│   ├── 01-title/
│   ├── audio/vos/*.wav         中文配音（250 条 qwen3-tts，已生成）
│   ├── bitmaps/                65 个界面图
│   ├── data/                   13 个关卡脚本
│   ├── rules/                  19 个规则文本
│   ├── strings/strings.txt     323 行界面文本（GBK）
│   ├── title.dat               3,502,576 B（回包，含中文贴图）
│   └── shared.dat              2,729,541 B（回包）
├── dinput.dll                  UAL（asi/dsound.dll 改名）
├── ddraw.dll / ddraw.ini       cnc-ddraw
├── LICENSE / License.txt       项目主许可 + 三方声明合并
├── 必读说明.txt                 UTF-8 带 BOM + CRLF
├── 如果不会安装，请把该文件发给AI，让AI教你.txt
└── 将此文件交给AI，让AI协助完善本项目.txt
```

---

## 7. CI 能做什么、不能做什么

**关键约束**：仓库里**不含 `amww.exe`**（版权 + 体积）。

| 步骤 | 需要 exe | CI 可跑 |
|---|---|---|
| 编译 ASI（msvc-wine） | ❌ | ✅ |
| `ci_build_am4.py`（含 dat 回包） | ❌ | ✅ |
| `make_patch_am4.py` | ❌ | ✅ |
| `verify_release_am4.py` | ❌ | ✅ |
| `verify_doc_links.py` | ❌ | ✅ |
| `Tools/verify_army4_assets.py` | ❌ | **❌ 不在 CI** |
| 实机验证（渲染/配音/多人菜单） | ✅ | ❌ |

> ★ `verify_army4_assets.py` **不在 CI 里跑**：它要逐字节比对作者本机的
> GOG 安装目录（`I:\`），Linux runner 上没有该目录。与 3 代同一口径
> （`verify_army3_assets.py` 同样不在 CI 里）。本地跑结果：
> 602/602 文件一致、`strings.txt` 323 行、`audio/vos` 298 个。

Workflow：**单一** `.github/workflows/build-release.yml`
（1 代 → 2 代 → 3 代 → 4 代 → 5 代 build → 合并 publish）。
五代产物挂在同一个 Release 下，附件名分别为：

| 系列序号 | 作品 | 附件名 |
|---|---|---|
| 1 代 | 玩具兵大战 | `ArmyMen-CHS-Patch-<stamp>.zip` |
| 2 代 | 玩具兵大战 II | `ArmyMen2-CHS-Patch-<stamp>.zip` |
| 3 代 | 太空玩具 | `armymen_TIS.zip` |
| 4 代 | 空中战术 | `armymen_AT.zip` |
| 5 代 | 世界大战 | `armymen_WW.zip` |

> ★ 3/4/5 代改用**固定短名**（不再带 `_CHS_%DATETIME%` 一类时间戳），
> 唯一性由 Release 的 tag 保证。

---

## 8. 已知遗留

| 项 | 状态 |
|---|---|
| **中文配音（250 条）** | ✅ 已生成，见 §4 |
| `Tools/title/am4_title_build.py` 的 `obj_0003` | ⚠️ 译文表要 6 行，`lines_a4.json` 只有 3 行；覆盖层产物（123 张）已入库，CI 不重跑生成，暂不影响构建 |
| `verify_army4_assets.py` 硬编码本机路径 | ⚠️ 与 3 代同类脚本一致，仅本地可跑 |
| 视频字幕（`avi/`） | ❌ 未做 |
| `obj_0000_k00080000.png`（标题画 640×480） | ✅ 走独立美术流程（`title/png/` 里已是中文版，与 `Army4_Image_Data_CHS/` 同源），非烧字流程 |

---

## 9. 发布前检查清单

```
[ ] 三段式全绿：ci_build_am4 --verify → make_patch_am4 → verify_release_am4
[ ] 校验器报出 "共 82 项检查，失败 0"（非空转）
[ ] MANIFEST.json 非空（配音到位后应为 399 条载荷）
[ ] 逐对象偏移/长度与原版一致（title.dat 197 / shared.dat 969）
[ ] 配音 250 条 qwen3-tts / >10 MB，且文件名全部对应英文原声子集
[ ] License.txt 含三方声明标识
[ ] 必读说明.txt 带 BOM + CRLF，且含「世界大战」、不含「太空玩具」
[ ] 资产树自检（本地）：python Tools/verify_army4_assets.py（602/602）
[ ] 文档内链：python Tools/ci/verify_doc_links.py（120 个链接全部有效）
[ ] 对抗性验证：python Tools/ci/_am4_adversarial_test.py（14/14 拦下）
[ ] 实机验证：主菜单/对话框/贴图/配音/多人菜单解锁
```

---

## 相关文档

| 文档 | 内容 |
|---|---|
| [`11-am4-reuse-plan.md`](11-am4-reuse-plan.md) | 4 代复用方案（dat / TTS / bmp 三条管线） |
| [`12-am4-reverse-findings.md`](12-am4-reverse-findings.md) | 4 代 exe 逆向实测（签名 / patchLen / 全局表） |
| [`10-am3-build-and-release.md`](10-am3-build-and-release.md) | 3 代构建与发布（本文件的模板） |
| [`00-porting-map.md`](00-porting-map.md) | 移植地图（含原理与坑） |
