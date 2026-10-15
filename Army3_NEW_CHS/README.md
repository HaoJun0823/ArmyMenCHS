# army3_new_chs —— 《玩具兵大战：太空玩具》简体中文译文

本目录存放 3 代（Army Men: Toys in Space）需要汉化的**文本文件**。

## 结论先行

3 代的可汉化文本**只有 `strings\strings.txt` 这一个文件**，320 行。

| 载体 | 是否需要翻译 | 说明 |
|---|---|---|
| `strings\strings.txt` | **是（本目录唯一产物）** | 全部 UI 文本：兵种/载具/建筑名、多人消息、难度、确认框、武器道具名、错误消息、队伍名 |
| `strings\strings.txt` 第 317 行 | **禁止翻译** | 被 6 处代码当**允许输入的字符集表**消费 |
| `strings\strings.txt` 第 320 行 | **禁止翻译** | 被 `strcmp` 比较（`tina_tomorrow`，开发者彩蛋） |
| `strings\strings.txt` 第 316 行 | 保持原样 | 同属字符集数据表 |
| 11 × `objects.dat` + `shared.dat` | **否** | 纯图像（精灵、图标），零文本 |
| `title.dat` | 需**改图**，不是改文本 | 18 个对话框面板标题栏 + 640×480 标题画面的英文与版权声明是**位图烘焙**的，改 TXT 无效；属独立美术任务 |
| `campaign.txt` / `mpmaps.txt` / `bootcamp.txt` | **禁止翻译** | 里面的 `map_name`/`folder`/`tileset` 是**路径与标识符**，翻译会破坏地图加载；只有 `map_text` 列是显示名 |

## 产物

```
army3_new_chs\
├─ strings\strings.txt      中文译文（GBK / CRLF / 320 行 / 无 BOM）
├─ rules\                   联机规则：10 个 *_desc.txt 说明 + 9 个机制文件的 showmessage
└─ data\                    15 个关卡脚本的 showpda / showfailure / showmessage
```

## 本轮新增（rules / data）

3 代无官方中文母盘，`strings.txt` 之外还有一批脚本内显示文本，本轮一并汉化。

| 目录 | 文件数 | 内容 |
|---|---|---|
| `rules\*_desc.txt` | 10 | 联机模式的玩法说明（`mpmaps.txt` 的 `rules_description_file` 列指向它们） |
| `rules\` 机制文件 | 9 | `death_common` `ffire` `caf` `ctf_common` `holdflag_common` `killer` `it` `koth` `node_common` 的 `showmessage` 联机播报 |
| `data\` 关卡脚本 | 15 | 任务 PDA、失败提示与阶段性播报 |

### 两个关键约束（改动时必须守住）

1. **颜色实参必须跟着汉化**：`rules` 里 `expand` 的第二个参数是显示用颜色名，
   原文形如 `expand koth_macro ( green "Green" 1 ... )`。只译 `showmessage`
   模板而留着 `"Green"`，会渲染出「绿队 is king of the hill」这类中英混拼。
   本轮已统一改为 `绿队 / 棕队 / 蓝队 / 灰队`（与 `strings.txt` 第 302-305 行一致）。
2. **只碰引号内的字符串**：指令名、缩进（含 TAB）、逗号、`@N` 占位符、
   `playsound` 文件名一律保持原样。校验脚本用「骨架比对」逐字节确认了这一点。

### 译文规格（全部已自动校验）

- **GBK**、**CRLF**、**无 BOM**，与 `Army2_NEW_CHS` 既有译文一致
- 逐行保留 `@N` 占位符及其**顺序**（`@2` 是颜色名，`@3`/`@4` 是敌方颜色/节点号）
- 无 TAB 变动、无 `^`（`^` 是渲染器的颜色转义符，会吃掉后一个字符）
- 关卡脚本**行数严格对齐**原文；`*_desc.txt` 允许压缩行数（2 代先例如此）
- 译文用到的 **48 个汉字**全部在 `Hzk16` 字库中有点阵（用 DLL 的官方公式
  `idx = trail + 94*lead - 15295; off = bpg*idx - 9688` 逐字验证，零缺字）

### 校验脚本

| 脚本 | 作用 |
|---|---|
| `Tools/verify_army3_assets.py` | 基线资产校验（原有） |
| `_am3_verify_final.py` | rules+data 结构校验：编码 / CRLF / BOM / 骨架一致 / 行数 / 占位符 |
| `_am3_verify_font.py` | Hzk16 缺字校验（官方公式 + DLL 自检表交叉验证） |
| `_am3_trans_data.py` | data 关卡脚本的译文映射表（幂等，可重复执行） |

> 三者位于 `I:\LocalGames\Army Men\`，未入 git；如需入库可移到 `Tools\`。

## 译文规格（全部已自动校验）

- **320 行**，与原文行数严格相同（游戏要求 ≥320 且数组容量恰为 320，多一行会溢出）
- **GBK 编码**、**CRLF 换行**、**无 BOM**，与游戏原文件格式一致
- 逐行保留 `%s` `%d` `%3d` 等格式说明符及其**顺序**
- 无 TAB；译文行内不含 `^`（`^` 是渲染器的颜色转义符，会吃掉后一个字符）
- 最长行 102 字节（`fgets(Buffer,512)` 上限 510，安全）
- 第 189 行保持**空行**（它同样占一个字符串槽位）
- 全部 292 个待用汉字均已确认存在于 `Hzk16` 字库且有笔画（零缺字）

## 部署步骤

1. 确认游戏目录已有 **ASI Loader**：`dinput.dll`
   （本作按名字导入 `dinput.dll!DirectInputCreateA`，代理加载器可正常工作）
2. 把文件放到游戏根目录：

   ```
   <游戏目录>\
   ├─ scripts\
   │   ├─ Army3_Extend_Dll.asi    <- 汉化运行库（由 Army3_Extend_Dll 编译）
   │   └─ Hzk16                   <- 中文字库（13×13 点阵）
   └─ strings\
       └─ strings.txt             <- 本目录的译文（覆盖原文件）
   ```

3. 启动游戏。日志写入 `scripts\ArmyMenTISCHS.log`。

## 回滚

译文是**独立文件**，回滚只需还原 `strings\strings.txt`：

```
python Tools\restore_am3_english.py
```

英文原文已备份在 `Army3_Original\strings\strings.txt`（SHA256 与游戏原文件一致）。

## 已知限制与待验证项

- **译文依赖 ASI 运行库**：中文是 GBK 双字节，必须由 `Army3_Extend_Dll.asi`
  接管渲染才能正确显示。若 ASI 未加载，游戏会用 ASCII 图集去画 GBK 字节
  → 文字乱码/花屏。此时请先查 `scripts\ArmyMenTISCHS.log` 是否生成。
- `title.dat` 里的英文（对话框面板标题、标题画面版权声明）**仍是英文**，
  需另行重绘位图。
- `amtisged.dll`（多人设置配置器，独立程序）有自己的 UI 字符串，
  **未纳入本次汉化**。
- 首次实机建议重点观察：居中菜单的行距（CENTER 纵向步进沿用 2 代的「高−3」推断值）
  与长文本换行位置。
