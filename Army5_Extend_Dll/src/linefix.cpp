// linefix.cpp —— 长文本分行"多写一行"的修复（v3）
//
// ════════════════════════════════════════════════════════════════════════
//  原始控制流（amat.exe sub_42EF50，IDA 反汇编 + 字节核对）
// ════════════════════════════════════════════════════════════════════════
//
//   0x42F067  cmp  byte [ebx], 0     ; *v5 == 0 ?
//   0x42F06A  jz   0x42F074          ; ★ 源串结束 -> 也去写行（bug）
//   0x42F06C  test al, al            ; al = v9 = 本轮是否断行
//   0x42F06E  jz   0x42F130          ; 没断行 -> 回 while 继续累积
//   ---- 以下是"写一行" ----
//   0x42F074  mov  edx, [ebp+8ECh]    ; 行索引
//   0x42F07F  inc  edx
//   0x42F082  mov  [ebp+8ECh], edx    ; 行数+1（封顶 16，超出则整体上滚）
//   0x42F0FE  rep movsd / movsb      ; strcpy(&lines[n], &v20)
//   0x42F10E  xor  edi, edi           ; ---- 写行后的初始化 ----
//   0x42F110  lea  esi, [var_84]
//   0x42F118  mov  [var_84], 5Eh      ; '^'
//   0x42F11D  mov  [var_83], al       ; 颜色
//   0x42F125  mov  edi, 2
//   0x42F12A  inc  [ebp+8F8h]         ; 行高累加
//   0x42F130  cmp  byte [ebx], 0      ; ---- while 条件 ----
//   0x42F133  jnz  0x42EFDE           ; 继续累积
//   0x42F139  mov  ebx, [var_88]      ; 收尾（free + ret）
//
//  ★ 0x42F130 是 while 条件，0x42F10E..0x42F12A 是"写完一行后的初始化"。
//    两者**不是一回事**，不能混用。
//  ★ ebx 在 0x42F0CF 被重载（`mov ebx,[var_8C]`），所以壳里读 [ebx]
//    必须在**调用点当刻**读，不能缓存。
//
// ════════════════════════════════════════════════════════════════════════
//  三条路径的正确目标
// ════════════════════════════════════════════════════════════════════════
//
//   ① 源串已结束（*v5 == 0）
//        原版 -> 0x42F074 写一行  ★ BUG：写的是未初始化的堆内存
//        现在 -> 直接回 while 条件 0x42F130（*v5==0 -> 走 0x42F139 收尾）
//                ★ 不写行、行数不 +1
//
//   ② 未断行（al == 0）
//        原版 -> 0x42F130（继续累积）
//        现在 -> 0x42F130（**完全不变**）
//         ★★ 上一版错误地也把它跳去了 0x42F10E，等于每个字符都触发
//            一次写行，行数暴涨到 16 后还继续上滚，最终越界崩溃。
//
//   ③ 真断行（al == 1）
//        原版 -> 落到 0x42F074 写行
//        现在 -> 0x42F074（**完全不变**）
//
//  所以修正只有一件事：**把"源串已结束"这条路径从 0x42F074 改到 0x42F130**。
//  另外两条保持原样。
//
// ════════════════════════════════════════════════════════════════════════
//  trampoline 设计
// ════════════════════════════════════════════════════════════════════════
//
//   替换 0x42F06A 起 8 字节：
//      74 08        jz  0x42F074      (2)
//      84 C0        test al, al       (2)
//      0F 84 BC 00  jz  0x42F130      (4)
//
//   壳逻辑（按顺序判定，命中即走）：
//       if (*ebx == 0)   -> jmp 0x42F130     ; 源串结束：不写行，回 while
//       if (al == 0)     -> jmp 0x42F130     ; 未断行：与原版一致
//       else             -> jmp 0x42F074     ; 真断行：与原版一致
//
//   ★ 三个出口全部是 jmp 绝对地址，不依赖相对位移，位置无关。
//   ★ 壳只读 [ebx] 和 al，不修改任何寄存器。
//   ★ 8 字节 patch：E9 rel32(5) + 3 × NOP，落在指令边界。
// ════════════════════════════════════════════════════════════════════════
#include "pch.h"
#include "linefix.h"
#include "log.h"

static BYTE* g_target = nullptr;
static BYTE  g_orig[16] = {0};
static int   g_len = 0;
static void* g_stub = nullptr;
static bool  g_active = false;

bool LineFixIsActive() { return g_active; }

// 壳：
//   cmp  byte [ebx], 0
//   jz   L_done            ; 源串结束 -> while
//   test al, al
//   jz   L_done            ; 未断行   -> while（与原版一致）
//   jmp  writeRowVA        ; 真断行   -> 写行（与原版一致）
// L_done:
//   jmp  loopTopVA         ; 0x42F130
static void* BuildStub(DWORD loopTopVA, DWORD writeRowVA)
{
    BYTE* p = (BYTE*)VirtualAlloc(nullptr, 256, MEM_COMMIT | MEM_RESERVE,
                                  PAGE_EXECUTE_READWRITE);
    if (!p) {
        Log("LineFix: trampoline 分配失败 (%lu)", GetLastError());
        return nullptr;
    }

    int n = 0;
    int lblDone = -1, fixA = 0, fixB = 0, fixC = 0, fixD = 0;

    // cmp byte [ebx], 0
    p[n++] = 0x80; p[n++] = 0x3B; p[n++] = 0x00;
    // jz L_done
    p[n++] = 0x0F; p[n++] = 0x84;
    fixA = n; n += 4;

    // test al, al
    p[n++] = 0x84; p[n++] = 0xC0;
    // jz L_done
    p[n++] = 0x0F; p[n++] = 0x84;
    fixB = n; n += 4;

    // jmp writeRowVA（真断行）
    p[n++] = 0xE9;
    fixC = n; n += 4;

    // L_done: jmp loopTopVA
    lblDone = n;
    p[n++] = 0xE9;
    fixD = n; n += 4;

    // ★★★ 关键（v1/v2/v3 崩溃的同一个根因）★★★
//    off  是「壳内偏移」（相对 p），target 是「目标绝对地址」。
//    rel 必须是 (绝对目标 - 绝对下一条指令)，
//    即 (BYTE*)target - (p + off + 4)，**绝不能**写成 target - (off + 4)。
//
//    上一版漏了 p：短跳转 jz 的目标是壳内地址，p 与偏移里的 p 抵消，
//    碰巧正确；但两个 jmp 的目标是游戏绝对地址（0x42F074 / 0x42F130），
//    rel 被算成 0x42F074-22=0x42F062，实际落点变成
//    stub+0x42F062 ≈ 0x0339F078 —— 未映射内存，必崩。
//    三条路径都以 jmp 收尾，所以每次调用都崩，崩溃点恒定。
    auto f32 = [&](int off, const BYTE* target) {
        int rel = (int)(DWORD_PTR)target - (int)(DWORD_PTR)(p + off + 4);
        memcpy(p + off, &rel, 4);
    };
    f32(fixA, p + lblDone);      // 源串结束 / 未断行 -> L_done
    f32(fixB, p + lblDone);      // 同上
    f32(fixC, (const BYTE*)(DWORD_PTR)writeRowVA);  // 真断行 -> 0x42F074
    f32(fixD, (const BYTE*)(DWORD_PTR)loopTopVA);   // L_done    -> 0x42F130

    // ★ 写完立即回读校验：反解出三个出口的实际落点并打印。
    //   之前三轮就是因为「只在地址 0 的假壳上用 capstone 看过」，
    //   真实落点从没被验证过。这里改成验证**实际分配地址**下的结果。
    {
        auto readRel = [&](int off) -> int {
            int v = 0; memcpy(&v, p + off, 4); return v;
        };
        DWORD dstA = (DWORD)(p + fixA + 4 + readRel(fixA));
        DWORD dstB = (DWORD)(p + fixB + 4 + readRel(fixB));
        DWORD dstC = (DWORD)(p + fixC + 4 + readRel(fixC));
        DWORD dstD = (DWORD)(p + fixD + 4 + readRel(fixD));
        Log("LineFix: 实际落点 源串结束->%#x 未断行->%#x 真断行->%#x L_done->%#x",
            dstA, dstB, dstC, dstD);
        bool ok = (dstA == (DWORD)(DWORD_PTR)(p + lblDone))
               && (dstB == (DWORD)(DWORD_PTR)(p + lblDone))
               && (dstC == writeRowVA)
               && (dstD == loopTopVA);
        Log("LineFix: 落点校验 %s（期望 %p / %p / %#x / %#x）",
            ok ? "通过" : "**失败，拒绝安装**",
            (void*)(p + lblDone), (void*)(p + lblDone), writeRowVA, loopTopVA);
        if (!ok) {
            VirtualFree(p, 0, MEM_RELEASE);
            return nullptr;
        }
    }

    Log("LineFix: trampoline %p, %d 字节（loopTop=%#x writeRow=%#x）",
        p, n, loopTopVA, writeRowVA);
    FlushInstructionCache(GetCurrentProcess(), p, n);
    return p;
}

bool LineFixInstall(const LineFixConfig& cfg)
{
    Log("LineFix: ===== 安装『多写一行』修复（v3）=====");

    if (!cfg.siteVA || cfg.patchLen < 5 || cfg.patchLen > 16) {
        Log("LineFix: 配置不完整，跳过");
        return false;
    }

    BYTE* base = (BYTE*)GetModuleHandleA(nullptr);
    DWORD imgBase = (DWORD)(DWORD_PTR)base;
    if (!base || cfg.siteVA < imgBase) {
        Log("LineFix: 模块基址异常，跳过");
        return false;
    }
    BYTE* target = base + (cfg.siteVA - imgBase);

    if (cfg.sigLen <= 0 || cfg.sigLen > (int)sizeof(cfg.sig)) {
        Log("LineFix: 签名长度非法 (%d)", cfg.sigLen);
        return false;
    }
    for (int i = 0; i < cfg.sigLen; i++) {
        if (target[i] != cfg.sig[i]) {
            Log("LineFix: 签名不匹配 @+%d: 期望 %02X 实得 %02X，拒绝安装",
                i, cfg.sig[i], target[i]);
            return false;
        }
    }

    void* stub = BuildStub(cfg.loopTopVA, cfg.writeRowVA);
    if (!stub) return false;

    DWORD oldProt = 0;
    if (!VirtualProtect(target, cfg.patchLen, PAGE_EXECUTE_READWRITE, &oldProt)) {
        Log("LineFix: VirtualProtect 失败 (%lu)", GetLastError());
        VirtualFree(stub, 0, MEM_RELEASE);
        return false;
    }

    memcpy(g_orig, target, cfg.patchLen);
    g_target = target;
    g_len = cfg.patchLen;
    g_stub = stub;

    BYTE patch[16];
    memset(patch, 0x90, sizeof(patch));
    patch[0] = 0xE9;
    DWORD rel = (DWORD)(DWORD_PTR)stub - (DWORD)(DWORD_PTR)(target + 5);
    memcpy(patch + 1, &rel, 4);
    memcpy(target, patch, cfg.patchLen);

    DWORD tmp = 0;
    VirtualProtect(target, cfg.patchLen, oldProt, &tmp);
    FlushInstructionCache(GetCurrentProcess(), target, cfg.patchLen);

    g_active = true;
    Log("LineFix: %#x 已替换 -> jmp %p（patchLen=%d）",
        cfg.siteVA, stub, cfg.patchLen);
    Log("LineFix: 原字节 = %02X %02X %02X %02X %02X %02X %02X %02X",
        g_orig[0], g_orig[1], g_orig[2], g_orig[3],
        g_orig[4], g_orig[5], g_orig[6], g_orig[7]);
    Log("LineFix: 仅『源串结束』改走 while；未断行/真断行保持原样");
    return true;
}

void LineFixRemove()
{
    if (!g_active || !g_target) return;
    DWORD oldProt = 0;
    if (VirtualProtect(g_target, g_len, PAGE_EXECUTE_READWRITE, &oldProt)) {
        memcpy(g_target, g_orig, g_len);
        DWORD tmp = 0;
        VirtualProtect(g_target, g_len, oldProt, &tmp);
        FlushInstructionCache(GetCurrentProcess(), g_target, g_len);
        Log("LineFix: 已恢复原始字节");
    }
    if (g_stub) { VirtualFree(g_stub, 0, MEM_RELEASE); g_stub = nullptr; }
    g_target = nullptr;
    g_len = 0;
    g_active = false;
}
