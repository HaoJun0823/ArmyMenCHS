#include "pch.h"
#include "cdspoof.h"
#include "log.h"

// ── 被改写的入口点原件（卸载时恢复）──────────────────────────────────
static BYTE* g_target = nullptr;
static BYTE  g_orig[16] = {0};
static int   g_len = 0;
static void* g_stub = nullptr;      // "mov eax,1 / ret" 桩
static bool  g_active = false;

bool CdSpoofIsActive() { return g_active; }

// ── stub：mov eax,1 ; ret ──────────────────────────────────────────────
//
//  sub_447450 是 __cdecl、无参、返回 int（IDA 原型 `int sub_447450()`）。
//  所以桩体只需要给 eax 一个 1 然后 ret，不需要平衡任何栈。
//  ★ 不要写成 `push 1 / pop eax`：多一条指令没有任何好处，
//    而 B8 01 00 00 00 C3 是 6 字节、语义最直白的形式。
static void* BuildStub()
{
    BYTE* p = (BYTE*)VirtualAlloc(nullptr, 64, MEM_COMMIT | MEM_RESERVE,
                                  PAGE_EXECUTE_READWRITE);
    if (!p) {
        Log("CdSpoof: stub 分配失败 (%lu)", GetLastError());
        return nullptr;
    }
    // mov eax, 1
    p[0] = 0xB8;
    p[1] = 0x01; p[2] = 0x00; p[3] = 0x00; p[4] = 0x00;
    // ret
    p[5] = 0xC3;
    FlushInstructionCache(GetCurrentProcess(), p, 6);
    return p;
}

// ── 把 byte_671288 填成 "<exe目录>\" ───────────────────────────────────
//
//  ★ 这个缓冲是后续所有"回退取资源"的根：
//        sub_43F4A0 / sub_4400B0 都是  _chdir(byte_671288 + 子目录)
//    所以必须以反斜杠结尾（原版 sprintf 的格式串也是 "%s_Setup\\"，
//    即盘符后面直接跟 "_Setup\"，这里换成 exe 目录 + "\"）。
//
//  ★ 容量：原版用 `sprintf(&byte_671288, "%s_Setup\\", v5)`，
//    盘符最多 3 字符 + "_Setup\" = 10 字节，缓冲区显然 ≥ 11。
//    实测该缓冲是 256 字节（.data 里 byte_671288 到下一个变量之间）。
//    exe 目录路径最长 MAX_PATH-1，必须截断保护，绝不允许溢出。
static bool WriteRootBuf(DWORD rootBufVA, int cap, const char* tag)
{
    if (!rootBufVA || cap <= 1) return false;
    char* buf = (char*)(DWORD_PTR)rootBufVA;

    // 取 exe 完整路径，去掉文件名
    char full[MAX_PATH] = {0};
    if (!GetModuleFileNameA(nullptr, full, MAX_PATH)) {
        Log("CdSpoof: GetModuleFileNameA 失败 (%lu)", GetLastError());
        return false;
    }
    char* slash = strrchr(full, '\\');
    if (!slash) {
        Log("CdSpoof: exe 路径无目录分量: %s", full);
        return false;
    }
    *(slash + 1) = 0;              // 保留结尾反斜杠： "<dir>\"

    size_t need = strlen(full);
    if ((int)need + 1 > cap) {
        // 路径超出缓冲容量。宁可整体放弃（游戏会退回原版行为），
        // 也不能截断成半截路径 —— 那会让 _chdir 到完全错误的地方。
        Log("CdSpoof: exe 目录长度 %u 超出缓冲容量 %d，放弃填充", (unsigned)need, cap);
        return false;
    }

    DWORD oldProt = 0;
    if (!VirtualProtect(buf, cap, PAGE_READWRITE, &oldProt)) {
        Log("CdSpoof: VirtualProtect(rootBuf) 失败 (%lu)", GetLastError());
        return false;
    }
    memset(buf, 0, (size_t)cap);
    memcpy(buf, full, need + 1);   // 含结尾 NUL
    DWORD tmp = 0;
    VirtualProtect(buf, cap, oldProt, &tmp);

    Log("CdSpoof[%s]: 根路径缓冲 <- \"%s\"", tag ? tag : "", full);
    return true;
}

bool CdSpoofInstall(const CdSpoofConfig& cfg)
{
    Log("CdSpoof: ===== 开始屏蔽 CD-ROM 校验 =====");

    if (!cfg.detectVA || cfg.patchLen < 5 || cfg.patchLen > 16) {
        Log("CdSpoof: 配置不完整（detectVA=%#x patchLen=%d），跳过",
            cfg.detectVA, cfg.patchLen);
        return false;
    }

    BYTE* base = (BYTE*)GetModuleHandleA(nullptr);
    if (!base) { Log("CdSpoof: 取主模块失败"); return false; }

    // ── ① 再校验一次目标地址的原始字节（防写坏别的函数）──
    //
    //  ★ 地址语义：cfg.detectVA 是 **绝对 VA**（IDA 显示值）。
    //    本作 ImageBase == 模块基址 == 0x400000（且无 DYNAMICBASE），
    //    但这里一律按"VA - 实际模块基址"换算，不假设两者相等 ——
    //    加了基址又减回去的写法虽然等价，却容易被后人改成单边运算而出错。
    DWORD imgBase = (DWORD)(DWORD_PTR)base;
    if (cfg.detectVA < imgBase) {
        Log("CdSpoof: detectVA=%#x 小于模块基址 %#x，拒绝", cfg.detectVA, imgBase);
        return false;
    }
    BYTE* target = base + (cfg.detectVA - imgBase);
    {
        // 期望的 11 字节指纹（与 target.cpp 里的 cdDetectSig 一致）
        // 51 53 55 56 57 = push ecx/ebx/ebp/esi/edi
        // 8B 3D xx xx xx xx = mov edi, ds:[GetLogicalDriveStringsA 的 IAT]
        static const BYTE kExpect[11] = {
            0x51, 0x53, 0x55, 0x56, 0x57,
            0x8B, 0x3D, 0xC0, 0x40, 0x4F, 0x00
        };
        const int n = (int)sizeof(kExpect);
        if (cfg.cdDetectSigLen >= n &&
            memcmp(cfg.cdDetectSig, kExpect, n) == 0) {
            // profile 里登记了同样的指纹，用它做实际比对（单一事实来源）
            if (memcmp(target, cfg.cdDetectSig, cfg.cdDetectSigLen) != 0) {
                Log("CdSpoof: 入口指纹与 profile 不符，拒绝改写（fail-closed）");
                return false;
            }
        } else {
            // profile 没登记或登记不一致 -> 用内置指纹兜底
            if (memcmp(target, kExpect, n) != 0) {
                Log("CdSpoof: 入口指纹不符，拒绝改写（fail-closed）");
                Log("CdSpoof:   期望 %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X",
                    kExpect[0], kExpect[1], kExpect[2], kExpect[3], kExpect[4],
                    kExpect[5], kExpect[6], kExpect[7], kExpect[8], kExpect[9], kExpect[10]);
                Log("CdSpoof:   实得 %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X",
                    target[0], target[1], target[2], target[3], target[4],
                    target[5], target[6], target[7], target[8], target[9], target[10]);
                return false;
            }
        }
    }

    // ── ② 先填根路径缓冲 + 置标志（**必须在改写入口之前**）──
    //
    //  ★ 顺序很重要：一旦 sub_447450 变成 return 1，它内部就再也不会
    //    写 byte_671288 / dword_6713B0。所以这两项必须我们预先填好，
    //    否则后续 40 处目录回退全部失效。
    bool rootOk = WriteRootBuf(cfg.rootBufVA, cfg.rootBufSize,
                               cfg.logTag.c_str());
    if (!rootOk) {
        Log("CdSpoof: !! 根路径缓冲填充失败 —— 已经写了一半，为保持一致，"
            "仍继续安装（入口改写后游戏能进，只是缺资源的目录会静默失败）");
    }

    if (cfg.readyFlagVA) {
        *(DWORD*)(DWORD_PTR)cfg.readyFlagVA = 1;
        Log("CdSpoof: dword(CD就绪标志)@%#x <- 1", cfg.readyFlagVA);
    }
    if (cfg.readyFlag2VA) {
        *(DWORD*)(DWORD_PTR)cfg.readyFlag2VA = 1;
        Log("CdSpoof: dword(伴随标志)@%#x <- 1", cfg.readyFlag2VA);
    }

    // ── ③ 改写入口为 return 1 ──
    void* stub = BuildStub();
    if (!stub) return false;

    DWORD oldProt = 0;
    if (!VirtualProtect(target, cfg.patchLen, PAGE_EXECUTE_READWRITE, &oldProt)) {
        Log("CdSpoof: VirtualProtect(target) 失败 (%lu)", GetLastError());
        VirtualFree(stub, 0, MEM_RELEASE);
        return false;
    }

    memcpy(g_orig, target, cfg.patchLen);
    g_target = target;
    g_len = cfg.patchLen;
    g_stub = stub;

    BYTE patch[16];
    memset(patch, 0x90, sizeof(patch));
    patch[0] = 0xE9;                                   // jmp rel32
    DWORD from = (DWORD)(DWORD_PTR)(target + 5);
    DWORD to = (DWORD)(DWORD_PTR)stub;
    DWORD rel = to - from;
    memcpy(patch + 1, &rel, 4);
    memcpy(target, patch, cfg.patchLen);

    DWORD tmp = 0;
    VirtualProtect(target, cfg.patchLen, oldProt, &tmp);
    FlushInstructionCache(GetCurrentProcess(), target, cfg.patchLen);

    g_active = true;
    Log("CdSpoof: sub_447450 @%#x 已改写 -> jmp %p（return 1）patchLen=%d",
        cfg.detectVA, stub, cfg.patchLen);
    Log("CdSpoof: 原字节 = %02X %02X %02X %02X %02X",
        g_orig[0], g_orig[1], g_orig[2], g_orig[3], g_orig[4]);
    Log("CdSpoof: ===== CD-ROM 校验已屏蔽（不再需要光盘）=====");
    return true;
}

void CdSpoofRemove()
{
    if (!g_active || !g_target) return;
    DWORD oldProt = 0;
    if (VirtualProtect(g_target, g_len, PAGE_EXECUTE_READWRITE, &oldProt)) {
        memcpy(g_target, g_orig, g_len);
        DWORD tmp = 0;
        VirtualProtect(g_target, g_len, oldProt, &tmp);
        FlushInstructionCache(GetCurrentProcess(), g_target, g_len);
        Log("CdSpoof: 已恢复 sub_447450 原始字节");
    }
    if (g_stub) { VirtualFree(g_stub, 0, MEM_RELEASE); g_stub = nullptr; }
    g_target = nullptr;
    g_len = 0;
    g_active = false;
}
