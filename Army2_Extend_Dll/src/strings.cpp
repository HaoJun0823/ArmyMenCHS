#include "pch.h"
#include "strings.h"
#include "log.h"

#include <windows.h>
#include <string>
#include <vector>
#include <cstdio>
#include <cstring>

// ── UTF-8 -> GBK（游戏是 ANSI 程序，内存里必须是 GBK 字节）────────────
static std::string Utf8ToGbk(const std::string& u)
{
    if (u.empty()) return {};
    int nw = MultiByteToWideChar(CP_UTF8, 0, u.c_str(), (int)u.size(), nullptr, 0);
    if (nw <= 0) return {};
    std::wstring w(nw, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, u.c_str(), (int)u.size(), &w[0], nw);
    int ng = WideCharToMultiByte(936, 0, w.c_str(), nw, nullptr, 0, nullptr, nullptr);
    if (ng <= 0) return {};
    std::string g(ng, '\0');
    WideCharToMultiByte(936, 0, w.c_str(), nw, &g[0], ng, nullptr, nullptr);
    return g;
}

static std::string Trim(const std::string& s)
{
    size_t a = s.find_first_not_of(" \t\r\n");
    if (a == std::string::npos) return {};
    size_t b = s.find_last_not_of(" \t\r\n");
    return s.substr(a, b - a + 1);
}

// ★ 还原生成脚本对英文原文做的转义："\x20" -> 空格, "\\" -> 反斜杠。
//
//   为什么需要：有些英文原文**自带前导/尾随空格**（实测 "  --  In Progress"），
//   而 INI 的解析（下面 ParseIni 里对 value 做 Trim）会把它们吃掉，
//   导致安全闸门比对失败、该条被静默跳过。
//   生成脚本 gen_am2_strings_ini.py 把空格写成 \x20，
//   这里必须做**同样的还原**，两边都改才有效。
static std::string Unescape(const std::string& s)
{
    std::string out;
    out.reserve(s.size());
    size_t i = 0;
    while (i < s.size()) {
        if (s.compare(i, 4, "\\x20") == 0) { out.push_back(' '); i += 4; }
        else if (s.compare(i, 2, "\\\\") == 0) { out.push_back('\\'); i += 2; }
        else { out.push_back(s[i]); i += 1; }
    }
    return out;
}

struct StrPatch {
    DWORD       rva;
    std::string en;      // 期望的英文原文（安全闸门）
    std::string zh;      // 中文译文（UTF-8 -> GBK 后写入）
    BYTE*       addr = nullptr;
    int         cap = 0;         // 可写容量（= 原长+1）
    std::string origBytes;       // 原始字节，用于恢复
    bool        applied = false;
};

static std::vector<StrPatch> g_patches;

// 找 INI：优先 scripts\strings\am2_strings.ini
static bool FindIni(std::wstring& out)
{
    wchar_t dllDir[MAX_PATH] = {0};
    if (!LogGetDllDir(dllDir, MAX_PATH)) return false;
    std::wstring base(dllDir);
    const wchar_t* cands[] = {
        L"strings\\am2_strings.ini",
        L"..\\strings\\am2_strings.ini",
    };
    for (auto c : cands) {
        std::wstring p = base + c;
        DWORD a = GetFileAttributesW(p.c_str());
        if (a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY)) {
            out = p;
            return true;
        }
    }
    return false;
}

static bool ReadWholeFile(const std::wstring& p, std::string& out)
{
    FILE* f = nullptr;
    if (_wfopen_s(&f, p.c_str(), L"rb") != 0 || !f) return false;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (n <= 0) { fclose(f); return false; }
    out.resize((size_t)n);
    size_t got = fread(&out[0], 1, (size_t)n, f);
    fclose(f);
    return got == (size_t)n;
}

// ── 解析 INI ────────────────────────────────────────────────────────────
// 行格式： 0xRRRRRR=英文原文|中文译文
static bool ParseIni(const std::string& text, std::vector<StrPatch>& out)
{
    std::string sec;
    size_t pos = 0;
    int lineNo = 0;
    while (pos <= text.size()) {
        size_t e = text.find('\n', pos);
        std::string raw = text.substr(pos, (e == std::string::npos) ? std::string::npos : e - pos);
        pos = (e == std::string::npos) ? text.size() + 1 : e + 1;
        lineNo++;

        std::string t = Trim(raw);
        if (t.empty() || t[0] == ';' || t[0] == '#') continue;
        if (t[0] == '[') {
            size_t c = t.find(']');
            sec = (c == std::string::npos) ? "" : t.substr(1, c - 1);
            continue;
        }
        if (sec != "Strings") continue;

        size_t eq = t.find('=');
        if (eq == std::string::npos) continue;
        std::string k = Trim(t.substr(0, eq));
        std::string v = Trim(t.substr(eq + 1));

        // RVA
        DWORD rva = 0;
        if (sscanf_s(k.c_str(), "0x%x", &rva) != 1 && sscanf_s(k.c_str(), "%x", &rva) != 1) {
            Log("strings: 第 %d 行 RVA 解析失败: %s", lineNo, k.c_str());
            continue;
        }
        size_t bar = v.find('|');
        if (bar == std::string::npos) {
            Log("strings: 第 %d 行缺少 '|' 分隔符，跳过", lineNo);
            continue;
        }
        StrPatch p;
        p.rva = rva;
        // ★ 英文原文先 Trim（去掉行尾空白/注释分隔），再还原 \x20 转义 ——
        //   顺序不能反：先还原会把转义出来的空格又 Trim 掉。
        p.en = Unescape(Trim(v.substr(0, bar)));
        p.zh = Trim(v.substr(bar + 1));
        if (p.zh.empty()) continue;
        out.push_back(p);
    }
    return !out.empty();
}

bool StringsApplyAll()
{
    std::wstring ini;
    if (!FindIni(ini)) {
        Log("strings: 未找到 am2_strings.ini（只做字形渲染，不改文本）");
        return false;
    }
    std::string text;
    if (!ReadWholeFile(ini, text)) {
        Log("strings: 读不到 %ls", ini.c_str());
        return false;
    }

    std::vector<StrPatch> patches;
    if (!ParseIni(text, patches)) {
        Log("strings: INI 里没有有效条目");
        return false;
    }
    Log("strings: 解析到 %d 条", (int)patches.size());

    BYTE* base = (BYTE*)GetModuleHandleA(nullptr);
    IMAGE_DOS_HEADER* dos = (IMAGE_DOS_HEADER*)base;
    IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(base + dos->e_lfanew);
    DWORD imgSize = nt->OptionalHeader.SizeOfImage;

    int applied = 0, skipped = 0, mismatch = 0;
    char buf[512];

    for (auto& p : patches) {
        if (p.rva == 0 || p.rva >= imgSize) {
            Log("strings: RVA %#x 越界，跳过", p.rva);
            skipped++; continue;
        }
        BYTE* addr = base + p.rva;

        // 读内存现状
        size_t maxScan = 512;
        size_t cur = 0;
        while (cur < maxScan && p.rva + cur < imgSize && addr[cur] != 0) cur++;
        std::string now((const char*)addr, cur);

        // ★ 安全闸门：内存现状必须等于 INI 声明的英文原文
        if (now != p.en) {
            snprintf(buf, sizeof(buf),
                     "strings: RVA %#x 原文不符（期望 \"%s\" 实得 \"%s\"）-> 不写",
                     p.rva, p.en.c_str(), now.c_str());
            Log("%s", buf);
            mismatch++; continue;
        }

        std::string gbk = Utf8ToGbk(p.zh);
        if (gbk.empty()) { skipped++; continue; }

        int cap = (int)p.en.size() + 1;
        if ((int)gbk.size() + 1 > cap) {
            Log("strings: RVA %#x 译文太长（%d > %d）-> 跳过（不截断，避免破坏相邻数据）",
                p.rva, (int)gbk.size() + 1, cap);
            skipped++; continue;
        }
        if (p.rva + (DWORD)cap > imgSize) { skipped++; continue; }

        DWORD oldProt = 0;
        if (!VirtualProtect(addr, cap, PAGE_READWRITE, &oldProt)) {
            Log("strings: VirtualProtect 失败 RVA %#x", p.rva);
            skipped++; continue;
        }
        p.origBytes.assign((const char*)addr, cap);
        p.addr = addr; p.cap = cap;
        memset(addr, 0, cap);
        memcpy(addr, gbk.c_str(), gbk.size());
        DWORD tmp = 0;
        VirtualProtect(addr, cap, oldProt, &tmp);

        p.applied = true;
        applied++;
        Log("strings: APPLY RVA %#x  \"%s\" -> \"%s\"", p.rva, p.en.c_str(), p.zh.c_str());
    }

    g_patches = std::move(patches);
    Log("strings: applied=%d skipped=%d mismatch=%d", applied, skipped, mismatch);
    return applied > 0;
}

void StringsRestoreAll()
{
    int n = 0;
    for (auto& p : g_patches) {
        if (!p.applied || !p.addr || p.origBytes.empty()) continue;
        DWORD oldProt = 0;
        if (VirtualProtect(p.addr, p.cap, PAGE_READWRITE, &oldProt)) {
            memcpy(p.addr, p.origBytes.data(), p.origBytes.size());
            DWORD tmp = 0;
            VirtualProtect(p.addr, p.cap, oldProt, &tmp);
            n++;
        }
    }
    if (n) Log("strings: 已恢复 %d 条", n);
}
