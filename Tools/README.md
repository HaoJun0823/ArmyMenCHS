# Tools — objects.dat 拆包 / 打包

## 1. objects.dat 格式（`src\fileio.cpp` 的 `OpenDataFile`）

```
偏移 0     : int FILEID          == 132415161 (0x7E3D2B9)  魔数校验
偏移 4     : 256 × RGBQUAD        = 1024 字节   256 色调色板
偏移 1028  : int nObjects         （注意：不是偏移 4）
偏移 1032  : nObjects × { key:DWORD, offset:DWORD }   8 字节/项
之后       : 各对象的 RLE 压缩位图（offset 为绝对文件偏移）
```

**已验证**：J:\ 与 Steam 三地形的**目录表 key 集合完全一致**，差异仅在调色板 + 精灵像素。
→ 改图后重打包**无需改 key 表**，只要保持 key 不变即可与游戏索引兼容。

**key 生成公式**（`compobj.cpp:451`）：
```c
key = damagelevel + (number << 5) + (category << 15)
```

完整定义摘录：`format_spec\OpenDataFile_excerpt.cpp`（fileio.cpp 行 988-1089）。

## 2. compobj\ — 官方打包器（源码 + 二进制齐全）

| 文件 | 说明 |
|---|---|
| `compobj.cpp` | 1637 行完整源码（Peter Hu, 980129） |
| `Compobj.mak` | 构建脚本 |
| `Compobj.exe` | 已编译产物（134656 B，32 位） |

用法：
```
compobj.exe <terrainpath>
```
要求 `<terrainpath>\` 下存在：
- `final_pal.bmp` — 256 色调色板
- `Objects\<category>\` — 分类子目录，内含
  - `*.bmp` 精灵图
  - `masks\<同名>.msk` 遮罩
  - `rects\<同名>.rec` 矩形
  - shadow 文件

分类目录见 `compobj.cpp:420` 的 `obj_category_dirs[]`。

## 3. Art2D — 英文原始 BMP 图源（重要）

源码仓库 `ArmyMenSourceCode\Art2D\` 下有 **4155 个文件 / 118 MB**，正是 compobj 的输入：

```
Art2D\ALPINE\OBJECTS\  ── BASE(60) BRIDGE(72) BUILDING(146) BUSH(22) EXPLOSIVES(7)
                          FALLENTREE(2) FENCE(64) GUNTURRET(16) MISCELLANEOUS(234)
                          ROCK(32) SITEMS(14) TREE(32)  + 各自 MASKS\ RECTS\
Art2D\BAYOU\OBJECTS\
Art2D\DESERT\OBJECTS\
```

**意义**：中文 objects.dat 不必靠逆向拆包重建 —— 有英文原图在手，
可对照中文版逐图改绘，再用 compobj 打包。**这是本项目优于原补丁的关键资源。**

## 4. unpack_objects\ — 拆包器（待实现，可选）

当前为空。若走"改英文原图 → compobj 重打包"路线，**可不必实现**。
若需直接编辑中文 objects.dat 的像素，则需按第 1 节格式实现拆包（Python 3 + Pillow）。

## 5. 推荐工作流

```
Art2D\<terrain>\OBJECTS\*.bmp   （英文原图，已在源码仓库）
        │  对照 Army1_CHS\terrain\<terrain>\objects.dat 的中文精灵改绘
        ▼
<terrain>\Objects\<category>\   + final_pal.bmp
        │  compobj.exe <terrain>
        ▼
objects.dat（新中文版）
```

> 注意：`compobj.exe` 是 1998 年 32 位程序，64 位 Windows 靠 WoW64 运行；
> 若失败，按 `compobj.cpp` 用现代工具链重编即可（源码齐全）。
