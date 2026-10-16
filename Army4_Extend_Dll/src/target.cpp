#include "pch.h"
#include "target.h"
#include "log.h"

#include <cstring>
#include <cstdio>

// ════════════════════════════════════════════════════════════════════════
//  Army Men: World War（4 代）档位表
//
//  ★ 全部数据来自本轮 IDA 逆向实测（见 docs/12-am4-reverse-findings.md）：
//      - PE 头：ImageBase / SizeOfImage / TimeDateStamp / 段布局
//      - 反编译：sub_466320 / sub_4664A0 / sub_466650 / sub_466290 / sub_466810
//      - 逐字节 get_bytes 核对序言（patchLen 边界）
//      - xrefs_to 统计调用点与全局量
//
//  ★★ 4 代与 3 代的四个决定性差异（决定了本文件不能照抄 3 代）：
//
//    ① 字体索引**算法不同** -> 3 代签名 0 命中
//       3 代：imul ecx, ecx, 0x20C           （font * 262 * 2）
//       4 代：shl edx,6; add edx,ecx; lea esi,[ecx+edx*2]
//             （同为 *262，但指令序列完全不同）
//       -> 全 exe 搜 `69 ?? 0C 02 00 00` 命中 **0** 次，已验证。
//
//    ② 序言形状不同 -> patchLen 全部不同
//       3 代：push ebp; mov ebp,esp; sub esp,38h   -> 6/6/6/5/8
//       4 代：mov eax,[dword_53C72C]; sub esp,30h; ... push*4
//                                                   -> 10/15/15/11/14
//
//    ③ 字形表**地址**不同，但"陷阱表"同样存在
//       3 代 0x698D6C(偏移) / 0x698DAC(陷阱)
//       4 代 0x6BE524(偏移) / 0x6BE564(陷阱)
//
//    ④ DIALOG 是**两级裁剪**
//       4 代 sub_4664A0 调两次 rectVA（rcSrc2 与 &a5 各一次），
//       3 代只裁 rcSrc2。
//
//  ★ 相同点（所以 renderer.cpp / hzk16.cpp 可以原样复用）：
//     3 个绘制 + 2 个测量；blit/rect 语义一致；ASCII 转调 stub 的契约一致。
// ════════════════════════════════════════════════════════════════════════

// ── 地址语义约定 ────────────────────────────────────────────────────────
//
//  本文件里，凡是**要与函数指针/全局量一起使用**的地址，
//  一律写成 IDA 里显示的**绝对 VA**（如 0x466320、0x6BE524），
//  读取时**不得**再加 ImageBase。
//
//  唯一的例外是 HookSite.rva —— 那是给 VirtualProtect/memcpy 用的
//  **映像内 RVA**，由 VA - ImageBase 换算得来。
//
//  历史教训（2 代，本项目因此崩过两次）：
//    * 一次"少加"：atlasBase 的内容是 malloc 堆指针，当 RVA 加了基址 -> 取不到字形
//    * 一次"多加"：surfaceVA 已是 VA，又加基址 -> 野地址 -> 崩溃
//  两者本质相同：**必须清楚每个数是 RVA 还是 VA，以及它指向的值是什么语义**。
static const DWORD IMAGE_BASE = 0x400000;   // ImageBase（实测 4 代同为 0x400000）

// ────────────────────────────────────────────────────────────────────────
//  签名（取各函数**序言**，对绝对地址与 rel32 通配）
//
//  4 代实测序言（get_bytes 原样抄录）：
//     LEFT    A1 2C C7 53 00 | 83 EC 30 | 85 C0 | 53 55 56 57 | 0F 84 rel32
//     DIALOG  A1 2C C7 53 00 | 83 EC 30 | 33 D2 | 53 55 56 | 3B C2 | 57 | 0F 84 rel32
//     CENTER  A1 2C C7 53 00 | 83 EC 30 | 33 D2 | 53 55 56 | 3B C2 | 57 | 0F 84 rel32
//     MEAS_W  8B 4C 24 08 | 53 | 8B D1 | 56 | C1 E2 06 | 03 D1 | 57 | 8B 7C 24 10 | 33 C0
//     MEAS_H  8B 4C 24 08 | 56 | 8B D1 | 8B 74 24 08 | C1 E2 06 | 03 D1 | 57 | 33 C0 | 8D ..
//
//  ★ A1 后面的 4 字节是 dword_53C72C 的**绝对地址**，不同构建会变，
//    故一律通配（mask=0）。0F 84 的 rel32 同理。
//
//  ★ DIALOG 与 CENTER 的序言**逐字节相同**，只靠 rel32 的落点区分
//    （0x4664A0 处 rel32=0x18F；0x466650 处 rel32=0x198）。
//    两者签名都取到 `0F 84` 为止并通配 rel32，已足够确认"这个 RVA 上是
//    4 代的 9 参文字绘制函数"；真正的区分靠 rva 本身。
//    （3 代靠 `[ebp+8]` vs `[ebp+0Ch]` 区分，4 代没有这个差异可用。）
// ────────────────────────────────────────────────────────────────────────

// LEFT：mov eax,[imm32]; sub esp,30h; test eax,eax; push ebx/ebp/esi/edi; jz rel32
#define SIG_WW_LEFT                                                       \
    { 0xA1,0,0,0,0, 0x83,0xEC,0x30, 0x85,0xC0, 0x53,0x55,0x56,0x57,       \
      0x0F,0x84,0,0,0,0 }
#define MSK_WW_LEFT                                                       \
    { 1,0,0,0,0, 1,1,1, 1,1, 1,1,1,1,                                     \
      1,1,0,0,0,0 }

// DIALOG/CENTER：mov eax,[imm32]; sub esp,30h; xor edx,edx;
//                push ebx/ebp/esi; cmp eax,edx; push edi; jz rel32
#define SIG_WW_DLG                                                        \
    { 0xA1,0,0,0,0, 0x83,0xEC,0x30, 0x33,0xD2, 0x53,0x55,0x56,            \
      0x3B,0xC2, 0x57, 0x0F,0x84,0,0,0,0 }
#define MSK_WW_DLG                                                        \
    { 1,0,0,0,0, 1,1,1, 1,1, 1,1,1,                                       \
      1,1, 1, 1,1,0,0,0,0 }

// 测量 A（累加字形宽）：
//   mov ecx,[esp+8]; push ebx; mov edx,ecx; push esi; shl edx,6; add edx,ecx; push edi
#define SIG_WW_MEASW                                                      \
    { 0x8B,0x4C,0x24,0x08, 0x53, 0x8B,0xD1, 0x56,                         \
      0xC1,0xE2,0x06, 0x03,0xD1, 0x57 }
#define MSK_WW_MEASW                                                      \
    { 1,1,1,1, 1, 1,1, 1,                                                 \
      1,1,1, 1,1, 1 }

// 测量 B（累加字形高-3）：
//   mov ecx,[esp+8]; push esi; mov edx,ecx; mov esi,[esp+8]; shl edx,6; add edx,ecx; push edi
//   ★ 第 4 条是 `8B 74 24 08`（mov esi,[esp+8]），与 MEASW 同位置的 `56`
//     （push esi）不同 —— 这是两者能互相区分的关键字节。
#define SIG_WW_MEASH                                                      \
    { 0x8B,0x4C,0x24,0x08, 0x56, 0x8B,0xD1, 0x8B,0x74,0x24,0x08,          \
      0xC1,0xE2,0x06, 0x03,0xD1, 0x57 }
#define MSK_WW_MEASH                                                      \
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
                      "签名超出 SIG_MAX，请调大 SIG_MAX");              \
        memcpy((profile).sig, _s, sizeof(_s));                        \
        memcpy((profile).sigMask, _m, sizeof(_m));                    \
        (profile).sigLen = (int)sizeof(_s);                           \
    } while (0)

static std::vector<GameProfile> MakeProfiles() {
    std::vector<GameProfile> v;

    // ══ Army Men: World War（GOG 英文版）══════════════════════════════
    {
        GameProfile g;
        g.id = "WorldWar";
        g.exeName = "amww.exe";

        // PE 实测：SizeOfImage=0x2F3000，TimeDateStamp=0x3B943B66
        //   ★ 与 3 代不同：4 代的时间戳是**正常值**（2001-09-04），
        //     不是 3 代那种伪造的 ASCII '1991'。两项校验都启用。
        g.imageSizeOfImage = 0x2F3000;
        g.timeStamp = 0x3B943B66;

        g.rendererVA = 0x466320;        // ★ 绝对 VA（勿再加 ImageBase）
        g.measureVA  = 0x466290;        // 测量：累加字形宽
        g.measureHVA = 0x466810;        // 测量：累加字形高-3

        // ── 游戏自身的绘制原语 ────────────────────────────────────────
        //   blit sub_427940：首句 v8 = dword_53D8F8 + a1 + dword_542220*a2
        //     1bpp RLE 字形 -> 目标表面
        //   rect sub_4430C0：(RECT*, clip, &x, &y, out) 返回 bool
        g.blitVA = 0x427940;
        g.rectVA = 0x4430C0;

        // ── 字体图集 ──────────────────────────────────────────────────
        //   ★★ 与 3 代的**地址**完全不同（结构对应，数值不同）：
        //     3 代 0x698D6C / 0x698DAC / 0x698F6C
        //     4 代 0x6BE524 / 0x6BE564 / 0x6BE724   (+ 0x6BE520 大小)
        g.atlasOffsetVA = 0x6BE524;     // word_6BE524：WORD[262*font + c] 字形偏移
        g.charWidthVA   = 0x6BE564;     // ★★ 不是宽度表，是上面的表右移 32 项
                                        //   （0x6BE564 - 0x6BE524 == 0x40 == 32 个
                                        //   WORD），即 CharWidth[c] ≡ atlasOffset[c+32]。
                                        //   当宽度用会让混排串从首个 ASCII 字符起整段消失。
                                        //   代码里已无读取点，仅登记备查。
        g.atlasSizeVA   = 0x6BE520;     // dword_6BE520：DWORD[131*font] 图集字节大小
        g.atlasBaseVA   = 0x6BE724;     // dword_6BE724：DWORD[131*font]
                                        //   ★ 其**内容**是堆指针，不是 RVA

        // ── 裁剪与表面 ────────────────────────────────────────────────
        g.clipRectVA    = 0x4AD330;     // rcSrc2（全局裁剪 RECT）
        g.rcVA          = 0x4AD350;     // rc 原点；rc.left@0x4AD350, rc.top@0x4AD354
        g.enabledVA     = 0x53C72C;     // dword_53C72C（表面锁标志）
                                        //   三个绘制函数开头都 `if(!dword_53C72C) return`
        g.surfaceVA     = 0x53D8F8;     // dword_53D8F8（目标像素缓冲）
        g.pitchVA       = 0x542220;     // dword_542220（行距）
        g.lockedSurfVA  = 0x53D7DC;     // dword_53D7DC（DirectDraw 对象；Lock/Unlock 用它）
        g.primarySurfVA = 0x546878;     // dword_546878（当前表面；与 dword_542224
                                        //   比较决定是否加 rc 原点）
        // ★ 显示区宽/高：4 代尚未定位到与 3 代 nWidth/nHeight(0x537828/0x53782C)
        //   对应的全局量。留 0 时 RendererValidateEnv 会跳过该项检查，
        //   像素写入的安全上界改由 rcSrc2 承担（语义裁剪本来就靠它）。
        g.dispWVA       = 0;
        g.dispHVA       = 0;

        DEFINE_SIG(g, SIG_WW_LEFT, MSK_WW_LEFT);
        g.logTag = "ArmyMenWWCHS";

        // ★ 是否只做"识别 + 无副作用标记"、不接管渲染。
        //   4 代五个函数的语义已全部经反编译确认，故**默认启用完整渲染**。
        //   ★ 出问题时的一键安全阀：把下面改成 true 重新编译，
        //     DLL 就只做识别验证而不改渲染行为。
        g.probeOnly = false;

        {
            static const BYTE _sl[] = SIG_WW_LEFT;
            static const BYTE _ml[] = MSK_WW_LEFT;
            static const BYTE _sd[] = SIG_WW_DLG;
            static const BYTE _md[] = MSK_WW_DLG;
            static const BYTE _sw[] = SIG_WW_MEASW;
            static const BYTE _mw[] = MSK_WW_MEASW;
            static const BYTE _sh[] = SIG_WW_MEASH;
            static const BYTE _mh[] = MSK_WW_MEASH;
            // ★ patchLen 必须落在指令边界上，4 代与 3 代不同：
            //     LEFT      : mov eax,[imm32](5) + sub esp,30h(3) + test(2) + push ebx(1)
            //                 -> 边界 10
            //     DIALOG    : 5 + 3 + xor(2) + push ebx(1) + push ebp(1) + push esi(1)
            //                 + cmp(2) + push edi(1) -> 边界 15
            //     CENTER    : 同 DIALOG -> 边界 15
            //     MEASURE   : mov(4) + push ebx(1) + mov(2) + push esi(1) + shl(3)
            //                 + add(2) -> 边界 11
            //     MEASURE_H : mov(4) + push esi(1) + mov(2) + mov esi,[esp+8](4)
            //                 + shl(3) -> 边界 14   ★ 不是 12（12 在 C1 E2 06 中间）
            AddHook(g, 0x466320, RK_LEFT,      _sl, _ml, (int)sizeof(_sl), 10);
            AddHook(g, 0x4664A0, RK_DIALOG,    _sd, _md, (int)sizeof(_sd), 15);
            AddHook(g, 0x466650, RK_CENTER,    _sd, _md, (int)sizeof(_sd), 15);
            AddHook(g, 0x466290, RK_MEASURE,   _sw, _mw, (int)sizeof(_sw), 11);
            AddHook(g, 0x466810, RK_MEASURE_H, _sh, _mh, (int)sizeof(_sh), 14);
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
