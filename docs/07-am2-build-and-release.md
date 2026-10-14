# Army Men II 构建与发布流程

> 2 代的构建、校验、打包、CI。与 1 代的差异在 §1 表格里。
> 1 代流程见 [`03-build-and-release.md`](03-build-and-release.md)。

---

## 1. 与 1 代的差异

| 项 | 1 代 | 2 代 |
|---|---|---|
| 注入代理 | `dsound.dll`（UAL 6.4） | **`dinput.dll`**（UAL，同一份文件改名） |
| 构建入口 | `Tools/ci/ci_build.py` | `Tools/ci/ci_build_am2.py` |
| 打补丁包 | `Tools/ci/make_patch.py` | `Tools/ci/make_patch_am2.py` |
| 产物校验 | `Tools/ci/verify_release.py` | `Tools/ci/verify_release_am2.py` |
| 产物目录 | `build_out` / `stage` | `build_out_am2` / `stage_am2` |
| 资产树 | `Army1_*` | `Army2_*` |
| 载荷目录 | `Army1_NEW_CHS/`（纯载荷） | `Army2_NEW_CHS/`（纯载荷，同构） |
| 文字渲染 | 走 GDI（换字体即可） | **引擎自带点阵，需 hook 4 个函数** |
| 校验器数量 | 4 | **7** |
| exe 是否入库 | 否 | 否（同） |

> ★ 2 代的构建链与 1 代**同构**（这是刻意对齐的）。
> 早期 2 代另起了一套 19 步编排 `build_all_am2.py` + 独立 workflow
> `build-am2.yml`，与 1 代分叉；那套编排已废弃删除。
> 原因：编排层把「维护工具」和「CI 构建」混在一起，且
> `build_new_chs_am2.py` 会**回写** `Army2_NEW_CHS` —— 而同一目录又被
> `build_update_am2.py` 当作人工覆盖层**读入**，输入被输出改写，
> 一旦中间态过期就会静默毁掉手工成果。

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

## 3. 构建：与 1 代同构的三段式

```powershell
# ① 编译 ASI（也可由 CI 用 msvc-wine 编译）
python Tools/ci/build_dll_local_am2.py

# ② 载荷 + 运行期文件 -> build_out_am2
python Tools/ci/ci_build_am2.py --out build_out_am2 --verify

# ③ 打补丁包 -> stage_am2
python Tools/ci/make_patch_am2.py --out stage_am2

# ④ 独立校验产物
python Tools/ci/verify_release_am2.py stage_am2

# ⑤ 部署到本地游戏目录（可选，仅作者本机）
python Tools/ci/deploy_am2.py --from stage_am2
```

任一步失败立即停止，**不做静默容错**。

| 环节 | 脚本 | 输入 → 输出 |
|---|---|---|
| 编译 | `build_dll_local_am2.py` / `compile_dll_wine.py --proj Army2_Extend_Dll` | `src/` → `Release/*.dll` |
| 组装 | `ci_build_am2.py` | `Army2_NEW_CHS/` + `Army2_Extend_Dll/` → `build_out_am2/` |
| 打包 | `make_patch_am2.py` | `build_out_am2/` → `stage_am2/` |
| 校验 | `verify_release_am2.py` | 独立复核 `stage_am2/` |

### 单向数据流（★ 关键设计）

```
Army2_NEW_CHS（人工维护，权威载荷，336 文件，只读）
        │  ci_build_am2.py 整树复制
        ▼
build_out_am2/（游戏原生布局 + dll/ini/Hzk16/strings）
        │  make_patch_am2.py 分流到 scripts\ 与 update\
        ▼
stage_am2/（玩家实际拿到的包）
```

**方向必须单向。** `Army2_NEW_CHS` 是人工成果（手工修的 BMP 等），
任何脚本都不得回写它。早期 `build_new_chs_am2.py` 从 `build_out_am2/update`
+ `stage_am2/scripts` 反向重建 `Army2_NEW_CHS`，而 `Army2_NEW_CHS` 同时
又是 `build_update_am2.py` 的**输入**（人工覆盖层）—— 输入被输出改写，
`build_out` 一旦过期，手工改的图就会被母盘原图静默顶掉。

### 未挂在 CI 上的「维护工具」

下列脚本用于**更新载荷**（从母盘重新推导差异），只在人工维护时跑，
不属于 CI 构建链（与 1 代 `build_new_chs.py` 的定位相同）：

| 脚本 | 作用 |
|---|---|
| `unpack_objects/build_update_am2.py` | 中英母盘逐文件对账，推导差异载荷 |
| `unpack_objects/gen_rules_chs_am2.py` | 生成 `rules/*_desc.txt` 汉化文本 |
| `unpack_objects/add_lost_mp_am2.py` | 补回被 Steam 阉割的多人地图 |
| `unpack_objects/gen_am2_strings_ini.py` 等 | 从 exe 生成/补录译文表 |
| `ci/refresh_asset_manifest_am2.py` | 资产树被有意改动后，重算 `_filehash.csv` |

### CI 与本地的分工

| 步骤 | 需要 `ArmyMen2.exe` | CI 可跑 |
|---|---|---|
| 编译 ASI（msvc-wine） | ❌ | ✅ |
| `verify_assets_am2.py`（资产结构 + sha256） | ❌ | ✅ |
| `ci_build_am2.py` | ❌ | ✅ |
| `make_patch_am2.py` | ❌ | ✅ |
| `verify_release_am2.py`（exe 相关项退化为 WARN） | 部分 | ✅ |
| `build_test_hzk16.py` / `verify_hzk_offset.py` | ❌ | ✅ |
| `verify_strings_cap_am2.py` | ❌ | ✅ |
| `verify_hook_sigs.py` | ✅ | ❌ |
| `verify_globals.py` | ✅ | ❌ |
| `verify_stub_boundary.py` | ✅ | ❌ |
| `verify_codepatch.py` | ✅ | ❌ |
| `gen_am2_strings_ini.py`（逐条对照 exe 原文） | ✅ | ❌ |

> exe 不入库（版权 + 体积），故带 ✅ 的步骤只能在作者本机跑。
> **这些步骤不被静默跳过**：`verify_release_am2.py` 会把 exe 相关项
> 退化为 WARN 并列明，CI 日志里能看到"哪些没覆盖"。

---

## 4. 部署：必须真拷贝 + 回读校验

`Tools/ci/deploy_am2.py`（原 `build_all_am2.py` 的 `DeployToGame()`）：

1. 真 `copyfile`（★ 早期版本这里**只有 print 没有 copy**，白费一轮实测）
2. 每个文件 **sha256 回读校验**
3. 失败即非零退出
4. 目标目录可用 `--scripts` 或环境变量 `AM2_GAME_SCRIPTS` 覆盖

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
│   ├── Hzk16                    # 202,966 B（字库**只此一处**）
│   └── strings/am2_strings.ini
├── update/                      # 336 文件（游戏原生目录布局）
│   ├── 01-title/
│   ├── audio/vos/               # 162 个中文配音 wav
│   ├── avi/                     # 3 部中文配音电影
│   ├── bitmaps/                 # 72 个界面图
│   ├── data/                    # 88 个地图数据/预览
│   ├── rules/                   # 6 个 *_desc.txt
│   └── mpmaps.txt / readme.txt / shared.dat / title.dat
└── dinput.dll                   # UAL（与 1 代同一份 asi/dsound.dll 改名）
```

> ★ 字库**只放一处**（`scripts/Hzk16`）。早期它同时出现在
> `update/Hzk16`、`scripts/Hzk16`、`Army2_NEW_CHS/Hzk16` 三处 ——
> 同一份 200 KB 文件打三遍，现已在 `build_update_am2.py` 的白名单里
> 排除 `hzk16`，由 `ci_build_am2.py` 从 `Army2_CHS/Hzk16` 取一次。

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
| `verify_release_am2.py` | 部分（exe 项退化为 WARN） | ✅ |
| `build_test_hzk16.py` | ❌ | ✅ |
| `verify_hzk_offset.py` | ❌（用仓库内 `Army2_CHS/Hzk16`） | ✅ |
| `build_dll_local_am2.py` | ❌ | ✅（需 MSVC） |
| `build_army2_assets.py` | ❌ | ✅ |
| `ci_build_am2.py` / `make_patch_am2.py` | ❌ | ✅ |
| `verify_assets_am2.py` / `verify_strings_cap_am2.py` | ❌ | ✅ |

因此 workflow 分两层：

| 层 | 内容 | 触发 |
|---|---|---|
| **CI 可跑层** | 编译 2 代 ASI + 资产结构自检 + 组装 + 打包 + 产物独立校验 + 字库判据 + 译文容量 + 文档内链 | 每次 push / PR |
| **本地补足层** | 需要 exe 的 4 个校验器 + 译文表逐条对照 + 部署实测 | 手动，本机执行 |

Workflow：**单一** `.github/workflows/build-release.yml`
（1 代 build → 2 代 build → 合并 publish）。
原独立 workflow `build-am2.yml` 已删除 —— 两代产物挂在同一个 Release
下，分两个 workflow 会导致「1 代成功、2 代失败」时 Release 状态不明。

### 关键设计：不静默跳过

CI 上需要 exe 的步骤跑不了。**处理方式不是静默跳过**，
而是在 `verify_release_am2.py` 的输出里**显式列出未覆盖项**：

```
❌ 以下检查**需要 ArmyMen2.exe**，CI 无法覆盖，须本地执行：
   verify_hook_sigs.py       逐 hook 签名比对
   verify_globals.py         全局量 VA 语义
   verify_stub_boundary.py   逐 hook patchLen 指令边界
   verify_codepatch.py       多字节原文比对
   gen_am2_strings_ini.py    译文表逐条对照 exe 原文
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
[ ] 三段式全绿：build_dll_local_am2 → ci_build_am2 → make_patch_am2 → verify_release_am2
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
[ ] 资产镜像目录含 MANIFEST.md + _filehash.csv
      （Army2_Original / Army2_CHS；Army2_NEW_CHS 是**纯载荷**，不带清单）
```

---

## 相关文档

| 文档 | 内容 |
|---|---|
| [`05-am2-technical-archive.md`](05-am2-technical-archive.md) | 2 代技术档案 |
| [`05-am2-porting-guide.md`](05-am2-porting-guide.md) | 3/4 代移植指南 |
| [`06-am2-pitfalls.md`](06-am2-pitfalls.md) | 2 代踩坑清单 |
| [`03-build-and-release.md`](03-build-and-release.md) | 1 代构建流程 |
