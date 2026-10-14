#include "pch.h"
#include "target.h"
#include "log.h"

#include <cstring>
#include <cstdio>

// ────────────────────────────────────────────────────────────────────────
// 档位表（全部来自实测，见 ArmyMen2-汉化DLL架构设计.md）
//
//  签名取各作渲染器的**函数序言**，对绝对地址与 rel32 通配。
//  AM2 两个构建共享同一序言形状（A1 ?? ?? ?? ?? 83 EC ?? 85 C0 53 55 56 57
//  0F 84 ?? ?? ?? ?? 8B 54 24 ?? 83 C9 FF 8B FA 33 C0 F2 AE），
//  区别在栈帧大小（2C vs 40）与参数偏移，因此**可以互相区分**。
// ────────────────────────────────────────────────────────────────────────

#define SIG_AM2_STEAM                                                     \
    { 0xA1,0,0,0,0, 0x83,0xEC,0x2C, 0x85,0xC0, 0x53,0x55,0x56,0x57,      \
      0x0F,0x84,0,0,0,0, 0x8B,0x54,0x24,0x48, 0x83,0xC9,0xFF,            \
      0x8B,0xFA,0x33,0xC0,0xF2,0xAE }
#define MSK_AM2_STEAM                                                     \
    { 1,0,0,0,0, 1,1,1, 1,1, 1,1,1,1, 1,1,0,0,0,0, 1,1,1,1, 1,1,1,        \
      1,1,1,1,1,1 }

#define SIG_AM2_CHS                                                       \
    { 0xA1,0,0,0,0, 0x83,0xEC,0x40, 0x85,0xC0, 0x53,0x55,0x56,0x57,      \
      0x0F,0x84,0,0,0,0, 0x8B,0x54,0x24,0x5C, 0x83,0xC9,0xFF,            \
      0x8B,0xFA,0x33,0xC0,0xF2,0xAE }
#define MSK_AM2_CHS                                                       \
    { 1,0,0,0,0, 1,1,1, 1,1, 1,1,1,1, 1,1,0,0,0,0, 1,1,1,1, 1,1,1,        \
      1,1,1,1,1,1 }

// ── AM2 文本**测量**函数 sub_446E00 的签名（capstone 实测）────────
//   8B 4C 24 08  mov ecx,[esp+8]       ; a2 = font
//   56           push esi
//   8B D1        mov edx,ecx
//   8B 74 24 08  mov esi,[esp+8]       ; a1 = str（push 后位置变了）
//   C1 E2 06     shl edx,6
//   03 D1        add edx,ecx           ; edx = font*65
//   57           push edi
//   33 C0        xor eax,eax
//   8D 14 51     lea edx,[ecx+edx*2]   ; edx = font*131
//   8B 3C 95 ..  mov edi,[edx*4 + atlasBase]
//   8A 16        mov dl,[esi]
//   84 D2        test dl,dl
//   74 ??        jz  ...
//   atlasBase 地址与 jz 位移随版本变，用掩码通配。
#define SIG_AM2_MEASURE                                                   \
    { 0x8B,0x4C,0x24,0x08, 0x56, 0x8B,0xD1, 0x8B,0x74,0x24,0x08,         \
      0xC1,0xE2,0x06, 0x03,0xD1, 0x57, 0x33,0xC0, 0x8D,0x14,0x51,         \
      0x8B,0x3C,0x95,0,0,0,0, 0x8A,0x16, 0x84,0xD2, 0x74,0 }
#define MSK_AM2_MEASURE                                                   \
    { 1,1,1,1, 1, 1,1, 1,1,1,1,                                           \
      1,1,1, 1,1, 1, 1,1, 1,1,1,                                           \
      1,1,1,0,0,0,0, 1,1, 1,1, 1,0 }

#define SIG_TIS                                                           \
    { 0x55,0x8B,0xEC, 0x83,0xEC,0x38, 0x83,0x3D,0,0,0,0,0x00,            \
      0x53,0x56,0x57, 0x0F,0x84,0,0,0,0, 0x8B,0x75,0x10, 0x56,           \
      0xE8,0,0,0,0 }
#define MSK_TIS                                                           \
    { 1,1,1, 1,1,1, 1,1,0,0,0,0,1, 1,1,1, 1,1,0,0,0,0, 1,1,1, 1,         \
      1,0,0,0,0 }

// ── 地址语义约定（★ 摔过两次的坑）──────────────────────────────────────
//
//  本文件里，凡是**要与函数指针/全局量一起使用**的地址，
//  一律写成 IDA 里显示的**绝对 VA**（如 0x446930、0x4FE1A8），
//  读取时**不得**再加 ImageBase。
//
//  唯一的例外是 HookSite.rva —— 那是给 VirtualProtect/memcpy 用的
//  **映像内 RVA**，由 VA - RVA 换算得来。
//
//  历史教训：
//    * 一次"少加"：atlasBase 的内容是 malloc 堆指针，我当 RVA 加了基址 -> 取不到字形
//    * 一次"多加"：surfaceVA 已是 VA，我又加基址 -> 0x8FE1A8 野地址 -> 崩溃
//  两者本质相同：**必须清楚每个数是 RVA 还是 VA，以及它指向的值是什么语义**。
static const DWORD RVA = 0x400000;   // ImageBase（三作一致）

// ── AM2 的另外两个文字渲染器签名（IDA + 离线校验器实测）────────────────
//
//   ★ 我一开始给 DIALOG/CENTER 套用了 LEFT 的签名，离线校验器报 18 处
//     不匹配 —— 险些又让你白跑一次实机。三者序言的真实差异：
//     LEFT   A1 80 DF 4F 00 83 EC 2C | 85 C0 | 53 55 56 57 | 0F 84 ?? ?? ?? ??
//     DLG    A1 80 DF 4F 00 83 EC 2C | 33 D2 | 53 55 56 3B C2 57 | 0F 84 ?? ?? ?? ??
//     CENTER 与 DLG 完全相同，只差 jz 的 rel32（0x182 vs 0x18B）
//
//   所以 DIALOG 与 CENTER 共用一份签名（把 rel32 通配）；
//   LEFT 用另一份。三者地址不同，无需靠签名互相区分。
#define SIG_AM2_DLG                                                       \
    { 0xA1,0,0,0,0, 0x83,0xEC,0x2C, 0x33,0xD2, 0x53,0x55,0x56,            \
      0x3B,0xC2, 0x57, 0x0F,0x84, 0,0,0,0, 0x8B,0x5C,0x24,0x48,          \
      0x83,0xC9,0xFF, 0x8B,0xFB, 0x33,0xC0, 0xF2,0xAE }
#define MSK_AM2_DLG                                                       \
    { 1,0,0,0,0, 1,1,1, 1,1, 1,1,1,                                       \
      1,1, 1, 1,1, 0,0,0,0, 1,1,1,1,                                      \
      1,1,1, 1,1, 1,1, 1,1 }

// 往档位里加一个 hook 目标
static void AddHook(GameProfile& g, DWORD va, RenderKind kind,
                    const BYTE* sig, const BYTE* mask, int n,
                    int patchLen = 5)
{
    HookSite h;
    h.rva = va - RVA;
    h.kind = kind;
    // ★ patchLen 必须落在**指令边界**上（见 target.h）：
    //   三个渲染器入口是 A1 imm32      -> 5 字节
    //   测量函数入口是 mov/push/mov     -> 7 字节
    //   stub 构造按此长度复制，不能再硬编码 5。
    h.patchLen = patchLen;
    memcpy(h.sig, sig, n);
    memcpy(h.sigMask, mask, n);
    h.sigLen = n;
    g.hooks.push_back(h);
}

// ★ 安全的签名/掩码拷贝。
//
// 踩过的坑：原先直接 `memcpy(g.sig, s, sizeof(s))`，而 s 是 33 字节、
// 字段只有 32 字节 —— 越界 1 字节把内容挤进了相邻字段，实机表现是
// "签名不匹配 @+32: 期望 01 实得 AE"（看着像签名写错，实为容器小 1 字节）。
//
// 现在：长度不符直接**拒绝该档位**（fail-closed），并写日志。
// 配合 static_assert，编译期就能拦住"签名比缓冲区还长"。
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

    // ── Army Men II（Steam 英文版，1999-02-03）────────────────────────
    {
        GameProfile g;
        g.id = "ArmyMenII";
        g.exeName = "armymen2.exe";
        g.imageSizeOfImage = 0x267000;
        g.timeStamp = 0x36B7AE36;
        g.rendererVA = 0x446930 - RVA;          // 0x46930
        g.measureVA  = 0x446E00;                 // ★ 绝对 VA：文本测量
        g.blitVA     = 0x41C710;                 // ★ 绝对 VA（勿再减 RVA）
        g.rectVA     = 0x42E220;                 // ★ 绝对 VA
        g.atlasOffsetVA = 0x6598D4;             // WORD[262*font + c]（字形偏移）
        g.charWidthVA   = 0x659914;             // WORD[262*font + c]（字符步进宽度）
        g.clipRectVA    = 0x485310;             // rcSrc2 全局裁剪矩形
        g.rcVA          = 0x485330;             // rc 原点偏移（RECT）
        g.lockedSurfVA  = 0x507128;             // 当前锁定表面
        g.primarySurfVA = 0x502AD4;             // 主表面
        g.enabledVA     = 0x4FDF80;             // 表面锁标志
        g.dispWVA       = 0x4852D8;             // nWidth
        g.dispHVA       = 0x4852DC;             // nHeight
        g.atlasBaseVA   = 0x659AD4;             // DWORD[131*font]
        g.surfaceVA     = 0x4FE1A8;
        g.pitchVA       = 0x502AD0;
        DEFINE_SIG(g, SIG_AM2_STEAM, MSK_AM2_STEAM);
        g.patchLen = 5;   // ★ 恰好一条完整指令（见 target.h 说明）
        g.logTag = "ArmyMen2CHS";
        // ★ 三个文字渲染器都要 hook（见 target.h 的 RenderKind 说明）
        {
            static const BYTE _sl[] = SIG_AM2_STEAM;
            static const BYTE _ml[] = MSK_AM2_STEAM;
            static const BYTE _sd[] = SIG_AM2_DLG;
            static const BYTE _md[] = MSK_AM2_DLG;
            static const BYTE _sm[] = SIG_AM2_MEASURE;
            static const BYTE _mm[] = MSK_AM2_MEASURE;
            AddHook(g, 0x446930, RK_LEFT,   _sl, _ml, (int)sizeof(_sl));
            AddHook(g, 0x446AB0, RK_DIALOG, _sd, _md, (int)sizeof(_sd));
            AddHook(g, 0x446C50, RK_CENTER, _sd, _md, (int)sizeof(_sd));
            // ★ 文本**测量**函数：漏 hook 它 -> 上层拿到错误宽度 ->
            //   拿它当裁剪矩形 -> 文字被切碎 = 花屏（本轮根因）
            AddHook(g, 0x446E00, RK_MEASURE, _sm, _mm, (int)sizeof(_sm), 7);
        }
        v.push_back(g);
    }

    // ── Army Men II（1999 上海育碧简体中文版，1999-03-30）─────────────
    //   该版本自带 CJK 渲染器，正常不需要我们介入。
    //   保留档位是为了：① 识别出来并**主动停用**（避免重复 hook 官方实现）
    //                  ② 给我们的渲染器提供"官方参考实现"地址做比对
    {
        GameProfile g;
        g.id = "ArmyMenII-CHS";
        g.exeName = "armymen2.exe";
        g.imageSizeOfImage = 0x267000;
        g.timeStamp = 0x3700BEB9;
        g.rendererVA = 0x446B00 - RVA;          // 0x46B00（CJK 版）
        g.blitVA     = 0x41C710;                 // ★ 绝对 VA
        g.rectVA     = 0x42E220;                 // ★ 绝对 VA
        // 中文版把图集表与表面全局量都换了地址（IDA 实测）
        g.atlasOffsetVA = 0x6594BC;
        g.charWidthVA   = 0x6594FC;
        g.clipRectVA    = 0x4852A8;             // rcSrc2（CHS 版地址不同）
        g.atlasBaseVA   = 0x6596BC;
        g.surfaceVA     = 0x4FDD90;
        g.pitchVA       = 0x5026B8;
        g.rcVA          = 0x4852C8;             // rc（CHS 版）
        g.lockedSurfVA  = 0x506D10;             // 锁定表面（CHS 版）
        g.primarySurfVA = 0x5026BC;             // 主表面（CHS 版）
        g.enabledVA     = 0x4FDB68;             // 表面锁标志（CHS 版）
        DEFINE_SIG(g, SIG_AM2_CHS, MSK_AM2_CHS);
        g.patchLen = 5;   // ★ 恰好一条完整指令（见 target.h 说明）
        g.logTag = "ArmyMen2CHS";
        {
            static const BYTE _s[] = SIG_AM2_CHS;
            static const BYTE _m[] = MSK_AM2_CHS;
            // 中文版自带 CJK 渲染器，正常不会被 hook（Detect 会主动停用），
            // 这里登记只为让签名校验/日志完整。
            AddHook(g, 0x446B00, RK_LEFT, _s, _m, (int)sizeof(_s));
        }
        v.push_back(g);
    }

    // ── Army Men: Toys in Space（Steam 英文版）────────────────────────
    {
        GameProfile g;
        g.id = "ToysInSpace";
        g.exeName = "armymentis.exe";
        g.imageSizeOfImage = 0;                 // 未测量，跳过该校验
        g.timeStamp = 0;                         // 时间戳无效（1996-02-26），跳过
        g.rendererVA = 0x450EA7 - RVA;          // 0x50EA7
        g.blitVA     = 0x4212F0;                 // ★ 绝对 VA
        g.rectVA     = 0x435EDE;                 // ★ 绝对 VA
        g.atlasOffsetVA = 0x698D6C;             // word_698D6C
        g.charWidthVA   = 0x698DAC;             // word_698DAC（步进宽度）
        g.atlasBaseVA   = 0x698F6C;             // dword_698F6C
        g.surfaceVA     = 0x522EF8;             // dword_522EF8
        g.pitchVA       = 0x527820;             // dword_527820
        DEFINE_SIG(g, SIG_TIS, MSK_TIS);
        g.patchLen = 5;   // ★ 恰好一条完整指令（见 target.h 说明）
        g.logTag = "ArmyMenTISCHS";
        // ⚠️ TIS 的渲染正确性**尚未实机验证**（ASCII 宽度、字形头语义未确认），
        //    暂时只做"识别 + 挂一个无副作用的标记"，不真正接管渲染。
        //    理由见 hooks.cpp 里 doProbeOnly 的处理。
        g.probeOnly = true;
        {
            static const BYTE _s[] = SIG_TIS;
            static const BYTE _m[] = MSK_TIS;
            AddHook(g, 0x450EA7, RK_LEFT, _s, _m, (int)sizeof(_s));
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
    //   （原先只校验主渲染器，导致"另一个渲染器签名写错"要到实机才暴露 ——
    //     离线校验器就是这么发现 DIALOG/CENTER 用错签名的。）
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

    {
        char b3[96];
        snprintf(b3, sizeof(b3), "%d 个 hook 目标签名全部一致", (int)gp.hooks.size());
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

        // 名字命中后，按可选元数据进一步区分同名 exe（AM2 有英文/中文两个构建）
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
        Log("Detect: 选中 '%s'  rendererRVA=%#x  校验=%s",
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
