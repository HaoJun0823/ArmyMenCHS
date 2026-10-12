# 贴图检查归档

导出自 objects.dat（Steam 原版 vs 中文母盘），供人工核对是否为汉化内容。

**对照图说明**：左 = Steam 原版，右 = 中文母盘，中间 8px 灰条分隔。

## 目录

### Alpine
- 差异汇总图：`objects/Alpine/_diff_overview.png`
- 差异逐张（21 张）：`objects/Alpine/diff/`
- 全量 cat44-47（253 张）：`objects/Alpine/all/`

### Bayou
- 差异汇总图：`objects/Bayou/_diff_overview.png`
- 差异逐张（21 张）：`objects/Bayou/diff/`
- 全量 cat44-47（253 张）：`objects/Bayou/all/`

### Desert
- 差异汇总图：`objects/Desert/_diff_overview.png`
- 差异逐张（21 张）：`objects/Desert/diff/`
- 全量 cat44-47（253 张）：`objects/Desert/all/`

## 已核实结论

| 分类 | 数量/地形 | 内容 | 处置 |
|---|---|---|---|
| cat44-47 | 253 个 key，其中 21 个与 Steam 不同 | HUD 面板、按钮文字贴图 | 已选入 Army1_Object_CHS |
| cat17 | 4 个 | 调色板索引 248 颜色不同（美术差异，非文字） | 未选入 |
| cat18 | 16 个 | 尚未展开确认 | 未选入 |

## 重新导出

```bash
python Tools/unpack_objects/export_sprites.py --out Archives \
       --cats 44 45 46 47 --diff      # 只差异
python Tools/unpack_objects/export_sprites.py --out Archives \
       --cats 44 45 46 47 --all       # 全量
```
