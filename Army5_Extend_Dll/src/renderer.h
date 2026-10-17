// renderer.h —— 文字渲染器（ASCII + CJK），Army Men: Air Tactics（本作）
//
// 背景（✅ 实测，本轮 IDA 逆向）：
//   游戏原本的渲染器是 **ASCII-only**：
//       for each c: 查 atlasOffset[262*font + c] -> 取 atlas 里的 2xWORD 头
//                   -> rectFn 算目标矩形 -> blit 到表面
//   我们的做法：**完全接管该函数**（不改游戏其它字节），
//       ASCII 段 -> 逐字转调 stub（原始实现的副本，零行为差异）
//       CJK  段 -> 自己从 Hzk16 取 13x13 点阵，直接写目标表面
//   这与 2 代官方中文版的思路一致（官方就是加了一条 `if (c > 0xA0)` 分支）。
//
// 为什么"ASCII 转调 stub"而不是"自己画"：
//   2 代在这里连摔四轮 —— blit 参数序写错、font 参数硬编码、返回值契约搞错、
//   编辑框输入不了。根因都是"我在重造游戏自己的逻辑"。
//   转调 stub 让游戏自己处理，字体/裁剪/返回值/颜色全部自动正确。
//
// ★★ 本作与 3/4 代的决定性差异（决定了本文件不能照搬）：
//
//   ① 只有 3 个绘制函数，**没有 CENTER**
//      4 代：LEFT / DIALOG / CENTER（CENTER 沿 y 累加 `高-3`）
//      本作：LEFT / DIALOG / GRADIENT
//      -> 本文件**没有** axisY 分支，全部沿 x 累加。
//      -> 但多一个 GRADIENT（sub_488B90），它用另一套单字节字体表
//         （word_C87E5C[256] / dword_C8805C），中文永远不会走它，
//         故**不接管其绘制**，仅保留识别校验。见 target.h 的 RK_GRADIENT。
//
//   ② 渲染器**返回 int**，但返回值是"循环变量的残值"，不是"文本结束后的 x"
//      实测 sub_488640 尾部：`mov eax, [var_30]`（= 上一轮的字符索引）
//      `inc eax` 后返回。那个值对调用方**没有语义**（没有一处调用点
//      用它来推进光标 —— 所有调用点都是 `call` 后立刻继续画下一行固定文本）。
//      -> 我们返回"已处理字符数"与之同构，既安全又与原版接近。
//      ★ 与 2 代的区别：2 代渲染器返回的是**真正的 x 累加结果**，
//        调用方（编辑框/列表）靠它定位光标。本作没有那个契约。
//
//   ③ 测量函数有两个：
//          sub_4885B0  累加字形**宽**   （17 调用点）-> RK_MEASURE
//          sub_488CF0  累加字形**高-3** （10 调用点）-> RK_MEASURE_H
//      漏 hook RK_MEASURE_H，多行文字的总行高会算错 -> 垂直居中错位。
//
//   ④ blitVA（sub_432F50）是 __fastcall，**我们不用它**：
//      CJK 走"直接写表面"。该地址仍登记在 profile 里，仅作参考。
//
// ════════════════════════════════════════════════════════════════════════
//  ★★ 关于地址语义：本项目在同一个坑里摔了两次，务必看清
//
//  下面这些 VA 字段填的是 **绝对虚拟地址**（即 IDA 里直接显示的那个值，
//  例如 0xC86FFC），**不是 RVA**。因此读取时必须**原样当地址用**，
//  绝不能再加 ImageBase —— 加了就会变成野地址。
//
//  2 代实机崩溃证据（dump 0x188028）：
//      异常地址 = Army2_Extend_Dll.asi + 0x4223
//      故障目标 = 0x008FE1A8   ← 正好是 0x4FE1A8 + 0x400000
//      寄存器 ECX = 0x004FE1A8 ← 正确的 VA
//
//  另有一个**语义相反**的坑（atlasBaseVA）：
//      该全局里存的是 malloc 得到的**堆指针**，
//      取出来要原样当指针用（见 AtlasBase 的实现注释）。
//
//  两者共同点：都要"把读取到的值当绝对地址/指针直接用"，
//  只要不多加 ImageBase 就是对的。
// ════════════════════════════════════════════════════════════════════════
#pragma once

#include <windows.h>
#include <string>

struct RendererEnv {
    DWORD blitVA = 0;           // ★ 本作不调用（见头文件说明）；登记备查
    DWORD rectVA = 0;           // 矩形裁剪/定位  sub_455BA0
    DWORD atlasOffsetVA = 0;    // ★ VA：WORD[262*font + c]   字形在 atlas 内的偏移
                                //   同时是字形头（宽/高）的入口：base + offs[c]
    DWORD atlasSizeVA = 0;      // ★ VA：DWORD[131*font]，图集**字节大小**
                                //   sub_4883A0 用它 malloc(size) + qmemcpy，
                                //   与 atlasBaseVA（堆指针）配对使用。
    DWORD atlasBaseVA = 0;      // ★ VA：DWORD[131*font]，其**内容**是 malloc 的堆指针
    DWORD charWidthVA = 0;      // ★ VA：word_C86E3C
                                //   ★★ 警告：这**不是宽度表** ★★
                                //   它与 atlasOffsetVA(0xC86DFC) 只差
                                //   0x40 == 32 个 WORD，实为字形偏移表右移
                                //   32 项：CharWidth[c] ≡ atlasOffset[c+32]。
                                //   当宽度用会让累加器一步跳出裁剪框，症状是
                                //   "中英混排从第一个 ASCII 字符起整段消失"。
                                //   代码里已无读取点，仅保留地址备查；
                                //   推进量一律取 SafeGlyphHeader 的 gh[0]。
    DWORD clipRectVA = 0;       // ★ VA：RECT  全局裁剪框 rcSrc2（stru_510A38）
                                //   原版每字形都按它裁剪；漏了会花屏
    // ★ 落笔时的原点偏移（原版在 blit 前做）：
    //   if (当前锁定表面 == 主表面) { x += rc.left; y += rc.top; }
    DWORD rcVA = 0;             // ★ VA：RECT  rc（后备缓冲在主表面中的原点）
    DWORD lockedSurfVA = 0;     // ★ VA：DWORD 当前锁定的表面
    DWORD primarySurfVA = 0;    // ★ VA：DWORD 主表面
    // ★ 表面锁标志：官方每个渲染器开头 `if (!flag) return;`
    //   为 0 时一个字都不画（表面未锁定 / 正在解锁）
    DWORD enabledVA = 0;        // ★ VA：DWORD dword_63C64C
    // 显示区尺寸，仅用作像素写入的内存安全上界（语义裁剪仍靠 rcSrc2）
    DWORD dispWVA = 0;          // ★ VA：int nWidth
    DWORD dispHVA = 0;          // ★ VA：int nHeight
    DWORD surfaceVA = 0;        // ★ VA：BYTE*  目标像素缓冲
    DWORD pitchVA = 0;          // ★ VA：int    目标行距
    int   fontCount = 9;        // 本作实测 9 档（sub_446AA0: i < 9）
};

void RendererSetEnv(const RendererEnv& env);

// 安装时自检：把所有全局量解引用一遍，检查是否落在合理范围并写日志。
// 这类"地址语义搞错"的问题靠它可以在实机第一时间暴露，
// 而不是等到崩在游戏里再回捞 dump。
bool RendererValidateEnv(std::string* report);

// 安装：在 targetRVA 处写 jmp 指向我们的实现。
//   kind     —— 渲染器类别（左对齐/对话框/测量宽/测量高）
//   expect/expectLen —— 安装前的原始字节（再校验一次，防写坏别的代码）
//   patchLen —— 被覆盖的字节数（>=5，且**必须落在指令边界**上）
// 返回是否成功。失败只写日志，绝不半途修改内存。
bool RendererInstallAt(DWORD targetRVA, int kind, const BYTE* expect,
                       int expectLen, int patchLen);

// ── 最小化介入方案：stub（原始函数副本）──────────────────────────────────
//
// 我们在函数入口写了 `jmp 我们的实现`，原函数开头就被覆盖了。
// 为了仍能调用"原始行为"，需要造一个 stub：
//     <原始前 N 字节（被覆盖的那几个）>
//     jmp 原函数 + N
// 这样调用 stub 就等于调用原函数（前 N 字节被原样执行，再跳回后续）。
//
// ★ N 必须等于实际覆盖长度（== patchLen），且该长度已落在**指令边界**上：
//      LEFT      : mov eax,[imm32] + sub esp,30h + test + push ebx  -> 10
//      DIALOG    : mov eax,[imm32] + sub esp,30h + test + push*4    -> 14
//      MEASURE_W : mov ecx,[esp+8] + push ebx + mov + push esi
//                  + shl + add                                       -> 11
//      MEASURE_H : mov ecx,[esp+8] + push esi + mov + mov esi,[esp+8]
//                  + shl                                             -> 14
//   ★ 本作**不能**沿用 4 代 DIALOG 的 15：那会把 `0F 84` 的首字节切进去，
//     stub 会执行到指令中间 -> 必崩（与 3 代"patchLen=5 切碎 sub esp,38h"同类）。
bool RendererBuildStubs();

// 卸载全部已安装的 hook
void RendererUninstall();

// ★ probeOnly 档位用：**只做识别校验，不写任何内存**。
//
//   "验证档位表是否正确"这件事，**读字节比对就已经完成了**
//   （见 Target::VerifySignature）。所以这里只读、比对、写日志，
//   不改一个字节。这比 2 代那种"改写立即数做哨兵"更安全，且证明力相同。
bool RendererProbeAt(DWORD targetRVA, const BYTE* expectOrig, int expectLen);

bool RendererIsInstalled();

// 统计（写日志用）
void RendererStats(LONG* calls, LONG* cjk, LONG* asciiFail);
