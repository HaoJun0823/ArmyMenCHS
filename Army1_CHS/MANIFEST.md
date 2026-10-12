# Army1_CHS — 中文母盘本地化资产清单

> 源盘：`J:\`（1998 上海育碧简体中文零售版）
> 基线对照：`Army1_Original\`（Steam 2K/Zoom 重发行版 v1.2）
> 生成方式：全量 sha256，详见 `_filehash.csv`

## 总量

| 项 | 值 |
|---|---|
| 文件数 | 593 |
| 总体积 | 248.7 MB |
| 单文件最大 | 24.2 MB (`video\final.smk`) |
| Git LFS | **不需要** |

## 目录结构

```
Army1_CHS\
├─ video\      16 个 .smk        143.5 MB
├─ audio\       4 个 (.asd/.ast)  19.9 MB
├─ text\
│   ├─ campaigns\  2 个 .cpn
│   └─ maps\      72 个 (.rul/.txt)
├─ ui\
│   ├─ Screens\  308 .BMP (根43 + Briefs138 + blue31 + green34 + grey31 + tan31)
│   └─ Stratmap\  20 .bmp
├─ maps\Maps\  149 个 (.AMM 18 / .ATL 18 / .BMP 41 / .rul 20 / .txt 52)
└─ terrain\
    ├─ Alpine\  ┐
    ├─ Bayou\   ├─ objects.dat + final_pal.bmp + explosions.axs + AiDefault.aai
    └─ Desert\  ┘  + Misc\ Units\ Vehicles\ ；src\ 与 raw_assets\ 预留给 unpack/pack
```

## 本地化状态（与 Steam 基线逐文件 sha256 比对结果）

### texture — 需本地化 147 项

| 位置 | 总数 | 与 Steam 不同 | 判据 |
|---|---|---|---|
| `ui\Screens\Briefs\` | 138 | **135** | `As3m1.BMP` 抽帧：中文完整简报文 vs 英文 |
| `ui\Screens\`(根) | 43 | **12** | `alp_load`/`bay_load`/`des_load`/`multihost`/`multiremote`/`Title_legal`/`title2`/`stard_*`/`Exit*`/`Scroll*` |
| `ui\Screens\{blue,green,grey,tan}` | 127 | **0** | 纯按钮底图，无文字，两侧完全一致 |
| `ui\Stratmap\` | 20 | **0** | 战略图，两侧一致 |
| `maps\Maps\*.BMP` | 41 | **27** | `Alpine3_1.BMP` 抽帧：中文烧入"绿军基地/伤员/出口" vs "GREEN BASE/INJURED MEN/OUT" |

### map — 地图数据全量收录（本地化强绑定）

| 类型 | 总数 | 说明 |
|---|---|---|
| `.AMM` | 18 | 关卡几何，两侧**字节相同**，作为地图 mod 基线收录 |
| `.ATL` | 18 | 图集，两侧**字节相同**，同上 |
| `.BMP` | 41 | 地图底图，27 个含中文标注 |
| `.rul` | 20 | 多人任务脚本，全部含目标文字 |
| `.txt` | 52 | 帧/配置数据；`blitz_1.txt`、`mheader_1.txt` 含 `SHOWMESSAGE` 中文字串 |

> 用户决策：地图内容**全量收录**（含与 Steam 相同的 AMM/ATL），供未来玩家地图 mod 使用。

### data — 需本地化 4 项

| 文件 | 与 Steam | 说明 |
|---|---|---|
| `text\campaigns\Campaign.cpn` | **不同** | 28 关 MISSION TITLE 全中文（含 Alpine3"弃物和残骸/套叠轨道/迂回作战"） |
| `text\campaigns\BootCamp.cpn` | 相同 | 新兵训练营，无需处理 |
| `terrain\Alpine\objects.dat` | **不同** | 中文版 +1108 B，目录表键集合一致，差异在调色板/精灵像素 |
| `terrain\Bayou\objects.dat` | **不同** | 字节数相同但 hash 不同 |
| `terrain\Desert\objects.dat` | **不同** | 字节数相同但 hash 不同 |
| `final_pal.bmp` / `explosions.axs` / `AiDefault.aai` | 相同 | ×3 地形，无需处理 |

### audio — 需收录 3 项

| 文件 | 与 Steam | 说明 |
|---|---|---|
| `voices.ast` | **不同** | 配音文本表（`VTXT` 块，GBK 可读："他在那儿！""我是中士，请求空投伞兵。完毕。"） |
| `voices.asd` | **不同** | **中文配音**（用户确认） |
| `sounds.asd` | **不同** | **中文音效/配音**（用户确认） |
| `streams.asd` | 相同 | 音乐流，未本地化 |

### video — 真汉化 10 / 未汉化 6

| 文件 | 判定 | 证据 |
|---|---|---|
| `intro.smk` | **含中文** | 640×480；同帧"绿军最新新闻/前进！前进！" vs "GREEN PLASTIC NEWS" |
| `IntroSml.smk` | **含中文** | 320×240 小版，同上 |
| `lose1.smk` ~ `lose4.smk` | **含中文** | 同画面"你完蛋了" vs "you lose"；4 种场景 |
| `lose1Sml` ~ `lose4Sml.smk` | **含中文** | 320×240 小版，同上 |
| `credits.smk` / `creditsSml.smk` | 未汉化 | sha 与 Steam 完全相同 |
| `logo20.smk` / `logo20Sml.smk` | 未汉化 | sha 与 Steam 完全相同 |
| `final.smk` / `FinalSml.smk` | 未汉化 | **同片重压版**：时长 86.8s / 640×400 一致，帧内容同为英文片尾字幕 |

> 判据说明：视频不能只看 sha。中文母盘 `.smk` 普遍比 Steam 小（低码率重编码），
> 但 `final.smk` 是"同片不同码率"而非汉化版，已用逐帧抽图纠正。

## 未收录（按用户指令）

- `Armymen.exe` / `ARMYMEN.ICO` / `*.DLL` / `*.cfg` / `cursor.bmp` / `Manual.pdf` / `ReadMe.txt`
- `Armymen.exe.i64`（IDA 数据库，会话分析产物）
- InstallShield 安装器残留：`_sys1.cab`、`data1.cab`、`setup.ins`、`lang.dat`、`AUTORUN.*`、`Directx\`、`M59\`、`MPLAYNOW\`
- Steam 独有 `videos\Revenant.avi`、`Soulreaver.avi`（3DO 其他游戏广告，非本作内容）

## 已知缺陷（待用源码修复）

| 缺陷 | 定位 | 现状 |
|---|---|---|
| Alpine3 吉普卡油桶 | `SCENARIO 01007 "羊肠河"` → `MISSION 00014/15/16` → `MAPFILE Alpine3` | `alpine3.AMM` 中英**字节相同** → 原始关卡数据缺陷，非汉化引入 |
| Alpine3 UI 未汉化 | `Screens\Briefs\As3m1/2/3.BMP` | 中文母盘**已汉化**（简报图 + 地图标注 + Campaign.cpn 三线齐全），需确认原补丁为何未覆盖 |
