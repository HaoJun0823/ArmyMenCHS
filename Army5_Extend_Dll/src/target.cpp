#include "pch.h"
#include "target.h"
#include "log.h"

#include <cstring>
#include <cstdio>

// ════════════════════════════════════════════════════════════════════════
//  Army Men: Air Tactics（本作）档位表
//
//  ★ 全部数据来自本轮 IDA 逆向实测（见 docs/15-am5-reverse-findings.md）：
//      - PE 头：ImageBase / SizeOfImage / TimeDateStamp / 段布局 / DYNAMICBASE
//      - 反编译：sub_488640 / sub_4887F0 / sub_488B90 / sub_4885B0 / sub_488CF0
//      - 逐字节 get_bytes 核对序言（patchLen 边界）
//      - xrefs_to 统计调用点与全局量
//
//  ★★ 与 3/4 代的决定性差异（决定了本文件不能照抄 3/4 代）：
//
//    ① 只有 3 个文字绘制函数，且**没有** CENTER
//       本作：LEFT / DIALOG / GRADIENT
//       4 代：LEFT / DIALOG / CENTER
//       3 代：LEFT / DIALOG / CENTER
//       -> 少一个 hook 目标，但多一个本作独有的 GRADIENT（不接管绘制）。
//
//    ② patchLen 与 4 代不同（DIALOG 是 14 不是 15）
//       本作 DIALOG 序言：A1 imm32 | 83 EC 30 | 85 C0 | 53 55 56 57 | 0F 84 rel32
//       4 代 DIALOG 序言：A1 imm32 | 83 EC 30 | 33 D2 | 53 55 56 | 3B C2 | 57 | 0F 84
//       前者 14 字节到 push edi 结束，后者 15 字节到 push edi 结束。
//       ★ 若沿用 4 代的 15，会把 `0F 84 xx` 的首字节切进去 -> stub 执行到
//         指令中间 -> 必崩（与 3 代"patchLen=5 切碎 sub esp,38h"同一类错误）。
//
//    ③ 字形表**地址**完全不同，但"陷阱表"同样存在
//       本作 0xC86DFC(偏移) / 0xC86E3C(陷阱)；4 代 0x6BE524 / 0x6BE564
//
//    ④ LEFT 与 DIALOG 的序言**前 14 字节逐字节相同**
//       两者都以 A1 4C C6 63 00 | 83 EC 30 | 85 C0 | 53 55 56 57 开头，
//       差别只在 rel32（0x191 vs 0x173）与其后的第一条指令
//       （LEFT `8B 6C 24 44` = mov ebp,[esp+44h+arg_0]；
//         DIALOG `8B 54 24 4C` = mov edx,[esp+4Ch+arg_8]）。
//       -> 签名必须取到 **24 字节**（含 rel32 与分化指令），
//          只取 14 字节会让两个 profile 互相误判。已用逐字节脚本验证：
//          24 字节签名在全文件中各命中 **1 次**，即目标自身。
//
//  ★ 相同点（所以 renderer.cpp / hzk16.cpp 的思路可以复用）：
//     3 个绘制 + 2 个测量；字形头 = WORD[0]宽 / WORD[1]高；ASCII 转调 stub 的契约一致。
// ════════════════════════════════════════════════════════════════════════

// ── 地址语义约定 ────────────────────────────────────────────────────────
//
//  本文件里，凡是**要与函数指针/全局量一起使用**的地址，
//  一律写成 IDA 里显示的**绝对 VA**（如 0x488640、0xC86DFC），
//  读取时**不得**再加 ImageBase。
//
//  唯一的例外是 HookSite.rva —— 那是给 VirtualProtect/memcpy 用的
//  **映像内 RVA**，由 VA - ImageBase 换算得来。
//
//  历史教训（2 代，本项目因此崩过两次）：
//    * 一次"少加"：atlasBase 的内容是 malloc 堆指针，当 RVA 加了基址 -> 取不到字形
//    * 一次"多加"：surfaceVA 已是 VA，又加基址 -> 野地址 -> 崩溃
//  两者本质相同：**必须清楚每个数是 RVA 还是 VA，以及它指向的值是什么语义**。
static const DWORD IMAGE_BASE = 0x400000;   // ImageBase（实测本作同为 0x400000）

// ────────────────────────────────────────────────────────────────────────
//  签名（取各函数**序言**，对绝对地址与 rel32 通配）
//
//  本作实测序言（get_bytes 原样抄录）：
//     LEFT     A1 4C C6 63 00 | 83 EC 30 | 85 C0 | 53 55 56 57 |
//              0F 84 91 01 00 00 | 8B 6C 24 44
//     DIALOG   A1 4C C6 63 00 | 83 EC 30 | 85 C0 | 53 55 56 57 |
//              0F 84 73 01 00 00 | 8B 54 24 4C
//     GRADIENT A1 4C C6 63 00 | 83 EC 28 | 33 D2 | 53 55 56 | 3B C2 | 57 |
//              0F 84 35 01 00 00 | 8B 7C 24 44
//     MEAS_W   8B 4C 24 08 | 53 | 8B D1 | 56 | C1 E2 06 | 03 D1 | 57
//     MEAS_H   8B 4C 24 08 | 56 | 8B D1 | 8B 74 24 08 | C1 E2 06 | 03 D1 | 57
//
//  ★ A1 后面的 4 字节是 dword_63C64C 的**绝对地址**，不同构建会变，
//    故一律通配（mask=0）。0F 84 的 rel32 同理 —— 但**本文件刻意不通配**：
//    LEFT / DIALOG 前 14 字节完全相同，只有 rel32 与"其后第一条指令"能区分。
//    把 rel32 也写死进去，等于用"版本锁定"换"识别确定性"，符合 fail-closed 原则。
// ────────────────────────────────────────────────────────────────────────

// LEFT：mov eax,[imm32]; sub esp,30h; test eax,eax; push ebx/ebp/esi/edi;
//       jz rel32(=0x191); mov ebp,[esp+44h+arg_0]
#define SIG_AT_LEFT                                                       \
    { 0xA1,0,0,0,0, 0x83,0xEC,0x30, 0x85,0xC0, 0x53,0x55,0x56,0x57,       \
      0x0F,0x84, 0x91,0x01,0x00,0x00, 0x8B,0x6C,0x24,0x44 }
#define MSK_AT_LEFT                                                       \
    { 1,0,0,0,0, 1,1,1, 1,1, 1,1,1,1,                                     \
      1,1, 1,1,1,1, 1,1,1,1 }

// DIALOG：同前 14 字节；jz rel32(=0x173); mov edx,[esp+4Ch+arg_8]
#define SIG_AT_DLG                                                        \
    { 0xA1,0,0,0,0, 0x83,0xEC,0x30, 0x85,0xC0, 0x53,0x55,0x56,0x57,       \
      0x0F,0x84, 0x73,0x01,0x00,0x00, 0x8B,0x54,0x24,0x4C }
#define MSK_AT_DLG                                                        \
    { 1,0,0,0,0, 1,1,1, 1,1, 1,1,1,1,                                     \
      1,1, 1,1,1,1, 1,1,1,1 }

// GRADIENT：sub esp,28h; xor edx,edx; push ebx/ebp/esi; cmp eax,edx; push edi
#define SIG_AT_GRAD                                                       \
    { 0xA1,0,0,0,0, 0x83,0xEC,0x28, 0x33,0xD2, 0x53,0x55,0x56,            \
      0x3B,0xC2, 0x57, 0x0F,0x84, 0x35,0x01,0x00,0x00, 0x8B,0x7C,0x24,0x44 }
#define MSK_AT_GRAD                                                       \
    { 1,0,0,0,0, 1,1,1, 1,1, 1,1,1,                                       \
      1,1, 1, 1,1, 1,1,1,1, 1,1,1,1 }

// 测量 A（累加字形宽）：
//   mov ecx,[esp+8]; push ebx; mov edx,ecx; push esi; shl edx,6; add edx,ecx; push edi
#define SIG_AT_MEASW                                                      \
    { 0x8B,0x4C,0x24,0x08, 0x53, 0x8B,0xD1, 0x56,                         \
      0xC1,0xE2,0x06, 0x03,0xD1, 0x57 }
#define MSK_AT_MEASW                                                      \
    { 1,1,1,1, 1, 1,1, 1,                                                 \
      1,1,1, 1,1, 1 }

// 测量 B（累加字形高-3）：
//   mov ecx,[esp+8]; push esi; mov edx,ecx; mov esi,[esp+8]; shl edx,6; add edx,ecx; push edi
//   ★ 第 2 字节是 `56`(push esi)，与 MEASW 同位置的 `53`(push ebx) 不同 ——
//     这是两者能互相区分的关键字节。
#define SIG_AT_MEASH                                                      \
    { 0x8B,0x4C,0x24,0x08, 0x56, 0x8B,0xD1, 0x8B,0x74,0x24,0x08,          \
      0xC1,0xE2,0x06, 0x03,0xD1, 0x57 }
#define MSK_AT_MEASH                                                      \
    { 1,1,1,1, 1, 1,1, 1,1,1,1,                                           \
      1,1,1, 1,1, 1 }

// 往档位里加一个 hook 目标
static void AddHook(GameProfile& g, DWORD va, RenderKind kind,
                    const BYTE* sig, const BYTE* mask, int n, int patchLen)
{
    HookSite h;
    h.rva = va - IMAGE_BASE;
    h.kind = kind;
    h.patchLen = patchLen;
    memcpy(h.sig, sig, n);
    memcpy(h.sigMask, mask, n);
    h.sigLen = n;
    g.hooks.push_back(h);
}

// ★ 安全的签名/掩码拷贝（2 代曾因 memcpy 越界 1 字节产生
//   "签名不匹配 @+32: 期望 01 实得 AE" 的假象，故保留 static_assert 防线）。
#define DEFINE_SIG(profile, SIGN, SMASK)                              \
    do {                                                              \
        static const BYTE _s[] = SIGN;                                \
        static const BYTE _m[] = SMASK;                               \
        static_assert(sizeof(_s) == sizeof(_m),                       \
                      "SIG 与 MSK 长度必须一致");                      \
        static_assert(sizeof(_s) <= SIG_MAX,                          \
                      "签名超出 SIG_MAX，请调大 SIG_MAX");             \
        memcpy((profile).sig, _s, sizeof(_s));                        \
        memcpy((profile).sigMask, _m, sizeof(_m));                    \
        (profile).sigLen = (int)sizeof(_s);                           \
    } while (0)

static std::vector<GameProfile> MakeProfiles() {
    std::vector<GameProfile> v;

    // ══ Army Men: Air Tactics（本作）══════════════════════════════════
    {
        GameProfile g;
        g.id = "AirTactics";
        g.exeName = "amat.exe";

        // PE 实测：SizeOfImage=0x94B000，TimeDateStamp=0x38BC3196
        //   ★ 与 3 代不同：本作的时间戳是**正常值**（1999-08-31），
        //     不是 3 代那种伪造的 ASCII '1991'。两项校验都启用。
        g.imageSizeOfImage = 0x94B000;
        g.timeStamp = 0x38BC3196;

        g.rendererVA = 0x488640;        // ★ 绝对 VA（勿再加 ImageBase）
        g.measureVA  = 0x4885B0;        // 测量：累加字形宽
        g.measureHVA = 0x488CF0;        // 测量：累加字形高-3
        g.gradientVA = 0x488B90;        // 渐变文字（不接管绘制，仅识别/日志）

        // ── 游戏自身的绘制原语 ────────────────────────────────────────
        //   blit  sub_432F50：(rgba?, srcX, srcY, dstW, dstH, color)
        //        ★ 它是 __fastcall（1 个栈参 + ecx/edx），我们**不直接调它**，
        //          而是走 rect + 自己的像素写入，避免趟调用约定的浑水。
        //        该字段登记仅作参考。
        //   rect  sub_455BA0：(desc*, clip*, x, y, out*) -> bool
        //        官方每个字形都先调它做两级裁剪。
        g.blitVA = 0x432F50;
        g.rectVA = 0x455BA0;

        // ── 字体图集 ──────────────────────────────────────────────────
        //   ★★ 与 3/4 代的**地址**完全不同（结构对应，数值不同）：
        //     3 代 0x698D6C / 0x698DAC / 0x698F6C
        //     4 代 0x6BE524 / 0x6BE564 / 0x6BE520 / 0x6BE724
        //     本作 0xC86DFC / 0xC86E3C / 0xC86DF8 / 0xC86FFC
        g.atlasOffsetVA = 0xC86DFC;     // word_C86DFC：WORD[262*font + c] 字形偏移
        g.charWidthVA   = 0xC86E3C;     // ★★ 不是宽度表，是上面的表右移 32 项
                                        //   （0xC86E3C - 0xC86DFC == 0x40 == 32 个
                                        //   WORD），即 CharWidth[c] ≡ atlasOffset[c+32]。
                                        //   当宽度用会让混排串从首个 ASCII 字符起整段消失。
                                        //   代码里已无读取点，仅登记备查。
        g.atlasSizeVA   = 0xC86DF8;     // dword_C86DF8：DWORD[131*font] 图集字节大小
        g.atlasBaseVA   = 0xC86FFC;     // dword_C86FFC：DWORD[131*font]
                                        //   ★ 其**内容**是堆指针，不是 RVA

        // ── 裁剪与表面 ────────────────────────────────────────────────
        g.clipRectVA    = 0x510A38;     // stru_510A38（全局裁剪 RECT）
        g.rcVA          = 0x510A58;     // rc 原点；rc.left@0x510A58, rc.top@0x510A5C
        g.enabledVA     = 0x63C64C;     // dword_63C64C（表面锁标志）
                                        //   三个绘制函数开头都 `if(!dword_63C64C) return`
        g.surfaceVA     = 0x63C874;     // dword_63C874（目标像素缓冲）
        g.pitchVA       = 0x641198;     // dword_641198（行距）
        g.lockedSurfVA  = 0x651850;     // dword_651850（当前表面）
        g.primarySurfVA = 0x64119C;     // dword_64119C（主表面；相等决定是否加 rc 原点）
        // ★ 显示区尺寸：本作有 nWidth@0x671170 / nHeight@0x671174
        //   （sub_430840 里 CreateSurface(nWidth, nHeight, 8) 实测）。
        //   ★ 但它们是**初始化时的请求值**，不一定等于实际表面尺寸；
        //     故仅用作像素写入的"内存安全上界"，语义裁剪仍靠 rcSrc2。
        g.dispWVA       = 0x671170;
        g.dispHVA       = 0x671174;

        g.fontCount = 9;                // sub_446AA0: for (i = 0; i < 9; ++i)

        // ── CD-ROM 校验屏蔽（见 src/cdspoof.h 的长注释）──────────────
        //
        //  启动链（_WinMain @ 0x40F050 实测）：
        //      40F345  call sub_43F200      ; 读 strings.txt（398 行校验）
        //      40F355  call sub_447450      ; ★ CD 检测
        //      40F35A  test eax, eax
        //      40F35C  jz   退出            ; 返回 0 -> 直接结束进程
        //  而 sub_447450 内部先弹 MessageBoxA("Please insert the ... CD.")
        //  再返回 0 —— 这就是"没挂 ISO 就进不去"的全部原因。
        //
        //  ★ sub_447450 只被 5 处调用（_WinMain 与 4 个切换盘符的地方），
        //    语义一致，全局改成 return 1 即可。
        g.cdDetectVA     = 0x447450;    // sub_447450
        g.cdRootBufVA    = 0x671288;    // byte_671288：256 字节 "<根>\" 缓冲
        g.cdReadyFlagVA  = 0x6713B0;    // dword_6713B0：1 = 根路径可用
        g.cdReadyFlag2VA = 0x6713BC;    // dword_6713BC：原版同时置 1（无读取点）
        g.cdDetectPatchLen = 5;         // push ecx/ebx/ebp/esi/edi 之后即边界
        {
            // 11 字节指纹，在本作 exe 里全文件**唯一**命中 sub_447450：
            //   51 53 55 56 57        push ecx/ebx/ebp/esi/edi
            //   8B 3D C0 40 4F 00     mov edi, ds:[0x4F40C0(GetLogicalDriveStringsA)]
            // ★ 只取 5 字节（那串 push）会与 8 个别的函数重名，
            //   所以必须取到 mov edi,ds:... 才唯一。
            static const BYTE kCdSig[] = {
                0x51, 0x53, 0x55, 0x56, 0x57,
                0x8B, 0x3D, 0xC0, 0x40, 0x4F, 0x00
            };
            static const BYTE kCdMask[] = {
                1, 1, 1, 1, 1,
                1, 1, 1, 1, 1, 1
            };
            static_assert(sizeof(kCdSig) == sizeof(kCdMask),
                          "CD 指纹与掩码长度必须一致");
            static_assert(sizeof(kCdSig) <= SIG_MAX,
                          "CD 指纹超出 SIG_MAX");
            memcpy(g.cdDetectSig, kCdSig, sizeof(kCdSig));
            memcpy(g.cdDetectSigMask, kCdMask, sizeof(kCdMask));
            g.cdDetectSigLen = (int)sizeof(kCdSig);
        }

        // ── 长文本换行的汉字边界修复（见 src/wrapfix.h 的长注释）──────
        //
        //  sub_42EF50 负责把长文本切成多行（每行 129 字节 × 16 行）。
        //  它的"超宽回退"是逐字节的，中文整句没空格时就退到 count<0，
        //  然后在任意字节上截断 —— 截点落在 GBK 汉字中间就是整行乱码。
        //
        //  ★ 只替换 0x42F019 起的 21 字节回退循环，不碰函数其余部分。
        g.wrapRollbackVA = 0x42F019;    // 回退循环起点
        g.wrapDoneVA     = 0x42F02E;    // 回退结束落点（test edi,edi）
        g.wrapPatchLen   = 21;          // 0x42F019..0x42F02D（含）
        g.wrapEnabled    = false;       // ★ 暂不启用：三轮实验证明它不是乱码/崩溃的解
                                         //   详细结论见 src/wrapfix.h 顶部
        {
            // ★ 签名起点必须与 patch 目标**一致**（都是 0x42F019）。
            //   之前误把起点写成 0x42F015（cmp eax,ecx），于是校验时拿
            //   0x42F019 处的字节去比 0x42F015 的期望值，
            //   报 "期望 3B 实得 4B"，补丁根本没装上。
            //
            //   21 字节（= patchLen）在全文件里已经**唯一**命中 0x42F019：
            //     4B 4E 4F        dec ebx / dec esi / dec edi
            //     78 10           js  +0x10
            //     0F BE 0B        movsx ecx, byte [ebx]
            //     51              push ecx
            //     E8 A2 8E 0B 00  call _isspace
            //     83 C4 04        add esp, 4
            //     85 C0           test eax, eax
            //     74 EB           jz  -0x15
            static const BYTE kWrapSig[] = {
                0x4B, 0x4E, 0x4F,                   // dec ebx/esi/edi
                0x78, 0x10,                         // js  +0x10
                0x0F, 0xBE, 0x0B,                   // movsx ecx,[ebx]
                0x51,                               // push ecx
                0xE8, 0xA2, 0x8E, 0x0B, 0x00,       // call _isspace
                0x83, 0xC4, 0x04,                   // add esp,4
                0x85, 0xC0,                         // test eax,eax
                0x74, 0xEB                          // jz  -0x15
            };                                      // 共 21 字节
            static const BYTE kWrapMask_c[] = { 1,1,1,1,1,1,1,1,1,1,1,
                                                1,1,1,1,1,1,1,1,1,1 };
            static_assert(sizeof(kWrapSig) == sizeof(kWrapMask_c),
                          "WrapFix 指纹与掩码长度必须一致");
            static_assert(sizeof(kWrapSig) == 21,
                          "WrapFix 指纹长度应等于 patchLen=21");
            static_assert(sizeof(kWrapSig) <= SIG_MAX,
                          "WrapFix 指纹超出 SIG_MAX");
            memcpy(g.wrapSig, kWrapSig, sizeof(kWrapSig));
            memcpy(g.wrapSigMask, kWrapMask_c, sizeof(kWrapMask_c));
            g.wrapSigLen = (int)sizeof(kWrapSig);
        }

        // ── 长文本分行"多写一行"的修复（见 src/linefix.h 的根因说明）──
        g.lineSiteVA    = 0x42F06A;
        // ★ 落点是 0x42F130 —— **while 循环条件**（cmp byte [ebx],0）。
        //   注意：0x42F10E..0x42F12A 是"写完一行后的初始化"（xor edi /
        //   lea esi / 插 '^'+颜色 / 行高累加），不是循环入口。
        //   v2 曾错误地把"源串结束"和"未断行"都跳去 0x42F10E，
        //   导致每个字符都触发一次写行，行数暴涨后越界崩溃。
        //   v3 只改"源串结束"这一条路径；未断行/真断行保持原样。
        g.lineLoopTopVA = 0x42F130;
        g.lineWriteRowVA= 0x42F074;
        g.linePatchLen  = 8;
        // ★ 当前禁用。原因见 linefix.cpp 头部：v1..v4 均未验证成功，
        //   且 v4 暴露了 BuildStub 相对位移漏算壳基址的老 bug（已修，
        //   但整个方案还缺一次可信的实测）。
        //   在拿到 x32dbg 实测执行流之前不再启用，避免持续性负面改动。
        g.lineFixEnabled= false;
        {
            // 8 字节 = 3 条完整指令，正好落在指令边界：
            //   74 08        jz   short  +0x08            (2)
            //   84 C0        test al, al                   (2)
            //   0F 84 BC 00  jz   near    +0xBC            (4)
            // 合计 2+2+4 = 8。下一条指令是 0x42F072 之后的 8B 95…，
            // 用 12 字节签名再确认一次唯一性。
            static const BYTE kLineSig[] = {
                0x74, 0x08,               // jz  loc_42F074（★ bug：源串结束也写行）
                0x84, 0xC0,               // test al, al
                0x0F, 0x84, 0xBC, 0x00    // jz  loc_42F130
            };
            static_assert(sizeof(kLineSig) == 8,
                          "LineFix 签名应为 8 字节（2+2+4）");
            memcpy(g.lineSig, kLineSig, sizeof(kLineSig));
            g.lineSigLen = (int)sizeof(kLineSig);
        }

        // ── CJK 长文本换行（真正的修法）──────────────────────────────
        //
        //  在 sub_42EF50 入口预处理串，让它的"回退找空格"逻辑有断点可用。
        //  入口第一条指令就是 `81 EC 90 00 00 00`（sub esp,90h，6 字节），
        //  完整复现后跳回 0x42EF56（push ebx）。
        g.wrapCjkSiteVA   = 0x42EF50;
        g.wrapCjkResumeVA = 0x42EF56;
        g.wrapCjkPatchLen = 6;
        g.wrapCjkEnabled  = true;
        {
            // 6 字节签名，同时把 0x42EF56 处的 `push ebx` 也带上做二次确认。
            static const BYTE kWrapCjkSig[] = {
                0x81, 0xEC, 0x90, 0x00, 0x00, 0x00,   // sub esp, 90h
                0x53,                                  // push ebx
                0x55,                                  // push ebp
                0x56,                                  // push esi
                0x8B, 0xB4, 0x24, 0xA0, 0x00, 0x00, 0x00  // mov esi,[esp+0A0h]
            };
            static_assert(sizeof(kWrapCjkSig) == 16,
                          "WrapCjk 签名应为 16 字节");
            memcpy(g.wrapCjkSig, kWrapCjkSig, sizeof(kWrapCjkSig));
            g.wrapCjkSigLen = (int)sizeof(kWrapCjkSig);
        }

        // ★ 主签名刻意取 **GRADIENT**（sub_488B90）而不是 LEFT：
        //   GRADIENT 不在 hooks 表里（我们不接管它），所以它的签名是一次
        //   **独立的、不重复的**构建指纹校验。LEFT 的签名已经在 hooks 表里
        //   逐个字节校验过了，再赋给主签名只是重复。
        DEFINE_SIG(g, SIG_AT_GRAD, MSK_AT_GRAD);
        g.logTag = "ArmyMenAATCHS";

        // ★ 是否只做"识别 + 无副作用标记"、不接管渲染。
        //   五个函数的语义都已反编译确认，故**默认启用完整渲染**。
        //   ★ 出问题时的一键安全阀：把下面改成 true 重新编译，
        //     DLL 就只做识别验证而不改渲染行为。
        g.probeOnly = false;

        {
            static const BYTE _sl[] = SIG_AT_LEFT;
            static const BYTE _ml[] = MSK_AT_LEFT;
            static const BYTE _sd[] = SIG_AT_DLG;
            static const BYTE _md[] = MSK_AT_DLG;
            static const BYTE _sw[] = SIG_AT_MEASW;
            static const BYTE _mw[] = MSK_AT_MEASW;
            static const BYTE _sh[] = SIG_AT_MEASH;
            static const BYTE _mh[] = MSK_AT_MEASH;
            // ★ patchLen 必须落在指令边界上，本作与 4 代不同：
            //     LEFT      : mov(5)+sub(3)+test(2)+push ebx(1)          -> 10
            //     DIALOG    : mov(5)+sub(3)+test(2)+push ebx/ebp/esi/edi -> 14
            //                 ★ 不是 15（15 会切进 0F 84 中间）
            //     MEASURE   : mov(4)+push ebx(1)+mov(2)+push esi(1)
            //                 +shl(3)+add(2)                            -> 11
            //     MEASURE_H : mov(4)+push esi(1)+mov(2)+mov esi,[esp+8](4)
            //                 +shl(3)                                   -> 14
            AddHook(g, 0x488640, RK_LEFT,      _sl, _ml, (int)sizeof(_sl), 10);
            AddHook(g, 0x4887F0, RK_DIALOG,    _sd, _md, (int)sizeof(_sd), 14);
            AddHook(g, 0x4885B0, RK_MEASURE,   _sw, _mw, (int)sizeof(_sw), 11);
            AddHook(g, 0x488CF0, RK_MEASURE_H, _sh, _mh, (int)sizeof(_sh), 14);
            // ★ GRADIENT 刻意**不进 hooks 表**：它用的是另一套单字节字体，
            //   中文永远不会走到它；接管它只会增加风险而没有任何收益。
            //   它的签名仍在 g.sig / VerifySignature 里随主签名一起校验，
            //   保证"识别到的是本作这个构建"。
        }
        v.push_back(g);
    }

    return v;
}

const std::vector<GameProfile>& Target::BuiltinProfiles() {
    static std::vector<GameProfile> s = MakeProfiles();
    return s;
}

static void ToLowerAscii(std::string& s) {
    for (char& c : s) if (c >= 'A' && c <= 'Z') c = (char)(c - 'A' + 'a');
}

bool Target::GetMainModuleInfo(std::string& exeName, DWORD& sizeOfImage,
                               DWORD& timeStamp) {
    HMODULE h = GetModuleHandleA(nullptr);
    if (!h) return false;
    char path[MAX_PATH] = {0};
    if (!GetModuleFileNameA(h, path, MAX_PATH)) return false;
    const char* slash = strrchr(path, '\\');
    exeName = slash ? (slash + 1) : path;
    ToLowerAscii(exeName);

    BYTE* base = (BYTE*)h;
    IMAGE_DOS_HEADER* dos = (IMAGE_DOS_HEADER*)base;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return false;
    IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return false;
    sizeOfImage = nt->OptionalHeader.SizeOfImage;
    timeStamp = nt->FileHeader.TimeDateStamp;
    return true;
}

bool Target::VerifySignature(const GameProfile& gp, std::string& why) {
    HMODULE h = GetModuleHandleA(nullptr);
    if (!h) { why = "no main module"; return false; }
    BYTE* base = (BYTE*)h;

    IMAGE_DOS_HEADER* dos = (IMAGE_DOS_HEADER*)base;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) { why = "bad DOS"; return false; }
    IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) { why = "bad NT"; return false; }

    DWORD size = nt->OptionalHeader.SizeOfImage;

    // ★ 逐个 hook 目标校验，全部通过才算该档位可用。
    //   （2 代最初只校验主渲染器，导致"另一个渲染器签名写错"要到实机才暴露。）
    if (gp.hooks.empty()) { why = "该档位没有登记任何 hook 目标"; return false; }

    int bad = 0;
    for (const HookSite& hs : gp.hooks) {
        if (hs.rva == 0) { bad++; continue; }
        if (hs.sigLen <= 0 || hs.sigLen > SIG_MAX) { bad++; continue; }
        if (hs.rva + (DWORD)hs.patchLen > size) { bad++; continue; }

        const BYTE* p = base + hs.rva;
        for (int i = 0; i < hs.sigLen; i++) {
            if (!hs.sigMask[i]) continue;
            if (p[i] != hs.sig[i]) {
                char buf[192];
                snprintf(buf, sizeof(buf),
                         "hook RVA %#x 签名不匹配 @+%d: 期望 %02X 实得 %02X",
                         hs.rva, i, hs.sig[i], p[i]);
                why = buf;
                return false;
            }
        }
    }
    if (bad) {
        char b2[96];
        snprintf(b2, sizeof(b2), "%d 个 hook 目标参数非法", bad);
        why = b2;
        return false;
    }

    // ★ 额外校验 GRADIENT 与主签名：它们不参与 hook，但能更强地确认"就是本作这个构建"。
    if (gp.gradientVA != 0 && gp.sigLen > 0) {
        DWORD rva = gp.gradientVA - IMAGE_BASE;
        if (rva + (DWORD)gp.sigLen <= size) {
            const BYTE* p = base + rva;
            for (int i = 0; i < gp.sigLen; i++) {
                if (!gp.sigMask[i]) continue;
                if (p[i] != gp.sig[i]) {
                    char buf[192];
                    snprintf(buf, sizeof(buf),
                             "主签名不匹配 @+%d: 期望 %02X 实得 %02X", i,
                             gp.sig[i], p[i]);
                    why = buf;
                    return false;
                }
            }
        } else {
            why = "GRADIENT 目标 RVA 超出映像";
            return false;
        }
    }

    {
        char b3[128];
        snprintf(b3, sizeof(b3), "%d 个 hook 目标 + 主签名全部一致",
                 (int)gp.hooks.size());
        why = b3;
    }
    return true;
}

bool Target::Detect(GameProfile& out) {
    std::string exe;
    DWORD sizeImage = 0, ts = 0;
    if (!GetMainModuleInfo(exe, sizeImage, ts)) {
        Log("Detect: 取主模块信息失败");
        return false;
    }
    Log("Detect: exe=%s SizeOfImage=%#x TimeDateStamp=%#x",
        exe.c_str(), sizeImage, ts);

    for (const auto& gp : BuiltinProfiles()) {
        if (exe != gp.exeName) continue;

        // 名字命中后，按可选元数据进一步区分同名 exe
        if (gp.timeStamp != 0 && ts != gp.timeStamp) {
            Log("Detect: '%s' 名字命中但时间戳不符（期望 %#x），跳过",
                gp.id.c_str(), gp.timeStamp);
            continue;
        }
        if (gp.imageSizeOfImage != 0 && sizeImage != gp.imageSizeOfImage) {
            Log("Detect: '%s' 名字命中但 SizeOfImage 不符（期望 %#x），跳过",
                gp.id.c_str(), gp.imageSizeOfImage);
            continue;
        }

        std::string why;
        bool sigOk = VerifySignature(gp, why);
        Log("Detect: 选中 '%s'  rendererVA=%#x  校验=%s",
            gp.id.c_str(), gp.rendererVA, why.c_str());
        if (!sigOk) {
            // ★ fail-closed：签名不符绝不 hook
            Log("Detect: !! 签名校验失败，拒绝适配该档位");
            continue;
        }
        out = gp;
        return true;
    }

    Log("Detect: 没有匹配的档位（本补丁不支持这个版本）");
    return false;
}
