// wrapcjk.h —— CJK 长文本换行修复（在 sub_42EF50 入口预处理字符串）
#pragma once

#include <windows.h>
#include <string>

struct WrapCjkConfig {
    DWORD siteVA    = 0;    // 0x42EF50：sub_42EF50 入口（`sub esp,90h`）
    DWORD resumeVA  = 0;    // 0x42EF56：复原前 6 字节后跳回的位置（`push ebx`）
    DWORD patchLen  = 0;    // 6（正好是 `sub esp,90h` 一条指令）
    BYTE  sig[16]   = {0};  // 期望的原始字节
    int   sigLen    = 0;
    std::string logTag;
};

bool WrapCjkInstall(const WrapCjkConfig& cfg);
void WrapCjkRemove();
bool WrapCjkIsActive();
