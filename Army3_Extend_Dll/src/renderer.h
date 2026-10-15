// renderer.h —— 文字渲染器（ASCII + CJK），Army Men: Toys in Space（3 代）
//
// 背景（✅ 实测，本轮 IDA 逆向）：
//   游戏原本的渲染器 sub_450EA7 是 **ASCII-only**：
//       for each c: 查 atlasOffset[262*font + c] -> 取 atlas 里的 2xWORD 头
//                   -> rectVA 算目标矩形 -> blitVA 画到表面
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
// ★★ 3 代与 2 代的决定性差异（决定了本文件不能照搬 2 代）：
//
//   ① 渲染器**返回 void**，不返回"文本结束后的 x"。
//      2 代：sub_446930 等返回 int，RenderCore 靠 stub 的返回值推进 ASCII 光标。
//      3 代：LEFT 内部用 `v18 += 字形宽` 推进，函数签名就是 `void`。
//      -> 靠返回值推进的契约**不存在**。ASCII 推进量必须自己从字形头取：
//           LEFT / DIALOG : acc += 字形[0]          （宽）
//           CENTER        : acc += 字形[1] - 3      （高 - 3，且沿 **y** 轴累加）
//         这正是原函数内部的做法（见 renderer.cpp 的 GlyphWidth/GlyphHeight）。
//
//   ② 测量函数有**两个**：
//           sub_450E3A  累加字形**宽**   （14 调用点）-> RK_MEASURE
//           sub_451267  累加字形**高-3** （ 3 调用点）-> RK_MEASURE_H
//      2 代只有一个（算宽）。漏 hook RK_MEASURE_H，居中菜单的裁剪矩形会算错。
//
//   ③ blitVA 在 3 代**不被我们调用**：
//      CJK 走"直接写表面"，ASCII 走 stub，都需要我们自己去调 blit。
//      该地址仍登记在 profile 里，仅作参考（其调用约定在反编译里
//      被推断成 __fastcall，与我们无关，不去趟这趟浑水）。
//
// ════════════════════════════════════════════════════════════════════════
//  ★★ 关于地址语义：本项目在同一个坑里摔了两次，务必看清
//
//  下面这些 VA 字段填的是 **绝对虚拟地址**（即 IDA 里直接显示的那个值，
//  例如 0x522EF8），**不是 RVA**。因此读取时必须**原样当地址用**，
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

struct RendererEnv {
    DWORD blitVA = 0;           // ★ 3 代不调用（见头文件说明）；登记备查
    DWORD rectVA = 0;           // 矩形裁剪/定位 sub_435EDE
    DWORD atlasOffsetVA = 0;    // ★ VA：WORD[262*font + c]   字形在 atlas 内的偏移
                                //   同时是字形头（宽/高）的入口：base + offs[c]
    DWORD atlasBaseVA = 0;      // ★ VA：DWORD[131*font]，其**内容**是 malloc 的堆指针
    DWORD charWidthVA = 0;      // ★ VA：WORD[262*font + c]   字符步进宽度
                                //   （原版只在"测量函数的出参"里用到它）
    DWORD clipRectVA = 0;       // ★ VA：RECT  全局裁剪框 rcSrc2
                                //   原版每字形都按它裁剪；漏了会花屏
    // ★ 落笔时的原点偏移（原版在 blit 前做）：
    //   if (当前锁定表面 == 主表面) { x += rc.left; y += rc.top; }
    DWORD rcVA = 0;             // ★ VA：RECT  rc（后备缓冲在主表面中的原点）
    DWORD lockedSurfVA = 0;     // ★ VA：DWORD 当前锁定的表面
    DWORD primarySurfVA = 0;    // ★ VA：DWORD 主表面
    // ★ 表面锁标志：官方每个渲染器开头 `if (!flag) return;`
    //   为 0 时一个字都不画（表面未锁定 / 正在解锁）
    DWORD enabledVA = 0;        // ★ VA：DWORD dword_521D2C
    // 显示区尺寸，仅用作像素写入的内存安全上界（语义裁剪仍靠 rcSrc2）
    DWORD dispWVA = 0;          // ★ VA：int nWidth
    DWORD dispHVA = 0;          // ★ VA：int nHeight
    DWORD surfaceVA = 0;        // ★ VA：BYTE*  目标像素缓冲
    DWORD pitchVA = 0;          // ★ VA：int    目标行距
};

void RendererSetEnv(const RendererEnv& env);

// 安装时自检：把所有全局量解引用一遍，检查是否落在合理范围并写日志。
// 这类"地址语义搞错"的问题靠它可以在实机第一时间暴露，
// 而不是等到崩在游戏里再回捞 dump。
bool RendererValidateEnv(std::string* report);

// 安装：在 targetRVA 处写 jmp 指向我们的实现。
//   kind     —— 渲染器类别（左对齐/对话框/居中/测量宽/测量高）
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
//      LEFT/DIALOG/CENTER : push ebp + mov ebp,esp + sub esp,38h  -> 6
//      MEASURE_W          : mov ecx,[esp+8] + push esi            -> 5
//      MEASURE_H          : mov ecx,[esp+8] + mov edx,[esp+4]     -> 8
//   ★ 3 代**不能**沿用 2 代的 patchLen=5：那会把 `sub esp,38h`（字节 3~5）
//     切成两半，stub 会执行到指令中间 -> 必崩（2 代 target.h 记录过此坑）。
bool RendererBuildStubs();

// 卸载全部已安装的 hook
void RendererUninstall();

// ★ probeOnly 档位用：**只做识别校验，不写任何内存**。
//
//   ★ 与 2 代的区别：2 代的标记之所以能"无副作用"，是因为它利用
//     "序言恰好是 5 字节的 mov eax,[imm32]" 这一形状，把立即数换成哨兵。
//     3 代序言是 `push ebp; mov ebp,esp; sub esp,38h`，没有那个形状，
//     硬套会破坏栈帧 -> 必崩。
//
//   而"验证档位表是否正确"这件事，**读字节比对就已经完成了**
//   （见 Target::VerifySignature）。所以 3 代的做法是：读、比对、写日志，
//   不改一个字节。这比 2 代的标记更安全，且证明力相同。
bool RendererProbeAt(DWORD targetRVA, const BYTE* expectOrig, int expectLen);

bool RendererIsInstalled();

// 统计（写日志用）
void RendererStats(LONG* calls, LONG* cjk, LONG* asciiFail);
