// dllmain.cpp —— Army Men II / Toys in Space 中文补丁（ASI）
//
// 设计要点（与 1 代一致 + 为多作兼容做的调整）：
//   1. **不修改 exe 文件**：所有改动都在进程内存里，退出即消失
//   2. 译文与地址结构全部外置为 INI，DLL 只是引擎
//   3. 目标识别 + 签名校验 + fail-closed：签名不符绝不 hook
//   4. 一套代码同时适配 Army Men II 与 Toys in Space（引擎同源）
//
// 与 1 代的关键差异：
//   1 代 hook 的是 GDI 的 CreateFontA/TextOutA；
//   本作游戏自带点阵字体引擎（不走 GDI 画文字），
//   所以必须 hook **游戏自己的文字绘制函数** sub_446930 / sub_450EA7。

#include "pch.h"
#include "hooks.h"
#include "log.h"

extern "C" BOOL APIENTRY DllMain(HMODULE hModule, DWORD reason, LPVOID reserved)
{
    switch (reason)
    {
    case DLL_PROCESS_ATTACH:
        DisableThreadLibraryCalls(hModule);
        LogSetModule(hModule);
        SetModuleHandle(hModule);
        // ★ 不在 DllMain 里做安装：此时 loader lock 被持有，
        //   任何 CreateFile / 字符串处理都可能死锁。
        //   真正的安装在 InitializeASI() 里由 UAL 调用。
        Log("DllMain: PROCESS_ATTACH (self=%p)", (void*)hModule);
        break;

    case DLL_PROCESS_DETACH:
        // 进程退出时不主动恢复（此时可能已持有其它锁）；
        // 内存随进程消亡，无需清理。仅 FreeLibrary 显式卸载时恢复。
        if (reserved == nullptr) {
            UninstallAll();
        }
        break;

    case DLL_THREAD_ATTACH:
    case DLL_THREAD_DETACH:
    default:
        break;
    }
    return TRUE;
}
