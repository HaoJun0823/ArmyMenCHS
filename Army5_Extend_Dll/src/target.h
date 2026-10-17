// target.h —— 目标识别与配置（Army Men: Air Tactics / 本作，仓库代号 ArmyMan5）
//
// ════════════════════════════════════════════════════════════════════════
//  与 3 代（Toys in Space）/ 4 代（World War）的关系
// ════════════════════════════════════════════════════════════════════════
//
//  结论：**同引擎家族、同字体图集数据结构，但地址与函数形态全部不同**。
//  本作（amat.exe）的实测结论全部来自 IDA 反编译 + 逐字节字节核对，
//  没有一条是从 3/4 代抄来的。完整地址表见 docs/15-am5-reverse-findings.md。
//
//  ① 字体索引算法：与 4 代同构（shl/add/lea 做 font*262），
//     3 代那批 `imul ecx, ecx, 0x20C` 签名在本作 **0 命中**。
//  ② 序言形状：与 4 代**几乎逐字节相同**（A1 imm32; 83 EC 30; ...），
//     但 **patchLen 不同**：4 代 10/15/11/14，本作 10/14/11/14。
//     原因：本作 DIALOG 序言是 `test eax,eax` + push*4（14 字节），
//     4 代是 `xor edx,edx` + push*3 + `cmp eax,edx` + push（15 字节）。
//  ③ 本作**没有** 4 代那个"居中沿 y 累加"的渲染器（CENTER）。
//     实际只有 3 个绘制函数：LEFT / DIALOG / GRADIENT（渐变文字）。
//  ④ 本作多出一个 GRADIENT（sub_488B90）：它用的是一套**独立的单字节字体**
//     （word_C87E5C[256] + dword_C8805C），只被"选项屏" sub_498D70 的
//     固定英文用。★ 中文绝不会走它，因此**不接管**它的渲染，
//     仅在**文本测量**层面兼容（见下方 RK_MEASURE 的注释）。
//  ⑤ 剪裁：LEFT 一级（rcSrc2），DIALOG / GRADIENT **两级**（rcSrc2 ∩ 调用方 RECT）。
//
// ════════════════════════════════════════════════════════════════════════
//  地址语义约定（★ 本项目在 2 代因为这个摔过两次，务必先读）
// ════════════════════════════════════════════════════════════════════════
//
//  本文件里凡是**与函数指针/全局量一起使用**的地址，一律写成 IDA 显示的
//  **绝对 VA**（如 0x488640、0xC86DFC），读取时**不得**再加 ImageBase。
//
//  唯一的例外是 HookSite.rva —— 那是给 VirtualProtect/memcpy 用的
//  **映像内 RVA**，由 VA - ImageBase 换算得来。
//
//  ★ 本作 ImageBase = 0x400000（实测），且 **DllCharacteristics 无 DYNAMICBASE**，
//    即系统不会给主模块做地址随机化 —— 这对我们是有利的（VA 恒定）。
//    但**依然按 VA-ImageBase 换算**，不赌"FileOffset == RVA"这个巧合。
//
//  设计原则（承接 1/2/3/4 代）：
//     ① 按主模块文件名/大小/时间戳 选中一个 profile
//     ② 校验：该 profile 声明的 RVA 处，字节必须与签名一致
//     ③ 任一环节失败 -> **不 hook，只写日志**（fail-closed）
//
//  ★ 为什么 fail-closed 很重要：如果签名不匹配还硬 hook，会把 jmp 写到
//    错误的函数上，直接让游戏崩溃且难以定位。宁可完全不汉化。
#pragma once

#include <windows.h>
#include <string>
#include <vector>

// ── 文字渲染器的类别 ────────────────────────────────────────────────────
//
// ★★ 这是本项目在 2 代踩过的最大的坑，本作同样适用：
//   游戏里**有多个独立的文字渲染器**，不是 1 个。
//   2 代最初只 hook 了左对齐那个，结果主菜单之外的文字（尤其对话框）
//   完全没被接管 —— 表现为"被 hook 的文字无法显示"。
//
//   本作实测：3 个绘制 + 2 个测量。
enum RenderKind {
    // 左对齐，一级裁剪（只有全局 rcSrc2），裁光则**整个函数返回**
    //   sub_488640(x, y, str, font, a5, color)      6 参，返回 int
    //   a5 原版**未使用**（反编译里只见 arg_C=font、arg_14=color）
    RK_LEFT = 0,

    // 对话框，两级裁剪（rcSrc2 ∩ 调用方 RECT），裁光只**跳过该字形**
    //   sub_4887F0(x, y, str, font, l, t, r, b, color)   9 参，返回 int
    RK_DIALOG,

    // 渐变文字，两级裁剪，逐字带 `sub_488A60` 算出的渐变颜色
    //   sub_488B90(x, y, str, font?, l, t, r, b, unknown)  9 参，返回 int
    //   ★ 它用的是**另一套单字节字体表** word_C87E5C[256] / dword_C8805C，
    //     与 C86DFC/C86FFC 完全无关。中文不会走到这里，
    //     故**不接管绘制**；本枚举值仅用于"识别 + 记日志"。
    RK_GRADIENT,

    // ★ 文本**测量**（不是绘制）：给定字符串算宽度。
    //   2 代漏 hook 它 -> 上层拿到错误宽度 -> 拿它当裁剪矩形 -> 花屏。
    //   本作是 sub_4885B0：`(str, font, int* out)`，
    //   累加 `*(WORD*)(atlas + offs[c] + 0)`，17 个调用点。
    //   ★ out[1] 原版填的是 `字形[1]`（高），必须由原实现填。
    RK_MEASURE,

    // ★ 第二个测量函数 sub_488CF0：`(str, font)` -> int
    //   累加 `*(WORD*)(atlas + offs[c] + 2) - 3`，即字形**高 - 3**，10 个调用点。
    //   漏 hook 它，多行文字的总行高会算错 -> 垂直居中错位 / 裁剪矩形算错。
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

// ── Air Tactics（本作）适配档位 ──────────────────────────────────────────
struct GameProfile {
    std::string id;             // "AirTactics"
    std::string exeName;        // 主模块文件名（小写）
    DWORD  imageSizeOfImage = 0;// 可选校验：SizeOfImage
    DWORD  timeStamp = 0;       // 可选校验：PE TimeDateStamp

    // 目标渲染器（主渲染器 = 左对齐）
    DWORD  measureVA = 0;       // 文本测量（累加字形宽）
    DWORD  measureHVA = 0;      // 文本测量（累加字形高-3）
    DWORD  rendererVA = 0;      // 主渲染器（左对齐）
    DWORD  gradientVA = 0;      // 渐变文字（只记录，不接管）
    BYTE   sig[SIG_MAX] = {0};
    BYTE   sigMask[SIG_MAX] = {0};
    int    sigLen = 0;

    // 全部需要 hook 的文字渲染器（含主渲染器）
    std::vector<HookSite> hooks;

    // 需要改写入口的字节数（必须落在**指令边界**上）。
    //
    // ★★ 本作与 4 代的序言形状几乎相同，但 patchLen **不能直接抄 4 代**：
    //   LEFT      : mov eax,[imm32](5) + sub esp,30h(3) + test(2) + push ebx(1)
    //               -> 边界 10   （与 4 代相同）
    //   DIALOG    : 5 + 3 + test(2) + push ebx/ebp/esi/edi(4)
    //               -> 边界 14   ★ 4 代是 15（它中间多 cmp/xor 两条）
    //   GRADIENT  : 5 + 3(sub 28h) + xor edx(2) + push*3(3) + cmp(2) + push(1)
    //               -> 边界 16   （本作独有，4 代无此函数）
    //   MEASURE   : mov(4) + push ebx(1) + mov(2) + push esi(1) + shl(3) + add(2)
    //               -> 边界 11   （与 4 代相同）
    //   MEASURE_H : mov(4) + push esi(1) + mov(2) + mov esi,[esp+8](4) + shl(3)
    //               -> 边界 14   （与 4 代相同）
    //   逐字节核算见 docs/15-am5-reverse-findings.md。
    int    patchLen = 0;

    // probeOnly = true：只做"识别 + 无副作用标记"，**不接管渲染**。
    bool   probeOnly = false;

    // 游戏自身的绘制原语（供我们的 CJK 分支复用）
    DWORD  blitVA = 0;          // glyph 位图 blit（RLE -> 目标表面）
    DWORD  rectVA = 0;          // 目标矩形计算/裁剪  sub_455BA0

    // 字体图集
    //
    // ★★ 本作的布局与 3/4 代**地址不同**，这是本文件最容易抄错的一处：
    //     3 代：0x698D6C(偏移表) -> +0x40 -> 0x698DAC(伪宽度表) -> +0x200 -> 0x698F6C(基址)
    //     4 代：0x6BE524(偏移) / 0x6BE564(伪宽度) / 0x6BE520(大小) / 0x6BE724(基址)
    //     本作：0xC86DFC(偏移) / 0xC86E3C(伪宽度) / 0xC86DF8(大小) / 0xC86FFC(基址)
    DWORD  atlasOffsetVA = 0;   // word_C86DFC：WORD[262*font + c] 字形在 atlas 内的偏移
    DWORD  atlasBaseVA   = 0;   // dword_C86FFC：DWORD[131*font]
                                //   ★ 其**内容**是 malloc 出来的**堆绝对地址**，不是 RVA！
    DWORD  atlasSizeVA   = 0;   // dword_C86DF8：DWORD[131*font] 图集字节大小
    DWORD  charWidthVA   = 0;   // word_C86E3C —— ★★ 注意：**不是宽度表** ★★
                                // 与 atlasOffsetVA 只差 0x40 == 32 个 WORD，
                                // 实为字形偏移表右移 32 项。代码里已无读取点。
    // ★ 全局裁剪矩形 rcSrc2（RECT: left/top/right/bottom）  stru_510A38
    DWORD  clipRectVA    = 0;
    DWORD  rcVA          = 0;   // rc 原点偏移（RECT）  0x510A58
    DWORD  lockedSurfVA  = 0;   // 当前锁定的表面  dword_651850
    DWORD  primarySurfVA = 0;   // 主表面          dword_64119C
    DWORD  enabledVA     = 0;   // 表面锁标志      dword_63C64C
    DWORD  dispWVA       = 0;   // 显示区宽（nWidth）
    DWORD  dispHVA       = 0;   // 显示区高（nHeight）
    DWORD  surfaceVA     = 0;   // DWORD              目标像素缓冲指针  dword_63C874
    DWORD  pitchVA       = 0;   // DWORD              目标行距（字节）  dword_641198

    // 字体档位数量（本作实测 9：sub_446AA0 里 `for (i = 0; i < 9; ++i)`）
    int    fontCount = 9;

    // ── CD 校验屏蔽（sub_447450）──────────────────────────────────────
    //
    // 本作启动时会走 sub_447450：
    //     枚举所有盘符 -> GetDriveTypeA()==5(CD-ROM)
    //     -> GetVolumeInformationA() 取卷标，必须等于 "AMAT PC"
    //     -> 命中则 sprintf(byte_671288, "%s_Setup\\", 盘符) 并置
    //        dword_6713B0=1
    //     -> 最后用 sub_43F4A0("audio/music") 探测是否真能切到音频目录；
    //        探不到就 MessageBoxA("Please insert the ... CD.") 并 return 0
    //     -> _WinMain 里 `test eax,eax / jz 退出`：返回 0 直接结束进程
    //
    // ★ byte_671288 与 dword_6713B0 是后续 40 处目录切换的回退依据：
    //     sub_43F4A0 / sub_4400B0 都是
    //         if (_chdir("<cwd>\\<子目录>")) {
    //             if (dword_6713B0) _chdir(byte_671288 + 子目录);
    //         }
    //   所以只让 sub_447450 返回 1 是不够的 —— 那样 dword_6713B0 仍为 0，
    //   凡是本地缺目录的地方都会静默失败（尤其音乐）。
    //   → 本档位另有 cdSpoofVA，安装时把 byte_671288 填成 exe 目录、
    //     dword_6713B0 置 1，然后把 cdDetectVA 整函数改成"返回 1"。
    //
    //   ★ 全程**不写 exe 文件、不碰注册表**，退出即还原。
    DWORD  cdDetectVA    = 0;   // sub_447450：CD 检测函数入口（被改写成 return 1）
    DWORD  cdRootBufVA   = 0;   // byte_671288：256 字节，"<根>\" 会被写到这里
    DWORD  cdReadyFlagVA = 0;   // dword_6713B0：1 = "CD 根可用"
    DWORD  cdReadyFlag2VA= 0;   // dword_6713BC：原版与上一项同时置 1（无读取点，仅保持一致）
    int    cdDetectPatchLen = 0;// 被覆盖的字节数（必须落在指令边界）
    BYTE   cdDetectSig[SIG_MAX] = {0};   // cdDetectVA 处期望的原始字节
    BYTE   cdDetectSigMask[SIG_MAX] = {0};
    int    cdDetectSigLen = 0;

    // ── 长文本换行的汉字边界修复（sub_42EF50）──────────────────────
    //
    //  sub_42EF50 把长文本按显示宽度切成多行，存进"每行 129 字节 × 16 行"
    //  的数组。它的核心循环是**逐字节**复制 + 超宽时**逐字节**回退找空白：
    //      while (*src) {
    //          *dst++ = *src++;
    //          if (测宽 < maxWidth) continue;
    //          do { --src; --dst; --count;
    //               if (count < 0) goto done;
    //          } while (!isspace(*src));
    //      done:
    //          *dst = 0;  strcpy(&lines[128*n+n+88], buf);
    //      }
    //
    //  ★ 英文靠空格断行，永远停得下来。
    //  ★ 中文整句无空格 -> 一路退到 count<0，在任意字节上截断，
    //    截点落在 GBK 汉字中间时，下一行从半个汉字开始 -> 整行乱码。
    //
    //  → 修法：把回退循环换成"感知 GBK 边界"的版本（见 wrapfix.h）。
    DWORD  wrapRollbackVA = 0;   // 0x42F019：回退循环起点
    DWORD  wrapDoneVA     = 0;   // 0x42F02E：回退结束落点（trampoline 跳这里）
    int    wrapPatchLen   = 0;   // 覆盖字节数（21，已核对落在指令边界）
    // ★ 默认 false。改了 sub_42EF50 的回退循环三轮，症状一字不变，
    //   说明这条字幕的乱码与崩溃另有原因。先关闭，拿一个稳定基线。
    bool   wrapEnabled    = false;
    BYTE   wrapSig[SIG_MAX] = {0};
    BYTE   wrapSigMask[SIG_MAX] = {0};
    int    wrapSigLen = 0;

    // ── 长文本分行"多写一行"的修复（sub_42EF50）───────────────────
    //
    //  ★ 根因（IDA 反汇编 + x32dbg 运行时数据双向确认）：
    //    sub_42EF50 在 0x42F067 起的行末处理是
    //        cmp  byte [ebx], 0      ; 源串是否结束
    //        jz   0x42F074            ; ★ 已结束也去"写一行"
    //        test al, al              ; al = 本轮是否断行
    //        jz   0x42F130            ; 没断行 -> 回循环
    //        ...
    //        0x42F082: mov [ebp+8ECh], edx   ; 行数 +1
    //        0x42F0FE: strcpy(行数组[n], buf)
    //    由于 0x42F06A 的 jz，"源串已结束"也落进写行路径，
    //    于是每次分行结束都多写一行，那行是从未初始化的堆内存。
    //    x32dbg 实读到第 2、3 行是重复的 0DF0ADBA（VC++ 已释放堆标记），
    //    sub_42EB90 按行数绘制它们 -> 整行乱码。
    //
    //  修法：源串已结束 -> 跳 0x42F130（循环顶部，会再判一次并正常收尾）。
    DWORD  lineSiteVA   = 0;   // 0x42F06A
    DWORD  lineLoopTopVA= 0;   // 0x42F130
    DWORD  lineWriteRowVA=0;   // 0x42F074
    int    linePatchLen = 0;   // 6
    BYTE   lineSig[16] = {0};
    int    lineSigLen = 0;
    bool   lineFixEnabled = true;

    // ── CJK 长文本换行（wrapcjk）──────────────────────────────────────
    //
    //  真正的乱码/不显示根因（IDA 全量反汇编 0x42EF50..0x42F150 确认）：
    //  sub_42EF50 塞满一行后回退找**空格**（_isspace），中文没有空格，
    //  一路退到 edi<=0，`0x42F034 jle 0x42F139` 直接跳出整个函数，
    //  剩余文字一行都不写；行数组残留旧内容/未初始化堆 -> 乱码或不显示。
    //
    //  修法：在入口预处理，按框宽在 GBK 边界插入空格，让它能正常断行。
    DWORD  wrapCjkSiteVA   = 0;   // 0x42EF50（`sub esp,90h`）
    DWORD  wrapCjkResumeVA = 0;   // 0x42EF56（`push ebx`）
    int    wrapCjkPatchLen = 0;   // 6
    BYTE   wrapCjkSig[16]  = {0};
    int    wrapCjkSigLen   = 0;
    bool   wrapCjkEnabled  = true;

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
