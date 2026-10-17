// wrapfix.cpp —— 长文本换行的 GBK 字符边界修复
//
// ════════════════════════════════════════════════════════════════════════
//  已验证的事实
// ════════════════════════════════════════════════════════════════════════
//
//  ① 症状：长中文换行后，第二行起整行乱码。
//     实验证实：在 COM.txt 的长中文里**插入半角空格**后，乱码完全消失，
//     且断行正好落在空格处。
//     → 证明：断行靠 `isspace` 回退；切点若落在 GBK 汉字两个字节中间，
//            第二行从尾字节开读，整行错位。
//
//  ② 原始回退循环（amat.exe 0x42F019 起 21 字节，反汇编实测）：
//        0x42F019  4B              dec  ebx        ; ebx = 源串指针
//        0x42F01A  4E              dec  esi        ; esi = 目标缓冲指针
//        0x42F01B  4F              dec  edi        ; edi = 已复制字节数
//        0x42F01C  78 10           js   loc_42F02E ; edi < 0 -> 放弃断行
//        0x42F01E  0F BE 0B        movsx ecx, byte [ebx]
//        0x42F021  51              push ecx
//        0x42F022  E8 A2 8E 0B 00  call _isspace
//        0x42F027  83 C4 04        add  esp, 4
//        0x42F02A  85 C0           test eax, eax
//        0x42F02C  74 EB           jz   loc_42F019 ; 非空白 -> 继续退
//        0x42F02E  85 FF           test edi, edi   ; <- 回退结束（我们跳这里）
//
//  ③ 三个寄存器必须**同步**增减：`ebx` 退 N 字节，`esi` 退 N 字节，
//     `edi` 减 N。三者一起退，等价于"把这 N 个字节从当前行撤掉"。
//
// ════════════════════════════════════════════════════════════════════════
//  修复策略（第三版）
// ════════════════════════════════════════════════════════════════════════
//
//  ② 反汇编复核后发现 **`0x42F019` 有两个入口**（这是前几版的关键遗漏）：
//
//        0x42EFF7  jge loc_42F019     ; 路径 A：宽度超限（cmp eax,ecx / jl 未跳）
//        0x42F017  jl  loc_42F063     ; 未超宽 -> 跳过回退块
//
//     路径 A 之外还有：
//        0x42EFEA  cmp  edi, 80h       ; edi = 已复制字节数
//        0x42EFF7  jge  loc_42F019    ; ★ 每满 128 字节就无条件进入回退块
//
//     → 所以 `0x42F019` 不只在"超宽"时执行，长文本每 128 字节也会走一次。
//        D4 实验（30 字 = 60 字节，远不到 128）本来不该进这里，
//        但它仍然崩溃，说明真正的问题在别处 —— 见下面的边界防御。
//
//  ③ 崩溃根因分析：
//     `ebx` 是**源串**（malloc 副本），`esi` 是**目标栈缓冲**，两者不同。
//     回退时 `dec ebx` 会一路退到源串开头；一旦再退 1，`[ebx-1]`
//     就读到 malloc 块头**之前**的内存 —— 若那里是不可读页就直接崩。
//
//     原版只做 `isspace(*ebx)`，而 isspace 内部会先 `movzx`，再拿 eax
//     索引 __ctype 表 —— 读的是 `[ebx]`（仍在块内），所以原版不会崩。
//     ★ 而我的对齐检查读的是 `[ebx-1]`，这才是越界的来源。
//
//     修法：在读 `[ebx-1]` 之前，必须确认 **ebx 仍在源串范围内**。
//     可用的可靠信号就是 `edi`：它是"本行已复制字节数"，
//     `edi >= 1` 表示至少还有 1 个字节属于本行，此时 `[ebx-1]` 必然
//     落在源串块内（因为那 1 个字节就在 `[ebx]` 上，它的前一个字节
//     要么是同一行更早的字节，要么是该行的 '^'前缀/颜色字节，
//     都在有效范围内）。
//     → 所以 `edi <= 0` 跳 done 是**必需**的，且不能提前退出循环。
// ════════════════════════════════════════════════════════════════════════
#include "pch.h"
#include "wrapfix.h"
#include "log.h"

static BYTE* g_target = nullptr;
static BYTE  g_orig[32] = {0};
static int   g_len = 0;
static void* g_stub = nullptr;
static bool  g_active = false;

bool WrapFixIsActive() { return g_active; }

// ════════════════════════════════════════════════════════════════════════
//  诊断：sub_42EF50 的输入/输出
//
//  ★ 这段是为了回答一个具体问题：**这条字幕到底断成了几行、每行是什么字节**
//    之前几轮都在改回退循环，但症状一字不变，说明
//    「0x42F019 那段回退循环」很可能根本不参与 backyard1 这条字幕的断行。
//    与其继续猜，不如把真实数据打出来。
//
//  布局（IDA 实测）：
//    入口 0x42EF50：sub esp,0x90 / push ebx,ebp,esi / mov esi,[esp+0xA4]（文本）
//                    / mov ebp,ecx（this） / push edi
//      → 入口时 [esp+0x90] = 返回地址，[esp+0x94] = 保存的 edi，
//        [esp+0x98]=esi, [esp+0x9C]=ebp, [esp+0xA0]=ebx,
//        [esp+0xA4]=arg_0(文本), [esp+0xA8]=arg_4(颜色)
//      → ecx = this
//    返回前 0x42F149：pop ebx（随后 pop esi? 实测顺序 ebx/esi/ebp/edi 逆序）
//
//    行数组：this + 88，每行 129 字节，共 16 行
//    行数：  this + 571（*(this+571) 是"下一行索引"，从 1 开始）
//            this + 574 是已写入行数
// ════════════════════════════════════════════════════════════════════════

// 把一段 GBK/ASCII 混合缓冲转成可打印形式（非 GBK 字节用 . 表示）
static std::string DumpBytes(const BYTE* p, int n)
{
    std::string out;
    char buf[8];
    for (int i = 0; i < n; i++) {
        if (p[i] >= 0x20 && p[i] < 0x7F) {
            out += (char)p[i];
        } else {
            _snprintf_s(buf, sizeof(buf), _TRUNCATE, "%02X", p[i]);
            out += '['; out += buf; out += ']';
        }
        if (i + 1 < n) out += ' ';
    }
    return out;
}

static volatile LONG g_diagCalls = 0;

static void __cdecl DiagIn(void* thisPtr, const char* text, int color)
{
    LONG n = InterlockedIncrement(&g_diagCalls);
    // 只打印含高位字节（中文）的输入，避免英文刷屏
    bool cjk = false;
    if (text) {
        for (const unsigned char* p = (const unsigned char*)text; *p; p++)
            if (*p > 0x7F) { cjk = true; break; }
    }
    if (!cjk) return;
    int len = text ? (int)strlen(text) : 0;
    Log("[DIAG] #%ld sub_42EF50 IN  this=%p color=%#x len=%d", n, thisPtr, color, len);
    Log("[DIAG]   raw = %s", DumpBytes((const BYTE*)text, len > 200 ? 200 : len).c_str());
}

static void __cdecl DiagOut(void* thisPtr)
{
    BYTE* base = (BYTE*)thisPtr;
    // 行数组在 this+88；行数字段在 this+571（下一行索引）与 this+574（已写行数）
    int nextLine = *(int*)(base + 571 * 4);
    int written  = *(int*)(base + 574 * 4);
    Log("[DIAG] sub_42EF50 OUT this=%p 行数(571*4)=%d 已写(574*4)=%d",
        thisPtr, nextLine, written);
    int show = (written > 0 && written < 20) ? written : 0;
    for (int i = 0; i < show; i++) {
        const BYTE* line = base + 88 + 129 * i;
        int len = 0;
        while (len < 128 && line[len]) len++;
        Log("[DIAG]   行%d len=%d  %s", i, len, DumpBytes(line, len > 80 ? 80 : len).c_str());
    }
}

// 构建 trampoline
//
// ★ 全部跳转用相对位移，代码位置无关。
// ★ 调用游戏自己的 _isspace（0x4E7EC9），不要用 GetProcAddress：
//     系统 msvcrt.dll 里同名符号地址不同，调用契约不符会导致卡死。
static void* BuildStub(DWORD doneVA)
{
    BYTE* p = (BYTE*)VirtualAlloc(nullptr, 256, MEM_COMMIT | MEM_RESERVE,
                                  PAGE_EXECUTE_READWRITE);
    if (!p) {
        Log("WrapFix: trampoline 分配失败 (%lu)", GetLastError());
        return nullptr;
    }

    int n = 0;
    int labelLoop = -1, labelAlign = -1, labelDone = -1;
    int fix32_a = 0, fix32_b = 0, fix8_a = 0;

    // ── loop: 逐字节回退找空白（与原版完全一致）──
    labelLoop = n;
    p[n++] = 0x4B;                          // dec ebx
    p[n++] = 0x4E;                          // dec esi
    p[n++] = 0x4F;                          // dec edi
    // js done
    p[n++] = 0x0F; p[n++] = 0x88;
    fix32_a = n; n += 4;

    // movzx ecx, byte [ebx]   ← 用无符号，避免负值喂 _isspace
    p[n++] = 0x0F; p[n++] = 0xB6; p[n++] = 0x0B;
    p[n++] = 0x51;                           // push ecx
    // call _isspace（游戏内副本）
    p[n++] = 0xB8;
    {
        DWORD isspaceAddr = 0x004E7EC9;
        memcpy(p + n, &isspaceAddr, 4); n += 4;
    }
    p[n++] = 0xFF; p[n++] = 0xD0;            // call eax
    p[n++] = 0x83; p[n++] = 0xC4; p[n++] = 0x04;  // add esp, 4
    p[n++] = 0x85; p[n++] = 0xC0;            // test eax, eax
    // jz loop
    p[n++] = 0x0F; p[n++] = 0x84;
    fix32_b = n; n += 4;

    // ── 到这里已停在空白上，做字符边界对齐 ──
    labelAlign = n;
    // edi <= 0 时 ebx 已在行首，不能再读 [ebx-1] -> 直接 done
    p[n++] = 0x85; p[n++] = 0xFF;            // test edi, edi
    p[n++] = 0x7E;                           // jle done(短跳)
    fix8_a = n; n += 1;

    // cmp byte [ebx], 0x40      ; GBK 尾字节下界
    p[n++] = 0x80; p[n++] = 0x3B; p[n++] = 0x40;
    p[n++] = 0x7C;                           // jl done(短跳)
    int jl1 = n; n += 1;

    // mov al, [ebx-1]
    p[n++] = 0x8A; p[n++] = 0x43; p[n++] = 0xFF;
    // cmp al, 0x81
    p[n++] = 0x3C; p[n++] = 0x81;
    p[n++] = 0x7C;                           // jl done(短跳)
    int jl2 = n; n += 1;

    // cmp al, 0xFE
    p[n++] = 0x3C; p[n++] = 0xFE;
    p[n++] = 0x77;                           // ja done(短跳)
    int ja1 = n; n += 1;

    // ★ 是 GBK 尾字节 -> 把整个汉字挪到下一行
    p[n++] = 0x4B;                          // dec ebx
    p[n++] = 0x4E;                          // dec esi
    p[n++] = 0x4F;                          // dec edi
    // js done（可能退过头）
    p[n++] = 0x0F; p[n++] = 0x88;
    int fix32_c = n; n += 4;

    // ── done ──
    labelDone = n;
    p[n++] = 0xB8;                          // mov eax, doneVA
    memcpy(p + n, &doneVA, 4); n += 4;
    p[n++] = 0xFF; p[n++] = 0xE0;            // jmp eax

    // ── 回填 ──
    auto f32 = [&](int off, int lbl) {
        int rel = lbl - (off + 4);
        memcpy(p + off, &rel, 4);
    };
    auto f8 = [&](int off, int lbl) {
        int rel = lbl - (off + 1);
        if (rel < -128 || rel > 127) {
            Log("WrapFix: 短跳转越界 %d（设计错误）", rel);
            rel = 0;
        }
        p[off] = (BYTE)(rel & 0xFF);
    };

    f32(fix32_a, labelDone);   // js done
    f32(fix32_b, labelLoop);   // jz loop
    f32(fix32_c, labelDone);   // js done（对齐后退过头）
    f8(fix8_a, labelDone);     // jle done
    f8(jl1, labelDone);        // jl done
    f8(jl2, labelDone);        // jl done
    f8(ja1, labelDone);        // ja done

    Log("WrapFix: trampoline %p, %d 字节", p, n);
    Log("WrapFix:   loop=%d align=%d done=%d", labelLoop, labelAlign, labelDone);
    FlushInstructionCache(GetCurrentProcess(), p, n);
    return p;
}

bool WrapFixInstall(const WrapFixConfig& cfg)
{
    Log("WrapFix: ===== 安装换行汉字边界修复 =====");

    if (!cfg.rollbackVA || !cfg.doneVA || cfg.patchLen < 5 || cfg.patchLen > 32) {
        Log("WrapFix: 配置不完整，跳过");
        return false;
    }

    BYTE* base = (BYTE*)GetModuleHandleA(nullptr);
    DWORD imgBase = (DWORD)(DWORD_PTR)base;
    if (!base || cfg.rollbackVA < imgBase) {
        Log("WrapFix: 模块基址异常，跳过");
        return false;
    }
    BYTE* target = base + (cfg.rollbackVA - imgBase);
    BYTE* doneP  = base + (cfg.doneVA - imgBase);

    if (cfg.sigLen <= 0 || cfg.sigLen > (int)sizeof(cfg.sig)) {
        Log("WrapFix: 签名长度非法 (%d)，跳过", cfg.sigLen);
        return false;
    }
    for (int i = 0; i < cfg.sigLen; i++) {
        if (!cfg.sigMask[i]) continue;
        if (target[i] != cfg.sig[i]) {
            Log("WrapFix: 签名不匹配 @+%d: 期望 %02X 实得 %02X，拒绝安装",
                i, cfg.sig[i], target[i]);
            return false;
        }
    }

    void* stub = BuildStub((DWORD)(DWORD_PTR)doneP);
    if (!stub) return false;

    DWORD oldProt = 0;
    if (!VirtualProtect(target, cfg.patchLen, PAGE_EXECUTE_READWRITE, &oldProt)) {
        Log("WrapFix: VirtualProtect 失败 (%lu)", GetLastError());
        VirtualFree(stub, 0, MEM_RELEASE);
        return false;
    }

    memcpy(g_orig, target, cfg.patchLen);
    g_target = target;
    g_len = cfg.patchLen;
    g_stub = stub;

    BYTE patch[32];
    memset(patch, 0x90, sizeof(patch));
    patch[0] = 0xE9;
    DWORD from = (DWORD)(DWORD_PTR)(target + 5);
    DWORD to = (DWORD)(DWORD_PTR)stub;
    DWORD rel = to - from;
    memcpy(patch + 1, &rel, 4);
    memcpy(target, patch, cfg.patchLen);

    DWORD tmp = 0;
    VirtualProtect(target, cfg.patchLen, oldProt, &tmp);
    FlushInstructionCache(GetCurrentProcess(), target, cfg.patchLen);

    g_active = true;
    Log("WrapFix: %#x 已替换 -> jmp %p（patchLen=%d）",
        cfg.rollbackVA, stub, cfg.patchLen);
    Log("WrapFix: 原字节 = %02X %02X %02X %02X %02X ...",
        g_orig[0], g_orig[1], g_orig[2], g_orig[3], g_orig[4]);
    Log("WrapFix: ===== 换行将按 GBK 字符边界回退 =====");
    return true;
}

void WrapFixRemove()
{
    if (!g_active || !g_target) return;
    DWORD oldProt = 0;
    if (VirtualProtect(g_target, g_len, PAGE_EXECUTE_READWRITE, &oldProt)) {
        memcpy(g_target, g_orig, g_len);
        DWORD tmp = 0;
        VirtualProtect(g_target, g_len, oldProt, &tmp);
        FlushInstructionCache(GetCurrentProcess(), g_target, g_len);
        Log("WrapFix: 已恢复原始字节");
    }
    if (g_stub) { VirtualFree(g_stub, 0, MEM_RELEASE); g_stub = nullptr; }
    g_target = nullptr;
    g_len = 0;
    g_active = false;
}