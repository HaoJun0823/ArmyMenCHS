# Army Men II 构建与发布流程

> 2 代的构建、校验、打包、CI。与 1 代的差异在 §1 表格里。
> 1 代流程见 [`03-build-and-release.md`](03-build-and-release.md)。

---

## 1. 与 1 代的差异

| 项 | 1 代 | 2 代 |
|---|---|---|
| 注入代理 | `dsound.dll`（UAL 6.4） | **`dinput.dll`**（UAL 9.0.0） |
| 产物目录 | `build_out` / `stage` | `build_out_am2` / `stage_am2` |
| 资产树 | `Army1_*` | `Army2_*` |
| 一键构建 | 多脚本手工串联 | **`build_all_am2.py` 17 步** |
| 文字渲染 | 走 GDI（换字体即可） | **引擎自带点阵，需 hook 4 个函数** |
| 校验器数量 | 4 | **7** |
| exe 是否入库 | 否 | 否（同） |

---

## 2. 工具链要求

### 本地（Windows）

| 组件 | 版本 | 说明 |
|---|---|---|
| MSVC | v141 `14.16.27023` | 与 1 代一致 |
| Windows SDK | `10.0.26100.0` | |
| Python | 3.x | |
| capstone | 最新 | 指令边界反汇编校验 |
| Pillow | 12.x | BMP 对比（可选） |

### CI（Linux）

`ubuntu-latest` + `msvc-wine` + MSVC v141，与 1 代同一套装配流程
（见 `.github/workflows/build-release.yml` 的注释，含"`--major 15` 是关键"
等经验）。

---

## 3. 一键构建：19 步

```powershell
python Tools/ci/build_all_am2.py
python Tools/ci/build_all_am2.py --skip-movies   # 不打包 123 MB 电影
```

任一步失败立即停止，**不做静默容错**。

| # | 步骤 | 作用 | 需要 exe |
|---|---|---|---|
| ① | 资产对账与差异打包 | 中英母盘逐文件 sha256 → `build_out_am2/update` | 否 |
| ①b | 生成 rules 汉化文本 | 6 个 `*_desc.txt` | 否 |
| ①c | 补回被移除的多人地图 | 6 张图 + 36 条 RULEMAP | 否 |
| ② | 编译 ASI 模块 | 断言 32 位 PE + 3 个导出 | 否 |
| ③ | 字库离线自测 | 13×13 几何 + 墨迹量 | 否 |
| **③b** | **校验字形偏移公式** | **全角 ASCII 判据（见 §5）** | 否 |
| **③c** | **资产结构与 sha256** | **防 autocrlf 改写 + MANIFEST 不符** | 否 |
| **③d** | **译文表容量自检** | **防中文超出槽容量 + 占位符不匹配** | 否 |
| ④ | 校验 hook 签名 | 4 个 hook 逐字节比对 | ✅ |
| ④b | 校验全局量 VA | 14 项地址语义 | ✅ |
| ④c | 校验 stub 边界 | 逐 hook patchLen 是否在指令边界 | ✅ |
| ④d | 校验代码补丁 | 多字节原文比对 | ✅ |
| ⑤ | 生成译文表 | 词典硬闸门 + 逐条容量校验 | ✅ |
| ⑤b | 补录难度三项 | | ✅ |
| ⑤c | 补录人工译文 | | ✅ |
| ⑤d | 补录单位名称 | | ✅ |
| ⑤e | 补录通讯消息 | | ✅ |
| ⑥ | 组装 stage | | 否 |
| ⑦ | 独立校验产物 | **独立实现**，不复用生成侧代码 | ✅ |

构建成功后**自动部署**到游戏目录（`scripts\{asi,ini,Hzk16}`）。

> ★ 带 ✅ 的步骤 CI 上跑不了（exe 不入库），必须在本地构建。
> ③b/③c/③d 三步是特意设计成**不依赖 exe** 的，好让 CI 有实际门禁可跑。

---

## 4. 部署：必须真拷贝 + 回读校验

`build_all_am2.py` 的 `DeployToGame()`：

1. 真 `copyfile`（★ 早期版本这里**只有 print 没有 copy**，白费一轮实测）
2. 每个文件 **sha256 回读校验**
3. 失败即非零退出
4. 目标目录可用环境变量 `AM2_GAME_SCRIPTS` 覆盖

### 幂等性

PE 的 `TimeDateStamp` 每次链接都变，且它在 `.rdata` 有一份**内联副本**。
逐字节对比两次构建：全文件仅 **4 字节**不同（PE 头 `+8`、
文件偏移 `0x2E7F4`）。比较前需把这两处抹平（`_norm_pe_hash`），
否则每次都报"已更新"，真正的改动被噪声淹没。

**双向验证**（已实测）：
- 连续两次构建 → 三次都报"已是最新（内容一致）"
- 篡改部署文件一个字节 → 能检出并修复

---

## 5. 校验器设计原则（★ 重要）

本项目校验器自己失效过 **4 次**，全部是"假绿"：

| 失效方式 | 修法 |
|---|---|
| 白名单过滤 → 新 hook 被静默忽略 | 按档位解析 + 断言覆盖度 |
| 硬编码条目数 → 新增项没查 | 从源码解析实际条目 |
| 累计到阈值就停 → 假红 | 反汇编完整窗口 |
| 解析正则不匹配 → 匹配 0 条 | 断言"检查数 > 0" |

**硬性要求**：

1. 报出**实际检查的条目数**
2. **断言覆盖度**（期望类别必须都被查到）
3. 空转即失败（`raise SystemExit(1)`）
4. 尽量让测试**能区分正误**

### 第 4 条的例子：`verify_hzk_offset.py`

它验证 Hzk16 字形偏移公式，用**不可混淆**的判据
（全角 ASCII `ＡＢＣＤＥＦ` / `０１２３`，形状与半角字母一致），
并**自证区分力**：

```
字库共 202940 个可能偏移；同时命中 10 个指纹之一的占 1456 个 = 0.717%
OK：误通过率 0.717% —— 判据具备区分力
```

为什么需要这个：同一个问题被误判过两次（目视把噪声当字形、
推导出"缺 dataStart"），两次都是判据太弱。

---

## 6. 产物布局

```
stage_am2/
├── scripts/
│   ├── Army2_Extend_Dll.asi     # 208–210 KB
│   ├── ArmyMenCHS.ini           # 译文表（92 条）
│   └── Hzk16                    # 202,966 B
├── update/                      # 336 文件（游戏原生目录布局）
│   ├── 01-title/
│   ├── audio/vos/               # 162 个中文配音 wav
│   ├── bitmaps/                 # 95 张界面图
│   ├── data/                    # 多人地图预览
│   ├── rules/                   # 6 个 *_desc.txt
│   ├── shared.dat / title.dat   # 中文 UI 精灵
│   ├── hzk16 / mpmaps.txt / readme.txt
└── dinput.dll                   # UAL 9.0.0
```

### UAL 的 `update\` 机制

游戏根目录下 `update\` 存在即生效，**无需 `global.ini`**（1 代实机验证）。

---

## 7. CI 能做什么、不能做什么

**关键约束**：仓库里的 `Army2_Original` / `Army2_CHS` **不含 exe**
（与 1 代一致，exe 不入库）。而多个校验器需要 exe。

| 脚本 | 需要 exe | CI 可跑 |
|---|---|---|
| `verify_hook_sigs.py` | ✅ | ❌ |
| `verify_stub_boundary.py` | ✅ | ❌ |
| `verify_globals.py` | ✅ | ❌ |
| `verify_codepatch.py` | ✅ | ❌ |
| `gen_am2_strings_ini.py` | ✅ | ❌ |
| `verify_release_am2.py` | ✅ | ❌ |
| `build_test_hzk16.py` | ❌ | ✅ |
| `verify_hzk_offset.py` | ❌（用仓库内 `Army2_CHS/Hzk16`） | ✅ |
| `build_dll_local_am2.py` | ❌ | ✅（需 MSVC） |
| `build_army2_assets.py` | ❌ | ✅ |

因此 workflow 分两层：

| 层 | 内容 | 触发 |
|---|---|---|
| **CI 可跑层** | 编译 DLL + 字库判据 + 资产结构自检 + 译文表容量自检 + 文档内链 | 每次 push / PR |
| **发布层** | 完整 19 步 + 打包（需 exe） | 手动 `workflow_dispatch`，由本地执行 |

Workflow：`.github/workflows/build-am2.yml`（2 代）+ `build-release.yml`（1 代）。

### 关键设计：不静默跳过

CI 上 6 个需要 exe 的步骤跑不了。**处理方式不是静默跳过**，
而是在最后一步**显式列出未覆盖项**：

```
❌ 以下步骤**需要 ArmyMen2.exe**，CI 无法覆盖，须本地构建：
   verify_hook_sigs.py       逐 hook 签名比对
   ...
   本地跑： python Tools/ci/build_all_am2.py
```

否则读者会以为 CI 覆盖了全部校验 —— 那正是本项目
"校验器空转报绿"的同类错误（见 §5）。

### 三个新门禁脚本

| 脚本 | 防什么 | 反向验证 |
|---|---|---|
| `verify_assets_am2.py` | 资产被 autocrlf 改写 / MANIFEST 与实际不符 | 篡改 1 字节 → 报 `sha256 不符` ✅ |
| `verify_strings_cap_am2.py` | 中文超出槽容量 / 占位符不匹配 / 重复键冲突 | 注入超容量译名 → 报 `需 9 B，槽 6 B` ✅ |
| `verify_doc_links.py` | 改文件名留下死链 | 插入死链 → 报 `死链 1 个` ✅ |

三者都**实测反向验证通过**（先证明能发现错误，再相信它能通过）。

> ★ 为什么不把 exe 放进仓库：版权与体积（585 KB 不贵，但会引出
> "仓库里放商业 exe"的合规问题）。1 代同样是排除了 exe 的。

---

## 8. 发布前检查清单

```
[ ] build_all_am2.py 17 步全绿
[ ] 部署后日志确认：
      · Detect 选中正确档位 + 4 个 hook 签名一致
      · 渲染环境自检通过（14 项）
      · hook 成功 4 个，失败 0 个
      · strings: applied=92 skipped=0 mismatch=0
      · codepatch 已应用
[ ] 实机验证：
      · 主菜单 / 对话框 / 任务简报 文字正常
      · 反复进出简报窗口 无花屏
      · 中文配音可播
[ ] 全部校验器都能报出检查条目数（非空转）
[ ] git 提交前全量 blob 保真校验
[ ] 资产目录含 MANIFEST.md + _filehash.csv
```

---

## 相关文档

| 文档 | 内容 |
|---|---|
| [`05-am2-technical-archive.md`](05-am2-technical-archive.md) | 2 代技术档案 |
| [`05-am2-porting-guide.md`](05-am2-porting-guide.md) | 3/4 代移植指南 |
| [`06-am2-pitfalls.md`](06-am2-pitfalls.md) | 2 代踩坑清单 |
| [`03-build-and-release.md`](03-build-and-release.md) | 1 代构建流程 |
