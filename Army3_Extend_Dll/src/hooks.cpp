#include "pch.h"
#include "hooks.h"
#include "log.h"
#include "target.h"
#include "hzk16.h"
#include "renderer.h"
#include "mpunlock.h"

#include <string>
#include <cstdio>

static HMODULE g_hModule = nullptr;
Hzk16Font* g_pFont = nullptr;      // renderer.cpp 引用

void SetModuleHandle(HMODULE h) { g_hModule = h; }

// ── 找 Hzk16 ────────────────────────────────────────────────────────────
//
// ★ 3 代与 2 代的一个现实差异：**3 代没有官方中文版**，所以游戏目录里
//   不会自带 Hzk16。字库必须随补丁一起发布。因此候选位置按"补丁优先"排：
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
    Log("===== Army Men: Toys in Space CHS 启动 =====");

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
    RendererSetEnv(env);

    // ★ probeOnly 档位：只做"识别 + 记录"，不接管渲染。
    //   它不读任何全局量，所以**必须先于自检**返回 —— 否则会因为
    //   该档位没填 rc/enabled 等字段而被自检挡下，连识别都验证不了。
    //
    //   ★ 3 代的探针是**只读**的（见 RendererProbeAt 的说明）：
    //     序言不是 2 代那种 5 字节 mov eax,[imm32]，硬写标记会破坏栈帧。
    if (gp.probeOnly) {
        // ★ rendererVA 是**绝对 VA**（IDA 显示值），不能再加模块基址 ——
        //   加了就变成 base+0x450EA7 的野地址，读出越界字节。
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

    // ★★ 逐个安装**全部 5 个** hook 目标：
    //    3 个绘制（LEFT/DIALOG/CENTER）+ 2 个测量（宽 / 高-3）。
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

    g_installed = hooked;

    // ④ 多人联机菜单解锁（与渲染 hook 无关，独立 1 字节内存补丁）
    //
    // ★ 放在这里而不是最前面：它只需要"档位识别成功"这一个前提，
    //   不需要字库也不需要渲染 hook。放最后只是为了让日志按
    //   「识别 -> 字库 -> 渲染 -> 杂项」的顺序读起来顺。
    //
    // ★ 幂等 + fail-closed：字节不是 EB 41/74 41 就只写日志不动内存，
    //   详见 mpunlock.cpp 顶部说明。
    if (MpUnlockInstall()) {
        Log("InstallAll: 多人联机菜单解锁完成");
    } else {
        Log("InstallAll: 多人联机菜单解锁未生效（不影响汉化，详见上一条日志）");
    }

    Log("InstallAll -> hook=%d(成功%d/失败%d) 字库=%d",
        (int)hooked, hookOk, hookFail, g_pFont ? 1 : 0);
    return hooked;
}

void UninstallAll()
{
    RendererUninstall();
    MpUnlockRemove();
    g_installed = false;
}

// ── 导出 ────────────────────────────────────────────────────────────────
extern "C" __declspec(dllexport) void InitializeASI()
{
    if (!g_hModule) g_hModule = GetModuleHandleA(nullptr);
    Log("InitializeASI: enter (self=%p)", (void*)g_hModule);
    InstallAll();
}

extern "C" __declspec(dllexport) bool ArmyMenTIS_Install()
{
    if (!g_hModule) g_hModule = GetModuleHandleA(nullptr);
    return InstallAll();
}

extern "C" __declspec(dllexport) void ArmyMenTIS_Uninstall()
{
    UninstallAll();
}
