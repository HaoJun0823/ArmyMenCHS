# Army3_Object_CHS —— 3 代 .dat 贴图解包工作区

本目录存放《玩具兵大战：太空玩具》**打包在 `.dat` 里的贴图**，已展开为可人工编辑的 PNG。

## 结论先行

3 代的 **UI 贴图确实打包在 `.dat` 里**（不在 `bitmaps\` 目录）：

| dat | 对象数 | 内容 | 编码 |
|---|---|---|---|
| `title.dat` | 203 | 标题画面、版权声明、**对话面板**、按钮、图标 | 全部未压缩 BMP |
| `shared.dat` | 1113 | 游戏内 UI 元素、图标、兵种/载具小图 | BMP 666 / WRLE 345 / TRLE 71 / SRLE 31 |

对比 `bitmaps\` 目录（61 张）：那是**加载画面与多人地图预览**，与 UI 控件无关。

## 目录结构

```
Army3_Object_CHS\
├─ title\
│   ├─ manifest.json      对象清单（key/尺寸/编码/校验和）
│   ├─ palette.bin        256 色调色板（1024 字节，RGBQUAD）
│   ├─ raw\obj_NNNN_kXXXXXXXX.bin   原始字节（逐字节无损）
│   └─ png\obj_NNNN_kXXXXXXXX.png   解码图像（供人工编辑）
└─ shared\                （同上结构）
```

`kXXXXXXXX` 是对象的 key（`manifest.json` 里同时给十进制与十六进制）。

## 工作流

### 1. 改图（人工）

直接编辑 `png\` 下的文件：

- 尺寸必须保持不变（否则 `pack` 会按新尺寸写出，可能破坏布局）
- 保持调色板可用色（工具会做最近色匹配，但颜色会失真）
- 不要改名

### 2. 回包（CI / 本地）

```bash
python Tools/am3_dat.py pack Army3_Object_CHS/title  <输出>/title.dat
python Tools/am3_dat.py pack Army3_Object_CHS/shared <输出>/shared.dat
```

`pack` 的判定规则：

- **PNG 未被改动** → 直接用 `raw\*.bin` 回填（**逐字节无损**）
- **PNG 被改动** → 从 PNG 重编码为索引位图

已实测：

```
未改动往返  title.dat  SHA256 完全一致  ✔
未改动往返  shared.dat SHA256 完全一致  ✔
改 PNG 后   重新打包成功，输出与原始不同  ✔
```

## 位图格式（两个坑，已在工具里处理）

3 代未压缩位图的对象数据里有**两个**容易读错的约定，任一读错图像都会坏：

| 约定 | 读错的后果 | 实测依据 |
|---|---|---|
| 每行按 **4 字节对齐**（stride = `align4(w)`） | **斜向撕裂**（错位逐行累积） | 869 个 BMP 对象**全部**满足 `graphicSize == align4(w) × h` |
| 行序 **自下而上**（文件首行 = 图像最底行） | **上下镜像**（文字倒置） | 605×370 面板翻转后 `CASUALTY REPLACEMENT DELAY` 等方可读 |

`Tools/am3_dat.py` 的 `decode_bmp` / `encode_bmp` 已按这两条对称实现。
**修复前已生成的 PNG 必须重新解包**（旧图是撕裂+镜像的）：

```bash
python Tools/am3_dat.py unpack "<游戏目录>/title.dat"  Army3_Object_CHS/title
python Tools/am3_dat.py unpack "<游戏目录>/shared.dat" Army3_Object_CHS/shared
```

> RLE 族（WRLE/TRLE/SRLE）不受影响：它们按行偏移表定位，行内自成一格。

## 用途判定（哪些需要改）

| key 范围 | 尺寸 | 说明 |
|---|---|---|
| `0x80000`~`0x84xxx` | 640×480 / 485×455 | 标题画面、版权、过场底板 |
| `0x100000`~ | 356×182 / 356×280 | **对话面板与选项框**（含英文标题栏） |
| `0x180000`~ | 81×32 | 按钮（含英文字样） |
| `0x1F0000`~ | 16×16 / 19×9 | 小图标 |

`shared.dat` 里的 `43×27` / `43×32` 等小图是**游戏内单位与武器图标**，多数无文字。

## 已知限制

- **31 个 SRLE 对象未能解出 PNG**（全部在 `shared.dat`，尺寸偏大，如 256×214）。
  SRLE 是另一种行压缩变体，本工具暂未实现解码。
  **不影响回包**：它们的 `raw\*.bin` 是逐字节无损的，`pack` 原样回填。
  若确需编辑这些图，需先补 SRLE 解码（见 `Tools/am3_dat.py` 的 `decode_rle`）。
- 仅支持 3 代 dat（FILEID `0x81920667` / `0x81920668`）。2 代用 `Tools/unpack_objects/objects_dat.py`。
- **不改 exe，不改 dat 结构**：只替换对象像素数据，key 表与调色板保持不变。

## 重建

```bash
python Tools/am3_dat.py unpack "<游戏目录>/title.dat"  Army3_Object_CHS/title
python Tools/am3_dat.py unpack "<游戏目录>/shared.dat" Army3_Object_CHS/shared
```
