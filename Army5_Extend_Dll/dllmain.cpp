// dllmain.cpp —— Army Men: Air Tactics（本作）中文补丁（ASI）
//
// 设计要点（承接 1/2/3/4 代）：
//   1. **不修改 exe 文件**：所有改动都在进程内存里，退出即消失
//   2. 译文与地址结构全部外置（译文在游戏自己的 strings\strings.txt /
//      strings\uiStrngs.txt 里）
//   3. 目标识别 + 签名校验 + fail-closed：签名不符绝不 hook
//
// 与 3/4 代的关键差异（详见 src/target.h 与 docs/15-am5-reverse-findings.md）：
//   * 只有 **3 个绘制函数**：LEFT / DIALOG / GRADIENT。
//     ★ 本作**没有 CENTER**（4 代 sub_466650 / 3 代 sub_451114），
//       所以 hook 目标只有 4 个（2 绘制 + 2 测量），比 4 代少一个。
//   * patchLen 是 10/14/11/14，**不能**沿用 4 代的 10/15/11/14
//     （4 代 DIALOG 序言中间多 `cmp eax,edx`，边界比本作晚 1 字节）
//   * 字形表地址 0xC86DFC / 0xC86E3C / 0xC86FFC（4 代是 0x6BE524 系列）
//   * 字体档 **9 个**（sub_446AA0: `for (i = 0; i < 9; ++i)`），
//     且各档字符单元高从 8 到 24 不等 -> CJK 逻辑盒必须**逐档取**，见 renderer.cpp
//   * GRADIENT（sub_488B90）用**另一套单字节字体**（word_C87E5C / dword_C8805C），
//     中文永远不走它 -> 不接管绘制，仅保留识别校验
//
// 本作同样自带点阵字体引擎（文字不走 GDI 绘制），所以必须 hook
// **游戏自己的文字绘制函数** sub_488640 / sub_4887F0。
//   ★ 注：本作确实用 GDI **构建** ASCII 图集（CreateFontA，9 档，
//     face 取 Arial Black / Arial Narrow / Times New Roman 与默认字体，
//     sub_4882A0 逐字符 TextOutA），但那两个字面不含 CJK 字形 ——
//     所以中文字形由我们直接喂 Hzk16 点阵，完全不经过 GDI。

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
