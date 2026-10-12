# 玩具兵大战 (Army Men) 简体中文补丁

复现 1998 年上海育碧中文零售版的本地化，并修复原版无法解决的两个问题。

**不修改 `Armymen.exe`** —— exe 文件一个字节都不动，所有汉化由
运行时内存补丁完成，卸载后不留痕迹。

---

## 特性

| | |
|---|---|
| 界面文本汉化 | 153 条（菜单/按钮/设置/单位名/武器名/按键名），外置为 INI |
| 中文字体 | 运行时把字体创建切换到宋体 + `GB2312_CHARSET` |
| 中文贴图 | 战略图迷你地图边框等，**差异移植**（只覆盖含中文的块） |
| 视频/音频 | 中文开场与失败动画、中文配音 |
| **修复** | 高山第三关「羊肠河」绿营地吉普车被油桶卡住 |
| **修复** | 高山四关战略图 UI 未汉化 |

---

## 快速开始

### 玩家：安装

下载 Release 里的 zip，**解压到游戏根目录**（`Armymen.exe` 所在处），
覆盖同名文件。详见包内 `安装说明.txt`。

### 开发者：构建

```powershell
cd G:\Projects\ArmyMenCHS

python Tools\ci\build_dll_local.py                    # 编译 DLL（MSVC 2017 x86）
python Tools\ci\ci_build.py --out build_out --verify  # 组装 + objects.dat 差异打包
python Tools\ci\make_patch.py --out stage             # 打成可发布布局
python Tools\ci\verify_release.py stage               # 独立校验
```

产物在 `stage/`（含 zip）。

---

## 文档

### 📖 想给 2 / 3 / 4 代做汉化 —— 先读这个

| 文档 | 内容 |
|---|---|
| **[`docs/00-porting-map.md`](docs/00-porting-map.md)** | **移植地图**：当前状态、开工前四项核查、可复用工具清单、开工顺序 |

### 技术资料

| 文档 | 内容 |
|---|---|
| [`docs/01-technical-archive.md`](docs/01-technical-archive.md) | objects.dat 二进制格式、内存补丁原理、exe 字符串地图、IAT Hook 写法 |
| [`docs/02-pitfalls.md`](docs/02-pitfalls.md) | **踩坑清单**：13 个真实坑（崩溃根因、不可译区域、静默失败） |
| [`docs/03-build-and-release.md`](docs/03-build-and-release.md) | 工具链、构建流程、CI、发布包布局、校验清单 |
| [`docs/04-asset-pipeline.md`](docs/04-asset-pipeline.md) | 资产对账、差异移植、掩膜剥离、视频/音频判定 |

### 子系统文档

| 文档 | 内容 |
|---|---|
| [`Army1_Extend_Dll/docs/translation_format.md`](Army1_Extend_Dll/docs/translation_format.md) | 翻译 INI 格式（`packed4` / `explicit` 两种布局） |
| [`Tools/README.md`](Tools/README.md) | objects.dat 格式与 1998 官方打包器 `compobj` |
| [`Army1_CHS/MANIFEST.md`](Army1_CHS/MANIFEST.md) | 1 代中文母盘资产清单（哪些文件真的被汉化过） |

---

## 仓库结构

```
Army1_Extend_Dll/        汉化 DLL 源码（C++，VS2017）
  ├─ src/hooks.cpp       IAT Hook + 字符串补丁 + 字体 Hook
  ├─ src/ini_reader.cpp  通用 INI 解析
  └─ strings/*.ini       翻译数据（6 块 / 153 条）
Army1_CHS/               1998 中文零售盘（594 文件 / 248.7 MB）
Army1_Original/          Steam v1.2 英文基线（595 文件 / 312.7 MB）
Army1_Object_CHS/        提取出的差异块（37 块/地形）
ArmyMenSourceCode/       1998 官方源码（git submodule）
Tools/
  ├─ ci/                 构建、打包、校验、对账
  ├─ unpack_objects/     objects.dat 拆包/打包/可视化
  └─ exe_scan/           IDA 辅助的 exe 字符串表测绘
docs/                    文档（见上）
asi/dsound.dll           Ultimate ASI Loader v6.4
```

> **注意**：`Army2_CHS` / `Army3_CHS` / `Army4_CHS` 等目录目前是
> **空的占位符**，2/3/4 代尚未开始。详见
> [`docs/00-porting-map.md`](docs/00-porting-map.md) 第 0 节。

---

## 本项目不做什么

- **不修改 `Armymen.exe`。** 所有补丁在运行时内存中完成。
- **不分发游戏素材。** 请配合你自己合法获取的游戏使用。

---

## 许可

GPL-3.0-or-later。见 [`LICENSE`](LICENSE) 与 [`LICENSES/`](LICENSES/)。

第三方组件：Ultimate ASI Loader (MIT, © 2023 ThirteenAG)，
随包分发为 `dsound.dll`。

《玩具兵大战》(Army Men) © 1998 The 3DO Company. All rights reserved.
本项目为非官方粉丝汉化，与游戏版权方无任何关联。
