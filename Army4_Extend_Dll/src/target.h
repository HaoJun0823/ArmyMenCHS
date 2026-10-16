// target.h —— 目标识别与配置（Army Men: World War / 4 代）
//
// 与 3 代（Toys in Space）target.h 的关系：
//   ★ 结论：**同引擎、同结构，地址与签名全部不同**。
//     3 代那批签名（`imul ecx, ecx, 0x20C` 系列）在 amww.exe 里
//     **0 命中** —— 4 代把 `font*262` 改成了
//         shl edx,6; add edx,ecx; lea esi,[ecx+edx*2]   （== *262）
//     所以 3 代签名不能直接抄，本文件是**重新实测**的结果。
//
//   ★ 另一个必须留心的差异：**字形表的顺序与 3 代相反**
//       3 代：0x698D6C 偏移表 / 0x698DAC "伪宽度表"（+0x40）
//       4 代：0x6BE524 偏移表 / 0x6BE564 "伪宽度表"（+0x40）
//     语义完全对应（后者都不是宽度表），但**地址不同**，
//     照抄 3 代会把偏移表指到陷阱表上 —— 症状与 3 代一致：
//     "中英混排从第一个 ASCII 字符起整段消失"。
//
// 档位数据来源全部是 **实测**（IDA 反编译 + 逐字节 get_bytes 核对），
// 完整地址表与 patchLen 依据见 docs/12-am4-reverse-findings.md。
//
// 设计原则（承接 1/2/3 代）：
//     ① 按主模块文件名/大小/时间戳 选中一个 profile
//     ② 校验：该 profile 声明的 RVA 处，字节必须与签名一致
//     ③ 任一环节失败 -> **不 hook，只写日志**（fail-closed）
//
//   ★ 为什么 fail-closed 很重要：如果签名不匹配还硬 hook，会把 jmp 写到
//     错误的函数上，直接让游戏崩溃且难以定位。宁可完全不汉化。
#pragma once

#include <windows.h>
#include <string>
#include <vector>

// ── 文字渲染器的类别 ────────────────────────────────────────────────────
//
// ★★ 这是本项目在 2 代踩过的最大的坑，3/4 代同样适用：
//   游戏里**有多个独立的文字渲染器**，不是 1 个。
//   2 代最初只 hook 了左对齐那个，结果主菜单之外的文字（尤其对话框）
//   完全没被接管 —— 表现为"被 hook 的文字无法显示"。
//
//   4 代实测同样是 3 个绘制 + 2 个测量（与 3 代数量、语义一致）：
//     LEFT    0x466320  (x, y, str, font, ?, color)              6 参
//                        沿 **x** 累加：v9 += 字形[0]
//     DIALOG  0x4664A0  (x, y, str, font, char a5, ..., color)   9 参
//                        ★ 4 代是**两级裁剪**：rcSrc2 ∩ &a5（调两次 rectVA）
//                        （3 代只裁 rcSrc2，这是 4 代独有的差异）
//     CENTER  0x466650  (x, y, str, font, char a5, ..., color)   9 参
//                        首字符 x = a1 - 宽/2；沿 **y** 累加 (y += 高 - 3)
enum RenderKind {
    RK_LEFT = 0,
    RK_DIALOG,
    RK_CENTER,
    // ★ 文本**测量**（不是绘制）：给定字符串算宽度。
    //   2 代漏 hook 它 -> 上层拿到错误宽度 -> 拿它当裁剪矩形 -> 花屏。
    //   4 代是 sub_466290：累加 `*(WORD*)(offs[c] + base + 0)`，14 调用点。
    RK_MEASURE,
    // ★ 第二个测量函数 sub_466810：累加 `*(WORD*)(offs[c] + base + 2) - 3`
    //   即字形**高 - 3**，3 调用点（居中菜单算总行高）。
    //   漏 hook 它，居中菜单拿到错误高度 -> 垂直居中错位 / 裁剪矩形算错。
    RK_MEASURE_H,
};

// ★ 签名缓冲区大小（2 代曾因差 1 字节出现过"期望 01 实得 AE"的假象）。
#define SIG_MAX 64

// 一个 hook 目标：地址 + 期望签名 + 等价原实现所需的参数
struct HookSite {
    DWORD      rva = 0;
    BYTE       sig[SIG_MAX] = {0};
    BYTE       sigMask[SIG_MAX] = {0};
    int        sigLen = 0;
    int        patchLen = 5;
    RenderKind kind = RK_LEFT;
};

// ── World War（4 代）适配档位 ────────────────────────────────────────────
struct GameProfile {
    std::string id;             // "WorldWar"
    std::string exeName;        // 主模块文件名（小写）
    DWORD  imageSizeOfImage = 0;// 可选校验：SizeOfImage
    DWORD  timeStamp = 0;       // 可选校验：PE TimeDateStamp

    // 目标渲染器（主渲染器 = 左对齐）
    DWORD  measureVA = 0;       // 文本测量（累加字形宽）
    DWORD  measureHVA = 0;      // 文本测量（累加字形高-3）
    DWORD  rendererVA = 0;      // 主渲染器（左对齐）
    BYTE   sig[SIG_MAX] = {0};
    BYTE   sigMask[SIG_MAX] = {0};
    int    sigLen = 0;

    // 全部需要 hook 的文字渲染器（含主渲染器）
    std::vector<HookSite> hooks;

    // 需要改写入口的字节数（必须落在**指令边界**上）。
    //
    // ★★ 4 代与 3 代的序言形状完全不同，patchLen **不能沿用 3 代的 6**：
    //   4 代三个绘制函数的序言是
    //       +0  mov eax, dword_53C72C  ; A1 <imm32>    —— 5 字节
    //       +5  sub  esp, 30h          ; 83 EC 30      —— 3 字节
    //       +8  测试/清零 + 4 个 push                  —— 各不相同
    //   三个绘制函数的边界分别是 10 / 15 / 15，两个测量函数是 11 / 14。
    //   ★ 若沿用 3 代的 6，会覆盖到 `push` 序列中间；若对 MEASURE_H 取 12，
    //     会落在 `C1 E2 06`(shl edx,6) 的操作数中间 -> stub 执行到指令中间
    //     -> 必崩（与 3 代"patchLen=5 切碎 sub esp,38h"是同一类错误）。
    //   逐字节核算见 docs/12-am4-reverse-findings.md。
    int    patchLen = 6;

    // probeOnly = true：只做"识别 + 无副作用标记"，**不接管渲染**。
    bool   probeOnly = false;

    // 游戏自身的绘制原语（供我们的 CJK 分支复用）
    DWORD  blitVA = 0;          // glyph 位图 blit（1bpp RLE -> 目标表面）
    DWORD  rectVA = 0;          // 目标矩形计算/裁剪

    // 字体图集
    //
    // ★★ 4 代的布局与 3 代**地址不同**，这是本文件最容易抄错的一处：
    //     3 代：0x698D6C(偏移表) -> +0x40 -> 0x698DAC(陷阱表) -> +0x200 -> 0x698F6C(基址)
    //     4 代：0x6BE524(偏移表) -> +0x40 -> 0x6BE564(陷阱表)
    //           0x6BE520(大小)  /  0x6BE724(基址)
    DWORD  atlasOffsetVA = 0;   // word_6BE524：WORD[262*font + c] 字形在 atlas 内的偏移
    DWORD  atlasBaseVA   = 0;   // dword_6BE724：DWORD[131*font]
                                //   ★ 其**内容**是 malloc 出来的**堆绝对地址**，
                                //     不是 RVA！取出来要原样当指针用。
    DWORD  atlasSizeVA   = 0;   // dword_6BE520：DWORD[131*font] 图集字节大小
                                //   （3 代没有单独登记这个字段）
    DWORD  charWidthVA   = 0;   // word_6BE564 —— ★★ 注意：**不是宽度表** ★★
                                // 与 atlasOffsetVA 只差 0x40 == 32 个 WORD，
                                // 实为字形偏移表右移 32 项，当宽度用会导致
                                // "混排串从第一个 ASCII 字符起整段消失"。
                                // 仅保留地址备查，代码里已无读取点。
    // ★ 全局裁剪矩形 rcSrc2（RECT: left/top/right/bottom）
    DWORD  clipRectVA    = 0;
    DWORD  rcVA          = 0;   // rc 原点偏移（RECT）
    DWORD  lockedSurfVA  = 0;   // 当前锁定表面
    DWORD  primarySurfVA = 0;   // 主表面
    DWORD  enabledVA     = 0;   // 表面锁标志（dword_53C72C）
    DWORD  dispWVA       = 0;   // 显示区宽（nWidth）
    DWORD  dispHVA       = 0;   // 显示区高（nHeight）
    DWORD  surfaceVA     = 0;   // DWORD              目标像素缓冲指针
    DWORD  pitchVA       = 0;   // DWORD              目标行距（字节）

    std::string logTag;
};

class Target {
public:
    // 识别当前进程运行的是哪个作。成功返回 true 并填充 out。
    static bool Detect(GameProfile& out);

    // 校验 profile 的签名是否与当前内存一致（不改任何东西）
    static bool VerifySignature(const GameProfile& gp, std::string& why);

    // 取主模块信息
    static bool GetMainModuleInfo(std::string& exeName, DWORD& sizeOfImage,
                                  DWORD& timeStamp);

    // 取内置档位表
    static const std::vector<GameProfile>& BuiltinProfiles();
};
