#include "pch.h"
#include "hooks.h"
#include "ini_reader.h"
#include <string>
#include <vector>
#include <map>
#include <algorithm>
#include <cstdio>
#include <cstdarg>

// ---------------------------------------------------------------- 全局状态（前置）

static HMODULE g_hModule = nullptr;      // 自身模块（LogToFile 需要）

// ---------------------------------------------------------------- 日志

// 同时输出到 OutputDebugString 与同目录日志文件。
// 崩溃排查必需：OutputDebugString 在无调试器时看不到。
static void LogToFile(const char* line) {
    static bool inited = false;
    static wchar_t path[MAX_PATH] = {0};
    if (!inited) {
        inited = true;
        if (g_hModule) {
            wchar_t mod[MAX_PATH] = {0};
            GetModuleFileNameW(g_hModule, mod, MAX_PATH);
            wchar_t* slash = wcsrchr(mod, L'\\');
            if (slash) *(slash + 1) = 0;
            else mod[0] = 0;
            wcsncpy_s(path, MAX_PATH, mod, _TRUNCATE);
            wcscat_s(path, MAX_PATH, L"ArmyMenCHS.log");
        }
    }
    if (!path[0]) return;
    FILE* f = nullptr;
    if (_wfopen_s(&f, path, L"a, ccs=UTF-8") == 0 && f) {
        SYSTEMTIME st;
        GetLocalTime(&st);
        fwprintf(f, L"[%02d:%02d:%02d.%03d] %S\n",
                 st.wHour, st.wMinute, st.wSecond, st.wMilliseconds, line);
        fclose(f);
    }
}

static void Log(const char* fmt, ...) {
    char buf[1024];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    OutputDebugStringA("[ArmyMenCHS] ");
    OutputDebugStringA(buf);
    OutputDebugStringA("\n");
    LogToFile(buf);
}

// ---------------------------------------------------------------- 全局状态

static std::vector<IniBlock> g_blocks;
static bool     g_dataLoaded = false;

struct PatchedEntry {
    DWORD       rva;
    std::string gbk;
    int         capacity;
    bool        applied;
};
static std::vector<PatchedEntry> g_patches;

static bool   g_fontEnable = true;
static bool   g_stringEnable = true;     // [Strings] Enable
static std::string g_faceName = "\xE5\xAE\x8B\xE4\xBD\x93";  // UTF-8 "宋体"
static BYTE   g_charSet = 134;   // GB2312_CHARSET

// "No unit" → 中文。空表示不改（保持英文）。
// ★ 不走 INI 槽位补丁：两处字面量容量只有 8 字节，"没有部队" GBK 是 9 字节，
//   必被 too-long 拒绝，所以改用立即数改写（见 PatchNoUnitString）。
static std::string g_noUnitZh = "没有部队";

// "Sarge" → 中文。空表示不改。
// 同样走立即数改写：原串被车辆动画路径共用，只改 ItemName 那一处引用。
static std::string g_sargeZh = "中士";

// ---------------------------------------------------------------- 编码转换

static std::string Utf8ToGbk(const std::string& utf8) {
    if (utf8.empty()) return {};
    int nw = MultiByteToWideChar(CP_UTF8, 0, utf8.c_str(), (int)utf8.size(),
                                 nullptr, 0);
    if (nw <= 0) return {};
    std::wstring w(nw, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, utf8.c_str(), (int)utf8.size(), &w[0], nw);

    int ng = WideCharToMultiByte(936 /*GBK*/, 0, w.c_str(), nw,
                                 nullptr, 0, nullptr, nullptr);
    if (ng <= 0) return {};
    std::string g(ng, '\0');
    WideCharToMultiByte(936, 0, w.c_str(), nw, &g[0], ng, nullptr, nullptr);
    return g;
}

// ---------------------------------------------------------------- 数据加载

static std::wstring GetDllDir() {
    wchar_t path[MAX_PATH] = {0};
    GetModuleFileNameW(g_hModule, path, MAX_PATH);
    std::wstring p(path);
    size_t pos = p.find_last_of(L"\\/");
    return (pos == std::wstring::npos) ? L"." : p.substr(0, pos);
}

bool LoadTranslationData() {
    std::wstring dir = GetDllDir();
    std::wstring cfgPath = dir + L"\\ArmyMenCHS.ini";

    IniReader r;
    std::ifstream f(cfgPath);
    if (!f.is_open()) {
        Log("config not found: %ls", cfgPath.c_str());
        return false;
    }

    std::string sec, line;
    while (std::getline(f, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        std::string t = ini_trim(line);
        if (t.empty() || t[0] == ';' || t[0] == '#') continue;
        if (t[0] == '[') {
            size_t e = t.find(']');
            sec = (e == std::string::npos) ? "" : t.substr(1, e - 1);
            continue;
        }
        size_t eq = t.find('=');
        if (eq == std::string::npos) continue;
        std::string k = ini_trim(t.substr(0, eq));
        std::string v = ini_trim(t.substr(eq + 1));

        if (sec == "Font") {
            if (k == "Enable") g_fontEnable = (v == "1" || v == "true");
            else if (k == "FaceName") {
                // ★★ 关键：ini 是 UTF-8，但 CreateFontA 是 **ANSI** 版，
                //   lfFaceName 期望 GBK 字节。直接把 UTF-8 的"宋体"
                //   (E5 AE 8B E4 BD 93) 传进去 → 字体名无效 → CreateFont
                //   返回 NULL → 游戏 SelectObject(NULL) → 渲染时崩溃
                //   （曾导致 Armymen.exe+0x49836 读 [0+0x20] 的访问违例）。
                //   此处统一转成 GBK。
                g_faceName = Utf8ToGbk(v);
                Log("Font FaceName: '%s' -> GBK %d bytes",
                    v.c_str(), (int)g_faceName.size());
            }
            else if (k == "CharSet") g_charSet = (BYTE)atoi(v.c_str());
        } else if (sec == "Strings") {
            if (k == "Enable") g_stringEnable = (v == "1" || v == "true");
            if (k == "NoUnit") {
                // 空值 = 关闭该项改写（保持英文 "No unit"）
                g_noUnitZh = v;
                Log("NoUnit 译名: '%s'", v.c_str());
            }
            if (k == "Sarge") {
                // 空值 = 关闭该项改写（保持英文 "Sarge"）
                g_sargeZh = v;
                Log("Sarge 译名: '%s'", v.c_str());
            }
            if (k == "Files") {
                size_t start = 0;
                while (start <= v.size()) {
                    size_t c = v.find(',', start);
                    std::string one = (c == std::string::npos)
                                      ? v.substr(start) : v.substr(start, c - start);
                    one = ini_trim(one);
                    if (!one.empty()) {
                        std::wstring wf(one.begin(), one.end());
                        std::wstring fp = dir + L"\\strings\\" + wf;
                        IniBlock blk;
                        if (r.load(fp, blk)) {
                            g_blocks.push_back(blk);
                            Log("loaded block: %ls (%d entries) base=%s",
                                fp.c_str(), (int)blk.entries.size(),
                                blk.baseRVA.c_str());
                        } else {
                            Log("FAILED load block: %ls", fp.c_str());
                        }
                    }
                    if (c == std::string::npos) break;
                    start = c + 1;
                }
            }
        }
    }

    g_dataLoaded = !g_blocks.empty();
    int total = 0;
    for (const auto& b : g_blocks) total += (int)b.entries.size();
    Log("blocks = %d, entries = %d", (int)g_blocks.size(), total);
    return g_dataLoaded;
}

// ---------------------------------------------------------------- 内存补丁

// 按 packed4 布局（C串 + padding对齐到4）计算每个序号的 RVA
static bool ComputeEntryRVAs(const IniBlock& blk,
                             std::vector<DWORD>& outRva,
                             std::vector<int>& outCap) {
    unsigned long base = 0;
    if (!ini_parseHex(blk.baseRVA, base)) {
        Log("bad BaseRVA: %s", blk.baseRVA.c_str());
        return false;
    }

    HMODULE hMain = GetModuleHandleA(nullptr);
    if (!hMain) return false;
    BYTE* imageBase = (BYTE*)hMain;

    IMAGE_DOS_HEADER* dos = (IMAGE_DOS_HEADER*)imageBase;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return false;
    IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(imageBase + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return false;
    BYTE* imageEnd = imageBase + nt->OptionalHeader.SizeOfImage;

    // 从 base 开始，逐个读原始 C 串，得到偏移与容量。
    // ★ 边界与有效性校验（崩溃教训：无边界扫描会读到段外导致 AV）。
    if (base == 0 || base >= nt->OptionalHeader.SizeOfImage) {
        Log("ComputeEntryRVAs: base 0x%X out of image", base);
        return false;
    }

    BYTE* p = imageBase + base;
    // ★ 槽位数必须覆盖到 INI 里出现的最大 index；空槽（长度为 0）也要占一个槽位，
    //   否则 INI 的跳号索引会错位。
    size_t maxIdx = 0;
    for (const auto& e : blk.entries)
        if ((size_t)e.index + 1 > maxIdx) maxIdx = (size_t)e.index + 1;
    if (maxIdx == 0) return false;
    // 留出余量：真实块可能比 INI 多几个空槽
    size_t wantSlots = maxIdx + 4;

    for (size_t i = 0; i < wantSlots; i++) {
        if (p >= imageEnd) {
            Log("ComputeEntryRVAs: 越界于槽位 %d", (int)i);
            break;
        }
        DWORD rva = (DWORD)(p - imageBase);
        outRva.push_back(rva);

        // 读到 NUL，最多 512 字节（防无终止串）
        BYTE* s = p;
        int guard = 0;
        while (s < imageEnd && *s != 0 && guard < 512) { s++; guard++; }
        if (s >= imageEnd) {
            Log("ComputeEntryRVAs: 串未终止于槽位 %d", (int)i);
            break;
        }
        BYTE* nxt = s + 1;
        DWORD absOff = (DWORD)(nxt - imageBase);
        DWORD pad = (4 - (absOff % 4)) % 4;
        nxt += pad;
        outCap.push_back((int)(nxt - p));
        p = nxt;
    }
    return !outRva.empty();
}

static bool ApplyStringPatches() {
    if (!g_dataLoaded) return false;
    if (!g_stringEnable) {
        Log("ApplyStringPatches: disabled by [Strings] Enable=0");
        return false;
    }

    HMODULE hMain = GetModuleHandleA(nullptr);
    if (!hMain) return false;
    BYTE* imageBase = (BYTE*)hMain;

    IMAGE_DOS_HEADER* dos = (IMAGE_DOS_HEADER*)imageBase;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return false;
    IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(imageBase + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return false;
    const DWORD nt_size = nt->OptionalHeader.SizeOfImage;

    // ★★ 关键：所有块的槽位必须在**任何写入之前**一次性算好。
    //   崩溃根因：各块的 RVA 区间互相交错（button 0xBD2C0 < menu 0xBD328
    //   < config 0xBD3E8），若边算边写，后处理的块会按"已被改成中文的
    //   内存"重新推算槽位，长度不同 → 槽位全错 → 写到无关数据上（曾导致
    //   Armymen.exe+0x144B7 处 dword_4B28BC 被破坏、esi=0 崩溃）。
    struct Plan {
        const IniBlock* blk;
        bool explicitLayout = false;
        std::vector<DWORD> rvas;
        std::vector<int> caps;
    };
    std::vector<Plan> plans;
    plans.reserve(g_blocks.size());
    for (const auto& blk : g_blocks) {
        Plan pl;
        pl.blk = &blk;
        // layout=explicit：条目自带显式 RVA，不做连续槽扫描
        if (blk.layout == "explicit") {
            pl.explicitLayout = true;
            for (const auto& e : blk.entries) {
                pl.rvas.push_back(e.rva);
                pl.caps.push_back(0);       // 容量未知，由原文长度推断
            }
            Log("block(EXPLICIT) entries=%d", (int)blk.entries.size());
            plans.push_back(std::move(pl));
            continue;
        }
        if (!ComputeEntryRVAs(blk, pl.rvas, pl.caps)) {
            Log("skip block (bad RVA)");
            continue;
        }
        plans.push_back(std::move(pl));
    }

    g_patches.clear();
    int applied = 0, skipped = 0;

    for (auto& pl : plans) {
        const IniBlock& blk = *pl.blk;
        Log("block base=%s entries=%d slots=%d", blk.baseRVA.c_str(),
            (int)blk.entries.size(), (int)pl.rvas.size());

        for (size_t k = 0; k < blk.entries.size(); k++) {
            const IniEntry& e = blk.entries[k];

            // ★★ 关键修正（两次崩溃的根因）：
            //   INI 里的"序号"可能**跳号**（如 menu_block 是 0,2,4,5,7,9,...），
            //   因为真实块内存在空槽。必须用 e.index 去索引槽位数组，
            //   绝不能用 INI 文件里的行位置 k —— 否则会写到错误的槽上，
            //   破坏游戏数据（曾导致 Armymen.exe+0x144B7 处 esi=0 崩溃）。
            //   explicit 布局下条目与槽一一对应（k 即 slot）。
            if (pl.explicitLayout) {
                // 无需 index 校验
            } else if (e.index < 0) { skipped++; continue; }
            size_t slot = pl.explicitLayout ? k : (size_t)e.index;
            if (slot >= pl.rvas.size()) {
                Log("REJECT '%s': index %d >= slots %d",
                    e.en.c_str(), e.index, (int)pl.rvas.size());
                skipped++;
                continue;
            }
            if (e.zh.empty()) { skipped++; continue; }

            // ★ 安全性闸门：INI 声明的英文原文必须与内存现状一致。
            //   不一致说明序号与真实槽位错位，**绝不写入**。
            {
                BYTE* chk = imageBase + pl.rvas[slot];
                if (chk < imageBase || chk >= imageBase + nt_size) {
                    skipped++;
                    continue;
                }
                size_t mlen = 0;
                while (chk + mlen < imageBase + nt_size &&
                       chk[mlen] != 0 && mlen < 256)
                    mlen++;
                std::string cur((const char*)chk, mlen);
                if (!e.en.empty() && cur != e.en) {
                    Log("MISMATCH idx=%d expect '%s' got '%s' (skip)",
                        e.index, e.en.c_str(), cur.c_str());
                    skipped++;
                    continue;
                }
            }

            std::string gbk = Utf8ToGbk(e.zh);
            int need = (int)gbk.size() + 1;   // + NUL
            int cap = pl.caps[slot];
            // explicit 布局下容量未知：用**原文长度**作上限（含结束符）。
            // 这是最保守也最可靠的界限——绝不超过原字符串占用的字节数。
            if (pl.explicitLayout) {
                size_t rawLen = e.en.size();
                cap = (int)rawLen + 1;
            }

            PatchedEntry pe;
            pe.rva = pl.rvas[slot];
            pe.gbk = gbk;
            pe.capacity = cap;
            pe.applied = false;

            if (cap > 0 && need > cap) {
                Log("SKIP idx=%d rva=0x%X cap=%d need=%d (too long)",
                    e.index, pl.rvas[slot], cap, need);
                skipped++;
                g_patches.push_back(pe);
                continue;
            }

            // ★ 写入范围必须完全落在映像内（防越界破坏相邻数据）
            if (pl.rvas[slot] < 0x1000 ||
                pl.rvas[slot] + (DWORD)cap > nt_size) {
                Log("REJECT idx=%d rva=0x%X cap=%d out of image",
                    e.index, pl.rvas[slot], cap);
                skipped++;
                g_patches.push_back(pe);
                continue;
            }

            BYTE* dst = imageBase + pl.rvas[slot];
            DWORD oldProtect = 0;
            if (!VirtualProtect(dst, cap, PAGE_READWRITE, &oldProtect)) {
                Log("VirtualProtect failed idx=%d", e.index);
                skipped++;
                g_patches.push_back(pe);
                continue;
            }
            memset(dst, 0, cap);
            memcpy(dst, gbk.c_str(), gbk.size());
            DWORD dummy = 0;
            VirtualProtect(dst, cap, oldProtect, &dummy);

            pe.applied = true;
            applied++;
            g_patches.push_back(pe);
            // 逐条记录写入详情（崩溃排查用）
            Log("APPLY idx=%d rva=0x%X cap=%d '%s' -> '%s'",
                e.index, pl.rvas[slot], cap,
                e.en.c_str(), e.zh.c_str());
        }
    }

    Log("applied=%d skipped=%d", applied, skipped);
    return applied > 0;
}

// ---------------------------------------------------------------- 字体 Hook

using PFN_CreateFontA = HFONT(WINAPI*)(
    int, int, int, int, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD,
    DWORD, DWORD, DWORD, LPCSTR);
using PFN_CreateFontIndirectA = HFONT(WINAPI*)(const LOGFONTA*);

static PFN_CreateFontA         g_orgCreateFontA = nullptr;
static PFN_CreateFontIndirectA g_orgCreateFontIndirectA = nullptr;

static bool NeedChineseFont(BYTE charset) {
    return charset == ANSI_CHARSET || charset == DEFAULT_CHARSET;
}

static HFONT WINAPI HookCreateFontA(
    int cHeight, int cWidth, int cEscapement, int cOrientation,
    int cWeight, DWORD bItalic, DWORD bUnderline, DWORD bStrikeOut,
    DWORD iCharSet, DWORD iOutPrecision, DWORD iClipPrecision,
    DWORD iQuality, DWORD iPitchAndFamily, LPCSTR pszFaceName)
{
    if (g_fontEnable && NeedChineseFont((BYTE)iCharSet) &&
        !g_faceName.empty()) {
        // ★ 用中文字体试一次；失败则回退原参数，绝不把 NULL 交给游戏。
        //   （游戏对 CreateFont 失败没有检查，拿到 NULL 会在渲染时崩溃）
        HFONT h = g_orgCreateFontA(cHeight, cWidth, cEscapement, cOrientation,
                                   cWeight, bItalic, bUnderline, bStrikeOut,
                                   g_charSet, iOutPrecision, iClipPrecision,
                                   iQuality, iPitchAndFamily,
                                   g_faceName.c_str());
        if (h) return h;
        Log("CreateFontA(中文字体) 失败，回退原参数");
    }
    return g_orgCreateFontA(cHeight, cWidth, cEscapement, cOrientation,
                            cWeight, bItalic, bUnderline, bStrikeOut,
                            iCharSet, iOutPrecision, iClipPrecision,
                            iQuality, iPitchAndFamily, pszFaceName);
}

static HFONT WINAPI HookCreateFontIndirectA(const LOGFONTA* lf) {
    if (!g_fontEnable || !lf) return g_orgCreateFontIndirectA(lf);
    if (!NeedChineseFont(lf->lfCharSet) || g_faceName.empty())
        return g_orgCreateFontIndirectA(lf);

    LOGFONTA copy = *lf;
    copy.lfCharSet = g_charSet;
    strncpy_s(copy.lfFaceName, LF_FACESIZE, g_faceName.c_str(), _TRUNCATE);
    HFONT h = g_orgCreateFontIndirectA(&copy);
    if (h) return h;
    Log("CreateFontIndirectA(中文字体) 失败，回退原参数");
    return g_orgCreateFontIndirectA(lf);
}

// ---------------------------------------------------------------- IAT Hook

// 安全读取：验证指针落在模块映像范围内，避免野指针崩溃。
// 崩溃教训（dump 0x6E21F8E0 = _stricmp 内部读野指针 0x6F3E74B2）：
// 导入表遍历必须做边界校验，任何一步取到无效 RVA 都要立即放弃，
// 不能依赖 "表中以 0 结尾" 这个假设。
struct ModRange {
    BYTE* base;
    DWORD size;     // 映像大小（SizeOfImage）
};

static bool ValidPtr(const ModRange& mr, const void* p, size_t need) {
    if (!p) return false;
    BYTE* b = (BYTE*)p;
    if (b < mr.base) return false;
    if (b + need > mr.base + mr.size) return false;
    return true;
}

static bool GetModRange(HMODULE hMod, ModRange& mr) {
    if (!hMod) return false;
    IMAGE_DOS_HEADER* dos = (IMAGE_DOS_HEADER*)hMod;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return false;
    IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)((BYTE*)hMod + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return false;
    mr.base = (BYTE*)hMod;
    mr.size = nt->OptionalHeader.SizeOfImage;
    return true;
}

static bool PatchIAT(HMODULE hMod, const char* dllName,
                     const char* funcName, void* newFn, void** oldFn) {
    ModRange mr;
    if (!GetModRange(hMod, mr)) {
        Log("PatchIAT: bad module");
        return false;
    }

    IMAGE_NT_HEADERS* nt =
        (IMAGE_NT_HEADERS*)((BYTE*)hMod +
                            ((IMAGE_DOS_HEADER*)hMod)->e_lfanew);
    DWORD impRva =
        nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT]
            .VirtualAddress;
    DWORD impSize =
        nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT]
            .Size;
    if (impRva == 0) {
        Log("PatchIAT: no import directory");
        return false;
    }
    if (!ValidPtr(mr, mr.base + impRva, sizeof(IMAGE_IMPORT_DESCRIPTOR))) {
        Log("PatchIAT: import dir RVA out of range 0x%X", impRva);
        return false;
    }

    IMAGE_IMPORT_DESCRIPTOR* imp =
        (IMAGE_IMPORT_DESCRIPTOR*)(mr.base + impRva);

    // 用目录声明的 Size 限制遍历项数（Size/20），并额外要求 Name!=0。
    DWORD maxDesc = (impSize >= sizeof(IMAGE_IMPORT_DESCRIPTOR))
                    ? (impSize / sizeof(IMAGE_IMPORT_DESCRIPTOR)) : 0;
    if (maxDesc == 0 || maxDesc > 1024) maxDesc = 256;   // 兜底上限

    int matched = 0;
    for (DWORD di = 0; di < maxDesc; di++, imp++) {
        if (!ValidPtr(mr, imp, sizeof(IMAGE_IMPORT_DESCRIPTOR))) break;
        if (imp->Name == 0) break;                       // 终止项

        if (!ValidPtr(mr, mr.base + imp->Name, 1)) {
            Log("PatchIAT: bad Name RVA 0x%X at desc %u", imp->Name, di);
            continue;
        }
        const char* name = (const char*)(mr.base + imp->Name);
        if (_stricmp(name, dllName) != 0) continue;
        matched++;

        if (imp->FirstThunk == 0) continue;
        if (!ValidPtr(mr, mr.base + imp->FirstThunk, sizeof(IMAGE_THUNK_DATA)))
            continue;

        // ★★ 关键修正（字体 hook 失败的根因）：
        //   必须用 **OriginalFirstThunk (INT)** 遍历以读取函数名，
        //   因为 **FirstThunk (IAT)** 在加载后其 AddressOfData 已被 loader
        //   替换成真实函数地址，读它当 RVA 用会得到垃圾。
        //   写回时用 FirstThunk（IAT）那一份。
        DWORD intRva = imp->OriginalFirstThunk;
        if (intRva == 0) intRva = imp->FirstThunk;   // 少数 PE 省略 INT
        if (!ValidPtr(mr, mr.base + intRva, sizeof(IMAGE_THUNK_DATA))) continue;

        IMAGE_THUNK_DATA* names =
            (IMAGE_THUNK_DATA*)(mr.base + intRva);
        IMAGE_THUNK_DATA* iat =
            (IMAGE_THUNK_DATA*)(mr.base + imp->FirstThunk);

        for (int ti = 0; ti < 4096; ti++, names++, iat++) {
            if (!ValidPtr(mr, names, sizeof(IMAGE_THUNK_DATA))) break;
            if (!ValidPtr(mr, iat, sizeof(IMAGE_THUNK_DATA))) break;
            if (names->u1.AddressOfData == 0) break;
            if (names->u1.Ordinal & IMAGE_ORDINAL_FLAG) continue;  // 序号导入

            DWORD ibnRva = (DWORD)names->u1.AddressOfData;
            if (!ValidPtr(mr, mr.base + ibnRva,
                          sizeof(IMAGE_IMPORT_BY_NAME))) continue;

            IMAGE_IMPORT_BY_NAME* ibn =
                (IMAGE_IMPORT_BY_NAME*)(mr.base + ibnRva);
            if (!ValidPtr(mr, ibn->Name, 2)) continue;
            if (_stricmp((const char*)ibn->Name, funcName) != 0) continue;

            DWORD oldProtect = 0;
            if (oldFn) *oldFn = (void*)iat->u1.Function;
            if (VirtualProtect(&iat->u1.Function, sizeof(DWORD),
                               PAGE_READWRITE, &oldProtect)) {
                iat->u1.Function = (DWORD_PTR)newFn;
                DWORD tmp = 0;
                VirtualProtect(&iat->u1.Function, sizeof(DWORD),
                               oldProtect, &tmp);
                Log("PatchIAT: %s!%s patched (desc %u, thunk %d)",
                    dllName, funcName, di, ti);
                return true;
            }
            Log("PatchIAT: VirtualProtect failed for %s", funcName);
            return false;
        }
    }

    Log("PatchIAT: %s!%s not found (scanned %u desc, %d dll matches)",
        dllName, funcName, maxDesc, matched);
    return false;
}

// ---------------------------------------------------------------- 内联补丁基元

// 校验目标处现有字节，完全一致才写入；不一致说明 exe 版本不符，**绝不盲写**。
static bool CheckBytes(const BYTE* p, const BYTE* pat, size_t n) {
    for (size_t i = 0; i < n; i++)
        if (p[i] != pat[i]) return false;
    return true;
}

static bool MakeWritable(void* p, size_t n, DWORD& oldProt) {
    return VirtualProtect(p, n, PAGE_EXECUTE_READWRITE, &oldProt) != 0;
}

static void RestoreProtect(void* p, size_t n, DWORD oldProt) {
    DWORD tmp = 0;
    VirtualProtect(p, n, oldProt, &tmp);
}

// 在 target 处写入 E9 rel32（余下用 NOP 填满 len 字节）。
// 返回 trampoline：先执行被覆盖的原始 len 字节，再跳回 target+len。
// 没有 trampoline 就**不能**再调原函数（会无限递归）。
static void* InstallInlineJmp(BYTE* target, size_t len, void* hook,
                              const BYTE* expect) {
    if (len < 5 || len > 16) return nullptr;
    if (expect && !CheckBytes(target, expect, len)) {
        Log("inline: 字节签名不符 @0x%p，放弃", (void*)target);
        return nullptr;
    }

    BYTE* tramp = (BYTE*)VirtualAlloc(nullptr, 32, MEM_COMMIT | MEM_RESERVE,
                                      PAGE_EXECUTE_READWRITE);
    if (!tramp) { Log("inline: VirtualAlloc 失败"); return nullptr; }
    memcpy(tramp, target, len);
    tramp[len] = 0xE9;
    *(DWORD*)(tramp + len + 1) =
        (DWORD)(target + len) - (DWORD)(tramp + len + 5);

    DWORD oldProt = 0;
    if (!MakeWritable(target, len, oldProt)) {
        Log("inline: VirtualProtect 失败 @0x%p", (void*)target);
        VirtualFree(tramp, 0, MEM_RELEASE);
        return nullptr;
    }
    target[0] = 0xE9;
    *(DWORD*)(target + 1) = (DWORD)hook - (DWORD)(target + 5);
    for (size_t i = 5; i < len; i++) target[i] = 0x90;
    RestoreProtect(target, len, oldProt);
    FlushInstructionCache(GetCurrentProcess(), target, len);

    Log("inline: 0x%p -> hook 0x%p, trampoline 0x%p (%d 字节)",
        (void*)target, hook, (void*)tramp, (int)len);
    return tramp;
}

// ---------------------------------------------------------------- 中文位图文字桥接
//
// 背景（IDA 实证，零售 1.2）：
//   · 1.2 的左下角信息屏不再走 GDI，而是预烘焙的**位图字体**：
//     BmpTextWrite = sub_44B760，逐字节查 dword_6975E0[fontid] 字形表。
//   · 该表由 sub_44BD60 用 sprintf("#a%c") 只烘焙 **ASCII 32..127** 共 96 个
//     字形（表头 96 个 WORD 偏移 = 192 字节）。GBK 汉字字节 >= 0x80 会索引到
//     2*byte-64 = 最大 446 字节处，远超出表头 → 把字形数据当偏移 → 花屏/越界。
//   · 1.0 中文零售版同一处走 GDI：sub_45AD30 → sub_4102D0 → sub_455B50(TextOutA)。
//     1.2 里对应的 GDI 路径函数 sub_413A30 仍然完好（菜单/简报仍在用）。
//
// 对策：含 >=0x80 字节的串切到 GDI 路径，字体取已被 RebuildFontTable 换成
//       宋体 GB2312 的 FONT_DASHCOMM 槽。纯 ASCII 串原样走原函数，视觉零变化。
//       GDI 槽表 7 项都在 RebuildFontTable 覆盖范围内；FONT_MAP(槽 7) 不在其中
//       且只用于 debug 覆盖层，故 BMPFONT_MAP 不桥接，直接回退原路径。

#define RVA_BMPTEXT_WRITE  0x004B760u   // sub_44B760  位图贴字
#define RVA_BMPTEXT_WIDTH  0x004BA60u   // sub_44BA60  位图量宽
#define RVA_TEXTWRITE_GDI  0x0013A30u   // sub_413A30  GDI 贴字
#define RVA_TEXTSETCOLOR   0x0013E00u   // sub_413E00  设前景/背景色
#define RVA_FONT_TABLE     0x000E9F48u  // HFONT[7] 表（dword_4E9F48）
#define RVA_TEXT_COLOR     0x000E9F70u  // 全局前景色
#define RVA_TEXT_BKCOLOR   0x000E9F6Cu  // 全局背景色

// 位图字体 id → GDI 字体槽（FONTS 枚举）。InitBitmapFonts 构建顺序：
//   [0]=MakeBitmapFont(FONT_DASHCOMM=3)  [1]=FONT_TIMES_20=2  [2]=FONT_MAP=7
// FONT_MAP 槽(0x4E9F64)不在 RebuildFontTable 的 7 项里，仍是无中文字形的
// Courier，所以 -1 = 不桥接。
static int GdiFontForBitmap(int fontid) {
    switch (fontid) {
        case 0:  return 3;    // BMPFONT_DASHCOMM -> FONT_DASHCOMM(0x4E9F54)
        case 1:  return 2;    // BMPFONT_BUTTON   -> FONT_TIMES_20(0x4E9F50)
        default: return -1;   // BMPFONT_MAP / 未知
    }
}

using PFN_BmpTextWrite = int(__fastcall*)(void*, int, int, const char*, int,
                                          SIZE*, int);
using PFN_BmpTextWidth = int(__fastcall*)(const char*, int, SIZE*);
using PFN_TextWriteGdi = int(__fastcall*)(void*, int, int, const char*, int,
                                          SIZE*);
using PFN_TextSetColors = void(__fastcall*)(DWORD, DWORD);

static PFN_BmpTextWrite  g_orgBmpTextWrite = nullptr;
static PFN_BmpTextWidth  g_orgBmpTextWidth = nullptr;
static PFN_TextWriteGdi  g_textWriteGdi    = nullptr;
static PFN_TextSetColors g_textSetColors   = nullptr;

// GBK 汉字首字节 0xB0..0xF7、次字节 0xA1..0xFE，都 >= 0x80
static bool HasHighByte(const char* s) {
    if (!s) return false;
    for (; *s; ++s)
        if ((BYTE)*s >= 0x80) return true;
    return false;
}

// 串尾是否为"只有首字节、缺次字节"的半个汉字。
// 断行乱码的根因就在这里：断行器 sub_441300 按**字节**截断，
// 中文没有空格可对，最终在任意字节处 v4[v9]=0，恰好劈开一个 GBK 字符。
static bool EndsWithPartialCjk(const char* s) {
    while (*s) {
        if ((BYTE)*s >= 0x80) {
            if (!s[1]) return true;    // 首字节后面就是 NUL → 半个字
            s += 2;                    // 完整的双字节汉字/符号
        } else {
            s += 1;
        }
    }
    return false;
}

static HFONT GetFontSlot(int gdiFont) {
    if (gdiFont < 0 || gdiFont > 6) return nullptr;
    HMODULE h = GetModuleHandleA(nullptr);
    if (!h) return nullptr;
    return (HFONT)*(DWORD*)((BYTE*)h + RVA_FONT_TABLE + gdiFont * 4);
}

// 量宽专用内存 DC（与绘制用的是同一批 GDI 字体，度量一致）
static HDC GetMeasureDC(HFONT font) {
    static HDC   s_dc   = nullptr;
    static HFONT s_font = nullptr;
    if (!s_dc) {
        s_dc = CreateCompatibleDC(nullptr);
        if (!s_dc) return nullptr;
    }
    if (font != s_font) {
        SelectObject(s_dc, font);
        s_font = font;
    }
    return s_dc;
}

// 取字符串"安全可绘制长度"：若结尾是半个汉字，则砍掉那半个字节。
// 绘制路径用它兜底——即使某条路径（如 sub_44E5B0 的血条文字）给了
// 半个汉字，也只是少显示一个字，不会画出乱码。
static size_t SafeCjkLen(const char* s) {
    size_t n = strlen(s);
    size_t i = 0;
    while (i < n) {
        if ((BYTE)s[i] >= 0x80) {
            if (i + 1 >= n) return i;   // 首字节后没了 → 丢弃这半个
            i += 2;
        } else {
            i += 1;
        }
    }
    return n;
}

// sub_44B760 替换体：签名/约定必须与原文一致（ecx=surf, edx=x, 5 个栈参, ret 14h）
static int __fastcall HookBmpTextWrite(void* surf, int x, int y,
                                       const char* text, int fontid,
                                       SIZE* sz, int color) {
    if (!g_textWriteGdi || !g_orgBmpTextWrite || !HasHighByte(text))
        return g_orgBmpTextWrite(surf, x, y, text, fontid, sz, color);

    int gdiFont = GdiFontForBitmap(fontid);
    if (gdiFont < 0 || !GetFontSlot(gdiFont))
        return g_orgBmpTextWrite(surf, x, y, text, fontid, sz, color);

    // ★ 兜底：砍掉结尾的半个汉字再画（GDI 收到半个 GBK 会画出垃圾字形）
    const char* s      = text;
    size_t      prefix = 0;
    if (text[0] == '#' && text[1] != 0) { s = text + 2; prefix = 2; }
    size_t safeLen = SafeCjkLen(s);
    char*  buf = nullptr;
    if (safeLen != strlen(s)) {
        buf = (char*)malloc(prefix + safeLen + 1);
        if (buf) {
            if (prefix) memcpy(buf, text, prefix);
            memcpy(buf + prefix, s, safeLen);
            buf[prefix + safeLen] = 0;
            s = buf + prefix;          // 保留颜色前缀供 TextWrite 解析
        }
    }

    HMODULE h = GetModuleHandleA(nullptr);
    DWORD* pFg = (DWORD*)((BYTE*)h + RVA_TEXT_COLOR);
    DWORD* pBg = (DWORD*)((BYTE*)h + RVA_TEXT_BKCOLOR);
    DWORD oldFg = *pFg, oldBg = *pBg;

    // RGB_GREEN / RGB_BLACK，与位图路径的 GREEN_IDX 观感一致
    g_textSetColors(0x0000FF00, 0x00000000);

    SIZE local;
    int r = g_textWriteGdi(surf, x, y, s, gdiFont, sz ? sz : &local);

    g_textSetColors(oldFg, oldBg);   // 还原全局色，别污染菜单的 GDI 文字
    if (buf) free(buf);
    (void)color;                     // 位图路径用调色板索引，GDI 路径用前景色
    return r;
}

// sub_44BA60 替换体：CJK 用 GDI 量宽，否则原样（ret 4）
//
// ★ 断行修复的支点：断行器 sub_441300 用
//     for (v19[v9]=0; BmpTextWidth(v19) > 窗口宽; v19[v9]=0) --v9;
//   逐字节后退找边界。中文没有空格可对，退出时 v9 可能落在汉字两字节之间，
//   随后 v4[v9]=0 把一个 GBK 字符劈成两半 → 乱码。
//   这里让"串尾是半个汉字"时返回一个必然超宽的数值，循环就会继续后退，
//   直到退到完整字符边界为止。无需改动游戏代码。
static int __fastcall HookBmpTextWidth(const char* text, int fontid, SIZE* sz) {
    if (!HasHighByte(text))
        return g_orgBmpTextWidth ? g_orgBmpTextWidth(text, fontid, sz) : 0;

    int gdiFont = GdiFontForBitmap(fontid);
    HFONT font = (gdiFont >= 0) ? GetFontSlot(gdiFont) : nullptr;
    HDC dc = font ? GetMeasureDC(font) : nullptr;
    if (!dc) {
        if (g_orgBmpTextWidth) return g_orgBmpTextWidth(text, fontid, sz);
        if (sz) sz->cx = sz->cy = 0;
        return 0;
    }

    // 与 BmpTextWrite 一致：跳过 "#X" 颜色前缀（'#' + 1 字节色号）
    const char* s = text;
    size_t n = strlen(text);
    if (n >= 2 && s[0] == '#') { s += 2; n -= 2; }

    SIZE out = { 0, 0 };
    if (n) GetTextExtentPoint32A(dc, s, (int)n, &out);

    TEXTMETRICA tm;
    if (GetTextMetricsA(dc, &tm)) out.cy = tm.tmHeight;

    // 半个汉字：报一个必然超宽的宽度，逼断行器继续回退到字符边界。
    // 加 0x4000 而不是直接给 INT_MAX，避免调用方做算术时溢出。
    if (EndsWithPartialCjk(s)) {
        out.cx += 0x4000;
        if (sz) *sz = out;
        return out.cx;
    }

    if (sz) *sz = out;
    return out.cx;
}

// ---------------------------------------------------------------- "No unit" 立即数改写
//
// 两处字面量容量只有 8 字节（"No unit\0" / "No Unit\0"），"没有部队" 的 GBK
// 是 8 字节 + NUL = 9，走 INI 槽位补丁必被 too-long 拒绝。所以直接改代码里的
// 绝对地址立即数（exe 无 ASLR，DllCharacteristics=0，静态地址可用），指向 DLL
// 自己的缓冲区 —— 顺带彻底摆脱容量限制。

#define RVA_NOUNIT_DASH_PUSH  0x0040302u  // 0x440302  push offset aNoUnit_0
#define RVA_NOUNIT_ITEM_MOV   0x0022670u  // 0x422670  mov edi, offset aNoUnit

static char g_noUnitGbk[64] = {0};

static void PatchNoUnitString(const std::string& zh) {
    std::string gbk = Utf8ToGbk(zh);
    if (gbk.empty() || gbk.size() + 1 > sizeof(g_noUnitGbk)) {
        Log("PatchNoUnitString: 转换失败或过长，跳过");
        return;
    }
    memcpy(g_noUnitGbk, gbk.c_str(), gbk.size());
    g_noUnitGbk[gbk.size()] = 0;

    HMODULE h = GetModuleHandleA(nullptr);
    if (!h) return;
    BYTE* base = (BYTE*)h;
    DWORD addr = (DWORD)(DWORD_PTR)g_noUnitGbk;

    // ① Dashboard_Update 选中单位栏：8B 56 0C | 68 imm32
    {
        static const BYTE kSig[] = { 0x8B, 0x56, 0x0C, 0x68,
                                     0x2C, 0xCC, 0x4B, 0x00 };
        BYTE* p = base + RVA_NOUNIT_DASH_PUSH - 4;
        if (CheckBytes(p, kSig, sizeof(kSig))) {
            DWORD oldProt = 0;
            BYTE* imm = base + RVA_NOUNIT_DASH_PUSH;
            if (MakeWritable(imm, 4, oldProt)) {
                *(DWORD*)imm = addr;
                RestoreProtect(imm, 4, oldProt);
                Log("NoUnit[dash] 0x%p -> '%s'", (void*)imm, zh.c_str());
            }
        } else {
            Log("NoUnit[dash]: 签名不符 @0x%p，跳过", (void*)p);
        }
    }

    // ② ItemName 兜底：85 C0 7F 22 | BF imm32
    {
        static const BYTE kSig[] = { 0x85, 0xC0, 0x7F, 0x22, 0xBF,
                                     0x50, 0x3E, 0x4B, 0x00 };
        BYTE* p = base + RVA_NOUNIT_ITEM_MOV - 5;
        if (CheckBytes(p, kSig, sizeof(kSig))) {
            DWORD oldProt = 0;
            BYTE* imm = base + RVA_NOUNIT_ITEM_MOV;
            if (MakeWritable(imm, 4, oldProt)) {
                *(DWORD*)imm = addr;
                RestoreProtect(imm, 4, oldProt);
                Log("NoUnit[item] 0x%p -> '%s'", (void*)imm, zh.c_str());
            }
        } else {
            Log("NoUnit[item]: 签名不符 @0x%p，跳过", (void*)p);
        }
    }
}

// ---------------------------------------------------------------- "Sarge" 立即数改写
//
// ItemName() 的 ARMY_SARGE 分支返回字面量 "Sarge"（TextData.cpp:317）。
// ★ 为什么不能改字符串，只能改立即数：
//   该串（RVA 0x4BDCA0）同时被 MsgVehicleNames[5].pString 引用
//   （off_4BD06C + 5*8，见 sub_446710/USA.h:165），而 VehicleName() 在
//   Vehicle.cpp:1648 / 1661 用它拼动画路径：
//       sprintf(filename, "%s/%s", VehicleName(eType), vehicle_anim_names[i]);
//   改了字符串 → "Alpine/Vehicles/中士/xxx.axs" 找不到 → Sarge 车辆动画全丢。
//   所以只改 ItemName 里那一条 mov 的立即数（B8 imm32，5 字节指令），
//   其余引用照旧指向原 "Sarge"。

#define RVA_SARGE_ITEMNAME_IMM 0x0046860u  // 0x44685F  mov eax, offset aSarge_0

static char g_sargeGbk[32] = {0};

static void PatchSargeString(const std::string& zh) {
    std::string gbk = Utf8ToGbk(zh);
    if (gbk.empty() || gbk.size() + 1 > sizeof(g_sargeGbk)) {
        Log("PatchSargeString: 转换失败或过长，跳过");
        return;
    }
    memcpy(g_sargeGbk, gbk.c_str(), gbk.size());
    g_sargeGbk[gbk.size()] = 0;

    HMODULE h = GetModuleHandleA(nullptr);
    if (!h) return;
    BYTE* base = (BYTE*)h;

    // imm32 在 RVA 0x46860，指令头 B8 在它前 1 字节（0x4685F）
    // 完整指令：B8 A0 DC 4B 00 = mov eax, 0x4BDCA0  (aSarge_0)
    static const BYTE kSig[] = { 0xB8, 0xA0, 0xDC, 0x4B, 0x00 };
    BYTE* p = base + RVA_SARGE_ITEMNAME_IMM - 1;   // 指向 B8 开头
    if (!CheckBytes(p, kSig, sizeof(kSig))) {
        Log("Sarge[ItemName]: 签名不符 @0x%p，跳过", (void*)p);
        return;
    }

    DWORD oldProt = 0;
    BYTE* imm = base + RVA_SARGE_ITEMNAME_IMM;
    if (MakeWritable(imm, 4, oldProt)) {
        *(DWORD*)imm = (DWORD)(DWORD_PTR)g_sargeGbk;
        RestoreProtect(imm, 4, oldProt);
        Log("Sarge[ItemName] 0x%p -> '%s'", (void*)imm, zh.c_str());
    }
}

// ---------------------------------------------------------------- 信息屏折行接管
//
// 乱码根因（IDA 实证，sub_441300 = ReceiveDashMessage，源码 ui.cpp:3370）：
//   超宽时它按**字节**截断，且截断后 v4 += v9 + 1 —— 把 v4[v9] 那个字节
//   **吃掉**了。原文逻辑假设断点处是空格，吃掉无害；中文没有空格可对，
//   断点必然落在汉字中间或吞掉某个汉字的首字节 → 半个 GBK 字 / 整串错位。
//   实测：39 字节的中文串，安全字节断点只有 0/2/4/.../22 与串尾，
//   而这些"安全点"全都靠吞掉 ASCII 才成立，中文里不存在可丢弃字节。
//
// 对策：在其入口接管。DLL 自己按**字符边界**贪心折行，再把每一段短串
//   交给原函数。短串宽度不超限 → 不进入断行分支 → 走
//   sprintf(listtext[v14], "%s", v4) 整行写入，字节一个不少。
//   这样完全不依赖游戏侧的字节截断逻辑。

#define RVA_ADD_DASH_MSG   0x0041300u   // sub_441300  ReceiveDashMessage
#define RVA_DASH_MSG_WIDTH 0x000B8AA4u  // dword_4B8AA4 信息屏可用像素宽

using PFN_AddDashMsg = void(__fastcall*)(const char*, void*);

static PFN_AddDashMsg g_orgAddDashMsg = nullptr;

// 单个字符（1 或 2 字节）的显示宽度
static int CjkAdvanceWidth(HDC dc, const char* p, int bytes) {
    SIZE s = { 0, 0 };
    GetTextExtentPoint32A(dc, p, bytes, &s);
    return s.cx;
}

// 按字符边界把 msg 贪心折成若干行，逐段交给原函数。
// 返回是否真的接管（false 表示调用方应回退到原函数）。
static bool WrapAndDispatch(const char* msg, void* unit) {
    if (!g_orgAddDashMsg || !g_textWriteGdi) return false;

    HMODULE h = GetModuleHandleA(nullptr);
    if (!h) return false;
    int limit = *(int*)((BYTE*)h + RVA_DASH_MSG_WIDTH);
    if (limit <= 0) return false;

    HFONT font = GetFontSlot(3);            // FONT_DASHCOMM
    HDC   dc   = font ? GetMeasureDC(font) : nullptr;
    if (!dc) return false;

    // 颜色前缀 '#X'：原函数每行都会带上前缀，这里照做
    const char* body   = msg;
    char        prefix[3] = { 0, 0, 0 };
    size_t      plen   = 0;
    if (msg[0] == '#' && msg[1] != 0) {
        prefix[0] = msg[0];
        prefix[1] = msg[1];
        plen = 2;
        body = msg + 2;
    }

    size_t len = strlen(body);
    if (len == 0) return false;

    // 一次性算好所有行边界，避免边切边改原串
    std::vector<std::pair<size_t, size_t> > lines;   // [begin, end)
    size_t p = 0;
    while (p < len) {
        size_t q = p;
        int    w = 0;
        while (q < len) {
            int adv = ((BYTE)body[q] >= 0x80) ? 2 : 1;
            if (q + (size_t)adv > len) break;        // 尾巴上半个残字，丢弃
            int cw = CjkAdvanceWidth(dc, body + q, adv);
            if (w + cw > limit) break;
            w += cw;
            q += (size_t)adv;
        }
        // 一个字都放不下：强制收一个完整字符，避免死循环
        if (q == p) {
            int adv = ((BYTE)body[p] >= 0x80) ? 2 : 1;
            q = (p + (size_t)adv <= len) ? p + (size_t)adv : len;
        }
        // 单行不得超过游戏的行缓冲上限（v19[68] / v9<=59）
        if (q - p > 59) q = p + 59;
        lines.push_back(std::make_pair(p, q));
        p = q;
    }

    if (lines.empty()) return false;

    // 逐段调用原函数（trampoline 不经过本 hook，无递归风险）
    std::string buf;
    buf.reserve(len + 2);
    for (size_t i = 0; i < lines.size(); i++) {
        buf.assign(prefix, plen);
        buf.append(body + lines[i].first, lines[i].second - lines[i].first);
        g_orgAddDashMsg(buf.c_str(), unit);
    }
    return true;
}

// sub_441300 替换体：ecx=msg, edx=unit（无栈参数，retn）
static void __fastcall HookAddDashMsg(const char* msg, void* unit) {
    if (!g_orgAddDashMsg) return;
    // 纯 ASCII 完全走原路径，行为零变化
    if (!msg || !HasHighByte(msg) || !WrapAndDispatch(msg, unit))
        g_orgAddDashMsg(msg, unit);
}

// ---------------------------------------------------------------- 中文渲染安装

static bool s_cjkInstalled = false;
static bool s_cjkAttempted = false;

static bool InstallCjkRenderer() {
    if (s_cjkInstalled) return true;

    // ★ 只尝试一次。若中途部分成功（一个 patch 成功、另一个签名不符），
    //   二次进入时已打补丁处的字节不再是原始签名 → InstallInlineJmp 失败返回
    //   nullptr → 把 trampoline 指针清空 → 而 E9 仍然跳进 hook → hook 判空后
    //   调用空地址崩溃。所以一旦尝试过就绝不再试。
    if (s_cjkAttempted) return s_cjkInstalled;
    s_cjkAttempted = true;

    HMODULE h = GetModuleHandleA(nullptr);
    if (!h) { Log("InstallCjkRenderer: 无主模块"); return false; }

    BYTE* base = (BYTE*)h;
    g_textWriteGdi  = (PFN_TextWriteGdi)(base + RVA_TEXTWRITE_GDI);
    g_textSetColors = (PFN_TextSetColors)(base + RVA_TEXTSETCOLOR);

    // BmpTextWrite 头部：81 EC 94 00 00 00  = sub esp,94h（6 字节，整条指令）
    static const BYTE kWriteSig[] = { 0x81, 0xEC, 0x94, 0x00, 0x00, 0x00 };
    g_orgBmpTextWrite = (PFN_BmpTextWrite)InstallInlineJmp(
        base + RVA_BMPTEXT_WRITE, sizeof(kWriteSig),
        (void*)HookBmpTextWrite, kWriteSig);

    // BmpTextWidth 头部：56 8B 35 E0 75 69 00 = push esi; mov esi,ds:6975E0（7 字节）
    static const BYTE kWidthSig[] = { 0x56, 0x8B, 0x35, 0xE0,
                                      0x75, 0x69, 0x00 };
    g_orgBmpTextWidth = (PFN_BmpTextWidth)InstallInlineJmp(
        base + RVA_BMPTEXT_WIDTH, sizeof(kWidthSig),
        (void*)HookBmpTextWidth, kWidthSig);

    // ReceiveDashMessage 头部：81 EC 20 01 00 00 = sub esp,120h（6 字节）
    // ★ 折行接管：必须在 BmpTextWidth hook 之后装，因为它依赖 GDI 量宽可用
    static const BYTE kDashSig[] = { 0x81, 0xEC, 0x20, 0x01, 0x00, 0x00 };
    g_orgAddDashMsg = (PFN_AddDashMsg)InstallInlineJmp(
        base + RVA_ADD_DASH_MSG, sizeof(kDashSig),
        (void*)HookAddDashMsg, kDashSig);

    s_cjkInstalled = (g_orgBmpTextWrite && g_orgBmpTextWidth);
    Log("InstallCjkRenderer: write=%p width=%p dash=%p -> %s",
        (void*)g_orgBmpTextWrite, (void*)g_orgBmpTextWidth,
        (void*)g_orgAddDashMsg, s_cjkInstalled ? "ok" : "FAILED");
    return s_cjkInstalled;
}

// ---------------------------------------------------------------- 安装

bool InstallHooks() {
    HMODULE hGame = GetModuleHandleA(nullptr);
    if (!hGame) { Log("no main module"); return false; }

    // 诊断：确认 hook 目标确实是游戏主模块，而非 .asi 自身
    {
        char modPath[MAX_PATH] = {0};
        GetModuleFileNameA(hGame, modPath, MAX_PATH);
        Log("InstallHooks: target module = %s @ 0x%p", modPath, (void*)hGame);
        Log("InstallHooks: self module     = 0x%p", (void*)g_hModule);
        if (g_hModule && hGame == g_hModule) {
            Log("!! 危险：hGame == 自身模块，IAT hook 目标错误");
        }
    }

    bool ok = false;
    if (PatchIAT(hGame, "gdi32.dll", "CreateFontA",
                 (void*)HookCreateFontA, (void**)&g_orgCreateFontA)) {
        Log("hooked CreateFontA"); ok = true;
    } else Log("FAILED hook CreateFontA");

    if (PatchIAT(hGame, "gdi32.dll", "CreateFontIndirectA",
                 (void*)HookCreateFontIndirectA,
                 (void**)&g_orgCreateFontIndirectA)) {
        Log("hooked CreateFontIndirectA");
    } else Log("FAILED hook CreateFontIndirectA");

    return ok;
}

// ── 字体表重建（修复绿点/方块：中文显示成绿点）────────────────────────
// 根因（IDA 反编译实证，零售 Armymen.exe）：
//   · TextInit = sub_413800，把 7 个 HFONT 写进 dword_4E9F48 起的一张表；
//     建字体走 sub_413D30 -> CreateFontA(...,0/*ANSI_CHARSET*/,...)，
//     字体名只有 "Times New Roman" / "ArialNarrow" —— 均无 GBK 字形。
//   · TextWrite = sub_413A30，取字体用 *(&dword_4E9F48 + fontid)，
//     随后 SelectObject + TextOutA 直接走 GDI（零售无位图字体路径）。
//   · 建表发生在 InitializeASI 之前，CreateFont* 的 IAT Hook 回收不到，
//     所以 Hook 装了也零拦截（运行时日志可证）。必须在建表之后直接改写表。
//
// 槽位布局（注意第 7 项 0x4E9F54 不连续，夹在 0x4E9F50/0x4E9F58 之间）：
//   [0] 0x4E9F48 Times 14   [1] 0x4E9F4C Times 18   [2] 0x4E9F50 Times 20
//   [3] 0x4E9F58 Arial 14   [4] 0x4E9F5C Arial 20   [5] 0x4E9F60 Arial 36
//   [6] 0x4E9F54 Arial -10  (FONT_DASHCOMM，左下角信息屏/战报用的就是这个)
static void RebuildFontTable() {
    if (!g_fontEnable) return;
    if (g_faceName.empty()) { Log("RebuildFontTable: 无中文字体名，跳过"); return; }

    HMODULE hGame = GetModuleHandleA(nullptr);
    if (!hGame) { Log("RebuildFontTable: 取不到主模块"); return; }

    ModRange mr;
    if (!GetModRange(hGame, mr)) { Log("RebuildFontTable: 读模块范围失败"); return; }

    struct SlotDef { DWORD rva; int height; const char* what; };
    // RVA = VA - 0x400000（零售映像基址 0x400000）
    static const SlotDef kSlots[7] = {
        { 0x0E9F48,  14, "Times14"   },
        { 0x0E9F4C,  18, "Times18"   },
        { 0x0E9F50,  20, "Times20"   },
        { 0x0E9F58,  14, "Arial14"   },
        { 0x0E9F5C,  20, "Arial20"   },
        { 0x0E9F60,  36, "Arial36"   },
        { 0x0E9F54, -10, "DashComm"  },   // 左下角信息屏
    };

    int ok = 0;
    for (int i = 0; i < 7; i++) {
        DWORD* pSlot = (DWORD*)((BYTE*)hGame + kSlots[i].rva);
        if (!ValidPtr(mr, pSlot, sizeof(DWORD))) {
            Log("RebuildFontTable: 槽 %s 越界，跳过", kSlots[i].what);
            continue;
        }

        // 直接调 Win32 CreateFontA：DLL 自身 IAT 指向真实 gdi32，不经 exe 的 Hook。
        // 参数对齐零售 sub_413D30：weight=400、(a3=0) 无斜体/下划线/删除线、
        // OUT_DEFAULT_PRECIS=0、CLIP_DEFAULT_PRECIS=0、DRAFT_QUALITY=1、
        // VARIABLE_PITCH=2，仅把 charset 换 GB2312、名字换中文字体。
        HFONT hNew = CreateFontA(kSlots[i].height, 0, 0, 0, 400, 0, 0, 0,
                                 (DWORD)g_charSet, 0, 0, 1, 2,
                                 g_faceName.c_str());
        if (!hNew) {
            Log("RebuildFontTable: 槽 %s 建中文字体失败 (err=%lu)", kSlots[i].what, GetLastError());
            continue;
        }

        DWORD oldProt = 0;
        if (!VirtualProtect(pSlot, sizeof(DWORD), PAGE_READWRITE, &oldProt)) {
            Log("RebuildFontTable: 槽 %s VirtualProtect 失败 (err=%lu)", kSlots[i].what, GetLastError());
            DeleteObject(hNew);
            continue;
        }

        HFONT hOld = (HFONT)*pSlot;
        *pSlot = (DWORD)(DWORD_PTR)hNew;

        DWORD tmp = 0;
        VirtualProtect(pSlot, sizeof(DWORD), oldProt, &tmp);

        // 旧 HFONT 不 DeleteObject：可能仍被 DDraw 表面/DC 选中，删除有失效风险；
        // 每进程仅重建一次，泄漏 7 个 GDI 对象可接受。
        Log("RebuildFontTable: %-8s h=%4d  %p -> %p", kSlots[i].what,
            kSlots[i].height, (void*)hOld, (void*)hNew);
        ok++;
    }

    Log("RebuildFontTable: 重建 %d/7 槽为 %s(GB2312=%u)", ok, g_faceName.c_str(), (unsigned)g_charSet);
}

void RemoveHooks() {
    HMODULE hGame = GetModuleHandleA(nullptr);
    if (!hGame) return;
    if (g_orgCreateFontA)
        PatchIAT(hGame, "gdi32.dll", "CreateFontA", g_orgCreateFontA, nullptr);
    if (g_orgCreateFontIndirectA)
        PatchIAT(hGame, "gdi32.dll", "CreateFontIndirectA",
                 g_orgCreateFontIndirectA, nullptr);
    Log("hooks removed");
}

void SetModuleHandle(HMODULE h) { g_hModule = h; }

// ── ASI 入口（Ultimate ASI Loader 约定的导出名）────────────────────────
// UAL 加载 .asi 后会自动调用 InitializeASI()（若导出存在）。
// 这里做实际初始化：读配置 -> 加载翻译 -> 装 Hook -> 打内存补丁。
extern "C" __declspec(dllexport) void InitializeASI() {
    if (!g_hModule) g_hModule = GetModuleHandleA(nullptr);
    Log("InitializeASI: enter");

    bool dataOk = LoadTranslationData();
    if (!dataOk) Log("translation data not loaded");

    bool hookOk = InstallHooks();

    bool patchOk = false;
    if (dataOk) patchOk = ApplyStringPatches();

    RebuildFontTable();   // 直接改写已建好的字体表（Hook 拦不到早先那次建表）

    // ★ 必须在 RebuildFontTable 之后：桥接要读中文字体的句柄是否已就位
    bool cjkOk = InstallCjkRenderer();
    if (!g_noUnitZh.empty()) PatchNoUnitString(g_noUnitZh);
    if (!g_sargeZh.empty())  PatchSargeString(g_sargeZh);

    Log("InitializeASI -> data=%d hook=%d patch=%d cjk=%d",
        (int)dataOk, (int)hookOk, (int)patchOk, (int)cjkOk);
}

extern "C" __declspec(dllexport) bool ArmyMenCHS_Install() {
    if (!g_hModule) g_hModule = GetModuleHandleA(nullptr);

    bool dataOk = LoadTranslationData();
    if (!dataOk) Log("translation data not loaded");

    bool hookOk = InstallHooks();

    bool patchOk = false;
    if (dataOk) patchOk = ApplyStringPatches();

    RebuildFontTable();   // 直接改写已建好的字体表（Hook 拦不到早先那次建表）

    bool cjkOk = InstallCjkRenderer();
    if (!g_noUnitZh.empty()) PatchNoUnitString(g_noUnitZh);
    if (!g_sargeZh.empty())  PatchSargeString(g_sargeZh);

    Log("Install -> data=%d hook=%d patch=%d cjk=%d",
        (int)dataOk, (int)hookOk, (int)patchOk, (int)cjkOk);
    return hookOk || patchOk || cjkOk;
}

extern "C" __declspec(dllexport) void ArmyMenCHS_Uninstall() {
    RemoveHooks();
}
