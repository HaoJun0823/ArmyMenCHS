#include "pch.h"
#include "codepatch.h"
#include "log.h"

#include <string>
#include <vector>
#include <cstdio>
#include <cstring>

// ════════════════════════════════════════════════════════════════════════
//  代码段补丁表
//
//  ★ 地址一律写 **绝对 VA**（IDA 显示值），与 RendererEnv 的约定一致 ——
//    本项目已因"RVA/VA 混用"崩过一次，这里不再犯。
//
//  ★ 每条必须给出**完整原文**（不是只给 1 字节）：
//    只比对一个字节时，任何偏移漂移都可能命中巧合位置并写坏代码。
//    多字节原文 + 长度校验能几乎消除误命中。
// ════════════════════════════════════════════════════════════════════════

struct CodePatch {
    const char* id;          // 可读标识（日志用）
    DWORD  va;               // ★ 绝对 VA
    BYTE   orig[16];         // 期望原文
    BYTE   patch[16];        // 替换为
    int    len;              // 字节数
    bool   applied;
    BYTE*  addr;
};

// AM2 Steam：解锁多人游戏
//
//  ★★ 地址换算（别搞混，本项目已因此崩过一次）：
//     用户给的 "Offset 4D8FE" 是**文件偏移**；
//     本作 .text 段 RA == VA，所以它同时等于 **RVA**。
//     而我们统一用**绝对 VA** -> 0x4D8FE + 0x400000 = 0x44D8FE。
//     目标字节 EB 在 VA 0x44D8FE。
//
//  原文 `EB 55` -> `74 55`
//
//  ★ 额外带上前面 4 字节 `03 00 00 00`（即 mov [esp+0x38],3 的立即数），
//    共 6 字节一起校验 —— 正是用户给的 "search hex 03 00 00 00 EB 55"。
//    这样即使将来偏移漂移也能立刻发现，而不是写错位置。
static const BYTE kMpOrig[6] = {0x03, 0x00, 0x00, 0x00, 0xEB, 0x55};
static const BYTE kMpNew[6]  = {0x03, 0x00, 0x00, 0x00, 0x74, 0x55};

static std::vector<CodePatch> g_patches;

int CodePatchesCount() { return (int)g_patches.size(); }

static void InitPatches() {
    if (!g_patches.empty()) return;
    CodePatch p;
    p.id = "解锁多人游戏（multiplay 按钮）";
    // RVA 0x4D8FA（含前 4 字节立即数）+ ImageBase 0x400000 = VA 0x44D8FA
    p.va = 0x44D8FA;
    p.len = 6;
    memcpy(p.orig, kMpOrig, 6);
    memcpy(p.patch, kMpNew, 6);
    p.applied = false;
    p.addr = nullptr;
    g_patches.push_back(p);
}

int CodePatchesApplyAll()
{
    InitPatches();

    BYTE* base = (BYTE*)GetModuleHandleA(nullptr);
    IMAGE_DOS_HEADER* dos = (IMAGE_DOS_HEADER*)base;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) {
        Log("codepatch: 主模块不是 PE");
        return 0;
    }
    IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(base + dos->e_lfanew);
    DWORD imgBase = nt->OptionalHeader.ImageBase;
    DWORD imgSize = nt->OptionalHeader.SizeOfImage;

    int ok = 0;
    for (auto& p : g_patches) {
        // ★ 地址必须是绝对 VA 且落在映像内（语义自查）
        if (p.va < imgBase || p.va + (DWORD)p.len > imgBase + imgSize) {
            Log("codepatch[%s]: VA %#010x 不在映像 [%#010x,%#010x) 内，跳过",
                p.id, p.va, imgBase, imgBase + imgSize);
            continue;
        }
        p.addr = (BYTE*)(DWORD_PTR)p.va;

        // ★ 多字节原文校验：不一致绝不写（可能游戏版本不同 / 已被别的补丁改过）
        if (memcmp(p.addr, p.orig, p.len) != 0) {
            char cur[64] = {0}, exp[64] = {0};
            for (int i = 0; i < p.len; i++) {
                sprintf_s(cur + i * 3, 4, "%02X ", p.addr[i]);
                sprintf_s(exp + i * 3, 4, "%02X ", p.orig[i]);
            }
            Log("codepatch[%s]: 原文不符 @%#010x\n      期望 %s\n      实得 %s  -> 不写",
                p.id, p.va, exp, cur);
            continue;
        }

        // 若已是目标状态（例如用户连着启动两次），不必重复写
        if (memcmp(p.addr, p.patch, p.len) == 0) {
            Log("codepatch[%s]: 已是目标状态，无需修改", p.id);
            ok++;
            continue;
        }

        DWORD oldProt = 0;
        if (!VirtualProtect(p.addr, p.len, PAGE_EXECUTE_READWRITE, &oldProt)) {
            Log("codepatch[%s]: VirtualProtect 失败 (%lu)", p.id, GetLastError());
            continue;
        }
        memcpy(p.addr, p.patch, p.len);
        DWORD tmp = 0;
        VirtualProtect(p.addr, p.len, oldProt, &tmp);
        FlushInstructionCache(GetCurrentProcess(), p.addr, p.len);

        p.applied = true;
        ok++;
        Log("codepatch[%s]: 已应用 @%#010x  %02X %02X -> %02X %02X",
            p.id, p.va, p.orig[p.len - 2], p.orig[p.len - 1],
            p.patch[p.len - 2], p.patch[p.len - 1]);
    }

    Log("codepatch: 共 %d 条，成功 %d 条", (int)g_patches.size(), ok);
    return ok;
}

void CodePatchesRestoreAll()
{
    int n = 0;
    for (auto& p : g_patches) {
        if (!p.applied || !p.addr) continue;
        DWORD oldProt = 0;
        if (VirtualProtect(p.addr, p.len, PAGE_EXECUTE_READWRITE, &oldProt)) {
            memcpy(p.addr, p.orig, p.len);
            DWORD tmp = 0;
            VirtualProtect(p.addr, p.len, oldProt, &tmp);
            FlushInstructionCache(GetCurrentProcess(), p.addr, p.len);
            n++;
        }
        p.applied = false;
    }
    if (n) Log("codepatch: 已恢复 %d 条", n);
}
