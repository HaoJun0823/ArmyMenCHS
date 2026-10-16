// hooks.h —— ASI 入口与装配（Army Men: World War / 4 代）
#pragma once

#include <windows.h>

// 记录自身模块句柄（DllMain 里调用）
void SetModuleHandle(HMODULE h);

// 完整安装：识别目标 -> 载入字库 -> hook 渲染器 -> 多人解锁
bool InstallAll();

// 卸载
void UninstallAll();

// ── ASI 导出约定 ────────────────────────────────────────────────────────
// Ultimate ASI Loader 加载 .asi 后调 DllMain，然后 GetProcAddress
// ("InitializeASI") 并调用（若存在）。**必须导出这个名字**。
//
// ★ 4 代可行性依据（docs/11-am4-reuse-plan.md §1 实测）：
//   amww.exe 的导入表里 **按名字** 导入了
//     DINPUT.dll!DirectInputCreateA  （VA 0x495008）
//     DDRAW.dll!DirectDrawCreate     （VA 0x495000）
//     DSOUND.dll!DirectSoundCreate   （VA 0x495010，按序号 ord1）
//   按名字导入意味着 UAL 的代理 DLL 可以正常接管，
//   与 2/3 代完全相同的加载方式。
extern "C" __declspec(dllexport) void InitializeASI();
extern "C" __declspec(dllexport) bool ArmyMenWW_Install();
extern "C" __declspec(dllexport) void ArmyMenWW_Uninstall();
