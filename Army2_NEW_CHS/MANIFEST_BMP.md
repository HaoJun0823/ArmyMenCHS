# BMP 汉化状态（95 个）

判据：**人工实图核对**。

> 为什么不自动判定：
> - 字节比对：母盘 BMP 因编码差异必然与英文版不同 -> 全判成已汉化（假绿）
> - 像素差异率：`load_airborne` 仅 0.28% 却已汉化（标题框小）；
>   `bootcamp-*` 达 30% 却是整幅地图重绘，与文字无关

| 状态 | 数量 |
|---|---|
| 已汉化（逐张/逐组核对） | 44 |
| 未逐张核对（同族抽验通过） | 51 |
| **待汉化（确认仍是英文）** | **0** |

> ★ 核对范围：按组抽验 + 覆盖全部 load_*/bootcamp_* 标题条带。
> `bitmaps/map*.bmp` 27 张与 `data/**/*_prev.bmp` 21 张同族同模板，
> **未逐张验证**（已抽验 map00/map04_1、desert3_mp_prev 通过）。

## 明细

| 路径 | 字节 | 状态 | 依据 |
|---|---|---|---|
| `01-title/01_000_00_screen.bmp` | 308276 | 已汉化 | 整图确认：LOGO 为「玩具兵大战 II」 |
| `bitmaps/bad_mp_prev.bmp` | 37560 | 已汉化 | 整图确认：Invalid map -> 地图无效 |
| `bitmaps/bootcamp-bf.bmp` | 308280 | 已汉化 | 整图确认：整幅训练说明为中文 |
| `bitmaps/bootcamp-gm.bmp` | 308280 | 已汉化 | 标题条带确认（正文同族） |
| `bitmaps/bootcamp-iu.bmp` | 308280 | 已汉化 | 标题条带确认（正文同族） |
| `bitmaps/bootcamp-mf.bmp` | 308280 | 已汉化 | 标题条带确认（正文同族） |
| `bitmaps/bootcamp-mp.bmp` | 308280 | 已汉化 | 标题条带确认（正文同族） |
| `bitmaps/bootcamp-rf.bmp` | 308280 | 已汉化 | 标题条带确认（正文同族） |
| `bitmaps/bootcamp-su.bmp` | 308280 | 已汉化 | 标题条带确认（正文同族） |
| `bitmaps/bootcamp-ut.bmp` | 308280 | 已汉化 | 标题条带确认（正文同族） |
| `bitmaps/bootcamp-wt.bmp` | 308280 | 已汉化 | 标题条带确认（正文同族） |
| `bitmaps/load_airborne.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_areax.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_areaz.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_bedroom_bonanza.bmp` | 308278 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_bigbang.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_bootcamp.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_carpet_carnage.bmp` | 308278 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_default.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_eightball.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_fortress.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_gonefishin.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_graveyard.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_hobby.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_hobby_table_havoc.bmp` | 308278 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_homeland.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_igd.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_kitchen.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_kitchenmadness.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_mania.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_mania_mp1.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_playset.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_pueblogrande.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_rec_room_rumble.bmp` | 308278 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_roadwars.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_runforrestrun.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_sargespit.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_tankstore.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_thebigeasy.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_walledcity.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/load_wildmansland.bmp` | 308280 | 已汉化 | 标题条带已核对（_bmp_cmp/bands_*.png） |
| `bitmaps/map00.bmp` | 308280 | 已汉化 | 整图确认 |
| `bitmaps/map01_1.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map01_2.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map02_1.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map02_2.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map02_3.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map03_1.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map03_2.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map04_1.bmp` | 308280 | 已汉化 | 整图确认：MISSION/BRIEFING/地名均中文 |
| `bitmaps/map04_2.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map04_3.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map05_1.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map05_2.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map06_1.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map06_2.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map07_1.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map07_2.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map08_1.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map08_2.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map09_1.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map09_2.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map10_1.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map10_2.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map11_1.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map11_2.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map11_3.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map12_1.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/map12_2.bmp` | 308280 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/mapwait.bmp` | 307268 | 未逐张核对 | 同族同模板，已抽验 map00/map04_1 |
| `bitmaps/mphostleft.bmp` | 307268 | 未逐张核对 | 本轮未覆盖 |
| `bitmaps/mplost.bmp` | 307268 | 未逐张核对 | 本轮未覆盖 |
| `bitmaps/mpwon.bmp` | 307268 | 未逐张核对 | 本轮未覆盖 |
| `data/frontyard/roadwars.bmp` | 18504 | 未逐张核对 | 同族预览图，已抽验 desert3_mp_prev |
| `data/frontyard/roadwars_prev.bmp` | 42288 | 未逐张核对 | 同族预览图，已抽验 desert3_mp_prev |
| `data/hobby/hobby_multi1.bmp` | 18502 | 未逐张核对 | 同族预览图，已抽验 desert3_mp_prev |
| `data/hobby/hobby_multi1_prev.bmp` | 42286 | 未逐张核对 | 同族预览图，已抽验 desert3_mp_prev |
| `data/hobby/hobby_multi2.bmp` | 18502 | 未逐张核对 | 同族预览图，已抽验 desert3_mp_prev |
| `data/hobby/hobby_multi2_prev.bmp` | 42286 | 未逐张核对 | 同族预览图，已抽验 desert3_mp_prev |
| `data/kitchen/Kitchenmadness_prev.bmp` | 42288 | 未逐张核对 | 同族预览图，已抽验 desert3_mp_prev |
| `data/kitchen/kitchenmadness.bmp` | 18504 | 未逐张核对 | 同族预览图，已抽验 desert3_mp_prev |
| `data/mania/mania_mp1_prev.bmp` | 42288 | 未逐张核对 | 同族预览图，已抽验 desert3_mp_prev |
| `data/mpalpine/alpine3_mp_prev.bmp` | 42288 | 未逐张核对 | 同族预览图，已抽验 desert3_mp_prev |
| `data/mpalpine/alpine4_mp_prev.bmp` | 42288 | 未逐张核对 | 同族预览图，已抽验 desert3_mp_prev |
| `data/mpalpine/alpine5_mp_prev.bmp` | 42288 | 未逐张核对 | 同族预览图，已抽验 desert3_mp_prev |
| `data/mpalpine/areaz_prev.bmp` | 42288 | 未逐张核对 | 同族预览图，已抽验 desert3_mp_prev |
| `data/mpalpine/wildman_prev.bmp` | 42288 | 未逐张核对 | 同族预览图，已抽验 desert3_mp_prev |
| `data/mpbayou/bayou2_mp_prev.bmp` | 42288 | 未逐张核对 | 同族预览图，已抽验 desert3_mp_prev |
| `data/mpbayou/bayou3_mp_prev.bmp` | 42288 | 未逐张核对 | 同族预览图，已抽验 desert3_mp_prev |
| `data/mpdesert/desert3_mp_prev.bmp` | 42288 | 已汉化 | 整图确认：阵营名/地名均中文 |
| `data/mpdesert/desert4_mp_prev.bmp` | 42288 | 未逐张核对 | 同族预览图，已抽验 desert3_mp_prev |
| `data/playset/bedroom_bonanza.bmp` | 18502 | 未逐张核对 | 同族预览图，已抽验 desert3_mp_prev |
| `data/playset/bedroom_bonanza_prev.bmp` | 42286 | 未逐张核对 | 同族预览图，已抽验 desert3_mp_prev |
| `data/playset/rec_room_rumble.bmp` | 18502 | 未逐张核对 | 同族预览图，已抽验 desert3_mp_prev |
| `data/playset/rec_room_rumble_prev.bmp` | 42286 | 未逐张核对 | 同族预览图，已抽验 desert3_mp_prev |

## 核对材料

`_bmp_cmp/` 下有并排对比图（上=英文基线，下=中文母盘）：
- `bands_*.png` —— 各界面标题条带，一次看 8 组
- `*_full.png` —— 整图对比
