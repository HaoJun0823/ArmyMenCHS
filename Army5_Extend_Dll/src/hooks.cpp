#include "pch.h"
#include "hooks.h"
#include "log.h"
#include "target.h"
#include "hzk16.h"
#include "renderer.h"
#include "cdspoof.h"
#include "wrapfix.h"
#include "linefix.h"
#include "wrapcjk.h"

#include <string>
#include <cstdio>

static HMODULE g_hModule = nullptr;
Hzk16Font* g_pFont = nullptr;      // renderer.cpp 引用

void SetModuleHandle(HMODULE h) { g_hModule = h; }

// ── 找 Hzk16 ────────────────────────────────────────────────────────────
//
// ★ 本作**没有**官方中文版（已全盘搜索 amat.exe，无 Hzk16 / RSE\x1a），
//   所以游戏目录里不会自带字库，必须随补丁一起发布。
//   因此候选位置按"补丁优先"排：
//     1) <DLL 目录>\Hzk16             （scripts\Hzk16，跟补丁放一起，最稳）
//     2) <DLL 目录>\..\Hzk16
//     3) <exe 目录>\Hzk16
//     4) <exe 目录>\..\Hzk16
//   不去猜运行时 CWD（2 代的教训：官方那套 "..\Hzk16" 相对路径依赖 CWD）。
static bool FindHzk16(wchar_t* out, size_t cch, std::string& tried)
{
    wchar_t dllDir[MAX_PATH] = {0};
    if (!LogGetDllDir(dllDir, MAX_PATH)) return false;

    wchar_t exePath[MAX_PATH] = {0};
    GetModuleFileNameW(nullptr, exePath, MAX_PATH);
    wchar_t* slash = wcsrchr(exePath, L'\\');
    std::wstring exeDir = slash ? std::wstring(exePath, slash - exePath) : L".";

    std::wstring cands[4] = {
        std::wstring(dllDir) + L"Hzk16",           // scripts\Hzk16
        std::wstring(dllDir) + L"..\\Hzk16",       // scripts\..\Hzk16
        exeDir + L"\\Hzk16",                        // <game>\Hzk16
        exeDir + L"\\..\\Hzk16",                    // <game>\..\Hzk16
    };
    for (int i = 0; i < 4; i++) {
        DWORD a = GetFileAttributesW(cands[i].c_str());
        if (a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY)) {
            wcsncpy_s(out, cch, cands[i].c_str(), _TRUNCATE);
            return true;
        }
        char u8[MAX_PATH * 3] = {0};
        WideCharToMultiByte(CP_UTF8, 0, cands[i].c_str(), -1, u8, sizeof(u8), 0, 0);
        tried += "  tried: ";
        tried += u8;
        tried += "\n";
    }
    return false;
}

static bool g_installed = false;

bool InstallAll()
{
    Log("===== Army Men: Air Tactics CHS 启动 =====");

    // ① 识别目标
    GameProfile gp;
    if (!Target::Detect(gp)) {
        Log("InstallAll: 目标识别失败 -> 不安装任何 hook（fail-closed）");
        return false;
    }
    LogSetGameTag(gp.logTag.c_str());
    Log("InstallAll: 适配档位 = %s", gp.id.c_str());

    // ② 载入字库
    //
    // ★ 顺序说明：先载字库再装 hook。因为渲染 hook 一旦装上，任何一次
    //   CJK 绘制都会用到 g_pFont；若此时字库还没就绪，g_pFont 为 null，
    //   我们的实现会走"跳过汉字"分支（安全，但不显示中文）。
    //   先准备好可以让第一批绘制就正确。
    static Hzk16Font font;
    wchar_t fontPath[MAX_PATH] = {0};
    std::string tried;
    if (FindHzk16(fontPath, MAX_PATH, tried)) {
        if (font.Load(fontPath)) {
            g_pFont = &font;
            Log("InstallAll: 字库 OK -> %ls", fontPath);
            std::string rep;
            int rc = font.SelfTest(rep);
            Log("InstallAll: 字库自检 rc=%d\n%s", rc, rep.c_str());
        } else {
            Log("InstallAll: 字库载入失败 -> %ls", fontPath);
        }
    } else {
        Log("InstallAll: !! 找不到 Hzk16，中文将无法显示\n%s", tried.c_str());
    }

    // ②' CD-ROM 校验屏蔽
    //
    // ★ 位置很关键：必须**早于任何资源读取**。
    //   游戏在 _WinMain 早期就调 sub_447450，一旦它返回 0 会直接结束进程；
    //   我们是在 InitializeASI 阶段（DLL 加载完、游戏代码还没跑到那里）
    //   就把入口改写掉，所以来得及。
    //
    // ★ 即使渲染 hook 最终失败，这一项也应该独立生效 ——
    //   它和汉化无关，是"能不能启动"的问题。所以放在字库/渲染之前。
    {
        CdSpoofConfig cdc;
        cdc.detectVA      = gp.cdDetectVA;
        cdc.rootBufVA     = gp.cdRootBufVA;
        cdc.readyFlagVA   = gp.cdReadyFlagVA;
        cdc.readyFlag2VA  = gp.cdReadyFlag2VA;
        cdc.patchLen      = gp.cdDetectPatchLen;
        cdc.rootBufSize   = 256;          // byte_671288 实测容量
        cdc.logTag        = gp.logTag;
        memcpy(cdc.cdDetectSig, gp.cdDetectSig, sizeof(cdc.cdDetectSig));
        memcpy(cdc.cdDetectSigMask, gp.cdDetectSigMask, sizeof(cdc.cdDetectSigMask));
        cdc.cdDetectSigLen = gp.cdDetectSigLen;
        if (CdSpoofInstall(cdc)) {
            Log("InstallAll: CD-ROM 校验屏蔽完成");
        } else {
            Log("InstallAll: CD-ROM 校验屏蔽未生效（游戏仍需要光盘才能启动）");
        }
    }

    // ③ 装 hook
    RendererEnv env;
    env.blitVA        = gp.blitVA;
    env.rectVA        = gp.rectVA;
    env.atlasOffsetVA = gp.atlasOffsetVA;
    env.atlasBaseVA   = gp.atlasBaseVA;
    env.charWidthVA   = gp.charWidthVA;
    env.clipRectVA    = gp.clipRectVA;
    env.rcVA          = gp.rcVA;
    env.lockedSurfVA  = gp.lockedSurfVA;
    env.primarySurfVA = gp.primarySurfVA;
    env.enabledVA     = gp.enabledVA;
    env.dispWVA       = gp.dispWVA;
    env.dispHVA       = gp.dispHVA;
    env.surfaceVA     = gp.surfaceVA;
    env.pitchVA       = gp.pitchVA;
    env.atlasSizeVA   = gp.atlasSizeVA;
    env.fontCount     = gp.fontCount;
    RendererSetEnv(env);

    // ★ probeOnly 档位：只做"识别 + 记录"，不接管渲染。
    //   它不读任何全局量，所以**必须先于自检**返回 —— 否则会因为
    //   该档位没填 rc/enabled 等字段而被自检挡下，连识别都验证不了。
    //
    //   ★ 本作的探针是**只读**的：序言不是 2 代那种 5 字节 mov eax,[imm32]，
    //     硬写标记会破坏栈帧。
    if (gp.probeOnly) {
        // ★ rendererVA 是**绝对 VA**（IDA 显示值），不能再加模块基址 ——
        //   加了就变成 base+0x488640 的野地址，读出越界字节。
        //   （2 代该字段存的是 RVA，这里语义不同，是本文件最容易踩反的一处。）
        BYTE* probed = (BYTE*)(DWORD_PTR)gp.rendererVA;
        Log("InstallAll: 该档位标记为 probeOnly —— 只做识别验证，不接管渲染");
        bool poked = RendererProbeAt(gp.rendererVA, probed, 5);
        Log("InstallAll -> probe=%d（无任何内存改动；这是刻意的）", (int)poked);
        return false;
    }

    // ★ 安装前自检全局量（把"地址语义搞错"在装 hook 前就拦下）
    {
        std::string rep;
        if (!RendererValidateEnv(&rep)) {
            Log("InstallAll: !! 渲染环境自检失败，拒绝安装（游戏保持英文，但不会崩）%s",
                rep.c_str());
            return false;
        }
        Log("InstallAll: 渲染环境自检通过%s", rep.c_str());
    }

    BYTE* base = (BYTE*)GetModuleHandleA(nullptr);

    // ★★ 逐个安装**全部 4 个** hook 目标：
    //    2 个绘制（LEFT/DIALOG）+ 2 个测量（宽 / 高-3）。
    //    ★ 本作**没有 CENTER**（4/3 代都有），只有 4 个目标。
    //    ★ GRADIENT（sub_488B90）刻意不装：它用另一套单字节字体，
    //      中文永远不走它，接管它只增加风险。
    //    2 代的教训：只装左对齐会导致对话框文字完全不显示；
    //    漏装测量函数会导致上层拿错宽度当裁剪矩形 -> 花屏。
    int hookOk = 0, hookFail = 0;
    for (const HookSite& h : gp.hooks) {
        if (h.rva == 0) continue;
        bool r = RendererInstallAt(h.rva, (int)h.kind, base + h.rva, 5, h.patchLen);
        if (r) hookOk++; else hookFail++;
    }
    Log("InstallAll: hook 成功 %d 个，失败 %d 个", hookOk, hookFail);
    bool hooked = (hookOk > 0);

    // ★★ 造 stub（原始函数副本）。
    //    我们的实现里 ASCII 段要转调"原始行为"，但入口已被 jmp 覆盖，
    //    所以必须在写 jmp **之后**、使用之前构造 stub。
    //    失败则 ASCII 段不会绘制（保持安全，不会花屏）。
    if (hooked) {
        if (RendererBuildStubs()) {
            Log("InstallAll: stub 构造完成（ASCII 段将转调原始实现）");
        } else {
            Log("InstallAll: !! stub 构造失败 —— ASCII 段将不绘制（安全降级）");
        }
    }

    // ⑤ 长文本换行的汉字边界修复
    //
    // ★ 当前默认关闭（gp.wrapEnabled == false）。
    //   改了 sub_42EF50 的回退循环三轮，症状一字不变：
    //     · 乱码仍在
    //     · 且引入"对话为空 + 卡死"
    //   D4 实验（30 字、60 字节、远未到 128 字节硬上限）仍然崩溃，
    //   说明这条字幕的乱码/崩溃与这个回退循环无关。
    //   先拿一个不含 WrapFix 的稳定基线，再用 x32dbg 抓真实字节流。
    if (gp.wrapEnabled) {
        WrapFixConfig wc;
        wc.rollbackVA = gp.wrapRollbackVA;
        wc.doneVA     = gp.wrapDoneVA;
        wc.patchLen   = gp.wrapPatchLen;
        wc.logTag     = gp.logTag;
        memcpy(wc.sig, gp.wrapSig, sizeof(wc.sig));
        memcpy(wc.sigMask, gp.wrapSigMask, sizeof(wc.sigMask));
        wc.sigLen = gp.wrapSigLen;
        if (WrapFixInstall(wc)) {
            Log("InstallAll: 换行汉字边界修复完成");
        } else {
            Log("InstallAll: 换行汉字边界修复未生效（长文本换行仍可能乱码）");
        }
    } else {
        Log("InstallAll: 换行汉字边界修复**已禁用**"
            "（实测无效且会引入卡死，待用调试器定位真正成因后再启用）");
    }

    // ⑥ 长文本分行"多写一行"的修复
    //
    // ★ 已禁用。这一系列（v1..v4）从未被验证为有效：
    //   改的是「源串结束也去写行」，但真正的乱码源是下面的 ⑦。
    //   保留代码只为将来对照，默认不装。
    if (gp.lineFixEnabled) {
        LineFixConfig lf;
        lf.siteVA     = gp.lineSiteVA;
        lf.loopTopVA  = gp.lineLoopTopVA;
        lf.writeRowVA = gp.lineWriteRowVA;
        lf.patchLen   = gp.linePatchLen;
        lf.logTag     = gp.logTag;
        memcpy(lf.sig, gp.lineSig, sizeof(lf.sig));
        lf.sigLen = gp.lineSigLen;
        if (LineFixInstall(lf)) {
            Log("InstallAll: 分行『多写一行』修复完成");
        } else {
            Log("InstallAll: 分行修复未生效（长文本换行仍会乱码）");
        }
    }

    // ⑦ CJK 长文本换行修复 —— 真正的乱码/不显示解
    //
    // 根因（IDA 全量反汇编 0x42EF50..0x42F150）：
    //   sub_42EF50 塞满一行后回退找**空格**（_isspace）。中文没有空格，
    //   一路退到 edi<=0，0x42F034 `jle 0x42F139` 直接跳出整个函数，
    //   剩余文字一行都不写。行数组残留旧内容 + 未初始化堆 -> 乱码/不显示。
    //
    // 修法：在入口按框宽在 GBK 边界插空格，让它的断行逻辑正常工作。
    //       ASCII 串、未超宽的串完全原样放行。
    if (gp.wrapCjkEnabled) {
        WrapCjkConfig wj;
        wj.siteVA   = gp.wrapCjkSiteVA;
        wj.resumeVA = gp.wrapCjkResumeVA;
        wj.patchLen = gp.wrapCjkPatchLen;
        wj.logTag   = gp.logTag;
        memcpy(wj.sig, gp.wrapCjkSig, sizeof(wj.sig));
        wj.sigLen = gp.wrapCjkSigLen;
        if (WrapCjkInstall(wj)) {
            Log("InstallAll: CJK 长文本换行修复完成");
        } else {
            Log("InstallAll: CJK 换行修复未生效（换行长句仍可能乱码）");
        }
    }

    g_installed = hooked;

    Log("InstallAll -> hook=%d(成功%d/失败%d) 字库=%d CD屏蔽=%d 换行修复=%d",
        (int)hooked, hookOk, hookFail, g_pFont ? 1 : 0,
        CdSpoofIsActive() ? 1 : 0, WrapCjkIsActive() ? 1 : 0);
    return hooked;
}

void UninstallAll()
{
    RendererUninstall();
    CdSpoofRemove();
    WrapFixRemove();
    LineFixRemove();
    WrapCjkRemove();
    g_installed = false;
}

// ── 导出 ────────────────────────────────────────────────────────────────
extern "C" __declspec(dllexport) void InitializeASI()
{
    if (!g_hModule) g_hModule = GetModuleHandleA(nullptr);
    Log("InitializeASI: enter (self=%p)", (void*)g_hModule);
    InstallAll();
}

extern "C" __declspec(dllexport) bool ArmyMenAT_Install()
{
    if (!g_hModule) g_hModule = GetModuleHandleA(nullptr);
    return InstallAll();
}

extern "C" __declspec(dllexport) void ArmyMenAT_Uninstall()
{
    UninstallAll();
}
