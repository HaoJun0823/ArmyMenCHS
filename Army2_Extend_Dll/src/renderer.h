// renderer.h —— 文字渲染器（ASCII + CJK）
//
// 背景（✅ 实测）：
//   游戏原本的渲染器 sub_446930(AM2) / sub_450EA7(TIS) 是 **ASCII-only**：
//       for each c: 查 atlasOffset[262*font + c] -> 取 atlas 里的 2xWORD 头
//                   -> rectVA 算目标矩形 -> blitVA(glyph, w, h, dx, dy, color)
//   中文版把**同一个函数**换成了 CJK 版 sub_446B00，多了一条分支：
//       if (c > 0xA0) 从 ..\Hzk16 取 13x13 点阵，直接写目标表面
//
//   我们的做法与官方一致：**完全接管该函数**（不改游戏其它字节），
//   自己实现 ASCII + CJK 两条路径。
//
// 为什么"完全接管"而不是"只处理双字节、单字节转调原函数"：
//   原函数序言含 `mov eax, [g_enabled]` + `sub esp, N`（栈帧），
//   做 trampoline 需要处理栈调整，指令边界一旦算错就是崩溃。
//   完全接管只需在我们自己的函数里重写那 ~40 行逻辑，风险更可控。
//
// ⚠️ 尚未实机验证的点（见文档 §8）：
//   * ASCII 图集的字形头确切语义（w/h 是否需 +1，left bearing 如何取）
//   * 调用方在每次调用前是否重设选中字体（若是，我们的 font 索引才准）
//   这两点都会在日志里留下可诊断痕迹。
#pragma once

#include <windows.h>

// ════════════════════════════════════════════════════════════════════════
//  ★★ 关于地址语义：本项目在同一个坑里摔了两次，务必看清
//
//  下面这些 VA 字段填的是 **绝对虚拟地址**（即 IDA 里直接显示的那个值，
//  例如 0x4FE1A8），**不是 RVA**。因此读取时必须**原样当地址用**，
//  绝不能再加 ImageBase —— 加了就会变成 0x8FE1A8 这种野地址。
//
//  实机崩溃证据（dump 0x188028）：
//      异常地址 = Army2_Extend_Dll.asi + 0x4223
//      故障目标 = 0x008FE1A8   ← 正好是 0x4FE1A8 + 0x400000
//      寄存器 ECX = 0x004FE1A8 ← 正确的 VA
//    即"把 VA 又加了一次镜像基址"，读野地址直接崩。
//
//  另有一个**语义相反**的坑（atlasBaseVA）：
//      该全局里存的是 malloc 得到的**堆指针**，
//      取出来要原样当指针用（见 AtlasBase 的实现注释）。
//
//  两者共同点：都要"把读取到的值当绝对地址/指针直接用"，
//  只要不多加 ImageBase 就是对的。
// ════════════════════════════════════════════════════════════════════════
struct RendererEnv {
    DWORD blitVA = 0;           // 函数 VA（安装时按 VA-ImageBase 用也可，见 .cpp）
    DWORD rectVA = 0;
    DWORD atlasOffsetVA = 0;    // ★ VA：WORD[262*font + c]   字形在 atlas 内的偏移
    DWORD atlasBaseVA = 0;      // ★ VA：DWORD[131*font]，其**内容**是 malloc 的堆指针
    DWORD charWidthVA = 0;      // ★ VA：WORD[262*font + c]   字符步进宽度
    DWORD clipRectVA = 0;       // ★ VA：RECT  全局裁剪框 rcSrc2
                                //   原版每字形都按它裁剪；漏了会花屏
    // ★ 落笔时的原点偏移（原版在 blit 前做）：
    //   if (当前锁定表面 == 主表面) { x += rc.left; y += rc.top; }
    DWORD rcVA = 0;             // ★ VA：RECT  rc（后备缓冲在主表面中的原点）
    DWORD lockedSurfVA = 0;     // ★ VA：DWORD 当前锁定的表面
    DWORD primarySurfVA = 0;    // ★ VA：DWORD 主表面
    // ★ 表面锁标志：官方每个渲染器开头 `if (!flag) return;`
    //   为 0 时一个字都不画（表面未锁定 / 正在解锁）
    DWORD enabledVA = 0;        // ★ VA：DWORD dword_4FDF80
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
//   kind     —— 渲染器类别（左对齐/对话框/居中），决定 ASCII 步进与首字符偏移
//   expect/expectLen —— 安装前的原始字节（再校验一次，防写坏别的代码）
//   patchLen —— 被覆盖的字节数（>=5）
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
// ★ 为什么需要：ASCII 段若由我们复刻，就要自己保证
//   字体/裁剪/返回值等全部语义正确 —— 本项目已在这里连摔 4 次。
//   转调 stub 则让游戏自己处理，零行为差异。
bool RendererBuildStubs();

// 卸载全部已安装的 hook
void RendererUninstall();

// probeOnly 档位用：在渲染器入口挂一个**无副作用的标记**（5 字节单指令）。
//
// 目的：验证签名与档位表是否正确，但**不接管渲染**。
// 做法与安全性依据（见 renderer.cpp 说明）：
//   原函数序言都是 `mov eax, [imm32]`（5 字节，A1 xx xx xx xx），
//   标记写成 `<原指令，但立即数换成我们的哨兵地址>; ret` ——
//   调用该函数会立刻返回（返回值 = 我们读到的哨兵值，非 0，与原路径
//   首个判断"未启用则跳过"方向一致），不会写入任何表面、不会崩。
//   所以这是"能证明流程跑通、又不冒未验证渲染风险"的最小验证手段。
bool RendererProbeAt(DWORD targetRVA, BYTE* expectOrig, int expectLen);

bool RendererIsInstalled();

// 统计（写日志用）
void RendererStats(LONG* calls, LONG* cjk, LONG* asciiFail);
