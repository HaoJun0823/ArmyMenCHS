# AMWW(4 代) 逆向实测结果 —— 全部来自 IDA + 逐字节 disasm，非推测

目标：`I:\LocalGames\Army Men\Army Men - World War GOG\amww.exe`
校对日期：2026-10-16 ｜ IDA session 已建 `amww.exe.i64`

## PE

| 项 | 值 |
|---|---|
| 大小 | 757,760 B |
| machine | `0x14C`（32 位） |
| ImageBase | `0x400000` |
| SizeOfImage | `0x2F3000` |
| TimeDateStamp | `0x3B943B66`（正常值，不是 3 代那种伪造 ASCII） |
| EntryRVA | `0x8AA6F` |
| .text | VA `0x1000` VS `0x93722` RawPtr `0x1000` → **文件偏移 == RVA** |

## 多人菜单解锁（已实测）

- 文件/RVA `0x6F270`，VA `0x46F270`，实得 `EB 55` ✅
- 前文 `... 3B F3 | C7 44 24 38 04 00 00 00 | EB 55`
  （与 3 代 `C7 45 FC 04 00 00 00 / EB 41` 同构：一个是栈槽 `[esp+38h]`，一个是 `[ebp-4]`）
- 特征码 `04 00 00 00 EB 55` 全文件**唯一**命中 @ file `0x6F26C` ✅
- 改 `EB -> 74` 即 `jmp short` → `jz short`

## 文字引擎（★ 与 3 代同构但**地址全部不同**，且**表布局相反**）

### 关键否决：不能照抄 3 代签名

3 代的字体索引是 `imul ecx, ecx, 0x20C`（262*2）。
在 amww.exe 全文件搜 `69 ?? 0C 02 00 00` → **0 命中**。
4 代改用 `shl edx,6; add edx,ecx; lea [ecx+edx*2]`（等价于 `*262`）再 `shl esi,2`。
→ 3 代的 5 个签名在 4 代**全部不适用**，必须重测。（已重测，见下）

### 字体图集构建链

```
sub_4660A0(font)                      构建图集；源码 C:\Armymenww\source\text.cpp
  ├ sub_465E10(face, height, flags)   CreateFontA 包装
  ├ sub_465FA0(...)                   逐字符 TextOutA 到临时 0x8000 缓冲
  └ sub_429E20(...)                   最终 malloc 出图集
sub_466230(font)                      释放图集
```

字体名表 `off_4B2788`（`ArialBlack` @0x4B27B8 / `ArialNarrow` @0x4B27C4）。

### 全局表（★ 与 3 代语义**相反**，这是最容易踩错的一处）

| VA | 3 代对应 | 4 代实测语义 |
|---|---|---|
| `0x6BE524` | atlasOffset `0x698D6C` | **字形偏移表** `WORD[262*font + c]` |
| `0x6BE564` | charWidth `0x698DAC` | 与 0x6BE524 相差 `0x40`（32 项），**不是宽度表**，仅给 `a3[1]` 取高度 |
| `0x6BE520` | atlasBase `0x698F6C` | `DWORD[131*font]` 图集**字节大小** |
| `0x6BE724` | — | `DWORD[131*font]` **堆绝对地址**（malloc 出来的图集，★ 不是 RVA） |

★ 3 代绘制用 `word_698D6C[...]` 取偏移、4 代用 `word_6BE524[...]`；
  3 代的"宽度表陷阱"（0x698DAC 实为偏移表右移）在 4 代换成了 `0x6BE564`。
  **两者都不要当宽度读。**

### 5 个 hook 目标（全部实测）

| Kind | VA | 签名 | 参数 | patchLen | 行为 |
|---|---|---|---|---|---|
| RK_LEFT | `0x466320` | `A1 2C C7 53 00 \| 83 EC 30 \| 85 C0 \| 53 55 56 57 \| 0F 84` | 6 参 `(x,y,str,font,?,color)` | 10 | `v9 += v17` 沿 **x** 累加 |
| RK_DIALOG | `0x4664A0` | `A1 2C C7 53 00 \| 83 EC 30 \| 33 D2 \| 53 55 56 \| 39 C2 \| 57 \| 0F 84` | 9 参，第 5 参 `&a5` 是裁剪 RECT | 15 | 两级裁剪：rcSrc2 ∩ a5 |
| RK_CENTER | `0x466650` | 同 DIALOG 序言 | 9 参 | 15 | 首字 `x = a1 - 宽/2`，沿 **y** 累加 `+高-3` |
| RK_MEASURE | `0x466290` | `8B 4C 24 08 \| 53 \| 8B D1 \| 56 \| C1 E2 06 \| 03 D1 \| 57` | 3 参 `(str, font, out)` | 11 | 累加 `*(WORD*)(off + base + 0)` 字形**宽** |
| RK_MEASURE_H | `0x466810` | `8B 4C 24 08 \| 56 \| 8B D1 \| 8B 74 24 08 \| C1 E2 06 \| 03 D1 \| 57` | 2 参 `(str, font)` | 14 | 累加 `*(WORD*)(off + base + 2) - 3` |

★ 实际字节（IDA get_bytes 实读，签名与 patchLen 以此为准）：

```
LEFT      0x466320: A1 2C C7 53 00 | 83 EC 30 | 85 C0 | 53 55 56 57 | 0F 84 63 01 00 00
DIALOG    0x4664A0: A1 2C C7 53 00 | 83 EC 30 | 33 D2 | 53 55 56 | 3B C2 | 57 | 0F 84 8F 01 ..
CENTER    0x466650: A1 2C C7 53 00 | 83 EC 30 | 33 D2 | 53 55 56 | 3B C2 | 57 | 0F 84 98 01 ..
MEASURE   0x466290: 8B 4C 24 08 | 53 | 8B D1 | 56 | C1 E2 06 | 03 D1 | 57 | 8B 7C 24 10 | 33 C0
MEASURE_H 0x466810: 8B 4C 24 08 | 56 | 8B D1 | 8B 74 24 08 | C1 E2 06 | 03 D1 | 57 | 33 C0 | 8D ..
```

指令边界（patchLen 依据，逐字节核算）：
- LEFT      : 0(mov eax,imm32=5) 5(sub esp,30h=3) 8(test eax,eax=2) 10(push ebx=1) → **10**
- DIALOG    : 0(5) 5(3) 8(xor edx,edx=2) 10(push ebx) 11(push ebp) 12(push esi) 13(cmp eax,edx=2) 15(push edi) → **15**
- CENTER    : 同 DIALOG → **15**
- MEASURE   : 0(mov=4) 4(push ebx=1) 5(mov edx,ecx=2) 7(push esi=1) 8(shl edx,6=3) 11(add edx,ecx=2) → **11**
- MEASURE_H : 0(mov=4) 4(push esi=1) 5(mov edx,ecx=2) 7(mov esi,[esp+8]=4) 11(shl edx,6=3) 14(add edx,ecx=2) → **14**

★ 注意 MEASURE_H 是 **14** 不是 12：字节 11~13 是 `C1 E2 06`（shl edx,6），
  取 12 会落在 shl 的操作数中间 —— 与 3 代"patchLen=5 切碎 sub esp,38h"是同一类错误。

调用点数量：LEFT 32 / DIALOG 16 / CENTER 4 / MEASURE 14 / MEASURE_H 3

### 游戏自身绘制原语

| VA | 角色 |
|---|---|
| `0x427940` | **blit**：1bpp RLE 字形 → 目标表面。首句 `v8 = dword_53D8F8 + a1 + dword_542220 * a2` |
| `0x4430C0` | **rect**：`sub_4430C0(RECT*, clip, &x, &y, out)` 返回 bool，in-place 改 x/y |

### 全局量

| 用途 | VA | 备注 |
|---|---|---|
| 裁剪矩形 rcSrc2 | `0x4AD330` | RECT；紧邻 `rc` @ `0x4AD350`（left/top，绘制时 `a4 += rc.left; a1 += rc.top`） |
| surface（像素缓冲） | `0x53D8F8` | DWORD |
| pitch（行距） | `0x542220` | DWORD |
| 表面锁标志 | `0x53C72C` | 三个绘制函数开头都 `if(!dword_53C72C) return` |
| 当前表面==主表面判定 | `dword_546878 == dword_542224` | 相等时才加 rc 原点 |
| lockedSurf / primarySurf | `0x53D7DC`(dd 对象) / 待定 | `sub_426BB0` / `sub_426C50` 是 Lock/Unlock |

## 与 3 代的差异总结

1. **表布局相反**：3 代 `0x698D6C` 偏移表 / `0x698DAC` 陷阱表；4 代 `0x6BE524` 偏移表 / `0x6BE564` 陷阱表。语义相同（都不是宽度），地址与顺序不同。
2. **字体索引算法不同**：3 代 `imul 0x20C`，4 代 `shl/add/lea` 组合 → 3 代签名 0 命中。
3. **patchLen 不同**：3 代 6/6/6/5/8，4 代 10/15/15/11/12。
4. **DIALOG 是两级裁剪**：4 代 `sub_4664A0` 调两次 `sub_4430C0`（rcSrc2 与 a5 各一次），3 代只裁 rcSrc2。
5. **CENTER 的 `-3`**：4 代 `v23 + v21 - 3`，与 3 代 MEASURE_H 的 `-3` 同源。
