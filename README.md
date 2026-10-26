# 玩具兵大战 (Army Men) 简体中文补丁

> ⚠️ **使用前必读**
>
> 本补丁为个人非官方作品，**未获游戏官方授权**；安装会修改或注入游戏文件，
> 可能与该游戏的用户协议（EULA）冲突。请自行判断是否可用，风险自担，
> **安装前请备份存档与原始文件**。
>
> **禁止商业使用**；二次修改后分发，须公开源代码与改动记录，并保留原作者署名。
> 作者不对使用后果承担责任，也不拥有本游戏及其原始素材的版权。
> 完整条款见 [LICENSE](LICENSE)。


把 1998–2000 年的《玩具兵大战》正统系列（1/2/3/5 代）做成简体中文版，并修复原版修不掉的问题。4 代 Air Tactics（空中战术）从未出过官方中文、不在本项目范围内。

**不修改任何 exe/dll。** 所有汉化由运行时内存补丁 + `update\` 覆盖层完成，
卸载即复原，游戏文件一个字节都不动。

---

## 现状

| 代次 | 游戏 | 状态 | 补丁体积 | 载荷 |
|---|---|---|---|---|
| **1 代** | Army Men (1998) 玩具兵大战 | ✅ 已发布 | 164.65 MB | 233 文件 / 215.5 MB |
| **2 代** | Army Men II (1999) 玩具兵大战2 | ✅ 已发布 | 151.38 MB | 350 文件 / 184.3 MB |
| **3 代** | Toys in Space (1999) 太空玩具（星际玩偶） | ✅ 已发布 | 14.79 MB | 280 文件 / 36.7 MB |
| **4 代** | Army Men: Air Tactics (2000) 空中战术（空中战略） | ⬜ 未汉化 | — | — |
| **5 代** | Army Men: World War (2000) 世界大战 | 🔧 CI 已就绪 | — | — |

> 体积取自 Release `汉化补丁-2026-10-16-00-26-32` 的实际产物。
> 4 代 Air Tactics **从未出过官方中文，也不在本项目汉化范围内**；
> 本地曾用于探索它的工作区 `amman7/` 已移出本仓库。
> 5 代 World War 与 2/3 代**同引擎**，可复用资产见
> [`docs/11-am4-reuse-plan.md`](docs/11-am4-reuse-plan.md)。
> 5 代的 CI 三段式已接好（`ci_build_am4` / `make_patch_am4` /
> `verify_release_am4`，校验器 82 项），**唯一缺口是中文配音**：
> `Army4_Voice_CHS/audio` 尚为空，构建会在该步按预期失败。
>
> ⚠️ **文件名偏移（读前注意）**：本仓库里 World War 的代码 / 文档 / 补丁沿用
> **"am4"** 命名（如 `Army4_Extend_Dll.asi`、`Army4_Voice_CHS`、
> `docs/11-am4-*`、`docs/13-am4-*`），但按系列正统代次它其实是 **5 代**；
> 而本地探索 Air Tactics（4 代）时用的补丁名为 `Army5_Extend_Dll.asi`。
> 即 **文件名里的数字 ≠ 正统代次**，阅读时请以"游戏名"为准做对照。

五代的实现路径差异很大，**不是同一套代码改五次**：

| | 1 代 | 2 代 | 3 代 | 5 代（World War，仓库内称 am4） |
|---|---|---|---|---|
| 官方中文母盘 | ✅ 1998 上育版 | ✅ 1999 上育版 | ❌ 从未有 | ❌ 从未有 |
| 可参考源码 | ✅ 全套 | ❌ | ❌ | ❌ |
| UI 文本 | exe `.rdata` 内存补丁 | exe `.rdata` 内存补丁 | 外置 `strings\strings.txt` | 外置 `strings\strings.txt` |
| 中文来源 | 差异移植母盘 | 差异移植母盘 | **从零翻译 + AI 配音** | **从零翻译**（配音待做） |
| 注入代理 | `dsound.dll` | `dinput.dll` | `dinput.dll` | `dinput.dll` |
| 渲染改造 | 换 GDI 字体 | hook 4 个文字函数 | hook 5 个文字函数 | hook 5 个文字函数 |

> 4 代 Air Tactics（空中战术）未在本项目汉化，上表不含。

---

## 快速开始

### 玩家：安装

下载 Release 里对应代次的 zip，**解压到游戏根目录**（exe 所在处），覆盖同名文件。

| 代次 | 文件名 |
|---|---|
| 1 代 | `ArmyMen-CHS-Patch-*.zip` |
| 2 代 | `ArmyMen2-CHS-Patch-*.zip` |
| 3 代 | `ArmyMen3-CHS-Patch-*.zip` |
| 5 代 | `ArmyMen4-CHS-Patch-*.zip`（仓库内沿用 am4 命名，实为 5 代） |

细节见包内 `必读说明.txt`。四代共同的注意事项：

- **不要**用兼容模式启动（2/3/4 代补丁已集成 cnc-ddraw，自带窗口化与渲染修正）
- **要**以管理员身份运行（写 `update\` 与注册表需要）
- 设置请在**主菜单**里改，不要进游戏内改

### 开发者：构建

四代都是同构的三段式（编译 → 组装 → 打包 → 独立校验）：

```powershell
cd G:\Projects\ArmyMenCHS

# 1 代
python Tools\ci\build_dll_local.py                          # 编译 ASI（MSVC 2017 x86）
python Tools\ci\ci_build.py        --out build_out    --verify
python Tools\ci\make_patch.py      --out stage
python Tools\ci\verify_release.py  stage

# 2 代
python Tools\ci\build_dll_local_am2.py
python Tools\ci\ci_build_am2.py    --out build_out_am2 --verify
python Tools\ci\make_patch_am2.py  --out stage_am2
python Tools\ci\verify_release_am2.py stage_am2

# 3 代（--audio 会把 Army3_Voice_CHS/audio 的 171 个配音拷进 update\）
python Tools\ci\ci_build_am3.py    --out build_out_am3 --verify
python Tools\ci\make_patch_am3.py  --out stage_am3
python Tools\ci\verify_release_am3.py stage_am3

# 5 代 / World War（仓库内称 am4；--audio 会把 Army4_Voice_CHS/audio 的配音拷进 update\；
#        ★ 配音尚未生成，此步目前预期失败，见 docs/11 §2.2）
python Tools\ci\compile_dll_wine.py --proj Army4_Extend_Dll
python Tools\ci\ci_build_am4.py    --out build_out_am4 --verify
python Tools\ci\make_patch_am4.py  --out stage_am4
python Tools\ci\verify_release_am4.py stage_am4
```

**任一步失败立即停止，不做静默容错。** 产物在各自的 `stage*/`。

CI 在 `ubuntu-latest` 上用 `msvc-wine` 编译 MSVC v141 x86，每次 push
构建已发布 / 就绪的代次产物（1/2/3/5 代；4 代 Air Tactics 不在范围内）并合并发布到同一个 Release。

---

## 文档

### 📖 想给 5 代（World War，仓库内称 am4）做汉化 —— 先读这三份

> 注意：下面文件名里的 "am4" 沿用仓库旧命名，对应的是**正统 5 代 World War**，不是
> 4 代 Air Tactics（Air Tactics 不在本项目范围内）。

| 文档 | 内容 |
|---|---|
| **[`docs/11-am4-reuse-plan.md`](docs/11-am4-reuse-plan.md)** | **5 代（am4）复用方案**：dat 拆包回包、qwen3-tts 配音、bmp/png AI 汉化三条管线怎么接着用 |
| **[`docs/13-am4-build-and-release.md`](docs/13-am4-build-and-release.md)** | **5 代（am4）构建与发布**：三段式命令、dat 权威值、82 项校验、14 项对抗验证、配音缺口 |
| **[`docs/00-porting-map.md`](docs/00-porting-map.md)** | **移植地图**：当前状态、开工前四项核查、可复用工具清单、开工顺序 |

### 技术资料（1 代 / 通用）

| 文档 | 内容 |
|---|---|
| [`docs/01-technical-archive.md`](docs/01-technical-archive.md) | objects.dat 二进制格式、内存补丁原理、exe 字符串地图、IAT Hook 写法 |
| [`docs/02-pitfalls.md`](docs/02-pitfalls.md) | **踩坑清单**：1 代 13 个真实坑（崩溃根因、不可译区域、静默失败） |
| [`docs/03-build-and-release.md`](docs/03-build-and-release.md) | 1 代工具链、构建流程、CI、发布包布局、校验清单 |
| [`docs/04-asset-pipeline.md`](docs/04-asset-pipeline.md) | 资产对账、差异移植、掩膜剥离、视频/音频判定 |

### 2 代（Army Men II）

| 文档 | 内容 |
|---|---|
| [`docs/05-am2-technical-archive.md`](docs/05-am2-technical-archive.md) | **2 代技术档案**：4 个文字函数实测地址/参数、全局量表、Hzk16 偏移公式、逐字节渐显陷阱 |
| [`docs/05-am2-porting-guide.md`](docs/05-am2-porting-guide.md) | **2→3/4 移植指南**：逐项对照表 + 开工清单 |
| [`docs/06-am2-pitfalls.md`](docs/06-am2-pitfalls.md) | **2 代踩坑清单**：15 个坑，按代价排序 |
| [`docs/07-am2-build-and-release.md`](docs/07-am2-build-and-release.md) | 2 代构建、部署幂等性、CI 覆盖范围说明 |

### 3 代（Toys in Space）

| 文档 | 内容 |
|---|---|
| [`docs/08-am3-i18n-inventory.md`](docs/08-am3-i18n-inventory.md) | **i18n 载体侦察**：`strings.txt` 320 行硬闸、510 B/行上限、exe 地址 |
| [`docs/09-am3-title-bitmap-chs.md`](docs/09-am3-title-bitmap-chs.md) | **title 贴图烧字**：Hzk16 直出、13 位对齐陷阱、墨迹数回归判据 |
| [`docs/10-am3-build-and-release.md`](docs/10-am3-build-and-release.md) | **3 代构建与发布**：dat 无损回包判据、171 配音配额、三方许可 |

### 管线工具（4 代可直接复用）

| 文档 | 内容 |
|---|---|
| [`Tools/README_pipelines.md`](Tools/README_pipelines.md) | `Tools/tts/`（qwen3-tts 配音）与 `Tools/title/`（贴图烧字）使用说明 |
| [`Tools/bmp_png_tool.py`](Tools/bmp_png_tool.py) | 8-bit 调色板 BMP ↔ PNG 可逆转换（保留原调色板） |

### 子系统文档

| 文档 | 内容 |
|---|---|
| [`Army1_Extend_Dll/docs/translation_format.md`](Army1_Extend_Dll/docs/translation_format.md) | 翻译 INI 格式（`packed4` / `explicit` 两种布局） |
| [`Tools/README.md`](Tools/README.md) | objects.dat 格式与 1998 官方打包器 `compobj` |
| [`Army1_CHS/MANIFEST.md`](Army1_CHS/MANIFEST.md) | 1 代中文母盘资产清单（哪些文件真的被汉化过） |

---

## 仓库结构

```
Army1_Extend_Dll/        1 代汉化 DLL 源码（C++，VS2017）
Army2_Extend_Dll/        2 代汉化 DLL 源码（hook 引擎文字渲染）
Army3_Extend_Dll/        3 代汉化 DLL 源码（含多人菜单解锁）
Army1_CHS/               1998 中文零售盘（594 文件 / 248.7 MB）
Army1_Original/          Steam v1.2 英文基线（595 文件 / 312.7 MB）
Army1_NEW_CHS/           1 代载荷（只含汉化差异）
Army1_Object_CHS/        提取出的差异块（37 块/地形）
Army2_CHS/               1999 中文零售盘（707 文件 / 501.2 MB，含 Hzk16 字库）
Army2_Original/          Steam 英文基线（717 文件 / 569.6 MB）
Army2_NEW_CHS/           2 代载荷（336 文件）
Army3_Original/          3 代英文基线（505 文件 / 29.5 MB，含 audio/vos 台词）
Army3_NEW_CHS/           3 代载荷：data/ 关卡脚本 + rules/ 规则文本
Army3_Voice_CHS/         3 代中文配音（171 wav）+ 音色基线 + ASR/译文源数据
Army3_Object_CHS/        title.dat / shared.dat 解包贴图与回包产物
Army3_Image_Data_CHS/    3 代位图资产
ArmyMenSourceCode/       1998 官方源码（git submodule）
cnc-ddraw/               ddraw.dll + 调优过的 ddraw.ini（MIT，1/2/3/5 代共用）
compat/                  2 代 Windows 兼容性 shim 的导入/还原 .reg
asi/dsound.dll           Ultimate ASI Loader v6.4（MIT）
LICENSES/                许可全文（ASILoader / cnc-ddraw / qwen3-tts / Apache-2.0）
Documents/               包内必读说明的源文件（各代一份）
Tools/
  ├─ ci/                 构建、打包、校验、对账（五代同构）
  ├─ unpack_objects/     objects.dat 拆包/打包/可视化
  ├─ am3_dat.py          3 代 dat 拆包（含 manifest 权威快照；5 代魔数相同可复用）
  ├─ am3_dat_pack.py     3 代 dat 无损回包（5 代同样走这个）
  ├─ tts/                qwen3-tts 配音生成管线（5 代待复用）
  ├─ title/              dat 打包贴图烧字汉化（5 代已复用，另有 am4_* 专用脚本）
  ├─ bmp_png_tool.py     8-bit 调色板 BMP ↔ PNG 可逆转换
  └─ exe_scan/           IDA 辅助的 exe 字符串表测绘
docs/                    文档（见上）
```

> 4 代 Air Tactics（空中战术）与 RTS（即时战略外传）均不在本仓库范围内：
> 前者从未出过官方中文、本地探索工作区已移出；后者是独立项目（见下）。

---

## 相关项目

- **Army Men: RTS 简体中文补丁**（独立项目，**非 The 3DO Company 出品**）：
  <https://github.com/HaoJun0823/ArmyMenRTSCHS>
  RTS（即时战略外传）不是《玩具兵大战》正统续作，也从未纳入本仓库的汉化范围，请到上述独立仓库查看。

---

## 本项目不做什么

- **不修改游戏 exe/dll。** 所有补丁在运行时内存中完成，或走 `update\` 覆盖层。
- **不分发游戏素材。** 请配合你自己合法获取的游戏使用。
- **不改动 `Army*_NEW_CHS/`（人工维护的权威载荷）。** 任何脚本不得回写它。

---

## 许可

本项目为个人非官方作品，采用 **HJNCSA-1.0（非商业源码可得许可）**：

- **禁止商业使用**（含任何以营利为目的的分发、售卖、打包或引流变现）
- **二次修改后再分发**，须公开源代码与改动记录，并保留原作者署名
- **作者不对使用后果承担责任**，亦**不拥有本游戏及其原始素材的版权**

完整条款见 [`LICENSE`](LICENSE) 与 [`LICENSES/`](LICENSES/)。

随包分发的第三方组件：

| 组件 | 许可 | 分发形式 |
|---|---|---|
| Ultimate ASI Loader (© 2023 ThirteenAG) | MIT | `dsound.dll`（1 代）/ `dinput.dll`（2/3 代） |
| [cnc-ddraw](https://github.com/FunkyFr3sh/cnc-ddraw) 7.0.0.1 | MIT | `ddraw.dll` + `ddraw.ini`（2/3 代） |
| Qwen3-TTS 生成的配音 | Apache-2.0 | 3 代 `update\audio\vos\*.wav` |

> 3 代中文配音由 qwen3-tts **独立生成，非克隆**任何真人声音。
> 因原版无语音字幕，为使中文玩家能听懂而制作，音质不完美，
> 同一角色不同台词的音色会有波动；不喜欢可删除 `update\audio`。

《玩具兵大战》系列 © 1998–2000 The 3DO Company. All rights reserved.
本项目为非官方粉丝汉化，与游戏版权方无任何关联。
