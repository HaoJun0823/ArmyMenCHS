# 构建与发布流程

> 覆盖：本地构建、CI 构建、打包、发布、校验。
> 2/3/4 代移植时，本文的**流程骨架可照搬**，具体路径与校验项需调整。

---

## 1. 工具链要求

### 本地（Windows）

| 项 | 版本 | 说明 |
|---|---|---|
| Visual Studio | **2017**（MSVC 14.16 / v141） | 与历史产物一致；只用 `cl.exe`/`link.exe`，不需要 MSBuild |
| Windows SDK | **10.0.26100.0** | |
| Python | 3.14（3.8+ 即可） | 脚本只用标准库 + Pillow |

### CI（Linux）

| 项 | 版本 |
|---|---|
| Runner | `ubuntu-latest` |
| 交叉编译 | `mstorsjo/msvc-wine` |
| MSVC | **15.9 / v141**（`vsdownload --major 15`） |
| 架构 | **x86 + x64 都要下载** |

> **x64 也必须下载。** 原因：`Hostx64\x86\cl.exe` 启动时要按 PATH 找
> `mspdbcore.dll`，而该文件只在 `Hostx64\x64` 下。只装 x86 会报
> `fatal error C1356: unable to find mspdbcore.dll`。

---

## 2. 完整构建流程

```
① build_dll_local.py        本地编译 DLL（Windows）
   或 compile_dll_wine.py   CI 编译 DLL（Linux）
        │  产出 Army1_Extend_Dll/Release/Army1_Extend_Dll.dll
        ▼
② ci_build.py --out build_out --verify
        │  ① 复制 Army1_NEW_CHS/* → build_out/
        │  ② pack_diff.py 以 Steam objects.dat 为基底 + 差异块 → 三地形 objects.dat
        │  ③ 复制 DLL / ini / strings
        ▼  build_out/  （平铺的中间目录）
③ make_patch.py --out stage
        │  组装成"可解压到游戏根目录"的最终布局，
        │  加入 dsound.dll / LICENSE / License.txt / 安装说明.txt
        ▼  stage/  （含 zip）
④ verify_release.py stage
        │  独立校验最终产物
        ▼
   发布
```

### 为什么 ③ 和 ④ 的顺序不能颠倒

`build_out` 是**中间目录**（平铺：`Audio/`、`strings/`、DLL 直接放根），
`stage` 是**最终产物**（安装布局：`update/`、`scripts/`、包根文件）。

`verify_release.py` 校验的是 `stage`，因为在 `build_out` 阶段
包根那 4 个文件**还不存在**（由 `make_patch.py` 添加）。

> **踩过的坑**：CI 最初是 `ci_build → verify_release build_out → pack_release`，
> 校验目标与实际产物不一致。现在已改为 `ci_build → make_patch → verify_release stage`。
>
> `verify_release.py` 内部用 `resolve()` 同时兼容两种布局。

---

## 3. 本地构建命令

```powershell
cd G:\Projects\ArmyMenCHS

# ① 编译 DLL（会自动 clean 旧的 .obj/.pch/.lib/.dll）
python Tools\ci\build_dll_local.py

# ② 组装中间产物
python Tools\ci\ci_build.py --out build_out --verify

# ③ 打补丁包
python Tools\ci\make_patch.py --out stage

# ④ 校验
python Tools\ci\verify_release.py stage
```

### 关于 `build_dll_local.py`

它**不用 MSBuild**（`msvc-wine` 也没有），而是把 `vcxproj` 的
`Release|Win32` 选项逐项翻译成 `cl`/`link` 命令行。

```python
CL_FLAGS = ["/nologo", "/c", "/GS", "/W3", "/Gy", "/Zc:wchar_t",
            "/Zc:inline", "/Zc:forScope", "/Gd", "/O2", "/Oi", "/Oy-",
            "/fp:precise", "/MT", "/EHsc", "/errorReport:prompt", "/utf-8",
            "/D_WINDLL", "/D_UNICODE", "/DUNICODE", "/DNDEBUG"]
LINK_FLAGS = ["/nologo", "/DLL", "/MACHINE:X86", "/OPT:REF", "/OPT:ICF",
              "/INCREMENTAL:NO", "/SUBSYSTEM:WINDOWS"]
LINK_LIBS  = ["kernel32.lib", "user32.lib", "gdi32.lib", "advapi32.lib"]
```

`/MT` = 静态 CRT，**不要改成 `/MD`** —— 否则目标机器需要相应运行库。

**编译顺序**：`pch.cpp` 用 `/Ycpch.h` 先生成 `.pch`，
其余源码用 `/Yupch.h` 引用。顺序错了会报 `C2857`。

### ★ 为什么用 Python 而不是 PowerShell

`cl.exe` 的参数里含内嵌引号（`/Yc"pch.h"`）。PowerShell 5.1 的
`& $exe @args` 会**静默吞掉这些引号**，导致只编译了 `pch.cpp`，
链接器复用陈旧的 `.obj`，产出**零导出且不报错**的 DLL。

Python `subprocess` 把参数列表直接交给 CRT，不做 shell 解析。

> **移植注意**：2/3/4 代如果也用 PowerShell 驱动编译，
> 会再次踩到同一个坑。**直接抄 Python 版本。**

---

## 4. CI 工作流

文件：`.github/workflows/build-release.yml`

### 触发条件

```yaml
on:
  push:      { branches: [main, master], paths-ignore: ['**.md', 'Archives/**', 'docs/**'] }
  pull_request: { ... 同上 ... }
  workflow_dispatch:
    inputs:
      skip_dll:    # 跳过 DLL 编译，复用已提交产物
```

### 步骤

| # | 步骤 | 说明 |
|---|---|---|
| 1 | 检出仓库 | |
| 2 | 检出 msvc-wine | |
| 3 | 配置 Python | |
| 4 | 安装 Pillow | 导出贴图用 |
| 5 | 安装 wine / msitools | |
| 6 | 还原 MSVC 工具链缓存 | 否则每次都要下载 |
| 7 | 下载装配 MSVC v141 + Win10 SDK 26100 | 缓存未命中时 |
| 8 | `install.sh` | 生成包装脚本 / 大小写修复 |
| 9 | **验证编译器为 v141 x86** | **门禁**，见下 |
| 10 | `compile_dll_wine.py` | 编译 32 位 DLL |
| 11 | `ci_build.py --out build_out --verify` | |
| 12 | `make_patch.py --out stage` | |
| 13 | `verify_release.py stage` | |
| 14 | 上传 artifact | |

然后是 `publish` job：下载 artifact → 按日期时间打 tag →
生成 Release 说明（取提交记录）→ 创建 Release 并上传 zip。

### 第 9 步为什么是门禁

`vsdownload` 可能**静默回退到新版工具集**。若编译器不是 19.16，
产物的 ABI 与历史不一致，且不易察觉。所以：

```bash
banner="$(cl 2>&1 || true)"
if ! echo "$banner" | grep -q "19\.16"; then
  echo "!! cl 不是 MSVC 14.16 (v141)" >&2
  exit 1
fi
```

同时打印 `mspdbcore.dll` 的位置（C1356 根因诊断）和磁盘余量。

---

## 5. 发布包布局

```
ArmyMen-CHS-Patch-<UTC 时间戳>.zip
├─ dsound.dll                 ASI Loader（Ultimate ASI Loader v6.4, MIT）
├─ 安装说明.txt               UTF-8 BOM + CRLF（记事本友好）
├─ LICENSE                    项目主许可（含游戏版权声明）
├─ License.txt                LICENSES/*.txt 合并正文
├─ scripts\
│   ├─ Army1_Extend_Dll.asi   ← build_out 里叫 .dll，落包时改名
│   ├─ ArmyMenCHS.ini
│   └─ strings\*.ini          6 块 / 153 条
└─ update\
    ├─ Audio\ AVI\ Campaigns\ Maps\ Screens\
    └─ Alpine\ Bayou\ Desert\  objects.dat
```

**解压即用**：直接覆盖到游戏根目录（`Armymen.exe` 所在处）。

### ★ 两个必须记住的约束

1. **DLL 必须改名 `.asi`**。ASI Loader 只扫描 `scripts\*.asi`，
   放 `.dll` 会被静默忽略 —— 游戏完全没反应且无报错。

2. **`update/` 目录层级不能打散**。ASI Loader 把它作为工作目录
   覆盖到游戏视图之上，游戏按 `Alpine/objects.dat` 这样的相对路径读取。

---

## 6. 校验项清单

`verify_release.py` 检查（8 项）：

| # | 检查 | 判据 |
|---|---|---|
| 1 | DLL 存在且为 **32 位 PE** | `machine == 0x14C` |
| 2 | DLL 导出完整 | 3 个：`InitializeASI` / `ArmyMenCHS_Install` / `ArmyMenCHS_Uninstall` |
| 3 | `ArmyMenCHS.ini` + 声明的 strings 文件 | 逐个存在且可解析 |
| 4 | 三个 `objects.dat` **能重新解析** | 魔数 + key 数量 + 块头合法 |
| 5 | `objects.dat` 的 key 集合与 Steam 原版一致 | 差异移植不应改 key 集合 |
| 6 | 载荷目录齐全 | Audio/AVI/Campaigns/Maps/Screens |
| 7 | **包根必备文件** | `dsound.dll` / `LICENSE` / `License.txt` / `安装说明.txt`（须 UTF-8 BOM） |
| 8 | **LICENSE 内容体检** | 不得残留其它项目名，必须含 GPL 与游戏版权方 |

### 第 7 项为什么是硬门禁

`dsound.dll` 缺失时，游戏**不会加载** `scripts\*.asi`，
汉化**完全失效且没有任何报错** —— 用户只会看到英文界面，
不知道该报告什么。必须在 CI 阶段拦下。

第 8 项是防止从别的项目复制 LICENSE 时**忘了改游戏名**
（1 代确实发生过：模板里留着 `Saints Row` / `Volition`）。

---

## 7. 对账与完整性验证

### 7.1 与官方汉化包对账

```powershell
python Tools\ci\cmp_official.py `
  --official "I:\...\玩具兵大战1" `
  --steam    "I:\...\Army Men I STEAM"
```

**两个路径必须显式传**，因为都是本机私有路径（官方包含 copyrighted
素材、Steam 是用户自己的游戏），不在仓库里。

> **踩过的坑**：最初设了默认值并拿仓库里的 `Army1_Original` 当基线，
> 但它是 1998 原盘结构，与 Steam 平铺结构对不上，
> 导致误报 "263 个文件缺失"。
>
> 现在改为**强制传参**，避免静默用不存在路径算出假阳性。

判定三类：

| 情况 | 处理 |
|---|---|
| 官方有、我们没有、**Steam 一样** | 官方冗余，**无害**，无需下发 |
| 官方有、我们没有、**Steam 不一样** | **真缺失**，必须补 |
| 两边都有但**内容不同** | 逐个查 |

### 7.2 objects.dat 结构校验

```powershell
python Tools\unpack_objects\verify_objects.py stage\update\Alpine\objects.dat
```

期望输出：

```
块边界精确匹配 : 1674 / 1674
异常块         : 0
```

### 7.3 git 保真校验（提交前必做）

`.gitattributes` 存在**不代表** blob 已正确规范化 ——
已暂存的文件需要 `git add --renormalize .` 才会更新。

必须**实际比对 blob 与磁盘字节**：

```python
# 用 git cat-file --batch 批量取 blob 再逐字节比对
# 完整脚本见 docs/02-pitfalls.md 坑 7
```

判定标准：游戏资产（`.dat/.aai/.txt/.rul/.smk/.BMP/.exe`）必须**逐字节一致**。

---

## 8. 发布前检查清单

```
[ ] build_dll_local.py 成功，DLL 大小合理，3 个导出齐全
[ ] ci_build.py --verify 通过（三地形 objects.dat 结构合法）
[ ] make_patch.py 成功，stage/ 含 4 个包根文件
[ ] verify_release.py stage 全部通过
[ ] Alpine strip 报告符合预期（requested 4, actually stripped 2）
[ ] 与官方包对账：真缺失 = 0
[ ] git 保真校验：游戏资产逐字节一致
[ ] 构建脚本连跑两次结果一致（幂等性）
[ ] ★ 实机启动游戏，确认日志 applied=N skipped=0，且无崩溃
[ ] 提交并推送
```

**最后一项不可省。** 1 代踩过"构建全绿但补丁根本没加载"的坑
（DLL 放错目录、Loader 只认 `.asi`）——
**只有实机跑一次才能确认。**

---

## 相关文档

| 文档 | 内容 |
|---|---|
| [`00-porting-map.md`](00-porting-map.md) | 移植地图（先读这个） |
| [`01-technical-archive.md`](01-technical-archive.md) | 技术档案 |
| [`02-pitfalls.md`](02-pitfalls.md) | 踩坑清单 |
| [`04-asset-pipeline.md`](04-asset-pipeline.md) | 资产流程 |
