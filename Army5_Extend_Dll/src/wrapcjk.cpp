// wrapcjk.cpp —— CJK 长文本换行修复（v2：用游戏自己的测量函数定边界）
//
// ════════════════════════════════════════════════════════════════════════
//  根因（IDA 全量反汇编 sub_42EF50 @0x42EF50..0x42F150）
// ════════════════════════════════════════════════════════════════════════
//
//    sub_42EF50 的断行是「贪心塞满 -> 往回退找空格」：
//
//      0x42EFE5  mov  [esi],cl          ; 逐字节复制进缓冲
//      0x42EFEA  cmp  edi,80h           ; 缓冲硬上限 128 字节
//      0x42F007  call sub_4885B0        ; ★ 用引擎自己的测量算当前缓冲宽
//      0x42F012  mov  ecx,[ebp+934h]    ; maxW
//      0x42F015  cmp  eax,ecx
//      0x42F017  jl   0x42F063          ; 宽 < maxW -> 继续塞
//    ---- 超宽，回退 ----
//      0x42F019  dec ebx / dec esi / dec edi
//      0x42F01E  movsx ecx,[ebx] ; call _isspace
//      0x42F02C  jz   0x42F019          ; 不是空格 -> 再退
//      0x42F02E  test edi,edi
//      0x42F034  jle  0x42F139          ; ★★ 退到开头仍无空格 -> 整个函数退出
//
//  ★ 中文没有空格。长句塞到超宽后一路退到 edi<=0，`jle 0x42F139` 直接
//    跳出整个函数，剩余文字一行都不写；行槽里残留旧内容或未初始化堆，
//    按 GBK 解码就是 `段#《庠档姆较甘镜苹峋` 这类怪字。
//    所以「乱码」和「不显示」是同一个根因。
//
// ════════════════════════════════════════════════════════════════════════
//  v1 的教训：不能用估算宽度
// ════════════════════════════════════════════════════════════════════════
//
//    v1 用「汉字=字体档字高、ASCII=字高/2」估算行宽来决定在哪插空格。
//    引擎实际宽度不是这个值（它按**单字节**查 ASCII 字形偏移表累加，
//    两个字节加起来并不等于字高），于是：
//
//      · 我插空格的位置 ≠ 引擎判定超宽的位置
//      · 引擎在别处超宽 -> 回退 -> 找到的是**上一个**空格 -> 截断点偏移
//      · 一旦偏移落在汉字的 lead/trail 之间，整个汉字被劈开：
//            运 = D4 CB，从 CB 起拼上下一字的 A1 -> CB A1 = 恕（用户实测）
//            范 = B7 B6，从 B6 起 -> 后续每字节错位 ->
//            段#《庠档姆较甘镜苹峋…（用户实测）
//
//  ★ 修法：**直接调引擎自己的测量函数 sub_4885B0（我们的 Hook_MEASURE）**
//    来判定边界。引擎用什么量，我们就用什么量，位置必然一致。
//
// ════════════════════════════════════════════════════════════════════════
//  当前做法
// ════════════════════════════════════════════════════════════════════════
//
//    在 sub_42EF50 入口拦下来，若串含 CJK 且超宽，就逐字符重建：
//    每追加一个字符就用 Hook_MEASURE 量当前行宽度，一旦 >= maxW 就
//    在**该字符之前**插入一个空格并把行起点移到该字符。
//
//    · 插入点永远在字符边界上（先判边界再插入），绝无劈字可能
//    · 判宽与引擎同源（同一个函数），位置必然对得上
//    · 插入的空格被引擎 `0x42F03A mov [esi],0` 截掉、再经
//      0x42F043..0x42F059 跳过，不会显示
//    · ASCII 串 / 未超宽串：完全原样放行
//
// ════════════════════════════════════════════════════════════════════════
//  ABI：__fastcall 精确匹配 __thiscall
// ════════════════════════════════════════════════════════════════════════
//
//    原函数 int __thiscall sub_42EF50(this/*ecx*/, const char* s, char color)
//    调用点是 `push color; push s` -> retn 8。
//    MSVC __fastcall: ecx->arg1, edx->arg2, 其余走栈。故声明成
//    (void* thisPtr, void* dummy, const char* s, char color) 与它同构，
//    返回时自动 `ret 8`，不需要 naked 壳。
//
//    trampoline：`sub esp,90h; jmp 0x42EF56`
//    原函数首条指令 81 EC 90 00 00 00 必须完整复现（0x42EF56 之后有
//    `[esp+9Ch+arg_0]` 这类依赖已减栈的寻址）。
// ════════════════════════════════════════════════════════════════════════
#include "pch.h"
#include "wrapcjk.h"
#include "log.h"

#include <string>

// 渲染层的测量入口（renderer.cpp，extern "C"，非 static）。
// 它就是引擎原本调用的那个函数，所以宽度语义与引擎 100% 同源。
extern "C" int __cdecl Hook_MEASURE(const char* str, int font, int* out);

typedef int (__fastcall* PFN_lineFn)(void* thisPtr, void* dummy,
                                     const char* str, char color);

static BYTE*      g_site   = nullptr;
static BYTE       g_orig[16] = {0};
static int        g_len    = 0;
static void*      g_tramp  = nullptr;
static PFN_lineFn g_origLine = nullptr;
static bool       g_active = false;

static const DWORD OFF_FONT = 0x904;   // 0x42EFF9 mov edx,[ebp+904h]
static const DWORD OFF_MAXW = 0x934;   // 0x42F00C mov ecx,[ebp+934h]

bool WrapCjkIsActive() { return g_active; }

// 兜底用的字高表（仅在 Hook_MEASURE 不可用时估算，正常路径不用）
static const int CJK_BOX_BY_FONT[9] = { 8, 12, 15, 18, 18, 24, 12, 14, 16 };

static int BoxForFont(int font)
{
    return (font >= 0 && font < 9) ? CJK_BOX_BY_FONT[font] : 15;
}

// 用引擎的测量函数量宽度。不可用时返回 -1。
static int MeasureExact(const char* s, int font)
{
    if (!s || !*s) return 0;
    int w = Hook_MEASURE(s, font, nullptr);
    return (w >= 0) ? w : -1;
}

// 估算（只在 MeasureExact 不可用时用）
static int MeasureEstimate(const char* s, int box)
{
    int w = 0;
    const unsigned char* p = (const unsigned char*)s;
    while (*p) {
        if (*p == 0x5E) { if (p[1] == 0) break; p += 2; continue; }
        if (*p > 0xA0) { w += box; p += (p[1] != 0) ? 2 : 1; continue; }
        if (*p < 0x1F) { p += 1; continue; }
        w += (box > 1) ? box / 2 : 6;
        p += 1;
    }
    return w;
}

static bool HasCjk(const char* s)
{
    const unsigned char* p = (const unsigned char*)s;
    while (*p) {
        if (*p == 0x5E) { if (p[1] == 0) break; p += 2; continue; }
        if (*p > 0xA0) return true;
        p += 1;
    }
    return false;
}

// ────────────────────────────────────────────────────────────────────────
//  按引擎的实际宽度插空格。
//
//  out         输出缓冲
//  cap         out 容量
//  insertPos  记录每个插入点在**源串**里的字节偏移（诊断用）
//  insertMax  insertPos 容量
//  返回新串长度；<=0 表示未处理/失败。
// ────────────────────────────────────────────────────────────────────────
static int BuildWrapped(const char* src, int font, int maxW,
                        char* out, int cap,
                        int* insertPos, int insertMax, int* insertCount)
{
    int n = 0;              // 输出游标
    int lineStart = 0;      // 当前行在 out 中的起始下标
    int charsInLine = 0;    // 当前行已放的**可计宽**字符数
    int nIns = 0;
    int i = 0;              // 源串字节偏移

    const int box = BoxForFont(font);

    while (src[i]) {
        unsigned char c = (unsigned char)src[i];

        // '^' 颜色转义：整体搬运，不计宽（引擎测量也会跳过它）
        if (c == 0x5E) {
            if (!src[i + 1]) break;
            if (n + 2 >= cap) return -1;
            out[n++] = src[i];
            out[n++] = src[i + 1];
            i += 2;
            continue;
        }

        // 控制字符：搬运，不计宽、不算字符
        if (c < 0x1F) {
            if (n + 1 >= cap) return -1;
            out[n++] = (char)c;
            i += 1;
            continue;
        }

        // ★ 字符边界：与渲染/测量同一条规则（>0xA0 视为双字节）
        int clen = 1;
        if (c > 0xA0) clen = (src[i + 1] != 0) ? 2 : 1;

        if (n + clen >= cap) return -1;

        // 先追加该字符（**整字**追加，绝不在中间断开）
        int before = n;
        out[n++] = src[i];
        if (clen == 2) out[n++] = src[i + 1];
        out[n] = 0;

        // 用引擎的量具判当前行是否已超宽
        int w = MeasureExact(out + lineStart, font);
        if (w < 0) w = MeasureEstimate(out + lineStart, box);

        // 超宽且本行已有字符 -> 把该字符挪到下一行（在它之前插空格）
        if (w >= maxW && charsInLine > 0) {
            n = before;                    // 退回该字符之前
            if (n + 1 >= cap) return -1;
            out[n++] = ' ';                // ★ 插入点在字符边界上
            if (nIns < insertMax) insertPos[nIns] = i;
            nIns++;
            lineStart = n;                 // 新行从空格之后开始
            charsInLine = 0;

            // 重新放入该字符
            if (n + clen >= cap) return -1;
            out[n++] = src[i];
            if (clen == 2) out[n++] = src[i + 1];
            out[n] = 0;
            charsInLine = 1;
        } else {
            charsInLine++;
        }

        i += clen;
    }

    if (n == 0) return -1;
    out[n] = 0;
    if (insertCount) *insertCount = nIns;
    return n;
}

int __fastcall Hook_Line(void* thisPtr, void* dummy,
                         const char* str, char color)
{
    if (!g_origLine) return 0;
    if (!thisPtr || !str || !*str)
        return g_origLine(thisPtr, dummy, str, color);

    const BYTE* base = (const BYTE*)thisPtr;
    int font = *(const int*)(base + OFF_FONT);
    int maxW = *(const int*)(base + OFF_MAXW);

    // 框宽/字体异常（未初始化或已释放）时完全不动，原样放行
    if (maxW <= 0 || maxW > 8192 || font < 0 || font > 31)
        return g_origLine(thisPtr, dummy, str, color);

    // 不含汉字 -> 引擎自己的空格断行够用，零干预
    if (!HasCjk(str))
        return g_origLine(thisPtr, dummy, str, color);

    // 引擎的量具不可用（渲染层还没装好）-> 不冒险，原样放行
    int total = MeasureExact(str, font);
    if (total < 0)
        return g_origLine(thisPtr, dummy, str, color);

    int box = BoxForFont(font);
    if (total <= 0) total = MeasureEstimate(str, box);

    // 本来就放得下 -> 不干预
    if (total < maxW)
        return g_origLine(thisPtr, dummy, str, color);

    char buf[4096];
    int  insPos[256];
    int  nIns = 0;
    int n = BuildWrapped(str, font, maxW, buf, (int)sizeof(buf), insPos, 256, &nIns);
    if (n <= 0) {
        static int once = 0;
        if (once++ < 3)
            Log("WrapCjk: 构造失败，放行原串（font=%d box=%d maxW=%d 原宽=%d）",
                font, box, maxW, total);
        return g_origLine(thisPtr, dummy, str, color);
    }

    static int logged = 0;
    if (logged++ < 12) {
        std::string pos;
        for (int k = 0; k < nIns && k < 12; k++) {
            char t[16];
            sprintf_s(t, sizeof(t), k ? ",%d" : "%d", insPos[k]);
            pos += t;
        }
        Log("WrapCjk: font=%d box=%d maxW=%d 原宽=%d 原长=%d -> 新长=%d 插%d处@[%s]",
            font, box, maxW, total, (int)strlen(str), n, nIns, pos.c_str());
    }
    return g_origLine(thisPtr, dummy, buf, color);
}

bool WrapCjkInstall(const WrapCjkConfig& cfg)
{
    Log("WrapCjk: ===== 安装『CJK 长文本换行』修复（v2 引擎量具定边界）=====");

    if (!cfg.siteVA || cfg.patchLen < 5 || cfg.patchLen > 16 ||
        cfg.sigLen <= 0 || cfg.sigLen > (int)sizeof(cfg.sig)) {
        Log("WrapCjk: 配置非法，跳过");
        return false;
    }

    BYTE* modBase = (BYTE*)GetModuleHandleA(nullptr);
    DWORD imgBase = (DWORD)(DWORD_PTR)modBase;
    if (!modBase || cfg.siteVA < imgBase) {
        Log("WrapCjk: 模块基址异常，跳过");
        return false;
    }
    BYTE* site = modBase + (cfg.siteVA - imgBase);

    for (int i = 0; i < cfg.sigLen; i++) {
        if (site[i] != cfg.sig[i]) {
            Log("WrapCjk: 签名不匹配 @+%d 期望 %02X 实得 %02X，拒绝安装",
                i, cfg.sig[i], site[i]);
            return false;
        }
    }

    // trampoline：复现 `sub esp,90h`，再跳回 0x42EF56
    BYTE* t = (BYTE*)VirtualAlloc(nullptr, 64, MEM_COMMIT | MEM_RESERVE,
                                  PAGE_EXECUTE_READWRITE);
    if (!t) {
        Log("WrapCjk: trampoline 分配失败 (%lu)", GetLastError());
        return false;
    }
    int tn = 0;
    t[tn++] = 0x81; t[tn++] = 0xEC;
    t[tn++] = 0x90; t[tn++] = 0x00; t[tn++] = 0x00; t[tn++] = 0x00;
    t[tn++] = 0xE9;
    {
        int off = tn; tn += 4;
        BYTE* resume = modBase + (cfg.resumeVA - imgBase);
        int rel = (int)(DWORD_PTR)resume - (int)(DWORD_PTR)(t + off + 4);
        memcpy(t + off, &rel, 4);

        // ★ 回读校验真实落点（踩过「rel 漏算壳基址」的坑，必须验）
        int back = 0; memcpy(&back, t + off, 4);
        DWORD dst = (DWORD)(t + off + 4 + back);
        if (dst != (DWORD)(DWORD_PTR)resume) {
            Log("WrapCjk: trampoline 落点校验失败 %#x != %p，放弃",
                dst, (void*)resume);
            VirtualFree(t, 0, MEM_RELEASE);
            return false;
        }
        Log("WrapCjk: trampoline %p -> 复原后跳到 %#x（校验通过）",
            t, cfg.resumeVA);
    }
    FlushInstructionCache(GetCurrentProcess(), t, tn);

    DWORD oldProt = 0;
    if (!VirtualProtect(site, cfg.patchLen, PAGE_EXECUTE_READWRITE, &oldProt)) {
        Log("WrapCjk: VirtualProtect 失败 (%lu)", GetLastError());
        VirtualFree(t, 0, MEM_RELEASE);
        return false;
    }

    memcpy(g_orig, site, cfg.patchLen);
    g_site  = site;
    g_len   = cfg.patchLen;
    g_tramp = t;
    g_origLine = (PFN_lineFn)t;

    BYTE patch[16];
    memset(patch, 0x90, sizeof(patch));
    patch[0] = 0xE9;
    {
        int rel = (int)(DWORD_PTR)&Hook_Line - (int)(DWORD_PTR)(site + 5);
        memcpy(patch + 1, &rel, 4);
    }
    memcpy(site, patch, cfg.patchLen);

    DWORD tmp = 0;
    VirtualProtect(site, cfg.patchLen, oldProt, &tmp);
    FlushInstructionCache(GetCurrentProcess(), site, cfg.patchLen);

    g_active = true;
    Log("WrapCjk: %#x 已替换 -> jmp %p（patchLen=%d，原字节 %02X %02X %02X %02X %02X %02X）",
        cfg.siteVA, &Hook_Line, cfg.patchLen,
        g_orig[0], g_orig[1], g_orig[2], g_orig[3], g_orig[4], g_orig[5]);
    Log("WrapCjk: 边界用引擎自己的 sub_4885B0 判定，插入点必在字符边界");
    return true;
}

void WrapCjkRemove()
{
    if (!g_active || !g_site) return;
    DWORD oldProt = 0;
    if (VirtualProtect(g_site, g_len, PAGE_EXECUTE_READWRITE, &oldProt)) {
        memcpy(g_site, g_orig, g_len);
        DWORD tmp = 0;
        VirtualProtect(g_site, g_len, oldProt, &tmp);
        FlushInstructionCache(GetCurrentProcess(), g_site, g_len);
        Log("WrapCjk: 已恢复原始字节");
    }
    if (g_tramp) { VirtualFree(g_tramp, 0, MEM_RELEASE); g_tramp = nullptr; }
    g_origLine = nullptr;
    g_site = nullptr;
    g_len  = 0;
    g_active = false;
}
