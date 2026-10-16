// dllmain.cpp —— Army Men: World War（4 代）中文补丁（ASI）
//
// 设计要点（承接 1/2/3 代）：
//   1. **不修改 exe 文件**：所有改动都在进程内存里，退出即消失
//   2. 译文与地址结构全部外置（译文在游戏自己的 strings\strings.txt）
//   3. 目标识别 + 签名校验 + fail-closed：签名不符绝不 hook
//
// 与 3 代的关键差异（详见 src/target.h 与 docs/12-am4-reverse-findings.md）：
//   * 3 代那批签名（imul ecx,ecx,0x20C 系列）在 4 代 **0 命中**
//     —— 4 代用 shl/add/lea 做 font*262，签名全部重测
//   * patchLen 是 10/15/15/11/14，**不能**沿用 3 代的 6/6/6/5/8
//   * 字形表地址 0x6BE524 / 0x6BE564 / 0x6BE724（3 代是 0x698D6C 系列）
//   * DIALOG 在 4 代是**两级裁剪**（rcSrc2 ∩ a5），3 代只有一级
//   * 多人解锁点 RVA 0x6F270（3 代是 0x5886F）
//
// 4 代游戏同样自带点阵字体引擎（文字不走 GDI 绘制），所以必须 hook
// **游戏自己的文字绘制函数** sub_466320 / sub_4664A0 / sub_466650。
//   ★ 注：4 代确实用 GDI **构建** ASCII 图集（CreateFontA("ArialBlack")，
//     sub_465FA0 逐字符 TextOutA），但那两个字面不含 CJK 字形 ——
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
