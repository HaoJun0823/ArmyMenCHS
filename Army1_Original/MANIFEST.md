# Army1_Original — Steam 英文基线

> 源：`I:\LocalGames\Army Men\Army Men I STEAM\`（2K / Zoom Platform 重发行版，v1.2）
> 用途：本地化对照基线 + 地图 mod 基底
> 详见 `_filehash.csv`（全量 sha256）

## 总量

| 项 | 值 |
|---|---|
| 文件数 | 594（比 CHS 多 1：Steam `AVI\greyscale.BMP`，非视频未收录于 CHS） |
| 总体积 | 312.7 MB |
| 单文件最大 | 43.6 MB (`video\IntroSml.smk`) |

## 与 Army1_CHS 的差异汇总（即"待本地化项"）

判定方法：`Army1_CHS` 同路径文件 sha256 比对 + 抽样抽帧/读文本确认。

| 类别 | 位置 | 不同 / 总 | 处理 |
|---|---|---|---|
| texture | `ui\Screens\Briefs\` | 135 / 138 | 需替换为中文 |
| texture | `ui\Screens\`(根) | 12 / 43 | 需替换 |
| texture | `ui\Screens\{blue,green,grey,tan}` | 0 / 127 | 无需 |
| texture | `ui\Stratmap\` | 0 / 20 | 无需 |
| texture | `maps\Maps\*.BMP` | 27 / 41 | 需替换（含地图内中文标注） |
| map | `maps\Maps\*.rul` | 20 / 20 | 需替换 |
| map | `maps\Maps\*.txt` | 2 / 52 | 需替换（`blitz_1.txt`、`mheader_1.txt`） |
| map | `maps\Maps\*.AMM` / `*.ATL` | 0 / 36 | 无需（几何数据） |
| data | `text\campaigns\Campaign.cpn` | 1 / 1 | 需替换（28 关标题） |
| data | `text\campaigns\BootCamp.cpn` | 0 / 1 | 无需 |
| data | `terrain\*\objects.dat` | 3 / 3 | 需替换（三地形全部不同） |
| audio | `voices.ast` | 1 | 需替换（配音文本表） |
| audio | `voices.asd` / `sounds.asd` | 2 | 需替换（中文配音，用户确认） |
| audio | `streams.asd` | 0 | 无需 |
| video | `AVI\*.smk` | 10 / 16 真汉化 | 需替换 `intro`/`IntroSml`/`lose1-4`/`lose1-4Sml` |
| video | `creditss`/`logo20s` smk | 0 / 4 | 无需 |
| video | `final`/`FinalSml.smk` | 0 / 2 | 无需（同片重压版） |

## 未收录

- `Armymen.exe`（993280 B，v0.1.2.0）、`ARMYMEN.ICO`、`*.DLL`、`*.cfg`、`cursor.bmp`
- `Armymen.exe.i64`（IDA 数据库，会话产物，非游戏资产）
- `Manual.pdf` / `ReadMe.txt`（英文文档）
- `videos\Revenant.avi` / `Soulreaver.avi`（3DO 其他游戏广告）
- `SaveGames\`（空目录）

## 复现本地化的最小替换集

把 `Army1_CHS` 中下列内容覆盖到 Steam 安装目录即可复现 1998 中文版：

```
text\campaigns\Campaign.cpn      → Campaigns\
text\maps\*.rul, *.txt           → Maps\
ui\Screens\**                    → Screens\
ui\Stratmap\**                   → Stratmap\
maps\Maps\**                     → Maps\
terrain\{Alpine,Bayou,Desert}\objects.dat → 对应地形目录
audio\*                          → Audio\
video\*.smk                      → AVI\
```

> 注意：`Armymen.exe` 不在替换集中。中文版 exe（v0.1.0.0，742912 B）含 GBK 界面字符串
> 与宋体字体切换逻辑；直接替换 Steam v0.1.2.0 会丢失新版内容。
> 原补丁（凱風）采用"中文 exe + 无 CD 破解"方案，代价是 Steam 新增内容不可用。
> 本项目的目标是**用源码重编一个既支持中文又保留 v1.2 内容的 exe**，尚未实施。
