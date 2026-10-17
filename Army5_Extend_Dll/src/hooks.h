// hooks.h —— ASI 入口与装配（Army Men: Air Tactics / 本作）
#pragma once

#include <windows.h>

// 记录自身模块句柄（DllMain 里调用）
void SetModuleHandle(HMODULE h);

// 完整安装：识别目标 -> 载入字库 -> hook 渲染器
bool InstallAll();

// 卸载
void UninstallAll();

// ── ASI 导出约定 ────────────────────────────────────────────────────────
// Ultimate ASI Loader 加载 .asi 后调 DllMain，然后 GetProcAddress
// ("InitializeASI") 并调用（若存在）。**必须导出这个名字**。
//
// ★ 本作可行性依据（本轮实测）：
//   amat.exe 的导入表里 **按名字** 导入了
//     DDRAW.dll!DirectDrawCreate     （IAT VA 0x4F4000）
//     DINPUT.dll!DirectInputCreateA  （IAT VA 0x4F4008）
//     DSOUND.dll!DirectSoundCreate   （IAT VA 0x4F4010）
//   按名字导入意味着 UAL 的代理 DLL 可以正常接管。
//   而游戏目录里的 dinput.dll（2,352,128 B，含 `InitializeASI` 与 `UAL` 串）
//   本身就是 Ultimate ASI Loader，所以 **scripts\*.asi 直接可用**。
//
//   ★ 与 3/4 代的一个细节差异：本作 DDRAW 也按名字导入，
//     而游戏目录里的 ddraw.dll 是 **cnc-ddraw**（396,288 B，无 ASI 支持），
//     所以本补丁**不要**放到 ddraw.dll 那条路径上，只走 scripts\*.asi。
extern "C" __declspec(dllexport) void InitializeASI();
extern "C" __declspec(dllexport) bool ArmyMenAT_Install();
extern "C" __declspec(dllexport) void ArmyMenAT_Uninstall();
