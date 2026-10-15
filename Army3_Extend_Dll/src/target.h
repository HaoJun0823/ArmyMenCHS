// target.h —— 目标识别与配置（Army Men: Toys in Space / 3 代）
//
// 与 2 代 target.h 的关系：
//   2 代要同时覆盖 AM2 英文版 / AM2 官方简体中文版 / TIS 三个档位，
//   3 代**只需要 TIS 一个档位**，因此这里做了大幅简化：
//     ① 去掉多作枚举，profile 表只剩一条
//     ② 去掉 strings.cpp 相关的内存串补丁（3 代文本全在 strings\strings.txt）
//     ③ RenderKind 由 4 个增至 5 个 —— 3 代有**两个**测量函数（见下）
//
// 档位数据来源全部是**实测**（IDA 反编译 + 逐字节 disasm 核对），
// 完整地址表与 patchLen 依据见本目录的 target.cpp；
// 文本载体与翻译范围见 docs/08-am3-i18n-inventory.md。
//
// 设计原则（承接 1/2 代）：
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
// ★★ 这是本项目在 2 代踩过的最大的坑，3 代同样适用：
//   游戏里**有 3 个独立的文字渲染器**，不是 1 个。
//   2 代最初只 hook 了左对齐那个，结果主菜单之外的文字（尤其对话框）
//   完全没被接管 —— 表现为"被 hook 的文字无法显示"：字符串确实被改成了
//   GBK 中文，但负责画它的那个函数还是原版 ASCII 实现，遇到 >0xA0 的字节
//   查图集越界 -> 什么都不画。
//
//   3 代实测同样是 3 个渲染器：
//     LEFT   0x450EA7  (int x,int y,char* Str,int font,int,int color)   6 参
//                       逐字符 x += 字形宽
//     DIALOG 0x450FCF  (x,y,Str,font,char a5,int a6..a8,int color)     9 参
//                       带裁剪矩形（&a5 即 RECT）
//     CENTER 0x451114  (x,y,Str,font,char a5,int a6..a8,int color)     9 参
//                       首字符 x = a1 - 宽/2；沿 **y** 累加 (y += 高 - 3)
enum RenderKind {
    RK_LEFT = 0,
    RK_DIALOG,
    RK_CENTER,
    // ★ 文本**测量**（不是绘制）：给定字符串算宽度。
    //   2 代漏 hook 它 -> 上层拿到错误宽度 -> 拿它当裁剪矩形 -> 花屏。
    //   3 代这个函数是 sub_450E3A：
    //       for each c: i += *(WORD*)(word_698D6C[262*a2+c] + atlasBase + 0)
    //       if (a3) { *a3 = i; a3[1] = *(WORD*)(word_698DAC[262*a2] + base + 2); }
    //   即累加**字形宽**，14 个调用点。
    RK_MEASURE,
    // ★★ 3 代**新增**的第二个测量函数 sub_451267：
    //       result += *(WORD*)(word_698D6C[262*a2+c] + atlasBase + 2) - 3;
    //   即累加**字形高 - 3**，3 个调用点（居中菜单，算总行高）。
    //   ★ 2 代没有这个函数，是本轮逆向新发现的；漏 hook 它，
    //     居中菜单拿到错误高度 -> 垂直居中错位 / 裁剪矩形算错。
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

// ── TIS（3 代）适配档位 ─────────────────────────────────────────────────
struct GameProfile {
    std::string id;             // "ToysInSpace"
    std::string exeName;        // 主模块文件名（小写）
    DWORD  imageSizeOfImage = 0;// 可选校验：SizeOfImage
    DWORD  timeStamp = 0;       // 可选校验：PE TimeDateStamp

    // 目标渲染器（主渲染器 = 左对齐）
    DWORD  measureVA = 0;       // 文本测量（累加字形宽）
    DWORD  measureHVA = 0;      // ★ 3 代新增：文本测量（累加字形高-3）
    DWORD  rendererVA = 0;      // 主渲染器（左对齐）
    BYTE   sig[SIG_MAX] = {0};
    BYTE   sigMask[SIG_MAX] = {0};
    int    sigLen = 0;

    // 全部需要 hook 的文字渲染器（含主渲染器）
    std::vector<HookSite> hooks;

    // 需要改写入口的字节数（必须落在**指令边界**上）。
    //
    // ★★ 3 代与 2 代的序言形状完全不同，patchLen **不能沿用 2 代的 5**：
    //   3 代三个渲染器的序言都是
    //       +0  push ebp          ; 55           —— 1 字节
    //       +1  mov  ebp, esp     ; 8B EC        —— 2 字节
    //       +3  sub  esp, 38h     ; 83 EC 38     —— 3 字节
    //   指令起点为 {0, 1, 3, 6, ...}。
    //   ★ 若沿用 5，就会把 `sub esp,38h`（字节 3~5）切成两半 ——
    //     运行时因为整段被 jmp 跳过看不出问题，但 stub 构造与恢复会
    //     执行到指令中间 -> 崩。必须用 **6**（恰好三条完整指令）。
    int    patchLen = 6;

    // probeOnly = true：只做"识别 + 无副作用标记"，**不接管渲染**。
    bool   probeOnly = false;

    // 游戏自身的绘制原语（供我们的 CJK 分支复用）
    DWORD  blitVA = 0;          // glyph 位图 blit（1bpp RLE -> 目标表面）
    DWORD  rectVA = 0;          // 目标矩形计算/裁剪

    // 字体图集（ASCII 用；我们的实现要完全接管渲染器）
    DWORD  atlasOffsetVA = 0;   // WORD[262*font + c]  字形在 atlas 内的偏移
    DWORD  atlasBaseVA   = 0;   // DWORD[131*font]     ★ 存的是 malloc 出来的
                                //   **堆绝对地址**，不是 RVA！
    DWORD  charWidthVA   = 0;   // word_698DAC —— ★★ 注意：**不是宽度表** ★★
                                // 与 atlasOffsetVA 只差 0x40 == 32 个 WORD，
                                // 实为字形偏移表右移 32 项，当宽度用会导致
                                // "混排串从第一个 ASCII 字符起整段消失"。
                                // 仅保留地址备查，代码里已无读取点。
    // ★ 全局裁剪矩形 rcSrc2（RECT: left/top/right/bottom）
    DWORD  clipRectVA    = 0;
    DWORD  rcVA          = 0;   // rc 原点偏移（RECT）
    DWORD  lockedSurfVA  = 0;   // 当前锁定表面
    DWORD  primarySurfVA = 0;   // 主表面
    DWORD  enabledVA     = 0;   // 表面锁标志（dword_521D2C）
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
