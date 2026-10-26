# Army Men: Toys in Space (3 代) 构建与发布流程

> 3 代的构建、校验、打包、CI。与 1 代 [`03-build-and-release.md`](03-build-and-release.md)、
> 2 代 [`07-am2-build-and-release.md`](07-am2-build-and-release.md) **同构**，
> 差异集中在 §1。
>
> 3 代的载体侦察见 [`08-am3-i18n-inventory.md`](08-am3-i18n-inventory.md)，
> 贴图烧字见 [`09-am3-title-bitmap-chs.md`](09-am3-title-bitmap-chs.md)。

---

## 0. 一句话结论

**3 代没有官方中文母盘，全部内容是从零翻译 + AI 配音做出来的**，
所以它的构建链比 1/2 代多了两件 1/2 代不需要的事：

1. **dat 无损回包**（`title.dat` / `shared.dat` 里塞进中文贴图）
2. **配音产物入库**（171 个 qwen3-tts 生成的 wav）

这两件事都有专门的**独立判据**，且都不允许"看起来对"就当对（见 §5）。

---

## 1. 与 1/2 代的差异

| 项 | 1 代 | 2 代 | 3 代 |
|---|---|---|---|
| 注入代理 | `dsound.dll` | `dinput.dll` | **`dinput.dll`**（同 2 代） |
| 构建入口 | `ci_build.py` | `ci_build_am2.py` | `ci_build_am3.py` |
| 打补丁包 | `make_patch.py` | `make_patch_am2.py` | `make_patch_am3.py` |
| 产物校验 | `verify_release.py` | `verify_release_am2.py` | `verify_release_am3.py` |
| 产物目录 | `build_out` / `stage` | `build_out_am2` / `stage_am2` | `build_out_am3` / `stage_am3` |
| 载荷目录 | `Army1_NEW_CHS/` | `Army2_NEW_CHS/` | `Army3_NEW_CHS/` + `Army3_Voice_CHS/` |
| 界面文本 | INI 内存补丁 | INI 内存补丁 | **游戏自带 `strings\strings.txt`** |
| 译文表 INI | ✅ | ✅ `ArmyMenCHS.ini` | ❌ **没有**（不需要） |
| cnc-ddraw | 不需要 | ✅ 包根 `ddraw.dll`+`.ini` | ✅ 同 2 代 |
| 兼容性 .reg | 不需要 | ✅ 2 个（ArmyMen2.exe 专属 shim） | ❌ 不需要 |
| 中文配音 | 官方母盘 | 官方母盘 | **qwen3-tts 生成（171 wav）** |
| 校验项数 | 4 | 7 | **76** |
| third-party 许可 | UAL | UAL + cnc-ddraw | UAL + cnc-ddraw + **qwen3-tts** |

> ★ 2 代与 3 代**共用** `cnc-ddraw/ddraw.ini`（同一份调优配置）。
> 见 §7 的风险说明。

---

## 2. 工具链

与 1/2 代完全一致：本地 MSVC v141 `14.16.27023` + Windows SDK，
CI 用 `ubuntu-latest` + `msvc-wine`（`vsdownload --architecture x86 x64`）。

3 代的 DLL 工程是 `Army3_Extend_Dll/`，源码列表由
`Tools/ci/compile_dll_wine.py` 里的 `sources` 显式维护。

> ★ **`sources` 必须与 `.vcxproj` 的 `<ClCompile>` 逐项一致。**
> 3 代曾漏掉 `src\mpunlock.cpp`（多人菜单解锁），
> 本机能编过（VS 按 vcxproj 编译），**CI 上却 `LNK2019`** ——
> 因为 CI 走的是这份手工清单。加文件时必须两处同改。

---

## 3. 构建：与 1/2 代同构的三段式

```powershell
# ① 载荷 + 运行期文件 -> build_out_am3（含 171 个配音 wav 入 MANIFEST）
python Tools/ci/ci_build_am3.py --out build_out_am3 --verify

# ② 打补丁包 -> stage_am3
python Tools/ci/make_patch_am3.py --out stage_am3

# ③ 独立校验产物
python Tools/ci/verify_release_am3.py stage_am3
```

任一步失败立即停止，**不做静默容错**。

| 环节 | 脚本 | 输入 → 输出 |
|---|---|---|
| 编译 | `compile_dll_wine.py --proj Army3_Extend_Dll` | `src/` → `Release/*.dll` |
| 组装 | `ci_build_am3.py` | `Army3_NEW_CHS/` + `Army3_Voice_CHS/` + dat 回包 → `build_out_am3/` |
| 打包 | `make_patch_am3.py` | `build_out_am3/` → `stage_am3/` |
| 校验 | `verify_release_am3.py` | 独立复核 `stage_am3/` |

### 单向数据流（★ 关键设计）

```
Army3_NEW_CHS/ (人工维护，权威载荷：data/ + rules/)
Army3_Voice_CHS/audio/ (人工维护，171 个中文配音)
Army3_Object_CHS/ (title/shared 解包 + 中文覆盖层)
        │  ci_build_am3.py（含 dat 回包）
        ▼
build_out_am3/ (游戏原生布局 + dll + Hzk16 + audio + title.dat/shared.dat)
        │  make_patch_am3.py 分流到 scripts\ 与 update\
        ▼
stage_am3/ (玩家实际拿到的包)
```

**方向必须单向**，与 2 代同。任何脚本都不得回写 `Army3_NEW_CHS/` 与
`Army3_Voice_CHS/`（那是人工成果，且配音重生成要几十分钟）。

### ★ 配音为什么在 `ci_build_am3.py` 而不是 `make_patch_am3.py` 里拷

`ci_build_am3.py` 第 5 步把 `Army3_Voice_CHS/audio`（171 文件 / 11.48 MB）
拷进 `build_out_am3/audio/`，从而**进入 `MANIFEST.json`**。

若只在打包阶段拷，配音就成了 `MANIFEST.json` 之外的"盲区"，校验器
第 K 节（逐条目 sha256 对照）会**静默跳过它们** —— 正是本项目
最忌讳的"假绿"。**凡是要校验的东西，必须先进入 `build_out`。**

相关常量（`ci_build_am3.py`）：

```python
AUDIO_DIR_NAME   = "audio"
AUDIO_SRC_DEFAULT= "Army3_Voice_CHS/audio"
AUDIO_EXPECT_FILES = 171
AUDIO_MIN_BYTES    = 10000000   # 明显低于此值说明拷漏了
```

---

## 4. dat 无损回包

3 代的 `title.dat`（UI 贴图）与 `shared.dat` 是**打包容器**，
中文贴图必须回包进去。工具是 `Tools/am3_dat.py`（拆）+
`Tools/am3_dat_pack.py`（回）。

### 4.1 权威值（写死在两处，刻意的）

| 文件 | FILEID | 原版大小 | 对象数 |
|---|---|---|---|
| `title.dat` | `0x81920667` | 4,298,896 B | 203 |
| `shared.dat` | `0x81920668` | 2,936,433 B | 1,113 |

> **为什么要写死两处**：`ci_build_am3.py` 的 `DAT_JOBS.expect_size` 与
> `verify_release_am3.py` 各写一份。校验器的判据**不该从被校验对象里读出来** ——
> 否则产物错了，判据也跟着错，校验就永远通过。

### 4.2 ★ 判据是"逐对象偏移与长度不变"，不是"总大小不变"

这是 3 代最重要的一条校验设计：

```
仅比总大小是不够的 —— 若在文件**中部**丢 24 字节、又在别处多 24 字节，
总大小可以完全不变，但其后**所有对象都会错位**，游戏读到的是乱码/崩溃。
```

因此校验器用**解包记录**（`Army3_Object_CHS/*/manifest.json`，
由 `am3_dat.py` 拆原版时写下，带 `source_sha256`）逐对象断言
「偏移与长度与原版逐一相同」。

> ★ `source_sha256` 是关键：它证明这份记录来自**原版 dat**，
> 而不是从产物自身反推出来的。判据必须来自独立来源。

`make_patch_am3.py` 的 `DAT_JOBS` 还要求回包结果**与原版等长**
（`expect_size`）—— 这是使用"偏移不变"不变量的前提条件。

### 4.3 已实测

- `title.dat`：126/126 张贴图处理完成、177 处文字、抹字零残留、
  回包后**逐对象回读零像素差异**
- `shared.dat`：1113 对象，其中 **31 个 SRLE 对象尚无法解码**（遗留，见 §8）

---

## 5. 校验器设计：76 项，按节

`verify_release_am3.py` 的检查分节（与 1/2 代同一套编号习惯）：

| 节 | 内容 |
|---|---|
| A | zip 完整性 |
| B/C/D | 结构（必须存在的文件与目录） |
| **B2** | **包根说明与许可**（`LICENSE` / `License.txt` / `必读说明.txt` / 2 个 AI 辅助 txt） |
| **C2** | **中文配音**（数量下限 + 抽样探针 + 总体积下限） |
| E | `update/` 不得含可执行文件（`.exe/.dll/.asi/.sys/.ocx`） |
| F | 代理 DLL 具名导出（`dinput.dll` 必须导出 `DirectInputCreateA`） |
| G | ASI 位数与导出 |
| H | Hzk16 字库（存在 + 几何参数） |
| **I** | **`strings.txt` 三条硬约束**（来自 exe 反编译） |
| **J** | **两条 dat 结构 + 尾部完整性**（逐对象偏移/长度） |
| K | 与 `build_out_am3/MANIFEST.json` 逐条目对照 |

### 5.1 ★ 为什么每项都要"数量下限"而不是"存在即可"

3 代的失效模式大多是**静默**的 —— 不报错、不崩溃，只是功能没了：

| 失效 | 表现 | 只能靠什么抓 |
|---|---|---|
| 配音丢了一半 | 游戏照常跑，但**部分台词变英文** | 数量下限 + 总体积下限 |
| 代理 DLL 改名 | 补丁装了但**中文完全不出现**，无任何报错 | F 节具名导出检查 |
| `strings.txt` 少于 320 行 | 游戏**弹框拒绝启动** | I 节行数断言 |
| dat 中部错位 | 贴图乱码/崩溃 | J 节逐对象偏移断言 |

> ★ 这也解释了为什么 B2/C2 节只查 `.txt` 正文里的**标识字符串**
> （`MIT License`、`github.com/FunkyFr3sh`、`Apache License`、
> `== ASILoader.txt` 等），**不查"文件多大"** —— 空壳声明没有意义。

### 5.2 校验器自己失效过 4 次（承自 1/2 代）

| 失效方式 | 修法 |
|---|---|
| 白名单过滤 → 新 hook 被静默忽略 | 按档位解析 + 断言覆盖度 |
| 硬编码条目数 → 新增项没查 | 从源码解析实际条目 |
| 累计到阈值就停 → 假红 | 反汇编完整窗口 |
| 解析正则不匹配 → 匹配 0 条 | 断言"检查数 > 0" |

**硬性要求**：报出实际检查条目数、断言覆盖度、空转即失败、判据要能区分正误。

### 5.3 反向验证（先证明能发现错误）

3 代产物做过 7 项对抗性验证，**全部被拦下**，恢复后回绿：

| 代次 | 注入的错误 | 结果 |
|---|---|---|
| 3 代 | 删 `必读说明.txt` | ✅ 拦下 |
| 3 代 | 删 `License.txt` | ✅ 拦下 |
| 3 代 | 删 1 个 wav | ✅ 拦下 |
| 3 代 | 去掉 BOM | ✅ 拦下 |
| 3 代 | 删 `ddraw.dll` | ✅ 拦下 |
| 2 代 | 删 `ddraw.dll` | ✅ 拦下 |
| 2 代 | 从 `License.txt` 剥掉 cnc-ddraw 声明 | ✅ 拦下 |

---

## 6. 产物布局

```
stage_am3/                      280 文件 / 36.74 MB（zip 14.79 MB）
├── scripts/
│   ├── Army3_Extend_Dll.asi    ← build_out 里叫 .dll，落包时改名
│   └── Hzk16                   202,966 B 中文字库（**只此一处**）
├── update/                     游戏原生目录布局
│   ├── 01-title/
│   ├── audio/vos/*.wav         171 个中文配音（qwen3-tts）
│   ├── bitmaps/                61 个界面图
│   ├── data/                   15 个关卡脚本（8 个关卡子目录）
│   ├── rules/                  19 个规则文本
│   ├── strings/strings.txt     320 行界面文本（GBK）
│   ├── title.dat               4,298,896 B（回包，含中文贴图）
│   └── shared.dat              2,936,433 B（回包）
├── dinput.dll                  UAL（asi/dsound.dll 改名）
├── ddraw.dll                   cnc-ddraw 7.0.0.1
├── ddraw.ini                   cnc-ddraw 配置（项目调优）
├── LICENSE                     项目主许可
├── License.txt                 许可合并（ASILoader+cnc-ddraw+qwen3-tts+Apache-2.0）
├── 必读说明.txt                 安装说明（UTF-8 **带 BOM** + CRLF）
├── 如果不会安装，请把该文件发给AI，让AI教你.txt
└── 将此文件交给AI，让AI协助完善本项目.txt
```

### ★ `必读说明.txt` 必须是 UTF-8 带 BOM + CRLF

目标用户是直接双击打开的普通玩家。Windows 记事本靠 **BOM** 判编码 ——
没有 BOM 的 UTF-8 会被当成 GBK 显示成乱码。校验器会断言 BOM 与 CRLF。

### ★ `strings\strings.txt` 必须是 GBK，不是 UTF-8

实测载荷：3425 B / 320 行 / 2224 个非 ASCII 字节 / **无 BOM**。
游戏按 GBK 读（与 2 代渲染器的汉字处理同源）。写成 UTF-8 会全部显示成乱码。

### UAL 的 `update\` 机制

游戏根目录下 `update\` 存在即生效，**无需 `global.ini`**。

---

## 7. CI 能做什么、不能做什么

**关键约束**：仓库里**不含 `ARMYMENTIS.exe`**（版权 + 体积，与 1/2 代一致）。
需要 exe 的步骤只能在作者本机跑。

| 步骤 | 需要 exe | CI 可跑 |
|---|---|---|
| 编译 ASI（msvc-wine） | ❌ | ✅ |
| `ci_build_am3.py`（含 dat 回包） | ❌ | ✅ |
| `make_patch_am3.py` | ❌ | ✅ |
| `verify_release_am3.py` | ❌ | ✅ |
| `verify_army3_assets.py` | ❌ | ✅ |
| `verify_doc_links.py` | ❌ | ✅ |
| 实机验证（渲染/配音/多人菜单） | ✅ | ❌ |

> **不静默跳过**：CI 上跑不了的项在日志里显式列出，避免读者
> 以为 CI 覆盖了全部校验 —— 那正是"校验器空转报绿"的同类错误（见 §5.2）。

Workflow：**单一** `.github/workflows/build-release.yml`
（1 代 build → 2 代 build → 3 代 build → 合并 publish）。
三代产物挂在同一个 Release 下。

### ★ 已知风险：`ddraw.ini` 由 2/3 代共用

`cnc-ddraw/ddraw.ini` 是**同一份文件**同时喂给 2 代与 3 代，但
**只在 3 代上做过实机验证**。若 2 代出现音频/视频不同步或速度异常，
首要嫌疑是 `maxgameticks=120` 与 `singlecpu=true`。

**万一要分开**：拆成 `cnc-ddraw/ddraw_am2.ini` + `ddraw_am3.ini`，
并在两个 `make_patch_*.py` 里各取所需。目前**不拆**（未观察到问题）。

---

## 8. 已知遗留

| 项 | 状态 |
|---|---|
| `shared.dat` 的 31 个 SRLE 对象 | ❌ 尚无法解码（`Army3_Object_CHS/README.md`） |
| `amtisged.dll`（启动配置器 UI） | ❌ 未汉化（见 `08` §5.3） |
| 视频字幕（`avi/`） | ❌ 未做（169.07 MB 未入库） |
| `obj_0000_k00080000.png`（标题画 640×480） | ❌ 带复杂背景，不适用烧字流程 |

---

## 9. 发布前检查清单

```
[ ] 三段式全绿：ci_build_am3 --verify → make_patch_am3 → verify_release_am3
[ ] 校验器报出 "共 76 项检查，失败 0"（非空转）
[ ] MANIFEST.json 非空（应为 270 条载荷）
[ ] 逐对象偏移/长度与原版一致（title.dat 203 / shared.dat 1113）
[ ] 配音 171 个 wav / >10 MB
[ ] License.txt 含三方声明标识
[ ] 必读说明.txt 带 BOM + CRLF
[ ] 资产树自检：python Tools/verify_army3_assets.py（503/503）
[ ] 文档内链：python Tools/ci/verify_doc_links.py（82 个链接全部有效）
[ ] 实机验证：主菜单/对话框/配音/多人菜单/窗口化切换
```

---

## 相关文档

| 文档 | 内容 |
|---|---|
| [`08-am3-i18n-inventory.md`](08-am3-i18n-inventory.md) | 3 代 i18n 载体侦察与入库清单 |
| [`09-am3-title-bitmap-chs.md`](09-am3-title-bitmap-chs.md) | 3 代 title 贴图烧字（Hzk16 直出） |
| [`11-am4-reuse-plan.md`](11-am4-reuse-plan.md) | 4 代复用方案（dat / TTS / bmp 三条管线） |
| [`07-am2-build-and-release.md`](07-am2-build-and-release.md) | 2 代构建与发布（本文件的模板） |
| [`03-build-and-release.md`](03-build-and-release.md) | 1 代构建与发布 |
| [`00-porting-map.md`](00-porting-map.md) | 移植地图（含原理与坑） |
