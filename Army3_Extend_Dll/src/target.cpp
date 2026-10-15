#include "pch.h"
#include "target.h"
#include "log.h"

#include <cstring>
#include <cstdio>

// ════════════════════════════════════════════════════════════════════════
//  Army Men: Toys in Space（3 代）档位表
//
//  ★ 全部数据来自本轮 IDA 逆向实测：
//      - 反编译：sub_450EA7 / sub_450FCF / sub_451114 / sub_450E3A / sub_451267
//      - 逐字节 disasm 核对序言（patchLen 边界）
//      - xrefs_to 统计调用点
//      - PE 头读 ImageBase / SizeOfImage / TimeDateStamp / 段布局
//
//  ★ 3 代与 2 代的三个决定性差异（决定了本文件不能照抄 2 代）：
//
//    ① 渲染器**返回 void**，不再返回"结束 x"
//       2 代：sub_446930 等返回 int（文本结束后的 x），AM2 的 RenderCore
//             靠 stub 返回值推进 ASCII 光标。
//       3 代：LEFT 用 `v18 += v15` 内部推进，函数声明就是 `void`。
//             -> 靠返回值推进的契约**不存在**，推进量必须自己从字形头取
//                （见 renderer.cpp 的 GlyphAdvance / GlyphHeight）。
//
//    ② 文本**不在 exe 里**，全在 strings\strings.txt
//       -> 3 代没有"内存字符串补丁"这一环，去掉 strings.cpp。
//
//    ③ 测量函数有**两个**，2 代只有一个
//       sub_450E3A 累加字形**宽**   （14 调用点，算文本宽度）
//       sub_451267 累加字形**高-3** （3 调用点，居中菜单算总行高）
//       -> 两个都必须 hook，否则居中菜单的裁剪矩形会算错。
// ════════════════════════════════════════════════════════════════════════

// ── 地址语义约定 ────────────────────────────────────────────────────────
//
//  本文件里，凡是**要与函数指针/全局量一起使用**的地址，
//  一律写成 IDA 里显示的**绝对 VA**（如 0x450EA7、0x698D6C），
//  读取时**不得**再加 ImageBase。
//
//  唯一的例外是 HookSite.rva —— 那是给 VirtualProtect/memcpy 用的
//  **映像内 RVA**，由 VA - RVA 换算得来。
//
//  历史教训（2 代，本项目因此崩过两次）：
//    * 一次"少加"：atlasBase 的内容是 malloc 堆指针，当 RVA 加了基址 -> 取不到字形
//    * 一次"多加"：surfaceVA 已是 VA，又加基址 -> 0x8FE1A8 野地址 -> 崩溃
//  两者本质相同：**必须清楚每个数是 RVA 还是 VA，以及它指向的值是什么语义**。
static const DWORD RVA = 0x400000;   // ImageBase（实测 3 代同为 0x400000）

// ────────────────────────────────────────────────────────────────────────
//  签名（取各函数**序言**，对绝对地址与 rel32 通配）
//
//  3 代三个渲染器的序言形状（实测）：
//     LEFT   55 8B EC | 83 EC 38 | 83 3D <dword_521D2C> 00 | 53 56 57 |
//            0F 84 <rel32> | 8B 75 10 | 56 | E8 <rel32>
//     DIALOG 55 8B EC | 83 EC 38 | 53 56 57 | 33 FF | 39 3D <dword_521D2C> |
//            0F 84 <rel32> | 8B 75 10 | 56 | E8 <rel32> | 59 3B C7 |
//            8B 4D **08** | 89 45
//     CENTER 与 DIALOG 完全相同，**只差末尾那个 [ebp+8 vs +C]** 与 jz rel32
//
//  ★ 为什么 DIALOG/CENTER 的签名要一直取到 `8B 4D 08 / 0C`：
//    若只取到 rel32 通配处，两者签名会完全一致 —— 虽然地址不同不至于
//    hook 错，但签名校验就失去了"确认这个 RVA 上确实是那个函数"的意义。
//    多取 8 字节后，08（DIALOG，第 5 参是 RECT）与 0C（CENTER）能互相区分。
//
//  ★ LEFT 与 DIALOG/CENTER 靠开头的 `83 3D`（cmp mem）vs `33 FF 39 3D`
//    （xor edi,edi; cmp mem）天然区分，无需额外字节。
// ────────────────────────────────────────────────────────────────────────

#define SIG_TIS_LEFT                                                      \
    { 0x55,0x8B,0xEC, 0x83,0xEC,0x38, 0x83,0x3D,0,0,0,0, 0x00,           \
      0x53,0x56,0x57, 0x0F,0x84,0,0,0,0, 0x8B,0x75,0x10, 0x56,           \
      0xE8,0,0,0,0 }
#define MSK_TIS_LEFT                                                      \
    { 1,1,1, 1,1,1, 1,1,0,0,0,0, 1,                                      \
      1,1,1, 1,1,0,0,0,0, 1,1,1, 1,                                      \
      1,0,0,0,0 }

// DIALOG：第 5 参（&a5）即裁剪 RECT 起点，[ebp+8] = a1 = x
#define SIG_TIS_DLG                                                       \
    { 0x55,0x8B,0xEC, 0x83,0xEC,0x38, 0x53,0x56,0x57, 0x33,0xFF,          \
      0x39,0x3D,0,0,0,0, 0x0F,0x84,0,0,0,0, 0x8B,0x75,0x10, 0x56,         \
      0xE8,0,0,0,0, 0x59,0x3B,0xC7, 0x8B,0x4D,0x08, 0x89,0x45 }
#define MSK_TIS_DLG                                                       \
    { 1,1,1, 1,1,1, 1,1,1, 1,1,                                           \
      1,1,0,0,0,0, 1,1,0,0,0,0, 1,1,1, 1,                                 \
      1,0,0,0,0, 1,1,1, 1,1,1, 1,1 }

// CENTER：与 DIALOG 同形，末尾是 [ebp+0Ch]
#define SIG_TIS_CTR                                                       \
    { 0x55,0x8B,0xEC, 0x83,0xEC,0x38, 0x53,0x56,0x57, 0x33,0xFF,          \
      0x39,0x3D,0,0,0,0, 0x0F,0x84,0,0,0,0, 0x8B,0x75,0x10, 0x56,         \
      0xE8,0,0,0,0, 0x59,0x3B,0xC7, 0x8B,0x4D,0x0C, 0x89,0x45 }
#define MSK_TIS_CTR                                                       \
    { 1,1,1, 1,1,1, 1,1,1, 1,1,                                           \
      1,1,0,0,0,0, 1,1,0,0,0,0, 1,1,1, 1,                                 \
      1,0,0,0,0, 1,1,1, 1,1,1, 1,1 }

// ── 测量函数 A：sub_450E3A，累加字形**宽** ──────────────────────────────
//   8B 4C 24 08   mov  ecx,[esp+8]        ; a2 = font
//   56            push esi
//   69 C9 0C 02 00 00  imul ecx,ecx,20Ch  ; ecx = font*524 = font*262*2
//   8B 74 24 08   mov  esi,[esp+8]        ; a1 = str（push 之后位置变了）
//   57            push edi
//   8B 91 <imm32> mov  edx,[ecx+698F6Ch]  ; edx = atlasBase[font]  ← 通配
//   33 FF         xor  edi,edi
//   ★ 指令边界：0,4,5,11,15,16,22 —— patchLen=5 恰好落在 push esi 之后
#define SIG_TIS_MEASW                                                     \
    { 0x8B,0x4C,0x24,0x08, 0x56, 0x69,0xC9,0x0C,0x02,0x00,0x00,           \
      0x8B,0x74,0x24,0x08, 0x57, 0x8B,0x91,0,0,0,0, 0x33,0xFF }
#define MSK_TIS_MEASW                                                     \
    { 1,1,1,1, 1, 1,1,1,1,1,1,                                            \
      1,1,1,1, 1, 1,1,0,0,0,0, 1,1 }

// ── 测量函数 B：sub_451267，累加字形**高-3**（3 代新增）─────────────────
//   8B 4C 24 08   mov  ecx,[esp+8]        ; a2 = font
//   8B 54 24 04   mov  edx,[esp+4]        ; a1 = str
//   69 C9 0C 02 00 00  imul ecx,ecx,20Ch
//   33 C0         xor  eax,eax
//   38 02         cmp  [edx],al
//   8B 89 <imm32> mov  ecx,[ecx+698F6Ch]  ← 通配
//   74 <rel8>     jz   ...
//   ★ 指令边界：0,4,8,14,16,18,24,26 —— patchLen=8 落在 imul 之后
#define SIG_TIS_MEASH                                                     \
    { 0x8B,0x4C,0x24,0x08, 0x8B,0x54,0x24,0x04,                           \
      0x69,0xC9,0x0C,0x02,0x00,0x00, 0x33,0xC0, 0x38,0x02,                \
      0x8B,0x89,0,0,0,0, 0x74,0, 0x53,0x56,0x57 }
#define MSK_TIS_MEASH                                                     \
    { 1,1,1,1, 1,1,1,1,                                                   \
      1,1,1,1,1,1, 1,1, 1,1,                                              \
      1,1,0,0,0,0, 1,0, 1,1,1 }

// 往档位里加一个 hook 目标
static void AddHook(GameProfile& g, DWORD va, RenderKind kind,
                    const BYTE* sig, const BYTE* mask, int n, int patchLen)
{
    HookSite h;
    h.rva = va - RVA;
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

    // ══ Army Men: Toys in Space（Steam 英文版）════════════════════════
    {
        GameProfile g;
        g.id = "ToysInSpace";
        g.exeName = "armymentis.exe";

        // PE 实测：SizeOfImage=0x2CC000，TimeDateStamp=0x31313931
        //   ★ 时间戳是个明显的伪造值（ASCII '1991'），3DO 当年常用这种手法，
        //     但仍可作为"这个具体构建"的判据 —— 换构建它大概率会变。
        //     故这里**启用**两项校验（2 代 TIS 档位当时只能留 0）。
        g.imageSizeOfImage = 0x2CC000;
        g.timeStamp = 0x31313931;

        g.rendererVA = 0x450EA7;        // ★ 绝对 VA（勿再减 RVA）
        g.measureVA  = 0x450E3A;        // 测量：累加字形宽
        g.measureHVA = 0x451267;        // 测量：累加字形高-3（3 代新增）

        // ── 游戏自身的绘制原语 ────────────────────────────────────────
        g.blitVA = 0x4212F0;            // 首句 v8 = dword_522EF8 + a1 + dword_527820*a2
                                        //   -> a1=x, a2=y（已确认）
        g.rectVA = 0x435EDE;            // 矩形裁剪/定位：in-place 改 x/y，返回 bool

        // ── 字体图集三张表 ────────────────────────────────────────────
        //   与 2 代完全同构的偏移关系（可交叉印证）：
        //     2 代 0x6598D4 + 0x40 -> 0x659914（charWidth）, + 0x200 -> 0x659AD4
        //     3 代 0x698D6C + 0x40 -> 0x698DAC（charWidth）, + 0x200 -> 0x698F6C
        g.atlasOffsetVA = 0x698D6C;     // word_698D6C：WORD[262*font + c] 字形偏移
        g.charWidthVA   = 0x698DAC;     // word_698DAC：WORD[262*font + c] 步进宽
        g.atlasBaseVA   = 0x698F6C;     // dword_698F6C：DWORD[131*font]
                                        //   ★ 其**内容**是堆指针，不是 RVA

        // ── 裁剪与表面 ────────────────────────────────────────────────
        g.clipRectVA    = 0x491088;     // rcSrc2（全局裁剪 RECT）
        g.rcVA          = 0x4910A8;     // rc 原点偏移；rc.left@0x4910A8, rc.top@0x4910AC
        g.lockedSurfVA  = 0x52BE78;     // dword_52BE78（当前锁定表面）
        g.primarySurfVA = 0x527824;     // dword_527824（主表面）
        g.enabledVA     = 0x521D2C;     // dword_521D2C（表面锁标志）
        g.surfaceVA     = 0x522EF8;     // dword_522EF8（目标像素缓冲）
        g.pitchVA       = 0x527820;     // dword_527820（行距）
        g.dispWVA       = 0x537828;     // nWidth（18 处引用）
        g.dispHVA       = 0x53782C;     // nHeight（13 处引用）

        DEFINE_SIG(g, SIG_TIS_LEFT, MSK_TIS_LEFT);
        g.logTag = "ArmyMenTISCHS";

        // ★ 是否只做"识别 + 无副作用标记"、不接管渲染。
        //   3 代四个函数的语义已全部经反编译确认，故**默认启用完整渲染**。
        //   ★ 出问题时的一键安全阀：把下面改成 true 重新编译，
        //     DLL 就只在渲染器入口挂标记（证明档位识别正确）而不改渲染行为。
        g.probeOnly = false;

        {
            static const BYTE _sl[] = SIG_TIS_LEFT;
            static const BYTE _ml[] = MSK_TIS_LEFT;
            static const BYTE _sd[] = SIG_TIS_DLG;
            static const BYTE _md[] = MSK_TIS_DLG;
            static const BYTE _sc[] = SIG_TIS_CTR;
            static const BYTE _mc[] = MSK_TIS_CTR;
            static const BYTE _sw[] = SIG_TIS_MEASW;
            static const BYTE _mw[] = MSK_TIS_MEASW;
            static const BYTE _sh[] = SIG_TIS_MEASH;
            static const BYTE _mh[] = MSK_TIS_MEASH;
            // ★ patchLen 必须落在指令边界上，3 代与 2 代不同：
            //     LEFT/DIALOG/CENTER : push ebp(1) + mov ebp,esp(2) + sub esp,38h(3)
            //                          -> 边界 6（★ 不是 2 代的 5）
            //     MEASURE_W          : mov ecx,[esp+8](4) + push esi(1) -> 边界 5
            //     MEASURE_H          : mov(4) + mov(4) -> 边界 8
            AddHook(g, 0x450EA7, RK_LEFT,      _sl, _ml, (int)sizeof(_sl), 6);
            AddHook(g, 0x450FCF, RK_DIALOG,    _sd, _md, (int)sizeof(_sd), 6);
            AddHook(g, 0x451114, RK_CENTER,    _sc, _mc, (int)sizeof(_sc), 6);
            AddHook(g, 0x450E3A, RK_MEASURE,   _sw, _mw, (int)sizeof(_sw), 5);
            AddHook(g, 0x451267, RK_MEASURE_H, _sh, _mh, (int)sizeof(_sh), 8);
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
