#include "pch.h"
#include "mpunlock.h"
#include "log.h"
#include "target.h"     // GameProfile / Target::BuiltinProfiles

#include <cstdio>

// ════════════════════════════════════════════════════════════════════════
//  多人联机菜单解锁（Army Men: World War / 4 代）
//
//  补丁点：RVA 0x6F270（== 文件偏移 0x6F270，因为 .text 的
//          PointerToRawData 与 VirtualAddress 都是 0x1000）
//          VA = 0x400000 + 0x6F270 = 0x46F270
//
//  字节：EB 55 (jmp short +0x55)  ->  74 55 (jz short +0x55)
//
//  实测上下文（IDA get_bytes @ 0x46F270 前 24 字节）：
//      ... E8 E4 96 01 00 | 8B F0 | 83 C4 04 | 89 74 24 0C | 3B F3
//          C7 44 24 38 04 00 00 00 | EB 55
//    即 `mov [esp+38h], 4` 之后紧跟那个被改的跳转。
//
//  ★★ 与 3 代的同构与差异（这个对照很重要，别照抄 3 代的注释）：
//      3 代：C7 45 **FC** 04 00 00 00 | EB 41      槽位是 [ebp-4]
//      4 代：C7 44 **24 38** 04 00 00 00 | EB 55   槽位是 [esp+38h]
//    形状一致（"置菜单项号 + 条件跳"），只有槽位与跳转距离不同。
//
//  为什么只改 1 字节就够：
//    主菜单构建函数对每个菜单项做一遍"CD 在位 / 注册表"检查，然后
//      mov  <槽位>, <项号>
//      jz   +0x55        <- 原版：检查通过才跳到"安装该项"的代码
//    GOG 把它改成无条件 jmp，于是**无论检查结果如何都跳过**，
//    Multiplayer 项彻底消失。改回 jz 后：检查失败仍然跳过（不会崩），
//    注册表项齐全时检查通过 -> 菜单项正常安装。
//
//  ★ fail-closed：目标字节不是 EB 55 也不是 74 55 时**不动内存**，
//    只写日志。避免往错误的构建上写字节。
// ════════════════════════════════════════════════════════════════════════

static const DWORD MP_UNLOCK_RVA = 0x6F270;
static const BYTE   MP_GOG_BYTE  = 0xEB;   // 现状（GOG 改过的）
static const BYTE   MP_ORIG_BYTE = 0x74;   // 原版（jz）
static const BYTE   MP_NEXT_BYTE = 0x55;   // 两个分支共有的第二字节，用于加强校验

static BYTE*  g_patchedAddr = nullptr;   // 已打补丁的绝对地址（nullptr = 未打）
static bool   g_wasGog      = false;     // 是否真的是从 EB 改成的

static bool ReadOriginal(BYTE* p, BYTE& b0, BYTE& b1)
{
    MEMORY_BASIC_INFORMATION mbi;
    if (!VirtualQuery(p, &mbi, sizeof(mbi))) return false;
    if (mbi.State != MEM_COMMIT) return false;
    if (!(mbi.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE |
                         PAGE_EXECUTE_WRITECOPY | PAGE_READONLY | PAGE_READWRITE)))
        return false;
    __try {
        b0 = p[0];
        b1 = p[1];
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

bool MpUnlockInstall()
{
    HMODULE h = GetModuleHandleA(nullptr);
    if (!h) { Log("MpUnlock: 取不到主模块，跳过"); return false; }
    BYTE* base = (BYTE*)h;

    // ★ 用 profile 里的元数据再确认一次身份，避免往别的 exe 上写字节
    const std::vector<GameProfile>& profs = Target::BuiltinProfiles();
    const GameProfile* gp = nullptr;
    for (const auto& p : profs) {
        if (p.exeName == "amww.exe") { gp = &p; break; }
    }
    if (!gp) { Log("MpUnlock: 档位表里没有 amww.exe，跳过"); return false; }

    BYTE* addr = base + MP_UNLOCK_RVA;

    // 边界检查：patchLen 至少 2 字节
    DWORD sizeOfImage = 0;
    {
        IMAGE_DOS_HEADER* dos = (IMAGE_DOS_HEADER*)base;
        if (dos->e_magic != IMAGE_DOS_SIGNATURE) {
            Log("MpUnlock: 主模块 DOS 头异常，跳过");
            return false;
        }
        IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(base + dos->e_lfanew);
        if (nt->Signature != IMAGE_NT_SIGNATURE) {
            Log("MpUnlock: 主模块 NT 头异常，跳过");
            return false;
        }
        sizeOfImage = nt->OptionalHeader.SizeOfImage;
    }
    if (MP_UNLOCK_RVA + 2 > sizeOfImage) {
        Log("MpUnlock: RVA %#x 超出映像 (%#x)，跳过", MP_UNLOCK_RVA, sizeOfImage);
        return false;
    }

    BYTE b0 = 0, b1 = 0;
    if (!ReadOriginal(addr, b0, b1)) {
        Log("MpUnlock: 读不到 RVA %#x 的内存，跳过", MP_UNLOCK_RVA);
        return false;
    }

    if (b0 == MP_ORIG_BYTE && b1 == MP_NEXT_BYTE) {
        Log("MpUnlock: RVA %#x 已是 74 55（非 GOG 版或已解锁），无需改动", MP_UNLOCK_RVA);
        return true;
    }
    if (!(b0 == MP_GOG_BYTE && b1 == MP_NEXT_BYTE)) {
        Log("MpUnlock: !! RVA %#x 实得 %02X %02X，既不是 EB 55 也不是 74 55 —— "
            "不是预期的构建，拒绝写入（fail-closed）", MP_UNLOCK_RVA, b0, b1);
        return false;
    }

    DWORD oldProt = 0;
    if (!VirtualProtect(addr, 2, PAGE_EXECUTE_READWRITE, &oldProt)) {
        Log("MpUnlock: VirtualProtect 失败 err=%lu，跳过", GetLastError());
        return false;
    }
    addr[0] = MP_ORIG_BYTE;
    VirtualProtect(addr, 2, oldProt, &oldProt);

    // 回读验证
    BYTE c0 = 0, c1 = 0;
    if (!ReadOriginal(addr, c0, c1) || c0 != MP_ORIG_BYTE || c1 != MP_NEXT_BYTE) {
        Log("MpUnlock: !! 写入后回读失败 (%02X %02X)", c0, c1);
        return false;
    }

    g_patchedAddr = addr;
    g_wasGog      = true;
    Log("MpUnlock: OK —— RVA %#x (VA %p)  EB 55 -> 74 55，主菜单多人项已恢复",
        MP_UNLOCK_RVA, (void*)addr);
    return true;
}

void MpUnlockRemove()
{
    if (!g_patchedAddr || !g_wasGog) return;
    BYTE* addr = g_patchedAddr;
    DWORD oldProt = 0;
    if (VirtualProtect(addr, 2, PAGE_EXECUTE_READWRITE, &oldProt)) {
        addr[0] = MP_GOG_BYTE;
        VirtualProtect(addr, 2, oldProt, &oldProt);
        Log("MpUnlock: 已恢复 EB 55");
    }
    g_patchedAddr = nullptr;
    g_wasGog      = false;
}
