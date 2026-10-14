#include "pch.h"
#include "log.h"

#include <cstdio>
#include <cstdarg>
#include <string>

static HMODULE g_hModule = nullptr;
static char    g_gameTag[32] = "ArmyMen2CHS";

void LogSetModule(HMODULE h) { g_hModule = h; }
void LogSetGameTag(const char* tag) {
    if (tag && *tag) {
        strncpy_s(g_gameTag, sizeof(g_gameTag), tag, _TRUNCATE);
    }
}

bool LogGetDllDir(wchar_t* out, size_t cch) {
    if (!out || cch == 0) return false;
    out[0] = 0;
    if (!g_hModule) return false;
    wchar_t mod[MAX_PATH] = {0};
    if (!GetModuleFileNameW(g_hModule, mod, MAX_PATH)) return false;
    wchar_t* slash = wcsrchr(mod, L'\\');
    if (slash) *(slash + 1) = 0; else mod[0] = 0;
    wcsncpy_s(out, cch, mod, _TRUNCATE);
    return true;
}

void Log(const char* fmt, ...) {
    char buf[2048];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);

    OutputDebugStringA("[AMCHS] ");
    OutputDebugStringA(buf);
    OutputDebugStringA("\n");

    static wchar_t path[MAX_PATH] = {0};
    static bool inited = false;
    if (!inited) {
        inited = true;
        wchar_t dir[MAX_PATH] = {0};
        if (LogGetDllDir(dir, MAX_PATH)) {
            wchar_t name[64];
            _snwprintf_s(name, _countof(name), _TRUNCATE, L"%S.log", g_gameTag);
            wcsncpy_s(path, MAX_PATH, dir, _TRUNCATE);
            wcscat_s(path, MAX_PATH, name);
        }
    }
    if (!path[0]) return;

    FILE* f = nullptr;
    // ★ 不要把 UTF-8 字节交给 fwprintf 的宽字符模式：
    //   Log() 收到的 buf 是 **UTF-8 字节**，而 "%S" 期望 ANSI/宽字符。
    //   用 fwprintf(f, L"...%S") 会让 UTF-8 字节先被当成 Latin-1 再编成 UTF-8，
    //   结果是"每个汉字变成 2~3 个乱码字符"（实测：è½½å¥...）。
    //   正确做法：以二进制追加，自己写时间戳前缀 + 原始 UTF-8 字节。
    if (_wfopen_s(&f, path, L"ab") == 0 && f) {
        SYSTEMTIME st;
        GetLocalTime(&st);
        char ts[64];
        int n = _snprintf_s(ts, sizeof(ts), _TRUNCATE,
                            "[%02d:%02d:%02d.%03d] ",
                            st.wHour, st.wMinute, st.wSecond, st.wMilliseconds);
        if (n > 0) fwrite(ts, 1, (size_t)n, f);
        fwrite(buf, 1, strlen(buf), f);
        fwrite("\r\n", 1, 2, f);
        fclose(f);
    }
}
