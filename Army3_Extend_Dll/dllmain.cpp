// dllmain.cpp —— Army Men: Toys in Space（3 代）中文补丁（ASI）
//
// 设计要点（承接 1/2 代）：
//   1. **不修改 exe 文件**：所有改动都在进程内存里，退出即消失
//   2. 译文与地址结构全部外置（译文在游戏自己的 strings\strings.txt）
//   3. 目标识别 + 签名校验 + fail-closed：签名不符绝不 hook
//
// 与 2 代的关键差异（详见 src/renderer.h 与 target.h 的长注释）：
//   * 3 代渲染器**返回 void**，2 代那套"靠返回值推进 ASCII"的契约不存在
//   * 3 代多一个测量函数（累加字形高-3），共 5 个 hook 目标
//   * 3 代文本全在 strings\strings.txt，**不需要**内存字符串补丁
//   * patchLen 是 6/6/6/5/8，**不能**沿用 2 代的 5（会切碎 sub esp,38h）
//
// 1 代 hook 的是 GDI 的 CreateFontA/TextOutA；
// 3 代游戏自带点阵字体引擎（文字不走 GDI 绘制），所以必须 hook
// **游戏自己的文字绘制函数** sub_450EA7 / sub_450FCF / sub_451114。
//   ★ 注：3 代确实用 GDI **构建** ASCII 图集（CreateFontA("ArialBlack")），
//     但那两个字面不含 CJK 字形 —— 所以中文字形由我们直接喂 Hzk16 点阵，
//     完全不经过 GDI。

#include "pch.h"
#include "src\hooks.h"      // ★ src/ 不在附加包含路径里，必须写相对路径
#include "src\log.h"

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
