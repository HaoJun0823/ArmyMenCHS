# army4_new_chs —— 《玩具兵大战：世界大战》简体中文译文

本目录存放 4 代（Army Men: World War）需要汉化的**文本文件**，可直接整树复制到游戏目录
（与 3 代 `Army3_NEW_CHS` 布局一致：只放需要替换的文件，其余沿用英文原版）。

## 结论先行

4 代可汉化文本共 **34 个文件**，分三类：

| 目录 | 文件数 | 内容 | 行数约束 |
|---|---|---|---|
| `strings\strings.txt` | 1 | 全部 UI 文本：兵种/载具/建筑名、多人消息、难度、确认框、武器道具名、错误消息、队伍名 | **324 parts 严格不变** |
| `rules\*_desc.txt` | 10 | 联机模式玩法说明（`mpmaps.txt` 的 `rules_description_file` 列指向） | 允许压缩行数 |
| `rules\` 机制文件 | 9 | `caf` `ctf_common` `death_common` `ffire` `holdflag_common` `killer` `koth` `last` `node_common` 的 `showmessage` 播报 + `expand` 颜色实参 | 行数严格一致 |
| `data\` 关卡脚本 | 13 | 任务 PDA、失败提示与阶段性播报 | 行数严格一致 |

## 两个关键约束（改动时必须守住）

1. **`strings.txt` 的 324 parts 是硬上限**：游戏用 `cmp ..., 320` 做下界闸门，
   出厂 323 行说明指针数组容量 >= 323，但**没有任何余量保证**。
   本译文逐 parts 替换，parts 数与原文件完全相同，不增不减。
2. **颜色实参必须跟着汉化**：`rules` 里 `expand` 的第二个参数是显示用颜色名，
   原文形如 `expand koth_macro ( green "Green" 1 ... )`。只译 `showmessage`
   模板而留着 `"Green"`，会渲染出「绿队 is king of the hill」这类中英混拼。
   本轮已统一改为 `绿队 / 棕队 / 蓝队 / 灰队`（与 `strings.txt` 第 304-307 行一致）。
3. **只碰引号内的字符串**：指令名、缩进（含 TAB）、逗号、`@N` 占位符、
   `playsound` 文件名一律保持原样。

## strings.txt 的三处禁译行

| 行号 | 内容 | 原因 |
|---|---|---|
| 318 | `" abcde...xyz...0123456789\`~!@#$%..."` | 被 6 处代码当**允许输入的字符集表**消费 |
| 319 | ` abcde...xyz...0123456789!'&+-_` | 同上 |
| 322 | `tina_tomorrow` | 被 `strcmp` 比较（开发者彩蛋） |

第 191 行原文是空行（同样占一个字符串槽位），译文保持空行。

## 与 3 代译文的对应关系

4 代与 3 代文本载体结构同构（`amww.exe` 内 `strings.txt` 字面量同为 5 处，
加载器同为 `ExtnText.cpp` 的 `ExtnTextLoad`），因此：

- 兵种/载具/建筑/武器/道具译名**直接沿用 3 代**，保证跨代一致
- 联机播报模板沿用 3 代句式，按 4 代英文微调（4 代把 `sarge killed` 改成了
  `unit killed` / `trooper killed`，中译相应从「中士」改为「士兵」）
- 4 代独有内容：`TURRET`/`炮塔`、`LTMG`/`轻机枪`、`HP`（载具耐久）、
  `last`（最后一人存活）模式的全部播报、第 323 行
  `Sir! My CO ordered me to stay in the vehicle.`
- 3 代有、4 代无：`it`（抓人）模式全部文件、`SPED`/`AUTO`/`SARGE` 三个缩写

## 译文规格（全部已自动校验）

- **GB18030 编码**、**CRLF 换行**、**无 BOM**，与游戏原文件格式一致
- 逐行保留 `%s` `%d` `%3d` `@N` 等格式说明符及其顺序
- 无新增 TAB 变动、无新增 `^`（`^` 是渲染器的颜色转义符，会吃掉后一个字符；
  `strings.txt` 第 318 行字符集表原文即含 `^`，属禁译行原样保留）
- 机制文件与关卡脚本**行数严格对齐**原文；`*_desc.txt` 允许压缩行数
- 译文用到的 **84 个汉字**全部在 `Hzk16` 字库中有点阵（用 DLL 的官方公式
  `idx = trail + 94*lead - 15295; off = bpg*idx - 9688` 逐字验证，零缺字）

## 已知的原文 bug（已修复，不复刻）

| 文件 | 行号 | 问题 |
|---|---|---|
| `data\beach\death_walk1.txt` | 41 | `showpda "` 后引号未闭合，字符串实际吞掉后续空行 |
| `data\inland\Escape_from_Toypiquet1.txt` | 261 | 同上 |

译文对这两条做了补全引号的整行替换。若需与原文逐字节一致，可改回未闭合形态。

## 校验脚本

| 脚本 | 作用 |
|---|---|
| `_am4_trans_strings.py` | `strings.txt` 译文映射表（幂等，可重复执行） |
| `_am4_trans_rules.py` | `rules/` desc 全文 + 机制文件 showmessage/expand 颜色替换 |
| `_am4_trans_data.py` | `data/` 关卡脚本译文映射表（幂等） |
| `_am4_verify_final.py` | 编码 / CRLF / BOM / 裸 LF / ^ / 骨架一致 / 行数 / 占位符 / Hzk16 缺字 |

> 四者位于 `I:\LocalGames\Army Men\`，未入 git；如需入库可移到 `Tools\`。

## 部署步骤

1. 确认游戏目录已有 **ASI Loader**：`dinput.dll`
2. 把文件按原相对路径复制到游戏根目录：

   ```
   <游戏目录>\
   ├─ scripts\
   │   ├─ Army4_Extend_Dll.asi    <- 汉化运行库（由 Army4_Extend_Dll 编译）
   │   └─ Hzk16                   <- 中文字库（13×13 点阵）
   ├─ strings\strings.txt         <- 本目录的译文
   ├─ rules\                      <- 本目录的 rules（覆盖同名文件）
   └─ data\                       <- 本目录的 data（覆盖同名文件）
   ```

3. 启动游戏。

## 回滚

译文是**独立文件**，回滚只需从 `Army4_Original` 还原对应文件
（SHA256 见 `Army4_Original\_filehash.csv`）。

## 已知限制与待验证项

- **译文依赖 ASI 运行库**：中文是 GBK 双字节，必须由 `Army4_Extend_Dll.asi`
  接管渲染才能正确显示。若 ASI 未加载，游戏会用 ASCII 图集去画 GBK 字节
  → 文字乱码/花屏。
- `bitmaps\` 里的 65 个 BMP（地图预览、标题画面、BCS 过场图）是**位图烘焙**的
  英文，改 TXT 无效；`Army4_NEW_CHS\bitmaps` 已有一批中文版位图，属独立美术任务。
- `license.txt`（EULA）与 `readme.txt`（说明文档）**未翻译**：非游戏内显示文本，
  与 3 代口径一致。
- `campaign.txt` / `mpmaps.txt` / `bootcamp.txt` **禁止翻译**：里面的
  `map_name`/`folder`/`tileset` 是路径与标识符，翻译会破坏地图加载。
