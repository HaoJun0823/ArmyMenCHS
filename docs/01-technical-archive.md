# 技术档案 —— Army Men (1998) 汉化实现细节

> 记录 1 代验证过的二进制格式、内存补丁原理、exe 字符串地图。
> 面向后续代次移植时参考。**未经本代验证的推断已明确标注。**

---

## 1. 整体架构

```
Armymen.exe (993280 B, 32-bit PE, sha256 0c3ad26468be7d1b)
     │
     │  ① ASI Loader (dsound.dll) 在进程启动时注入并加载 scripts/*.asi
     ▼
scripts/Army1_Extend_Dll.asi  (构建时叫 .dll，落包时改名)
     │
     ├─ ② 读 scripts/ArmyMenCHS.ini          主配置（字体、开关、串块列表）
     ├─ ③ 读 scripts/strings/*.ini            翻译数据（6 块，153 条）
     ├─ ④ PatchIAT 挂 gdi32!CreateFontA / CreateFontIndirectA   → 中文字体
     └─ ⑤ 按 RVA 把 GBK 译文写入游戏内存 .data 段
```

**关键点：exe 文件本身从不被写入。** 所有修改都在进程内存中，
退出即消失。这是"不重编 exe"约束的实现方式。

### 为什么能这么做

游戏对界面文字的处理是"运行时从 `.data` 段的静态字符串数组读取"。
这些字符串在内存中有固定 RVA，只要我们在游戏读取之前改写它们，
就达到了汉化效果，且无需触碰文件。

---

## 2. ASI Loader 的加载规则

使用 Ultimate ASI Loader（ThirteenAG，MIT），以 `dsound.dll` 名义代理。

### 硬性约束

| 约束 | 后果 |
|---|---|
| 只扫描 `scripts\*.asi` | 放 `scripts\*.dll` 会被**静默忽略**，无任何报错 |
| 读 `update\global.ini` | "UPDATE FOLDER" 功能把 `update/` 合并进游戏视图 |
| 需要 exe 导入同名 DLL | 不导入则代理不生效（1 代导入了 `dsound.dll`） |

第一条是实际踩过的坑：补丁第一版把 `Army1_Extend_Dll.dll` 放进 `scripts\`，
游戏完全没反应。改名 `.asi` 后立即生效。

### `update/` 的工作方式

ASI Loader 把 `update/` 目录**覆盖到游戏文件视图之上**，而不是物理复制。
所以资产放在 `update/Alpine/objects.dat`，游戏读取 `Alpine/objects.dat` 时
会拿到我们的版本。这样卸载只需删目录。

> **移植注意**：2/3/4 代要重新确认游戏导入了哪些 DLL。
> 用 `Tools/exe_scan/list_imports.py` 查。若 Steam 版已自带某个
> dsound 代理，会冲突，需换一个被导入的 DLL 名。

---

## 3. objects.dat 二进制格式

依据 `src/fileio.cpp` 的 `OpenDataFile()`，已用 3 个地形的实际文件验证。

### 3.1 文件结构

```
偏移 0      int  FILEID == 132415161 (0x7E3D2B9)   ← 魔数
偏移 4      256 × RGBQUAD = 1024 B                  调色板
偏移 1028   int  nObjects
偏移 1032   nObjects × { key:DWORD, offset:DWORD }  8 字节/项
之后        各对象数据块（offset 为绝对文件偏移）
```

### 3.2 key 编码

```c
key = damagelevel + (number << 5) + (category << 15)
```

反向提取：

```python
dmg      =  key        & 0x1F        # 5 bit
number   = (key >> 5)  & 0x3FF       # 10 bit
category = (key >> 15) & 0x7F        # 7 bit
```

### 3.3 ★ 目录表必须按 key 升序

**这是最容易被忽略的硬约束。** 游戏用二分查找定位块
（`GetObjectTableIndex()`，`fileio.cpp:1224`）。

若目录表未排序，游戏会找不到块 —— 但**不报错**，只是渲染缺失或行为异常。
重新打包时必须排序。

> 实测：本项目的 `pack_diff.py` 产出与官方中文盘的文件 MD5 **不同**，
> 但逐块内容完全相同。差异**仅在于数据区块的物理排列顺序**。
> 已验证两者都能被游戏正确读取（`verify_objects.py` 报
> `块边界精确匹配 N/N，异常块 0`）—— 因为游戏只依赖目录表，不依赖物理顺序。

### 3.4 数据块布局

```
int   key
int   w
int   h
int   sprite_flags
SPOINT hotspot          (8 B)
SPOINT linkspot         (8 B)
int   graphicSize
byte  graphic[graphicSize]
int   shadowSize
byte  shadow[shadowSize]
int   maskSize
byte  mask[maskSize]
RECT  maskRect          (16 B)
```

### 3.5 ★ maskSize == 0 的特殊含义

```c
// fileio.cpp:1424-1434
fread(&ibuf, sizeof(int), 1, f);     // maskSize
if (ibuf > 0) { malloc(...); fread(pMask, ...); }
```

`maskSize == 0` **不是"空掩膜"，而是"没有掩膜指针"**（`pMask == NULL`）。

这个区别导致游戏走**不同的代码路径**：

```c
// Map.cpp:3311 / 3420 / 3581 / 3651
if (pobj->cell.pSprite->pMask) { ... 精确像素碰撞 ... }
else { ... 退化为矩形/宽松碰撞 ... }
```

**这正是「羊肠河」bug 的修复原理**：1998 中文盘里木屋建筑多一份掩膜，
让本该可通行的地块变成不可通行；把 `maskSize` 置 0 后，
游戏改用宽松碰撞，吉普车就能开过去了。

### 3.6 sprite_flags 位定义

`Dd.h:302-321`：

| 值 | 名称 | 含义 |
|---|---|---|
| 0x01 | `BM_OPAQUE` | 不透明 |
| 0x02 | `BM_RLE` | RLE 压缩 |
| 0x04 | `BM_DRLE` | |
| 0x08 | `BM_WRLE` | |
| 0x10 | `BM_TRLE` | |
| 0x20 | `BM_SRLE` | |
| 0x40 | `BM_SYSTEMMEMORY` | |
| 0x80 | `BM_NOTRANSLATE` | |

> 不要"规范化"这些标志。Steam 自己的 Alpine 里就有 574 个块带 `0x48`，
> 属于正常数据。

### 3.7 对象分类（`obj_category_dirs[]`，`scripts.cpp:5006`）

| cat | 名称 | cat | 名称 |
|---|---|---|---|
| 17 | Building | 45 | AAGun |
| 18 | PillBox | 46 | Base |
| 44 | GunTurret | 47 | Auxbase |
| 9 | Explosives | 25 | Sitems |

1 代的汉化块集中在 **18 / 44 / 45 / 46 / 47**，每地形 37 块。

---

## 4. exe 字符串补丁机制

### 4.1 两种布局

DLL 支持两种串块布局，由 `Layout=` 决定。

**`packed4`（紧凑连续）** —— 适用于规整的字符串数组：

```
[串0][NUL][pad→4][串1][NUL][pad→4][串2]...
```

容量 = `原串长 + 1(NUL) + padding`。DLL 从 `BaseRVA` 开始连续扫描，
按 `index` 定位第 N 个槽。

**`explicit`（显式 RVA）** —— 适用于项之间夹杂指针/数值的**不规整结构**：

```ini
[Explicit]
0x000D0714=前进   ; Forward
0x000D072C=左转   ; Left
```

`keyname_block.ini` 必须用这种 —— 它的项间隔 0x18 字节且中间有其它数据，
连续扫描会读到垃圾。

### 4.2 容量约束

中文 GBK 每字 2 字节，而英文槽位是按 ASCII 设计的，所以**经常放不下**。

| 例 | 英文 | 槽容量 | 可用 | 上限 |
|---|---|---|---|---|
| `Mine Sweeper` | 12 + NUL = 13 → 对齐 16 | 16 | 15 B | **7 个汉字** |

**DLL 的行为：超限时跳过并写日志，不截断、不越界。** 这是刻意设计 ——
宁可少翻一条，也不能破坏相邻数据。

1 代实际有 3 条因超限被跳过，处理方式是缩短译文
（如 `下一支部队` 11 B 超过 10 B 上限 → 改为 `下一部队`）。

### 4.3 译文写入流程

```
INI (UTF-8)  →  Utf8ToGbk()  →  VirtualProtect(PAGE_EXECUTE_READWRITE)
                                  →  memcpy 到 imagebase + RVA
                                  →  恢复保护属性
```

`Utf8ToGbk` 用 `MultiByteToWideChar(CP_UTF8)` + `WideCharToMultiByte(936)`。
**不能直接把 UTF-8 字节交给 `CreateFontA`** —— 那是 ANSI 版 API，
收到 `宋体` 的 UTF-8 字节（`E5 AE 8B E4 BD 93`）会得到一个无效字体名，
而且游戏对 `CreateFont` 失败不做检查，拿到 NULL 会在渲染时崩溃。

### 4.4 字体 Hook 的实现要点

```c
// 必须检查返回值，失败要回退原参数
HFONT h = g_orgCreateFontA(..., "宋体"(GBK), ..., 134 /*GB2312_CHARSET*/, ...);
if (!h) { Log("中文字体失败，回退"); return g_orgCreateFontA(原参数); }
```

`CharSet=134`（`GB2312_CHARSET`）是必需的。游戏源码 `Text.cpp:886`
硬编码了 `ANSI_CHARSET`，中文会显示为乱码。

---

## 5. IAT Hook 的正确写法

1 代踩过一个隐蔽的坑，值得单独记录。

### 错误写法：用 FirstThunk 读函数名

```c
// ✗ 错的
IMAGE_THUNK_DATA* thunk = (IMAGE_THUNK_DATA*)(base + imp->FirstThunk);
// 遍历时读 thunk->u1.AddressOfData 取函数名
```

**为什么错**：`FirstThunk` 指向 IAT，**加载后其内容已被 loader 改写成
真实函数地址**，不再是 `AddressOfData` 指针。拿它当名字表读会得到垃圾。

### 正确写法

```c
DWORD intRva = imp->OriginalFirstThunk;      // INT：保留原始名字表
if (intRva == 0) intRva = imp->FirstThunk;   // 少数 PE 省略 INT

// 用 INT 遍历取名字
IMAGE_THUNK_DATA* nameThunk = (IMAGE_THUNK_DATA*)(base + intRva);
// 写回时用 IAT（FirstThunk）那一份
IMAGE_THUNK_DATA* iatThunk = (IMAGE_THUNK_DATA*)(base + imp->FirstThunk);
```

即：**INT 读名字，IAT 写地址。**

---

## 6. exe 字符串地图（1 代实测）

| 块 | BaseRVA | Layout | 条数 |
|---|---|---|---|
| `button_block.ini` | `0x000BD2C0` | packed4 | 12 |
| `menu_block.ini` | `0x000BD328` | packed4 | 12 |
| `config_block.ini` | `0x000BD3E8` | packed4 | 9 |
| `unit_block.ini` | `0x000BD780` | packed4 | 7 |
| `ui_block.ini` | `0x000BD8E0` | packed4 | 68 |
| `keyname_block.ini` | 显式 RVA | explicit | 45 |
| **合计** | | | **153** |

运行日志印证：`applied=153 skipped=0`。

> **注意**：`unit_block.ini` 里写的 `Count=9` 与实际 7 条不符。
> 经查 `ini_reader.cpp:81` 解析了 `Count` 但**代码中从未使用** ——
> 它是死字段，DLL 以实际解析到的条目数为准。文档保留此说明以免误导。

### 关键 RVA 区域（1 代）

| RVA 范围 | 内容 | 可译性 |
|---|---|---|
| `0xBD2C0` ~ `0xBD3E8` | 按钮/菜单/配置文本 | ✅ |
| `0xBD780` 起 | `UnitNames[]` | ✅ 仅显示用 |
| `0xBD8E0` 起 | UI 串块 | ✅ |
| `0xBD70C` ~ `0xBD72F` | **`TrooperNames[]`** | ❌ 拼路径用 |
| `0xBD9xx` | `USA.h` 的 `*Title_Text` | ✅ 已由 ui_block 处理 |
| `0xD0384` 起 | `GamePlayKeyDescs[]` | ✅ |
| `0xD0714` ~ `0xD0Axx` | `TKeyDescriptors[].desc` | ✅ 按键设置界面 |
| `0xD0CB0` 起 | **注册表配置键名** | ❌ `strcmp` 用 |
| `0xD04E0` 起 | **注册表键名（White/Red/Move…）** | ❌ `strcmp` 用 |

---

## 7. 未解问题（留给后续代次）

以下问题 1 代**没有查明**，如实记录，不要当成已知事实：

1. **调色板 index 248 的用途**
   - 1998 中文盘：蓝色 `(89, 132, 212)`
   - Steam v1.2：暗红 `(120, 36, 76)`
   - 当前产物使用 Steam 调色板，cat 44-47 的中文渲染正常
   - 但该色位的**原始设计意图**不明

2. **窗口模式**
   - `-w` 参数未验证
   - 可能需要生成 `wndmode.ini`（ThirteenAG 的通用窗口化插件）

3. **`titles` 等其它资源包**
   - 仅处理了 `objects.dat`，是否有其它含中文的包未确认

---

## 8. 相关文档

| 文档 | 内容 |
|---|---|
| [`00-porting-map.md`](00-porting-map.md) | 移植地图（先读这个） |
| [`02-pitfalls.md`](02-pitfalls.md) | 踩坑清单 |
| [`03-build-and-release.md`](03-build-and-release.md) | 构建与发布 |
| [`04-asset-pipeline.md`](04-asset-pipeline.md) | 资产流程 |
