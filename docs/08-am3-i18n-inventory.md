# Army Men: Toys in Space (3 代) —— i18n 载体侦察与入库清单

> 本文记录**已实测验证**的事实，作为 3 代汉化的开工依据。未验证项一律标 ❓。
> 2 代的技术原理见 [`05-am2-technical-archive.md`](05-am2-technical-archive.md)，
> 移植对照见 [`05-am2-porting-guide.md`](05-am2-porting-guide.md)。
>
> 侦察日期：2026-10-14 ｜ 目标：`I:\LocalGames\Army Men\Army Men - Toys in Space STEAM`

---

## 0. 一句话结论

**3 代与 2 代最大的差异：官方把几乎全部界面文本外置成了 `strings\strings.txt`。**

2 代文本硬编码在 exe 的 `.rdata` 里（当文件路径用），所以 2 代汉化要逐个 RVA 做内存补丁。
3 代官方自己做了同样的事——320 条 UI 文本全部搬到外部文件，exe 里只剩一个加载器和一个访问器。

**这意味着 3 代汉化的主力手段从"内存字符串补丁"变成了"直接改外部文件"**，
难度显著低于 2 代，但要防住一个硬约束：**行数不得少于 320，否则游戏直接弹框拒绝启动。**

---

## 1. 与 2 代的结构性差异（实测）

| 项 | 2 代 | 3 代 | 验证方式 |
|---|---|---|---|
| 外置文本文件 | ❌ 无 | ✅ `strings\strings.txt` | exe 内 `strings.txt` 字面量计数：2 代 **0** / 3 代 **5** |
| exe 内 UI 文本 | ✅ 全在 `.rdata` | ❌ 基本清空 | 见 §1.1 |
| 文本加载器 | — | `sub_427F9C`（`ExtnTextLoad`） | IDA xref + 反编译 |
| 文本访问器 | — | `sub_4280FA(i) -> dword_534F90[i]` | IDA 反编译 |
| 访问器调用点 | — | **97 处** | IDA xref |
| 字符串指针数组 | `.rdata` 表（步长 `0x24`） | `dword_534F90` @ `0x534F90`（`DWORD[320]`） | 地址间隔核算 |
| Hzk16 中文字库 | ✅ 官方中文版带 | ❌ exe 内无 `Hzk16`/`RSE\x1a` | 字节搜索 |

### 1.1 exe 内 UI 文本已清空（逐字节搜索）

以下字符串在 3 代 exe 中**命中数全部为 0**，证明它们只在 `strings.txt` 里：

```
Are you sure you want to quit?   Rifleman        POWER-UPS
Machine Gunner                   Flame Throwers  MISCELLANEOUS
Easy                             Squad %d (shortcut F%d)
```

仍留在 exe 的：`Army Men: Toys in Space`（窗口标题）、`Attack`、`Player`、
`Green/Tan/Blue/Grey`、`None`、`Recon`（少量漏网，含义待定 ❓）。

---

## 2. `strings\strings.txt` —— 主力载体

### 2.1 文件事实

| 项 | 值 |
|---|---|
| 路径 | `strings\strings.txt`（相对游戏根，**反斜杠**） |
| 大小 | 4,420 B |
| 行数 | **320**（含 1 个空行，位于第 189 行） |
| 行尾 | CRLF（320 个 CR + 320 个 LF），以 `"rt"` 文本模式读取 |
| 编码 | **纯 ASCII**（非 ASCII 字节数 = 0） |
| 最长行 | 103 字节 |
| 末行 | `tina_tomorrow`（无结尾换行歧义，文件以 CRLF 结束） |
| 首行 | `Rifleman` |

### 2.2 加载器 `sub_427F9C` 的精确行为

反编译 + 反汇编双确认：

```c
char sub_427F9C() {
    sub_42816A("strings");                      // 设基准路径
    FILE* f = fopen("strings\\strings.txt", "rt");
    if (!f) {
        MessageBoxA(..., "Invalid installation. The file "
                         "'strings\\strings.txt' cannot be read.", ..., 0x10);
        return 0;                               // 拒绝启动
    }
    int n = 0;
    char* p = dword_534F90;                     // ★ 数组起点，容量 320
    while (fgets(Buffer, 512, f)) {             // ★ 单行上限 510 字节
        if (Buffer[0] == '"') { /* 去引号 + 去尾随 TAB */ }
        else                  { /* 去换行 + 去尾随 TAB */ }
        *p++ = _strdup(解析后的串);              // ★ 无上界检查
        n++;
    }
    fclose(f);
    if (n < 320) {                              // ★ 只查下界，不查上界
        MessageBoxA(..., "Invalid installation. The file "
                         "'strings\\strings.txt' contains the wrong "
                         "number of strings.", ..., 0x10);
        nullsub_1(&stru_484558._file, n, 320);
        return 0;                               // 拒绝启动
    }
    byte_535490 = 1;                            // 加载成功标志
    return 1;
}
```

### 2.3 三条硬约束（翻译时必须遵守）

| # | 约束 | 依据 | 违反后果 |
|---|---|---|---|
| **C1** | 行数 **≥ 320** | `cmp [ebp+var_4], 140h` / `jge`，`140h = 320` | 弹 "wrong number of strings" 并**拒绝启动** |
| **C2** | 单行（含换行）**≤ 510 字节** | `fgets(Buffer, 512, ...)`，Buffer 是 `char[512]` | 该行被截断 → 一行裂成两行 → 后续**全部索引错位** |
| **C3** | 数组容量 **320** 项，写入无上界检查 | `dword_534F90`(`0x534F90`) 到 `byte_535490`(`0x535490`) 间隔 `0x500` = 1280 B = 320×4 | 超过 320 行会**溢出覆盖**加载成功标志及后续全局量 |

> **C1 的解释**：条件只有下界。所以**保持 320 行**最安全；
> 若译文比原文长需要拆行，可超过 320 行，但绝不能超过 320 项容量（C3）。
> 目前英文原文恰好 320 行 = 容量上限，**没有任何余量**。

### 2.4 解析规则（影响怎么写译文）

```c
// 如果行首是双引号 "  —— 走"带引号"分支
//   去尾：从行尾往前跳 TAB，再若末字节是 " 则置 0
// 否则                —— 走普通分支
//   去尾：从行尾往前跳 TAB（strchr('\n') 之后）
```

**要点**：
- **文件以 `"rt"`（文本模式）打开** —— 反汇编确认 `fopen(path, "rt")`。
  文本模式下 CRT 会把 CRLF 折成 LF，所以 `fgets` 拿到的行**不含 `\r`**，
  代码只需处理 `\n`。这也解释了为什么代码里完全没有碰 `\r`。
- 以 `"` 开头的行会被**剥掉外层引号**。实测共 **5 行**属于此分支
  （1-based 行号 **115 / 308 / 309 / 310 / 316**）：

  ```
  L115  "Game type: %s, Goal: %d"
  L308  "Game type: %s, map: %s, playing time: %d:%d:%d"
  L309  "Player:%s, left the game or was disconnected"
  L310  "Player: %s(%s), score: %d, teamscore: %d, rank: %d, teamrank: %d"
  L316  " abcdefghijklmnopqrstuvwxyzABC...XYZ0123456789`~!@#$%^&*()..."
  ```

  这些串在内存里**没有外层引号**。翻译时若**删掉开头的 `"`**，
  解析会切到另一条分支 —— 尾部的 `"` 可能残留进最终字符串。
  **必须保留行首的 `"`**。
- 行尾的 **TAB 会被剥掉**（循环 `dec` + `cmp 9` 持续剥离）。
  译文若以 TAB 结尾会被静默吃掉。
- 现有文件**没有任何一行含 TAB**（实测），所以"剥 TAB"逻辑目前是空转，
  但写译文时不要引入 TAB。
- 第 316 行是一串"合法字符表"（` abcdefghijklmnopqrstuvwxyzABC...`），
  **不是 UI 文本，不可翻**（含义待定 ❓，疑似输入过滤白名单）。
- **空行位于第 189 行**（1-based）。加载器**不为空行跳过**，它同样
  推进索引计数器并占一个槽位，该槽内容为空串。

> ⚠ 空行还有个细节：普通分支会从 `\n` 位置**向前**逐字节剥 TAB。
> 对"整行只有换行"的行，这个反向扫描会落到缓冲区首字节之前（`Buffer[-1]`）。
> 这是原版代码的既有行为，**出厂文件里本来就带这个空行且游戏能正常运行**，
> 所以实践中是良性的（读到的字节恰好不是 TAB 就立即停止）。
> 但**不要在译文里新增空行**，避免触发这条未定义路径。

> **对中文字节的影响**：文本模式只翻译 CRLF，不触碰 `>0x7F` 的字节。
> 所以 GBK 中文写进 `strings.txt` 不会被 CRT 破坏。
> 真正的问题在**渲染器能否画汉字**（见 §6），不在文件读取层。

### 2.5 索引空间（已核对无越界）

- `sub_4280FA` 被调用 **97** 处。
- 静态可解析出 **73** 个不同索引，范围 **2 .. 319**。
- **无任何 ≥ 320 的越界索引**（已断言）。
- 其余 24 个调用点的索引是运行时算出的（未静态解析）。
- 0..319 中未被静态直接引用的有 268 个——正常，多数走动态索引
  （如按单位类型 / 道具 ID 查表）。

> 也就是说**不能只翻"被静态引用的 73 条"**：动态索引意味着
> 320 行几乎都可能被使用。需要实机逐一验证。

---

## 3. 其余 i18n 载体

### 3.1 地图脚本的显示文本（`.txt`）

3 代地图脚本用两条命令直接携带显示文本：

| 命令 | 条数 | 样例 |
|---|---|---|
| `showmessage` | 42 | `showmessage "Larva!!!"` |
| `showpda` | 30 | `showpda "The Alien menace is no more. You win!"` |

合计 **72** 条，分布在这些文件（部分）：

```
data\alienhive\bugged1.txt          data\alienworld\spacesavers1.txt
data\alienworld\alienated1.txt      data\livingroom\livingroom1.txt
data\alienworld\firstcontact1.txt   ...
```

### 3.2 引号字面量（含 UI 与资源名，需区分）

全量 **148** 个 `.txt`（不含 `save/`）中，引号字面量共 **1,326 次 / 973 唯一**，
但**绝大多数不是 UI 文本**。精确分类：

| 类别 | 出现次数 | 唯一 | 是否翻译 |
|---|---|---|---|
| `text`（含空格，疑似 UI 文本） | 94 | **72** | ✅ 可翻 |
| `ident`（资源名/变量名/音效名，如 `striker`、`pant1`） | 858 | 719 | ❌ 不可翻 |
| `.wav` 音效文件名 | 313 | 159 | ❌ 不可翻 |
| `other`（其它，多为格式串） | 61 | 23 | ⚠ 逐条判定 |
| **合计** | **1,326** | **973** | |

> 分类判据：`.wav` 结尾 → wav；完整匹配 `^[A-Za-z_][A-Za-z0-9_\-@.]*$`（无空格
> 单一 token）→ ident；否则含空格且有两个以上英文词 → text。
> 该判据**可能低估 `text`**（例如单词感叹型 `Larva!!!` 会落入 `other`），
> 实际待译量应介于 **72 ~ 95** 之间。

**72 条 `text` 中跨文件复用的有 8 条**，代表作：

```
A tank pilot was Killed!                       x6
You let Sarge die!                             x4
Sarge? Sarge? Sarge!                           x4
WARNING!!! Low Civilian count.                 x3
Tina Tomorrow was killed in action. Mission failed.
Good job Sarge, you rescued the civilians!
It's a way in! GO! GO! GO!
Held area for 30 seconds. 10 seconds remaining!
Get Tina Tomorrow to the eject button on the game system.
@2 Flag was dropped and not picked up for 2 minutes - moved to base
```

> 注意最后一条含 `@2` 占位符；`other` 类里的 `Larva!!!` 来自
> `showmessage "Larva!!!"`，是纯 UI 文本。

### 3.3 `rules\*.txt` —— 多人模式战报模板

`rules/` 共 75 个 `.txt`，引号串 **89** 条（未按 §3.2 判据细分，含资源名），
其中多数是战报模板（含 `@1`~`@4` 占位符）：

```
@2 gained @3 flag
@2 scored with @3 flag
@2 sarge killed by @3
@2 sarge killed by @1 friendly fire
@2 holds the flag
@2 sarge killed by enemy @3 and becomes it
@2 is king of the hill
@2 takes control of node @4
Player: %s(%s), score: %d, teamscore: %d, rank: %d, teamrank: %d
```

> 这些是**格式化模板**，含 `@N` 占位符，翻译时占位符必须原样保留。
> 另有 `*_desc.txt`（规则描述，如 `rules\ctf_desc.txt`）是纯说明文本。

### 3.4 顶层地图定义表

`campaign.txt` / `bootcamp.txt` / `mpmaps.txt` 的第二列 `map_text` 是**显示名**：

```
MAP  hostage   Hostage      backyard  backyard ...
MAP  bugged    The_Hive     alienhive bugged   ...
MAP  spacesavers Space_Saviors alienworld spacesavers ...
```

**注意**：`map_text` 是显示名，但同一行的 `map_name`（第一列）与 `folder`/`tileset`
（第三、四列）是**文件路径片段，不可翻**——这是 1 代踩过的坑
（见 [`00-porting-map.md`](00-porting-map.md) §3 陷阱 2）。

### 3.5 `amtisged.dll` —— Steam 启动配置器（独立载体）

`amtisged.dll`（49,152 B）是 Steam 版附带的**多人游戏设置器**，
有自己的窗口和硬编码 UI 文本，**与主 exe 完全独立**：

| 项 | 事实 |
|---|---|
| 段 | `.text` / `.rdata` / `.data` / `.rsrc` / `.reloc` |
| 导入 | `MSVCRT.dll`（无游戏 DllImport） |
| 读的外部文件 | `mpmaps.txt`（2 处）、`mpconfig.txt`（2 处） |
| 读 `strings.txt` | ❌ **不读**（独立文本集） |

**该 DLL 独有的 UI 文本**（exe 内没有，必须单独翻）：

```
Internal error: couldn't initialize game settings [code 1a]
Internal error: couldn't initialize game settings [code 1]
A newer version of your HEAT software may be required for the
  game settings to appear correctly.
Army Men: Toys in Space Settings
Could not open mpmaps.txt.
Out of memory: couldn't initialize settings.
Try closing other applications.
You will have to insert the Army Men: Toys in Space CD-ROM before
  you can join this game
No Teams
No Friendly Fire
Hurt Everyone
Hurt Yourself
```

另有配置键名与格式串（**不可翻**）：

```
%s -mpconfig:mpconfig.txt   color %lu   team %lu   plastic %lu
player %d   colorsdefined %d   teamsdefined %d
poweruprespawn %lu   unitrespawn %lu   options1..3 %lu   goal %lu
```

> 它读 `mpmaps.txt` 说明**多人地图显示名**也影响这个界面，
> 与 §3.4 的 `map_text` 是同一份数据 —— 改一处必须两处都验证。

### 3.6 BMP（116 个，16.06 MB）

按存放位置与命名精确分组：

| 组 | 数量 | 位置 | 说明 |
|---|---|---|---|
| `load_*.bmp` | **29** | `bitmaps/` | 载入/关卡图，**含英文关卡名概率高** |
| `bcs0NN.bmp` | **26** | `bitmaps/` | 任务简报/说明页，**含文字概率最高** |
| `mp*` / `mapwait` / `bad_mp_prev` | **5** | `bitmaps/` | 多人模式结算图（3）、战略图等待页、多人预览占位图 |
| `datamap.bmp` | 1 | `bitmaps/` | 战略图 |
| `01_000_00_screen.bmp` | 1 | `01-title/` | 标题画 |
| `palette*.bmp` | **11** | `data/*/` | 调色板（1082 B），**非图像** |
| `*_prev.bmp` | **15** | `data/*/` | 多人地图缩略图（37942 B） |
| 地图预览 `*.bmp` | **28** | `data/*/` | 各关卡/多人图预览（18502 / 19576 B） |
| **合计** | **116** | | 与 §5.2 一致 |

> **优先处理顺序建议**：`bcs*`（26）→ `load_*`（29）→ 预览图（28）。
> `palette*.bmp` 与 2 代同为 1082 B，是**纯调色板数据，不要当图翻**。

> 3 代的载入图与 2 代同为 **308,278 B**（640×480×8bit + 调色板）格式，
> 2 代的对比工具（`Tools/bmp_*_am2.py`）应可直接复用。判据必须是
> **人工实图核对**（见 [`05-am2-porting-guide.md`](05-am2-porting-guide.md) §3）。

---

## 4. 不存在官方中文母盘

| 检查 | 结果 |
|---|---|
| 本机 `玩具兵大战*` 目录 | 只有 `玩具兵大战1`、`玩具兵大战2` |
| 3 代中文零售盘 | ❌ 未发现 |
| 3 代 exe 内 `Hzk16` / `RSE\x1a` | ❌ 0 命中（官方中文版必然带字库） |

**结论**：3 代必须**从零翻译**，无法走"差异移植"。
但 2 代已经验证过的技术框架（Hzk16 渲染、DLL 内存补丁方案）可完全复用。

> 另注：`I:\LocalGames\Army Men\Army Men II Lost MP Content` 是 2 代的
> 多人模式补充内容，与 3 代无关。

---

## 5. 入库结果：`Army3_Original/`

### 5.1 为什么不是"照 2 代全量镜像"

`Army2_Original` 是 **717 文件 / 569 MB 的完整资产树**（含 309 个 `.wav`、
165 个 `.bmp`、25 个 `.smk`）。原因是 2 代**有**官方中文母盘，
中文配音/贴图/视频本身就是 i18n 依据，所以整棵树都相关。

3 代**没有**母盘，可译面天然只有文本载体。因此本树采用
**i18n 精确入库**：只收 `.txt` 与 `.bmp`。

### 5.2 实际入库

| 项 | 值 |
|---|---|
| 文件数 | **264** |
| 总体积 | **16.63 MB** |
| 生成脚本 | `am3_build_assets.py` |
| 清单 | `Army3_Original/MANIFEST.md` |
| 全量哈希 | `Army3_Original/_filehash.csv` |

| 扩展名 | 文件数 | 体积 (MB) |
|---|---|---|
| `.bmp` | 116 | 16.06 |
| `.txt` | 148 | 0.57 |

| 顶层 | 文件数 | 体积 (MB) |
|---|---|---|
| `bitmaps` | 61 | 14.71 |
| `data` | 121 | 1.48 |
| `01-title` | 1 | 0.29 |
| `rules` | 75 | 0.10 |
| `(根)` | 5 | 0.04 |
| `strings` | 1 | 0.004 |

### 5.3 未收录（505 文件 / 494.70 MB）

| 类别 | 文件数 | 体积 (MB) | 原因 |
|---|---|---|---|
| `.wav` | 360 | 162.78 | 英文配音，无中文母盘可比对 |
| `.smk` | 10 | 169.07 | 英文视频，无中文母盘可比对 |
| `.atl` | 23 | 62.57 | 图集数据，无文字 |
| `.dat` | 13 | 42.96 | 打包数据（objects/title/shared） |
| `.ani` | 42 | 31.92 | 动画帧数据，无文字 |
| `.amm` | 28 | 12.44 | 地图数据，无文字 |
| `.i64` | 1 | 9.67 | IDA 数据库（会话产物） |
| `.dll` | 5 | 1.33 | 第三方/兼容 DLL；其中 **`amtisged.dll` 含独立 UI 文本（见 §3.5）** |
| `.pdf` | 1 | 1.22 | 英文文档 |
| `.exe` | 1 | 0.61 | 主程序（硬约束：不改 exe） |
| `.aai` | 18 | 0.11 | AI 行为表，非显示文本 |
| `.ico`/`.vdf`/`.sdb` | 3 | 0.00 | 非资产 |
| `3do.smk` | 1 | 1.54 | 第三方广告 |
| `.id0/.id1/.id2/.nam/.til` | 5 | 9.68 | IDA 松散工作文件（打开 IDB 时解出，会话产物） |

另有运行期 `save/` 整目录未收（存档，非资产）。

> ⚠ **一处待定**：`amtisged.dll`（49 KB）的 UI 文本**当前未入库**，
> 因为它被 `*.dll` 规则排除了。若决定汉化启动配置器界面，
> 需单独纳入该 DLL（或因"不改 exe/dll"硬约束改为走内存补丁）。

> 后续若要做中文配音，需再拉 `audio/`（162.78 MB）；
> 若要嵌视频字幕，需再拉 `avi/`（169.07 MB）。

### 5.4 校验结果

| 检查 | 结果 |
|---|---|
| 与源逐字节 sha256 一致 | ✅ 264/264，0 不一致 |
| `_filehash.csv` 自校验 | ✅ 264 条，0 不符 |
| `strings.txt` 行数 | ✅ 320（= 数组容量） |
| `strings.txt` 非 ASCII 字节 | ✅ 0 |
| 单行超 510 字节 | ✅ 无（最长 103） |
| `rules`/`data`/`strings` 的 `.txt` 计数与源一致 | ✅ 75/75、67/67、1/1 |

---

## 6. 对 3 代汉化路线的影响

与 [`05-am2-porting-guide.md`](05-am2-porting-guide.md) 的对照，3 代新增/变化的项：

| 项 | 2 代 | 3 代 | 影响 |
|---|---|---|---|
| UI 文本改法 | 内存补丁（RVA 表） | **直接改 `strings.txt`** | 🟢 大幅简化 |
| 行数约束 | 槽容量 `len(en)+1` | **320 行硬闸 + 510 B/行** | 🟡 新增约束 |
| 地图脚本文本 | 同 | 同（`showpda`/`showmessage`） | 🟢 照搬 |
| 中文字库 | 复用中文母盘 `Hzk16` | **需自备**（无母盘） | 🟡 需解决 |
| 文本渲染器 | 3 绘制 + 1 测量 | ❓ 需重测（源码里已有 `probeOnly` 档位） | 🟡 需重测 |
| 注入方式 | `dinput.dll`（按名导入） | ❓ 需查导入表 | 🟡 需重测 |
| 启动配置器 | 无独立界面 | **`amtisged.dll` 自带一套 UI 文本** | 🟡 新增载体 |

> **`target.cpp` 里已有 TIS 档位且标为 `probeOnly = true`**（不接管渲染）。
> 3 代的渲染正确性尚未实机验证，ASCII 宽度与字形头语义未确认。

### 建议的下一步

```
① 打通 strings.txt 改字（唯一门槛是行数与编码）—— 风险最低，先做
② 确认中文字库来源（无母盘，需自备 13×13 点阵或改用其它方案）
③ 重测 3 代文本渲染器（能否沿用 2 代的 3+1 函数结构）
④ 查 3 代导入表，确认 ASI 代理 DLL
⑤ 再处理 BMP 烧字与地图脚本
```

---

## 7. 相关文档

| 文档 | 内容 |
|---|---|
| [`05-am2-technical-archive.md`](05-am2-technical-archive.md) | 2 代技术档案（渲染器、Hzk16、内存补丁原理） |
| [`05-am2-porting-guide.md`](05-am2-porting-guide.md) | 2 → 3/4 代移植指南（逐项对照表） |
| [`06-am2-pitfalls.md`](06-am2-pitfalls.md) | 2 代踩坑清单（15 个真实坑） |
| [`00-porting-map.md`](00-porting-map.md) | 1 代视角的移植地图 |
| [`../Army3_Original/MANIFEST.md`](../Army3_Original/MANIFEST.md) | 3 代入库资产清单 |
