// target.h —— 目标识别与配置
//
// 设计原则（承接 1 代，但针对"要兼容多作"做了调整）：
//
//   1 代的做法是"每次只服务一个固定的 exe"，RVA 直接写死在 INI 里。
//   2 代要求同时覆盖 AM2 与 TIS（引擎同源），因此这里改成
//   **profile（档位）+ 身份校验 + 签名校验** 三段式：
//
//     ① 按主模块文件名/大小/时间戳 选中一个 profile
//     ② 校验：该 profile 声明的 RVA 处，字节必须与签名一致
//     ③ 任一环节失败 -> **不 hook，只写日志**（fail-closed）
//
//   ★ 为什么 fail-closed 很重要：如果签名不匹配还硬 hook，会把 jmp 写到
//     错误的函数上，直接让游戏崩溃且难以定位。宁可完全不汉化。
//
// 档位数据来源全部是**实测**，见：
//   ArmyMen2-汉化DLL架构设计.md        （hook 点与调用点数）
//   ArmyMen2-汉化可行性-逆向侦察报告.md （PE 元数据）
#pragma once

#include <windows.h>
#include <string>
#include <vector>

// ── 文字渲染器的类别 ────────────────────────────────────────────────────
//
// ★★ 这是本项目踩过的最大的坑：
//   AM2 里**有 3 个独立的文字渲染器**，不是 1 个。
//   我最初只 hook 了 sub_446930（左对齐），结果主菜单之外的文字
//   （尤其是对话框，走 sub_446AB0）完全没被接管 —— 表现为
//   "被 hook 的文字无法显示"：字符串确实被我们改成了 GBK 中文，
//   但负责画它的那个函数还是原版 ASCII 实现，遇到 >0xA0 的字节
//   查图集越界 -> 什么都不画。
//
//   三个渲染器的差异（IDA 实测）：
//     LEFT   sub_446930  (int x, int y, str, font, ?, color)
//                        逐字符 x += 字宽
//     DIALOG sub_446AB0  (x, y, str, font, ?, l, t, r, b)  带裁剪矩形
//                        被 sub_4569A0 等对话框绘制函数调用
//     CENTER sub_446C50  (x, y, str, font, ?, l, t, r, b)
//                        首字符 x -= 字宽/2；逐字符 x += 字宽 - 3
enum RenderKind {
    RK_LEFT = 0,
    RK_DIALOG,
    RK_CENTER,
};

// ★ 签名缓冲区大小。
//
// 踩过的坑（实机日志报 "签名不匹配 @+32: 期望 01 实得 AE"）：
//   签名实际是 **33** 字节，但这里原先只声明了 32，
//   而 MakeProfiles 里用的是 `memcpy(g.sig, s, sizeof(s))` ——
//   于是 memcpy 越界写 1 字节，把 s[32] 写进了 sigMask[0]；
//   紧接着 memcpy 写 sigMask 又越界 1 字节，把 m[32] 写进了 sigLen。
//   校验循环走到 i=32 时两边都越界读，得到"期望 01 实得 AE"这种
//   看着像签名写错、实则是缓冲区差 1 字节的假象。
//
// 现在：缓冲区留足余量 + static_assert 卡住长度 + 运行时再兜一道边界检查。
#define SIG_MAX 64

// 一个 hook 目标：地址 + 期望签名 + 等价原实现所需的参数
struct HookSite {
    DWORD      rva = 0;
    BYTE       sig[SIG_MAX] = {0};
    BYTE       sigMask[SIG_MAX] = {0};
    int        sigLen = 0;
    int        patchLen = 7;
    RenderKind kind = RK_LEFT;
};

// ── 单个作（游戏）的适配档位 ────────────────────────────────────────────

struct GameProfile {
    std::string id;             // "ArmyMenII" / "ToysInSpace"
    std::string exeName;        // 主模块文件名
    DWORD  imageSizeOfImage = 0;// 可选校验：SizeOfImage
    DWORD  timeStamp = 0;       // 可选校验：PE TimeDateStamp

    // 目标渲染器（要 hook 的 ASCII 文字绘制函数）
    //
    // ★ 保留 rendererVA 作为"主渲染器"（左对齐），其余渲染器放在 hooks[] 里。
    //   两者内容一致，保留 rendererVA 是为了兼容既有代码与日志。
    DWORD  rendererVA = 0;
    BYTE   sig[SIG_MAX] = {0};      // 期望在 rendererVA 处看到的字节
    BYTE   sigMask[SIG_MAX] = {0};  // 1=必须匹配, 0=通配
    int    sigLen = 0;

    // 全部需要 hook 的文字渲染器（含主渲染器；由 MakeProfiles 填充）
    std::vector<HookSite> hooks;

    // 需要改写入口的字节数。
    //
    // ★★ 必须落在**指令边界**上（capstone 实测，见 verify_stub_boundary.py）：
    //   三个渲染器的序言都是
    //       +0  mov eax, [0x4fdf80]   ; A1 80 DF 4F 00  —— 5 字节
    //       +5  sub esp, 0x2c         ; 83 EC 2C        —— 3 字节
    //   指令起点为 {0, 5, 8, ...}，**+7 不是边界**（落在 sub 指令中间）。
    //
    //   我最初用 7（想着"jmp 5 字节 + 2 字节 NOP 更整齐"），
    //   结果把 `sub esp,0x2c` 切成了两半：
    //     * 运行时因为整段被 jmp 跳过，看不出问题
    //     * 但卸载/恢复时、以及任何"跳回 +7"的路径都会执行到指令中间 -> 崩
    //   改为 **5**，恰好一条完整指令。
    int    patchLen = 5;

    // probeOnly = true：只做"识别 + 无副作用标记"，**不接管渲染**。
    //
    // 用途：AM2 的渲染实现已在实机验证通过；TIS 的还没验证
    // （ASCII 字宽与字形头语义未确认）。与其让 TIS 用户拿到花屏，
    // 不如先只在渲染器入口挂一个 5 字节单指令标记：
    //   ① 证明 TIS 的签名与档位表正确（拿到实机日志）
    //   ② 标记本身不改变程序语义（`mov eax,[imm32]` 后接 `ret`，
    //      而原函数开头本就是同一形状的指令），所以不会崩
    // 验证通过后把这个标志去掉即可启用完整渲染。
    bool   probeOnly = false;

    // 游戏自身的绘制原语（供我们的 CJK 分支复用）
    DWORD  blitVA = 0;          // glyph 位图 blit（1bpp RLE -> 目标表面）
    DWORD  rectVA = 0;          // 目标矩形计算/裁剪

    // 字体图集（ASCII 用；我们的实现要**完全接管**渲染器，
    // 所以 ASCII 也必须自己画，需要这两张表 + 目标表面全局量）
    DWORD  atlasOffsetVA = 0;   // WORD[262*font + c]  字形在 atlas 内的偏移
    DWORD  atlasBaseVA   = 0;   // DWORD[131*font]     ★ 存的是 malloc 出来的
                                //   **堆绝对地址**，不是 RVA！
    DWORD  charWidthVA   = 0;   // WORD[262*font + c]  字符步进宽度
    // ★ 全局裁剪矩形 rcSrc2（RECT: left/top/right/bottom）。
    //   原版每个字形都先按它裁剪（见 sub_446930 里的 sub_42E220 调用），
    //   我最初漏了这一步 -> 文字渐显/部分显示时花屏。
    DWORD  clipRectVA    = 0;
    DWORD  rcVA          = 0;   // rc 原点偏移（RECT）
    DWORD  lockedSurfVA  = 0;   // 当前锁定表面
    DWORD  primarySurfVA = 0;   // 主表面
    DWORD  enabledVA     = 0;   // 表面锁标志
    DWORD  dispWVA       = 0;   // 显示区宽
    DWORD  dispHVA       = 0;   // 显示区高
    DWORD  surfaceVA     = 0;   // DWORD              目标像素缓冲指针
    DWORD  pitchVA       = 0;   // DWORD              目标行距（字节）

    // 日志标签（决定日志文件名）
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
