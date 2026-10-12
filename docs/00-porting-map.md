# Army Men 中文汉化 —— 移植地图（面向 2 / 3 / 4 代）

> 本文是**决策文档**：把 1 代踩过的坑、验证过的事实、可复用的工具，整理成
> 后续几代可以直接照搬的路线。技术细节见 `01-technical-archive.md`。

---

## 0. 先读这段：当前仓库的真实状态

**这是最重要的一节。** 仓库里已经有 `Army2/3/4/RTS_CHS` 和 `*_Original` 的空目录，
但它们**全是 0 文件的占位符**，不是已完成的资产。

| 目录 | 文件数 | 体积 | 状态 |
|---|---|---|---|
| `Army1_CHS` | 594 | 248.7 MB | ✅ 1998 中文母盘，已提取 |
| `Army1_Original` | 595 | 312.7 MB | ✅ Steam v1.2 英文基线 |
| `Army2_CHS` … `ArmyRTS_Original` | **0** | 0 | ⬜ 空占位符 |

同样地，`ArmyMenSourceCode/` 只有**1998 年 1 代**的源码：

> These files contain the source code to the first Army Men game released in
> 1998 by The 3DO Company. — `ArmyMenSourceCode/README.md`

**这意味着：**

| 能力 | 1 代 | 2/3/4 代 |
|---|---|---|
| 有源码可查 | ✅ 全套 | ❌ 需另行获取或纯逆向 |
| 有中文母盘 | ✅ 1998 上育版 | ❓ 需确认是否存在 |
| 有工具链 | ✅ 已建好 | 部分可复用 |
| exe 字符串地图 | ✅ 已测绘 | ❌ 需重新测绘 |

**所以不要假设可以照抄。** 每一代都需要先做第 1 节的可行性核查。

---

## 1. 新作开工前必做的四项核查

按顺序做，任何一项失败的应对方式不同。

### 核查 1：中文母盘是否存在

1998 年上海育碧只汉化了 1 代。2 代（Army Men II, 1999）、3 代
（Army Men: Toys in Space, 1999）、4 代（Army Men: World War, 2000）
**是否有官方中文版，必须先确认**。

- 有官方中文版 → 走「差异移植」路线（本项目已验证，成功率高）
- 没有官方中文版 → 只能**从零翻译**，工作量数量级不同，
  但 exe 内存补丁的**技术框架可以完全复用**

判据：找一份中文零售盘，检查是否含 `ArmyMen2.exe` 之类的中文资源。
最快的入手点是看有没有 `objects.dat` 里烧入中文的贴图，或视频里有没有中文。

### 核查 2：是否有源码泄漏

1 代源码 2021 年前后被 `_Z3N_` 发现并公开（`OnyeNacho/ArmyMen`）。
2/3/4 代是否也有，需检索确认。

**有源码的价值极高**，它能直接回答三个最难的问题：

1. 某个字符串是否被 `strcmp` / 当作文件路径使用（决定能否翻译）
2. `objects.dat` 的精确结构（包括 maskSize==0 的分支行为）
3. 崩溃点的寄存器状态含义

没有源码时，替代手段是 IDA + 本项目已有的 `Tools/exe_scan/` 系列脚本。

### 核查 3：确认 exe 是否为 32 位且无加壳

```powershell
# 看 PE machine 字段：0x14C = i386，0x8664 = x64
python -c "import struct;b=open('ArmyMen2.exe','rb').read();o=struct.unpack_from('<I',b,0x3C)[0];print(hex(struct.unpack_from('<H',b,o+4)[0]))"
```

1 代是 `0x14C`，因此 DLL 必须 `/MACHINE:X86`，且**不能用 x64 的 ASI Loader**。
若某代是 64 位或有 SecuROM/StarForce 之类保护，内存补丁方案要重新评估。

### 核查 4：确认 ASI Loader 能否工作

1 代用 `dsound.dll` 代理（Ultimate ASI Loader v6.4）。
**关键约束**：该 loader 只扫描 `scripts\*.asi`，
把 `.dll` 丢进 `scripts\` 会被静默忽略，没有任何报错。

2/3/4 代需要重新确认：

- 游戏是否导入了 `dsound.dll`（用 `Tools/exe_scan/list_imports.py` 查）
- 若不导入，需换成它实际导入的 DLL 名做代理，或改用其它注入方式
- 注意：**Steam 版可能已经带了别的 dsound 代理**，会互相覆盖

---

## 2. 核心技术路线（可直接复用到 2/3/4 代）

1 代验证成功的方案，本质上是三个独立决定：

### 决定 A：不改 exe，只做内存补丁

**为什么**：exe 一改，Steam 更新会让补丁失效，且难以回滚、无法通过校验。

**代价**：需要找 IAT 表项、手工构造 ASI Loader 环境。

**结论**：收益远大于代价，**建议 2/3/4 代沿用**。

### 决定 B：翻译数据外置为 INI，不写死在 DLL 里

DLL 只是"读表 → 写入内存"的引擎。改译文不需要重新编译。
这对 2/3/4 代尤其重要 —— 那些游戏文本量大，编译一次 DLL 成本高。

格式见 `01-technical-archive.md` 第 4 节。

### 决定 C：资产用「差异移植」而非整体替换

以 Steam 原版为基底，只覆盖**确实含中文**的资源块。

**为什么**：1 代原补丁图省事整包替换 `objects.dat`，
结果把 2018 版修好的 bug 退回了 1998 版的缺陷（详见第 3 节）。
差异移植能避免这类"用旧换新"的倒退。

---

## 3. 必须避免的三个倒退陷阱

这三个都是 1 代真实踩过的，2/3/4 代一定会再遇到同类问题。

### 陷阱 1：整包替换资材，把上游修复一起退回

1998 中文盘的 `Alpine/objects.dat` 里，建筑（cat 17）带有一份多余的
**碰撞掩膜**，导致第三关「羊肠河」的吉普车被油桶卡死。

第一版补丁直接用了这个文件 → bug 进入中文版。
本项目改成"Steam 基底 + 只覆盖 37 个汉化块"后确认：
**Steam 自己也只在 d1 形态删了掩膜，d0 形态的还在** —— 所以单纯
"不覆盖 cat 17" 并不够，必须**主动剥离掩膜**。

> **可移植的经验**：
> 拿到一份汉化资源时，不要问"它和原版哪里不同"，
> 要问"**它比新版少了哪些修复**"。旧汉化包 = 旧版本 bug 集合。

### 陷阱 2：改动了被当作标识符用的字符串

1 代有三处字符串**看起来是界面文字、实际是逻辑标识符**，改了必崩：

| 区域 | 用途 | 改了会怎样 | 源码位置 |
|---|---|---|---|
| `TrooperNames[]` | 拼装动画目录名 | 加载不存在的路径 → 单位精灵为空 → 崩溃 | `TextData.cpp:189` |
| `MsgVehicleNames[]` | 同上，载具 | 同上 | `USA.h:165` |
| `obj_category_dirs[]` | 文件路径片段 | 找不到对象目录 | `fileio.cpp:111` |
| 注册表配置键名 | `strcmp` 比对后读写注册表 | 配置读写失败 | `Commands.cpp:1078` |

> **可移植的经验**：翻译任何字符串之前，先在源码（或 IDA）里搜它有没有
> 被 `strcmp` / `sprintf` 到路径 / 当作文件名。**"只用于显示"** 才安全。

### 陷阱 3：假定构建脚本是幂等的

`build_object_chs.py` 有个隐蔽 bug：它先清空 `raw/` 缓存，
第二次运行时把"文件读不到"误判成"与 Steam 不同"，
于是把 37 个块错误地扩成 273 个。

> **可移植的经验**：构建脚本必须**连跑两次结果一致**才算写对。
> 用增量缓存做的比较逻辑尤其危险 —— 缓存缺失和内容不同是两件事，
> 不能共用一条判断分支。

---

## 4. 哪些工具可以直接复用

按「可直接用 / 需小改 / 完全不能用」三档。

| 工具 | 复用性 | 说明 |
|---|---|---|
| `Tools/ci/build_dll_local.py` | 需小改 | 改路径与源码目录即可 |
| `Tools/ci/compile_dll_wine.py` | 需小改 | 同上，Linux 编译用 |
| `Tools/ci/make_patch.py` | **可直接用** | 布局约定与游戏无关，改常量即可 |
| `Tools/ci/verify_release.py` | 需小改 | 校验项里的字符串块/地形名要改 |
| `Tools/ci/cmp_official.py` | 需小改 | 逐文件对账逻辑通用，改目录名即可 |
| `Tools/unpack_objects/objects_dat.py` | **需验证** | 格式大概率相同，但要重新核对魔数 |
| `Tools/unpack_objects/pack_diff.py` | 需小改 | 差异覆盖 + 掩膜剥离逻辑可复用 |
| `Tools/unpack_objects/verify_objects.py` | 需小改 | 块边界校验逻辑通用 |
| `Tools/exe_scan/*.py` | **可直接用** | IDA 辅助分析，与游戏无关 |
| `Army1_Extend_Dll/src/ini_reader.cpp` | **可直接用** | 通用 INI 解析 |
| `Army1_Extend_Dll/src/hooks.cpp` | 需大改 | IAT Hook 框架可复用，RVA 表要重测 |

### 关于 objects.dat 格式

1 代的格式（`fileio.cpp` 的 `OpenDataFile`）：

```
偏移 0     : int FILEID == 132415161   ← 魔数，2/3/4 代**必须重新确认**
偏移 4     : 256 × RGBQUAD = 1024 B    调色板
偏移 1028  : int nObjects
偏移 1032  : nObjects × {key:DWORD, offset:DWORD}
之后       : 各对象数据块
```

> **不要假设魔数相同。** 先用 `objects_dat.py --probe` 之类的逻辑
> 打印前 1032 字节并验证，再决定要不要复用代码。
> 若 3/4 代引擎换过（比如改 DirectX 版本），格式可能已经变了。

---

## 5. 建议的开工顺序

```
①  确认中文母盘是否存在 ──────┐
②  确认源码是否可得 ──────────┤ 四项核查
③  确认 exe 位数与保护 ───────┤
④  确认 ASI Loader 可用 ──────┘
        │
        ▼
⑤  测绘 exe 字符串表（Tools/exe_scan/）
    · 记录每块的 RVA、槽容量、是否被 strcmp 使用
    · 这一步决定了后面能不能翻译，最耗时也最关键
        │
        ▼
⑥  拆解资源包（objects.dat 等），验证格式假设
        │
        ▼
⑦  建 DLL 骨架：先只做 Hook，不做翻译，确认能加载
        │
        ▼
⑧  小批量试译（10~20 条），跑起来看效果和崩溃
        │
        ▼
⑨  全量翻译 + 差异移植
        │
        ▼
⑩  对账（cmp_official.py）+ 校验（verify_release.py）+ 打包
```

**第 ⑤ 步是最容易低估的。** 1 代的 exe 字符串表测绘花了大量时间，
且踩了几次"看起来是 UI 文字、实际是逻辑标识符"的坑。
2/3/4 代没有源码时，这一步会更慢 —— 建议尽早开始，且
**每确认一块就写进 INI 的注释里**（1 代的 `keyname_block.ini` 就是这么做的，
现在回头看那些注释就是最有价值的资料）。

---

## 6. 每个新代次开工时的清单

复制这段，逐项打勾：

```
[ ] 中文母盘路径：____________  存在？（是/否）
[ ] 源码可得？  来源：__________
[ ] exe 大小/哈希：________  位数：32/64  加壳：是/否
[ ] 游戏导入的 DLL 列表（选 ASI 代理用）：____________
[ ] scripts/*.asi 能否被加载（做一个 log-only 的空 DLL 测试）
[ ] objects.dat 魔数：________  与 1 代相同？（是/否）
[ ] exe 字符串表是否已测绘？（是/否）  块数：____
[ ] 已识别出的"不可翻译"区域：____________
[ ] 汉化包相比新版少了哪些修复：____________
[ ] 构建脚本连跑两次结果一致？（是/否）
```

---

## 7. 相关文档

| 文档 | 内容 |
|---|---|
| [`01-technical-archive.md`](01-technical-archive.md) | 技术档案：二进制格式、内存补丁原理、exe 字符串地图 |
| [`02-pitfalls.md`](02-pitfalls.md) | 踩坑清单：崩溃根因、不可译区域、工具缺陷 |
| [`03-build-and-release.md`](03-build-and-release.md) | 构建、CI、打包、发布流程 |
| [`04-asset-pipeline.md`](04-asset-pipeline.md) | 资产提取、差异移植、对账方法 |
| [`../Army1_Extend_Dll/docs/translation_format.md`](../Army1_Extend_Dll/docs/translation_format.md) | 翻译 INI 格式详述 |
| [`../Tools/README.md`](../Tools/README.md) | objects.dat 格式与官方打包器 |
