# AMAA(Army Men: Air Tactics / 系列第 4 代，目录号 Army5) 中文显示与长文本换行 —— 逆向实测记录

> ★ 编号说明：「5 代」在本文指的是**汉化施工批次**（目录号 `Army5_*`）。
> 本作是游戏系列的**第 4 代**；系列第 5 代是《世界大战 / World War》，
> 对应目录 `Army4_*`（见 [`13-am4-build-and-release.md`](13-am4-build-and-release.md)）。
> 面向玩家的说明按**系列序号**称呼，不按目录号。

目标：`I:\LocalGames\Army Men\amman7\amat.exe`
IDA database：`amat.exe.i64`（session 会过期，过期后重新 `idb_open`）
插件代码：`Army5_Extend_Dll/`，产物 `amman7\scripts\Army5_Extend_Dll.asi`
记录日期：2026-10-17

本文所有地址、字节、语义均来自 IDA 反汇编与 x32dbg 实读，**未验证的部分会明确标注为推测**。

---

## 1. PE 与注入链

| 项 | 值 |
|---|---|
| 大小 | 1,277,952 B |
| machine | `0x14C`（32 位） |
| ImageBase | `0x400000` |
| SizeOfImage | `0x94B000` |
| TimeDateStamp | `0x38BC3196` |
| DYNAMICBASE | 无（固定基址，可直接写死 VA） |
| `.text` / `.rdata` / `.data` | 文件偏移 == RVA |

注入方式：游戏目录自带 Ultimate ASI Loader（`dinput.dll`，含 `InitializeASI` / `UAL` 串），插件放 `amman7\scripts\*.asi` 即被加载。

导入链按名称走：`DDRAW!DirectDrawCreate`、`DINPUT!DirectInputCreateA`。

---

## 2. 文字引擎全局表

| 用途 | VA |
|---|---|
| 字形偏移表 `WORD[262*font + c]` | `0xC86DFC` |
| 陷阱表（= 上表 +0x40，**不是宽度表**） | `0xC86E3C` |
| 图集堆基址 `DWORD[131*font]` | `0xC86FFC` |
| 图集字节大小 | `0xC86DF8` |
| 表面锁标志 | `0x63C64C` |
| 像素缓冲 | `0x63C874` |
| 行距 | `0x641198` |
| 全局裁剪 RECT（rcSrc2） | `0x510A38` |
| rc 原点 | `0x510A58` |
| 当前/主表面 | `0x651850` / `0x64119C` |
| nWidth / nHeight | `0x671170` / `0x671174` |
| 字体档表（9 个） | `off_516368` |

字体档字高（GDI `CreateFontA` 实测，与字形头 `gh[1]` 完全相等）：

```
idx : 0  1  2  3  4  5  6  7  8
h   : 8 12 15 18 18 24 12 14 16
```

> `0xC86E3C` 与 `0xC86DFC` 相差 `0x40`（32 项），**不要当宽度表读**。它只在 `sub_4885B0` 里用于取 `a3[1]` 的行高。

---

## 3. 四个 hook 目标

签名均实测唯一（fail-closed：签名不符拒绝安装，不写 exe，只改进程内存）。

| Kind | VA | 原型 | patchLen |
|---|---|---|---|
| LEFT | `0x488640` | `(x, y, str, font, a5, color)` | 10 |
| DIALOG | `0x4887F0` | `(x, y, str, font, l, t, r, b, color)` 9 参 | 14 |
| MEASURE | `0x4885B0` | `(str, font, int* out)` | 11 |
| MEASURE_H | `0x488CF0` | `(str, font)` | 14 |

GRADIENT `0x488B90` 用另一套单字节字体（`0xC87E5C` / `0xC8805C`），**不接管**。

### 3.1 测量函数语义（`sub_4885B0`，IDA 反编译）

```c
int __cdecl sub_4885B0(_BYTE *a1, int a2, _DWORD *a3)
{
    int w = 0;
    int base = dword_C86FFC[131 * a2];
    while (*p) {
        if (*p == 0x5E) ++p;                      // '^' 颜色转义，跳 1 字节
        else if (*p >= 0x1F)
            w += *(WORD*)(base + word_C86DFC[262*a2 + (BYTE)*p]);
    }
    if (a3) { a3[0] = w; a3[1] = 行高; }
    return w;
}
```

关键点：

- 它是**逐字节**累加 ASCII 偏移表的，两个字节相加**不等于**字高
- `out` 允许为 `NULL`（`sub_42EF50` 调用时就是 `push 0`）
- 函数体内**没有**表面锁检查 `0x63C64C`

---

## 4. CJK 渲染（已完成，验证有效）

方案：GDI `CreateFontA` 建 ASCII 图集（游戏自己做的），汉字由我们喂 `Hzk16`（RSE\x1a 宋体 13×13）直写表面。

判定：GBK 双字节，`*s > 0xA0` 即视为汉字首字节。

### 4.1 踩过的坑：`PFN_rect` 参数被误声明为指针

`sub_455BA0` 的 `x` / `y` 是**按值传的 `int`**。误声明成 `int*` 后，游戏拿到的是栈地址 `0x001AFC84`，右界算成 1768604，超出裁剪框 475，**全部被裁光**。

改成按值后显示正常。这是本项目最容易复发的错误——签名必须逐个参数核对栈偏移。

---

## 5. CD-ROM 校验屏蔽

- 检测函数：`sub_447450` @ `0x447450`
- 启动链：`_WinMain` → `40F355 call sub_447450` → `test eax,eax` → `jz 退出`
- 指纹 11 字节 `51 53 55 56 57 8B 3D C0 40 4F 00` 全文件唯一命中
- patchLen = 5

做法：填 `byte_671288` = `<exe目录>\`，置 `dword_6713B0` / `dword_6713BC` = 1，再把 `0x447450` 入口改成 `mov eax,1; ret`。

> 屏蔽后若无声，检查资源是否在 `amman7\update\audio\`（music / codesfx / scriptsfx / voice），而不是游戏根目录。

---

## 6. 长文本换行 —— 本轮的核心问题

### 6.1 现象

只有**需要换行**的长句会坏，不换行的句子完全正常。

具体表现两类，会同时出现在同一句里：

```
无线电萨姆：
雷达上的任务目标会闪黄光。如果目标超出雷达
段#《庠档姆较甘镜苹峋齦媚勘甑姆轿弧        ← 乱码
```

另外「祝你好运」的**运**显示成**恕**。

### 6.2 根因（IDA 全量反汇编 `sub_42EF50` @ `0x42EF50..0x42F150`）

分行函数 `sub_42EF50(int this, const char* s, char color)`，行数组 `this+0x8D9`（每行 129 字节），行数 `this+0x8EC`。

断行算法是「贪心塞满 → 往回退找空格」：

```asm
0x42EFE5  mov  [esi], cl          ; 逐字节复制进行缓冲
0x42EFE8  inc  ebx                ; 源游标++
0x42EFEA  cmp  edi, 80h           ; 缓冲硬上限 128 字节
0x42EFF7  jge  0x42F019           ; 超了 -> 回退
0x42F007  call sub_4885B0         ; 用引擎自己的量具测当前行宽
0x42F015  cmp  eax, [ebp+934h]    ; 与框宽 maxW 比较
0x42F017  jl   0x42F063           ; 未超 -> 继续塞
--- 超宽，开始回退 ---
0x42F019  dec  ebx / dec esi / dec edi
0x42F01C  js   0x42F02E
0x42F01E  movsx ecx, [ebx]
0x42F022  call _isspace           ; 找空格
0x42F02C  jz   0x42F019           ; 不是空格 -> 继续退
--- 退到第一个空格，或退到开头 ---
0x42F02E  test edi, edi
0x42F034  jle  0x42F139           ; ★★ edi<=0 -> 整个函数退出 ★★
0x42F03A  mov  [esi], 0           ; 截断
0x42F043..0x42F05F  跳过连续空格，置 v9=1（断行成功）
```

**中文没有空格。** 长句塞到超宽后一路退到 `edi <= 0`，`jle 0x42F139` **直接跳出整个函数**，剩余文字一行都不写。

行槽里残留的是上一条的内容或未初始化的堆（x32dbg 实读 `0xBAADF00D`，VC++ 已释放堆标记），按 GBK 解码就是 `段#《庠档姆较甘镜苹峋` 这类怪字；旧内容为空时则整段不显示。

所以「乱码」和「不显示」是**同一个根因**，也解释了为什么只有换行的句子会坏。

### 6.3 走错的三条路（记录以免重犯）

| 版本 | 做法 | 结果 | 教训 |
|---|---|---|---|
| WrapFix v1-v3 | 改回退循环（`0x42F019` 起），用 `isspace` 硬编码 `0x4E7EC9` | 空对话 / 卡死 / 无效 | 未先验证 `sub_42EF50` 是否被调用就改代码 |
| LineFix v1-v4 | 改 `0x42F06A`（源串结束也去写行） | 同一处崩溃 ×4 | 见 6.4，位置根本不对 |
| WrapCjk v1 | 用**估算**宽度插空格 | 劈字：`运 D4CB` → `CB`+`A1` = **恕** | 见 6.5 |

#### 6.3.1 一个反复犯的元错误

插入空格实验同时改变了「长度」和「空格」两个变量，据此断定「空格提供断点」这个**前提本身**是靠不住的；后续三轮 WrapFix 全部建立在这个未验证的假设上。

正确顺序应该是：先用调试器确认函数被谁调用、参数是什么、执行流怎么走，再决定改哪里。

### 6.4 LineFix 连续四次崩溃的真相：trampoline 相对位移漏算壳基址

`BuildStub` 里原本写：

```cpp
auto f32 = [&](int off, DWORD target) {
    int rel = (int)target - (off + 4);   // ★ 漏了 p
    memcpy(p + off, &rel, 4);
};
```

`off` 是壳内偏移，`target` 是绝对地址。正确的 rel 必须是：

```cpp
rel = (BYTE*)target - (p + off + 4);
```

| 分支 | 目标 | 旧写法实际落点 | 结果 |
|---|---|---|---|
| `jz` ×2 | 壳内地址 | 正确 | 凑巧对（`p` 与偏移里的 `p` 抵消） |
| `jmp` → 写行 | `0x42F074` | `0x0339F074` | 未映射 |
| `jmp` → while | `0x42F130` | `0x0339F130` | 未映射 |

三条路径**全部以 `jmp` 收尾**，所以每次调用 `sub_42EF50` 必崩，崩溃点恒定 —— 这就是为什么改语义（v1/v2/v3 逻辑各不相同）崩溃位置始终一样。**语义改动从来不是原因。**

> 更严重的是：用来核对机器码的 Python 脚本在**地址 0** 上反汇编，等于在验证一个假壳，所以四次都显示「核对通过」。真实分配地址下的字节从未被验证过。

正确做法：写完字节后**回读反解实际落点**再做断言。现已在 `WrapCjkInstall` 中实现（`trampoline 落点校验失败 -> 放弃安装`）。

### 6.5 WrapCjk v1 劈字：为什么估算宽度必错

v1 用「汉字 = 字高、ASCII = 字高/2」估算行宽来决定插入位置。但引擎在 `0x42F007` 调用 `sub_4885B0`，它按**单字节**查表累加，两个字节加起来并不等于字高。

于是：

1. 我插空格的位置 ≠ 引擎判定超宽的位置
2. 引擎在别处超宽 → 回退 → 找到的是**上一个**空格 → 截断点偏移
3. 偏移一旦落在汉字的 lead/trail 之间，整个汉字被劈开

实测证据（用户画面 + 源文本逐字节比对）：

```
原文「...超出雷达范围，外缘的方向指示灯会给出该目标的方位。」
    范围 = B7B6  CEA7
乱码  段#《庠档姆较甘镜苹峋齦媚勘甑姆轿弧
    B6CE = 段   E2D4 = 庠   B5B5 = 档   C4B7 = 姆   BDCF = 较
    B8CA = 甘   BEB5 = 镜   C6BB = 苹   C3C4 = 媚   BFB1 = 勘
    EAB5 = 甑   BDCE = 轿
```

从 `B6` 起**整体错位一字节**，逐字对得上。

另一个更直观的例子：`运 = D4 CB`，在 `D4` 与 `CB` 之间插了 `0x20`，剩下的 `CB` 与后一字 `。` 的首字节 `A1` 拼成 `CB A1` = **恕**。

### 6.6 最终方案：用引擎自己的量具定边界

`Army5_Extend_Dll/src/wrapcjk.cpp`

在 `sub_42EF50` 入口 hook，对「含汉字**且**超框宽」的串做预处理：

1. 逐字符（GBK 边界，`>0xA0` 取 2 字节）**整字**追加到新缓冲
2. 每追加一个就用 `Hook_MEASURE`（即 `sub_4885B0`）量当前行宽
3. 一旦 `>= maxW`，**退回该字符之前**插入一个空格，把该字符放到下一行

三个关键点：

- **插入点永远在字符边界**：先追加整字、再判宽、超了才退回插空格，逻辑上不存在劈字可能
- **判宽与引擎同源**：用的是同一个函数，位置必然一致
- **插入的空格不显示**：被 `0x42F03A mov [esi],0` 截掉，再经 `0x42F043..0x42F059` 跳过

ASCII 串、未超宽的串**完全原样放行**。

### 6.7 ABI：用 `__fastcall` 匹配 `__thiscall`

原函数 `int __thiscall sub_42EF50(this /*ecx*/, const char* s, char color)`，调用点是 `push color; push s`，`retn 8`。

MSVC `__fastcall` 把 `ecx->arg1`、`edx->arg2`，其余照常走栈。所以声明成：

```cpp
typedef int (__fastcall* PFN_lineFn)(void* thisPtr, void* dummy,
                                     const char* str, char color);
```

就与 `thiscall` **完全同构**，返回时自动 `ret 8`。**不需要 naked 壳，不需要手工平衡栈。**

trampoline 必须完整复现原函数首条指令（`0x42EF50` 处的 `81 EC 90 00 00 00` = `sub esp,90h`），再跳回 `0x42EF56`（`push ebx`）。因为 `0x42EF56` 之后有 `[esp+9Ch+arg_0]` 这类依赖已减栈的寻址。

### 6.8 本段用到的 `this` 偏移

| 偏移 | 语义 | 出处 |
|---|---|---|
| `+0x904` | 字体档 | `0x42EFF9 mov edx,[ebp+904h]` |
| `+0x934` | 框宽 maxW | `0x42F00C mov ecx,[ebp+934h]` |
| `+0x8EC` | 行数 | `0x42F082 mov [ebp+8ECh],edx` |
| `+0x8F8` | 行高累加 | `0x42F12A inc dword ptr [ebp+8F8h]` |
| `+0x8D9` | 行数组首地址（每行 129 字节，16 行） | `sub_42EB90` 绘制时按 `129` 步进 |

### 6.9 兄弟函数

`sub_45D360`（`0x45D360`）—— 对话推进，`sprintf(Buffer, "%s: %s", 说话人, this+88)` 后调 `sub_42EF50`，并有行窗口滚动逻辑（`this+2464`）。

`sub_42EB90`（`0x42EB90`）—— 按行数绘制，逐行 `sub_4887F0`，行间 `v12 += this[2312]`（行距）。

---

## 7. 验证方式

### 7.1 离线

- `_am5_wrapcjk_v2_sim.py` —— 4 字体档 × 3 框宽 × 8 条真实字幕 = 96 组，断言「不 abort / 不劈字 / 还原一致」，**全部通过**
- `_am5_linefix_tramp_real.py` —— 在**真实 stub 基址**下反汇编并反解落点，同时复现旧 bug 的落点（`0x0339f074` / `0x0339f130`）

### 7.2 实机

日志 `amman7\scripts\ArmyMenAATCHS.log`：

```
WrapCjk: trampoline 03090000 -> 复原后跳到 0x42ef56（校验通过）
WrapCjk: 0x42ef50 已替换 -> jmp 6EBC9140（patchLen=6，原字节 81 EC 90 00 00 00）
WrapCjk: font=8 box=16 maxW=446 原宽=635 原长=81 -> 新长=82 插1处@[57]
```

`插1处@[57]` 中的 `57` 是**源串字节偏移**。用它回到源文本按偏移切开，即可直接确认是否落在字边界：

```
byte[57] = 0xB5（「的」的首字节）
前 57 字节 = "Sam: 雷达上的任务目标会闪黄光。如果目标超出雷达范围，外缘"
第 57 起   = "的方向指示灯会给出该目标的方位。"
```

边界正确，用户实测确认不再乱码、不再劈字。

---

## 8. 当前状态

| 项 | 状态 |
|---|---|
| 中文显示（GBK 混排） | ✅ 已验证 |
| CD-ROM 校验屏蔽 | ✅ 已验证 |
| CJK 长文本换行 | ✅ 已验证（v2，引擎量具定边界） |
| WrapFix（改回退循环） | ❌ 已禁用，方向错误 |
| LineFix（多写一行） | ❌ 已禁用，位置错误 |

相关代码：

```
Army5_Extend_Dll/src/
  renderer.cpp   中文渲染、4 个 hook、Hook_MEASURE
  target.cpp/.h  地址表与签名
  cdspoof.cpp    CD 校验屏蔽
  wrapcjk.cpp    ★ 长文本换行修复（当前方案）
  wrapfix.cpp    旧方案，已禁用
  linefix.cpp    旧方案，已禁用
```

---

## 9. 待办

- 文本量大，`update\data\**\COM.txt` 里仍有未经打磨的机翻，需人工校对
- 未验证：字体档 5（24px）在对话框里是否会因行高不足而裁掉字底（离线模拟通过，实机未逐档确认）
- 未验证：`sub_42EF50` 的 128 字节硬上限在超长句（>128 字节 GBK）下的表现 —— 现方案会插入空格，但是否触发整体上滚（`this+0x8EC > 16`）尚未构造用例实测
