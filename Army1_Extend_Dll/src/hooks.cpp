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

    Log("InitializeASI -> data=%d hook=%d patch=%d",
        (int)dataOk, (int)hookOk, (int)patchOk);
}

extern "C" __declspec(dllexport) bool ArmyMenCHS_Install() {
    if (!g_hModule) g_hModule = GetModuleHandleA(nullptr);

    bool dataOk = LoadTranslationData();
    if (!dataOk) Log("translation data not loaded");

    bool hookOk = InstallHooks();

    bool patchOk = false;
    if (dataOk) patchOk = ApplyStringPatches();

    RebuildFontTable();   // 直接改写已建好的字体表（Hook 拦不到早先那次建表）

    Log("Install -> data=%d hook=%d patch=%d",
        (int)dataOk, (int)hookOk, (int)patchOk);
    return hookOk || patchOk;
}

extern "C" __declspec(dllexport) void ArmyMenCHS_Uninstall() {
    RemoveHooks();
}
