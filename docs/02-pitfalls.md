# 踩坑清单 —— 1 代真实踩过的坑

> 每条都标注了**根因**（不只是症状）和**判据**（怎么确认是真因）。
> 面向 2/3/4 代移植时避坑。这些坑会以不同面貌重现。

---

## 坑 1：把符号链接/占位目录当成"已有资产"

**症状**：仓库里看到 `Army2_CHS/`、`Army3_CHS/` 等目录，以为 2/3/4 代
已经在做或已做完。

**实际**：这些目录**全是 0 文件的空占位符**。

| 目录 | 文件数 |
|---|---|
| `Army1_CHS` | 594 |
| `Army2_CHS` … `ArmyRTS_Original` | **0** |

同理 `ArmyMenSourceCode/` 只有 **1998 年 1 代**源码，
README 明确写了 "the first Army Men game released in 1998"。

**判据**：`Get-ChildItem <dir> -Recurse -File | Measure-Object` 看真实文件数，
不要只看目录是否存在。

---

## 坑 2：翻译了被当作路径/标识符的字符串 → 崩溃

这是**最严重**的一类坑。字符串看起来是界面文字，实际参与逻辑。

### 2.1 `TrooperNames[]` —— 拼动画目录名

`TextData.cpp:189`：

```c
static char *TrooperNames[] = {
    "RifleMen", "GrenadeMen", "FlameMen", "BazookaMen", "SweeperMen",
    "MortarMen", "MinerMen", "SpecialMen", "NoTrooper"
};
```

`Unit.cpp:2164` 用它拼文件路径：

```c
sprintf(filename, "%s/%s", TrooperName(eType), troop_anim_names[i]);
CSpriteCatalog *pCat = AnimImport(filename, flags);
```

**改成中文的后果**：会去加载 `迫击炮兵/xxx.axs` 这种不存在的路径 →
单位精灵表为空 → `Armymen.exe+0x144B7` 处 `esi=0` 访问 `0xC` 崩溃。

**判据**：崩溃在固定偏移，且当时正在加载关卡。

### 2.2 `MsgVehicleNames[]` —— 同类，载具版

`USA.h:165`。同样的拼路径用途。

### 2.3 `obj_category_dirs[]` —— 对象目录名

`fileio.cpp:111`（定义）、`fileio.cpp:819/1020`（使用）：

```c
char *obj_category_dirs[] = { ... "BUILDING", "PILLBOX", ... };
```

用于定位 `Objects\<category>\` 子目录。**改了找不到对象。**

### 2.4 注册表值名与值数据 —— `strcmp` 比对

`Commands.cpp:1076-1122`：

```c
if (gpComm->RegGet(TEXT("Cursor"), (LPBYTE)&bData, &dwSize)) {
    if (strcmp(bData, "White") == 0)      // ← 值数据参与比较
        UseAltGunsight = !(0);
}
...
pData = UseAltGunsight ? "White" : "Red";  // ← 写回
gpComm->RegSet(TEXT("Cursor"), (const BYTE*)pData, len);
```

**不可翻译的有两类**：

| 类别 | 具体值 |
|---|---|
| 注册表**值名** | `Cursor`、`MouseRight` |
| 注册表**值数据** | `White`、`Red`、`Move`、`ChgWeapon` |

翻译任一类都会导致配置读写失败。

### ★ 可移植的通用判据

翻译任何字符串前，**先搜它在源码里的所有引用**：

```bash
rg -n "\bTrooperNames\b|\bMsgVehicleNames\b|\bobj_category_dirs\b" ArmyMenSourceCode/src
```

然后检查每个引用点是不是：

- `strcmp` / `strncmp` → ❌ 不可译
- `sprintf` 到路径 / `fopen` / `AnimImport` → ❌ 不可译
- 仅赋给控件做显示（`pDescription = ...`）→ ✅ 可译

1 代的 `keyname_block.ini` 顶部就记录了这个判断过程，可作模板：

```ini
; ★ 安全性（已用源码验证）：
;   desc 字段仅用于显示：
;     Screen.cpp:4506/4591  pDescription = SargeKeyDescs[i].desc;
;     debug.cpp:1600        ...SargeKeyDescs[j].desc...
;   **没有任何 strcmp / 文件路径使用**，因此可以安全翻译。
```

**没有源码时的替代手段**：在 IDA 里对该字符串地址做 xref，
看引用处是否调用了 `strcmp`/`sprintf`。

---

## 坑 3：整包替换资材，把上游修复一起退回

**症状**：中文版第三关「羊肠河」绿营地吉普车被油桶卡死。

**根因**：1998 中文盘的 `Alpine/objects.dat` 里，建筑（cat 17）的
num 328 / 903 带有一份多余的**碰撞掩膜**，覆盖了本该可通行的地块。

**更深一层**（这条最反直觉）：

> Steam v1.2 自己**只删掉了 d1 形态的掩膜，d0 形态的还在**。

实测数据：

| key | 1998 中文盘 | Steam v1.2 | 形态 |
|---|---|---|---|
| 567552 | maskSize 5264 | **maskSize 5264** | n328 d0 |
| 567553 | maskSize 5264 | maskSize 0 | n328 d1 |
| 585952 | maskSize 5824 | **maskSize 5824** | n903 d0 |
| 585953 | maskSize 5824 | maskSize 0 | n903 d1 |

所以"**不覆盖 cat 17**"这个显而易见的第一反应**并不足以**解决问题 ——
d0 的那两块仍带掩膜。必须**主动剥离**。

**修复方式**：`pack_diff.py --strip-mask`，把指定 key 的 `maskSize` 置 0
并移除掩膜数据，保留 Steam 的美术图形。

**验证结果**：产物与 1998 母盘的差异**精确为这 4 个块**，
且 4 块 `maskSize` 全为 0。

### ★ 可移植的经验

拿到一份旧汉化包时，问的问题应该是：

> ❌ "它和原版哪里不同"（会得到一堆要覆盖的差异）
> ✅ "**它比新版少了哪些修复**"（才能避免把修好的 bug 改回去）

旧汉化包 = 旧版本 bug 集合。差异移植时必须逐块核对来源版本。

---

## 坑 4：`maskSize == 0` 的两义性

**症状**：以为 `maskSize == 0` 表示"掩膜全零/无效"，于是也当成"有掩膜"处理。

**实际**（`fileio.cpp:1424-1434`）：

```c
fread(&ibuf, sizeof(int), 1, f);   // maskSize
if (ibuf > 0) { malloc(...); fread(pMask, ...); }   // 只在 >0 时分配
```

`maskSize == 0` 时 `pMask` **保持 NULL**，游戏走**不同代码路径**：

```c
// Map.cpp:3311 / 3420 / 3581 / 3651 —— 四处都这么判断
if (pobj->cell.pSprite->pMask) { ...精确像素碰撞... }
else                          { ...宽松/矩形碰撞... }
```

所以"置 0"不是"清空掩膜"，而是"**切换到宽松碰撞分支**"。

**判据**：这是 bug 修复的关键，误判会导致改完仍卡。

---

## 坑 5：构建脚本不幂等

**症状**：`build_object_chs.py` 第二次运行时，把 37 个块错误地扩成 273 个。

**根因**：脚本先清空 `raw/` 缓存，然后比较时把
"**文件读不到**"和"**内容与 Steam 不同**"归到了同一个判断分支：

```python
# ✗ 错的：缓存缺失被当成"有差异"
if not os.path.exists(cached) or open(cached,'rb').read() != steam_blob:
    include(block)
```

第一次运行时 `raw/` 里有文件，正常；第二次运行时刚被自己删掉，
于是**所有块**都被判定为"有差异"。

**修复**：比较基准改为**始终从中文母盘的原始 objects 读取**
（`Army1_CHS/terrain/<T>/objects.dat`），不依赖可能被清空的缓存。

**判据**：**构建脚本必须连跑两次结果一致**才算写对。

### 相关的 Python 坑

同一次修复中还踩到：

```python
# ✗ 变量遮蔽：src 既是目录路径字符串，又被赋成 bytes
src = os.path.join(root, "Army1_CHS")     # str
src = chs_objs.get(o["key"])              # bytes → 后面 open(src) 报 UnicodeDecodeError
```

改名 `chs_blob` 解决。**报错是 `UnicodeDecodeError: 'utf-8' codec can't decode
byte 0x81`**，看起来像编码问题，实际是变量遮蔽。

---

## 坑 6：构建成功但产物是垃圾（静默失败）

这是**最危险**的一类 —— 没有任何报错，但产物不可用。

### 6.1 PowerShell 吞掉 `/Yc"pch.h"` 的内嵌引号

用 PowerShell 5.1 的 `& $exe @args` 数组调用 `cl.exe` 时，
`/Yc"pch.h"` 的引号被吞掉 → 只编译了 `pch.cpp` → 链接器
**复用了 4 小时前的陈旧 `.obj`** → 产出一个 **86528 字节、
零导出、且不报错**的 DLL。

尝试过的失败修法：`Start-Process -ArgumentList`（`$p.ExitCode` 为空）、
手工拼 `cmd.exe /c` 字符串（引号丢失，报 `D8003 missing source filename`）。

**最终解法：放弃 PowerShell，改用 Python `subprocess`** ——
参数列表直接交给 CRT，不做 shell 解析。

顺带加了 `clean()`：编译前删除所有 `.obj/.pch/.lib/.dll`，
**从结构上杜绝复用陈旧中间产物**。

**判据**：链接后必须断言
1. DLL 文件大小合理
2. PE machine == `0x14C`
3. **三个导出都存在**（`InitializeASI` / `ArmyMenCHS_Install` / `ArmyMenCHS_Uninstall`）

第 3 条是抓这种 bug 的关键 —— 零导出的 DLL 也能是合法 PE。

### 6.2 清理逻辑静默吞掉失败 → 陈旧文件混入产物

`ci_build.py` 的清理：

```python
for fn_ in f_:
    try:
        os.chmod(...); os.remove(...)
    except OSError:
        pass          # ← 吞掉了删除失败
```

若文件被占用（如 IDA 打开着、杀软扫描），删除失败但**不报错**，
随后 `shutil.copyfile` **跳过已存在的目标**，
于是上一次构建的陈旧文件被打进了发布包。

**实际后果**：`Screens/Title_legal.BMP` 变成一个 921656 字节的
**24 位 RGB** 文件（正常的 8 位索引色是 308280 字节），
而所有其它文件都是 308280 —— 说明它是上一次构建的遗留物。

**修复**：产物目录改用"先整体删除，失败即报错"，不做静默容错。

**判据**：构建后**逐文件比对产物与源**，而不是只看"复制了几个文件"。

### 6.3 硬编码绝对路径 → CI 上静默写到错误位置

5 个脚本把 `G:\Projects\ArmyMenCHS` 写死为 `--root` 默认值：

```
Tools/ci/ci_build.py
Tools/ci/make_patch.py
Tools/ci/cmp_official.py
Tools/build_new_chs.py
Tools/unpack_objects/build_object_chs.py
Tools/unpack_objects/export_sprites.py
```

CI 在 ubuntu runner 上跑，仓库位于 `$GITHUB_WORKSPACE`，
`G:` 盘**根本不存在** → 脚本把产物写到不存在的路径 →
下一个步骤报告"缺少全部文件"，**错误信息完全指向错误方向**。

**修复**：`root` 一律由 `__file__` 上溯推导：

```python
root = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
```

**判据**：**从仓库外的其它位置 clone 一份，跑完整流程能成功**。

---

## 坑 7：`core.autocrlf=true` 破坏游戏资产

**症状**：地图加载崩溃，或资源行为异常。

**根因**：Windows 上 `core.autocrlf=true` 时，git 检出会把 LF 改成 CRLF。
对纯文本无害，但游戏资产是**按字节解析**的：

- `.txt` 任务脚本
- `.rul` 地图规则
- `.cpn` 战役定义
- `.aai` AI 行为表

每行多 1 字节 → 后续所有偏移错位。

**实测证据**（`AiDefault.aai`）：

```
磁盘 28473 B  CRLF=896  LF=896
git blob 27577 B  CRLF=0  LF=896   ← 少了 896 字节，全是 CR
```

**修复**：加 `.gitattributes` 显式锁死：

```gitattributes
*.txt      -text
*.rul      -text
*.cpn      -text
*.aai      -text
*.dat      -text
*.exe      -text
*.dll      -text
*.smk      -text
```

**额外的坑**：加了 `.gitattributes` 后**已暂存的文件不会自动重新规范化**。
必须：

```bash
git rm --cached -r . -q
git add --renormalize .
git add -A
```

否则 `git check-attr` 显示 `text: unset`（规则生效了），
但 blob 里仍是旧的不正确内容。

**判据**：验证脚本必须**实际比对 git blob 与磁盘字节**，
不能只看 `.gitattributes` 的文本。

### 验证脚本自身的坑

写这个校验器时踩到：`git cat-file --batch` 对**每个**输入都输出一行 header，
对象不存在时 header 是 `<name> missing`（**2 个字段，无 payload**）。
按顺序 `zip(names, contents)` 对齐时遇到 missing 就**整体错位一格**，
导致后面所有文件都拿到别人的内容，报出一堆**假的**"损坏"。

正确做法：逐个解析 header，missing 的直接跳过。

---

## 坑 8：用错对照基线，得出假结论

**症状**：对账脚本报告"263 个文件缺失"。

**根因**：拿仓库里的 `Army1_Original` 当基线，但它与官方汉化包的
**目录结构不同**：

| | 结构 |
|---|---|
| `Army1_Original`（仓库） | 1998 原盘式：`audio/ video/ text/ maps/ ui/` |
| Steam 实机安装 | 平铺式：`Audio/ AVI/ Campaigns/ Maps/ Screens/` |
| 官方汉化包 | 1998 原盘式 |

两者只有 4 个文件路径重合，于是几乎全部被误判为"缺失"。

**修复**：改用**Steam 实机安装目录**做基线。修正后：
缺失 **0**，冗余 264（官方只是把未汉化的文件也全量复制了一遍）。

### ★ 可移植的经验

对账前先确认三方结构：

| 类别 | 判据 |
|---|---|
| 官方有、我们没有、**Steam 是一样的** | 官方冗余，**无害**，无需下发 |
| 官方有、我们没有、**Steam 不一样** | **真缺失**，必须补 |
| 两边都有但**内容不同** | 必须逐个查 |

**"官方包里的文件"≠"需要汉化的文件"。** 官方包图省事做了全量复制。

---

## 坑 9：把映像文件格式的字段读错

写 BMP 位深体检时：

```python
return struct.unpack_from("<H", b, 28)[0] * 8   # ✗ biBitCount 本身就是位深
```

`biBitCount` 字段**本身就是位深**（8 = 8 位），再乘 8 得到 64，
于是误报"174 个 64 位 BMP"，引发一场虚惊。

正确：`struct.unpack_from("<H", b, 28)[0]`。

**判据**：拿一个已知正确的文件先验证解析器，再批量跑。
（用 Pillow 交叉验证：`Image.open(p).mode == "P"` 表示 8 位索引色。）

---

## 坑 10：Python SyntaxWarning 让脚本退出码变 1

**症状**：`set -euo pipefail` 的 CI 中，脚本"什么都没做就失败"。

**根因**：docstring 里的未转义反斜杠（如路径 `G:\Projects\...`）：

```python
"""
    python foo.py --root G:\Projects\ArmyMenCHS
"""                        # \P 是无效转义序列
```

Python 3.12+ 会发 `SyntaxWarning: "\P" is an invalid escape sequence`。
警告本身不中断，但**在 PowerShell 下会让退出码变成 1**，
`set -e` 的 CI 直接红。

**修复**：docstring 里的 Windows 路径用 `\\` 或改成正斜杠。

**判据**：

```python
import warnings, glob
for f in glob.glob('Tools/**/*.py', recursive=True):
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        compile(open(f, encoding='utf-8').read(), f, 'exec')
        for x in w:
            if 'escape' in str(x.message): print(f, x.message)
```

---

## 坑 11：ASI Loader 只认 `.asi`

**症状**：装好补丁，游戏完全没反应，没有任何报错。

**根因**：把 `Army1_Extend_Dll.dll` 放进了 `scripts\`。
Ultimate ASI Loader **只扫描 `scripts\*.asi`**。

**修复**：`make_patch.py` 落包时改名（`DLL_DST = "scripts/Army1_Extend_Dll.asi"`）。

**判据**：**必须在真实游戏里验证装载**，看是否产生了日志。
写完补丁不实测就发布，这个坑 100% 会中。

---

## 坑 12：把"推断"当成"已验证"

1 代过程中出现过几次**用确定语气包装猜测**的情况，实际造成误导：

| 曾经的错误说法 | 实际 |
|---|---|
| "Steam 的 d0 块本来就无掩膜，`strip` 会报 0" | Steam d0 **有**掩膜，`strip` 实际干了活 |
| "官方包覆盖了全部汉化资产" | 官方 Alpine 目录**根本不存在** |
| 只看目录存在就以为 2/3/4 代有资产 | 全是 0 文件占位符 |

**做法**：文档里**明确区分**三种状态：

- ✅ **已实测**（附命令与输出）
- ⚠️ **推断**（说明依据）
- ❓ **未知**（如实标注，不要用确定语气）

本套文档中，`01-technical-archive.md` 第 7 节专门列了"未解问题"。

---

## 坑 13：用子串匹配做发布校验，会误判

`verify_release.py` 最初用字节子串判断 DLL 导出：

```python
for name in (b"ArmyMenCHS_Install", b"ArmyMenCHS_Uninstall"):
    if name in open(dll,'rb').read(): ...
```

RVA 偏移值可能包含相同字节序列，且子串匹配不能保证是真导出表项。

**更严格的做法**：解析 PE 导出目录（`IMAGE_EXPORT_DIRECTORY`），
遍历 `AddressOfNames` 数组。

**判据**：如果用子串匹配，至少也要确认导出**数量**正确
（1 代是 3 个：`InitializeASI` + 两个自定义导出）。

---

## 相关文档

| 文档 | 内容 |
|---|---|
| [`00-porting-map.md`](00-porting-map.md) | 移植地图（先读这个） |
| [`01-technical-archive.md`](01-technical-archive.md) | 技术档案 |
| [`03-build-and-release.md`](03-build-and-release.md) | 构建与发布 |
| [`04-asset-pipeline.md`](04-asset-pipeline.md) | 资产流程 |
