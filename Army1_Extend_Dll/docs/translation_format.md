# 翻译数据格式说明

翻译内容**不写死在 DLL 里**，全部外置为数据文件，DLL 只做"读表 → 应用"的引擎。

## 为什么选 INI

| 格式 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| INI | 人工可读可编辑、中文直观、Windows 原生 `GetPrivateProfileString` 可用 | 不适合嵌套结构 | **选它** |
| XML | 结构化强 | 手写繁琐、需解析库 | 否 |
| CSV | 表格友好 | 含逗号/引号的中文要转义 | 作辅助导出 |
| JSON | 通用 | 手写易错、需库 | 否 |

INI 用 UTF-8 存储（GBK 转换在 DLL 内做），避免中文乱码。

## 文件布局

```
ArmyMenCHS.ini                    ← 主配置（路径、开关）
strings/
├─ ui_block.ini                   ← UI 串块（菜单/对象名/单位名/武器名）
├─ ...                            ← 后续新增串块
```

## 主配置 `ArmyMenCHS.ini`

```ini
[General]
; 游戏主模块名（用于定位 imagebase）
Module=Armymen.exe

[Font]
; 是否 Hook CreateFontA/CreateFontIndirectA 强制中文字体
Enable=1
; 字体名（GBK 写入）
FaceName=宋体
; charset: 134 = GB2312_CHARSET, 1 = DEFAULT_CHARSET, 0 = ANSI_CHARSET
CharSet=134

[Strings]
; 翻译数据目录（相对 DLL 所在目录）
Dir=strings
; 加载哪些文件（逗号分隔）
Files=ui_block.ini
```

## 串块文件 `strings/*.ini`

```ini
[Meta]
; 该块在英文 exe 中的起始 RVA（.data 段）
BaseRVA=0xBDA6C
; 编码：写入时用 GBK
Encoding=GBK
; 块内字符串按 "C串 + padding对齐4字节" 紧凑排列，按顺序编号
Layout=packed4

[Entries]
; 格式：序号 = 中文译文   ; 英文原文（注释，便于校对）
0=摇杆按钮                ; Joystick Buttons
1=基本游戏动作            ; Basic Game Actions
2=中士动作                ; Sarge Actions
```

### 关键字段

| 字段 | 说明 |
|---|---|
| `BaseRVA` | 块起始 RVA。DLL 用它 + 运行时 `imagebase` 算出实际 VA |
| `Layout=packed4` | 每个串是 C 串，后补 NUL 并对齐到 4 字节 |
| 序号 | 块内第 N 个串（从 0 开始） |
| 中文译文 | DLL 转 GBK 后写入；**若超过该槽容量则跳过并记日志** |

## 槽容量约束

exe 里每个串占据 `原串长 + 1(NUL) + padding(对齐到4)` 字节。
中文 GBK 每字 2 字节，所以：

- 例：`Mine Sweeper` 长 12，槽容量 16 → 可用 15 字节 → 最多 7 个汉字
- 超限时 DLL 会**跳过该条并写日志**，不会截断也不会越界覆盖下一条

若某条确实需要更长，解决办法（按风险从低到高）：
1. 缩短译文
2. 用英文缩写 + 中文（如 "AA炮"）
3. 改指针重定向（需改代码引用处，风险高，暂不实现）

## 存疑译文处理

源码 `TextData.cpp:280-305` 是该表的权威顺序：

```
Rock, Bush, Tree, Big Tree, Fallen Tree, Fence, Wall, Bridge, Foot Bridge,
Explosive, Gun Turret, AA Gun, Base, Auxbase, Air Strip, Heli Pad,
Prison Camp, Building, PillBox, PowerPlant, FenceGate, WallGate,
RadarBuilding, Miscellaneous, Overpass, Special Item
```

**已知官方误译**：`PillBox`（= 碉堡/地堡）被中文官方版译为「医疗箱」。
本表按「碉堡」翻译，并在该行注释标注 `; [疑] 官方译"医疗箱"，疑误译`。
