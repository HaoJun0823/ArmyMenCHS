#include "pch.h"
#include "hooks.h"
#include "log.h"
#include "target.h"
#include "hzk16.h"
#include "renderer.h"
#include "strings.h"
#include "codepatch.h"

#include <string>
#include <cstdio>

static HMODULE g_hModule = nullptr;
Hzk16Font* g_pFont = nullptr;      // renderer.cpp 引用

void SetModuleHandle(HMODULE h) { g_hModule = h; }

// ── 找 Hzk16 ────────────────────────────────────────────────────────────
// 官方代码用的是相对路径 "..\Hzk16"，但那依赖运行时 CWD，
// 我们不去猜 CWD，直接按**确定的几个候选位置**依次找：
//   1) scripts\Hzk16            （跟补丁放一起，最稳）
//   2) <DLL 目录>\Hzk16
//   3) <exe 目录>\Hzk16         （官方中文版就是放这里）
//   4) <exe 目录>\..\Hzk16      （官方相对路径的另一种解释）
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

// ── 安装 ────────────────────────────────────────────────────────────────
static bool g_installed = false;

bool InstallAll()
{
    Log("===== Army Men CHS (AM2/TIS) 启动 =====");

    // ① 识别目标
    GameProfile gp;
    if (!Target::Detect(gp)) {
        Log("InstallAll: 目标识别失败 -> 不安装任何 hook（fail-closed）");
        return false;
    }
    LogSetGameTag(gp.logTag.c_str());
    Log("InstallAll: 适配档位 = %s", gp.id.c_str());

    // ② 中文版自己就支持中文，我们不该再插一脚
    if (gp.id == "ArmyMenII-CHS") {
        Log("InstallAll: 检测到官方中文版，本补丁无需介入，主动停用");
        return false;
    }

    // ③ 载入字库
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

    // ④ 装 hook
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

    // ★ probeOnly 档位（如 TIS）：只做"识别 + 挂无副作用标记"，不接管渲染。
    //   它不读任何全局量，所以**必须先于自检**返回 —— 否则会因为
    //   该档位没填 rc/enabled 等字段而被自检挡下，连识别都验证不了。
    if (gp.probeOnly) {
        BYTE* b2 = (BYTE*)GetModuleHandleA(nullptr);
        Log("InstallAll: 该档位标记为 probeOnly —— 只做识别验证，不接管渲染");
        bool poked = RendererProbeAt(gp.rendererVA, b2 + gp.rendererVA, 5);
        Log("InstallAll -> probe=%d（无渲染改动；这是刻意的，避免未验证的档位花屏）",
            (int)poked);
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

    // ★★ 逐个安装全部文字渲染器（不是只装一个！）
    //    实测：AM2 有 3 个（左对齐/对话框/居中），
    //    只装左对齐会导致对话框文字完全不显示。
    int hookOk = 0, hookFail = 0;
    for (const HookSite& h : gp.hooks) {
        if (h.rva == 0) continue;
        bool r = RendererInstallAt(h.rva, (int)h.kind, base + h.rva, 5, h.patchLen);
        if (r) hookOk++; else hookFail++;
    }
    Log("InstallAll: 渲染器 hook 成功 %d 个，失败 %d 个", hookOk, hookFail);
    bool hooked = (hookOk > 0);

    // ★★ 造 stub（原始函数副本）。
    //    我们的实现里 ASCII 段要转调"原始行为"，但入口已被 jmp 覆盖，
    //    所以必须在写 jmp **之后**、使用之前构造 stub。
    //    失败则退回"完全自己画"的旧路径（ASCII 可能仍有瑕疵，但不崩）。
    if (hooked) {
        if (RendererBuildStubs()) {
            Log("InstallAll: stub 构造完成（ASCII 段将转调原始实现）");
        } else {
            Log("InstallAll: !! stub 构造失败 —— ASCII 段将自行绘制，可能有偏差");
        }
    }

    // ⑤ 写中文串（数据段，来自 INI，可关）
    bool strOk = false;
    if (hooked) {
        strOk = StringsApplyAll();
    } else {
        Log("InstallAll: hook 未成功，跳过字符串补丁（避免画不出来却改了内存）");
    }

    // ⑥ 代码段补丁（解锁多人游戏等）
    //    ★ 与字符串补丁独立：即使渲染 hook 失败也应当尝试，
    //      因为它不依赖渲染（只是让被封锁的菜单项能被创建）。
    //      每条都做多字节原文校验，不符即跳过。
    int cpOk = CodePatchesApplyAll();

    g_installed = hooked;
    Log("InstallAll -> hook=%d(成功%d/失败%d) strings=%d codepatch=%d",
        (int)hooked, hookOk, hookFail, (int)strOk, cpOk);
    return hooked;
}

void UninstallAll()
{
    RendererUninstall();
    StringsRestoreAll();
    CodePatchesRestoreAll();
    g_installed = false;
}

// ── 导出 ────────────────────────────────────────────────────────────────
extern "C" __declspec(dllexport) void InitializeASI()
{
    if (!g_hModule) g_hModule = GetModuleHandleA(nullptr);
    Log("InitializeASI: enter (self=%p)", (void*)g_hModule);
    InstallAll();
}

extern "C" __declspec(dllexport) bool ArmyMenCHS_Install()
{
    if (!g_hModule) g_hModule = GetModuleHandleA(nullptr);
    return InstallAll();
}

extern "C" __declspec(dllexport) void ArmyMenCHS_Uninstall()
{
    UninstallAll();
}
