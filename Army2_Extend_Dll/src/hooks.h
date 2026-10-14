// hooks.h —— ASI 入口与装配
#pragma once

#include <windows.h>

// 记录自身模块句柄（DllMain 里调用）
void SetModuleHandle(HMODULE h);

// 完整安装：识别目标 -> 载入字库 -> hook 渲染器 -> 写中文串
bool InstallAll();

// 卸载
void UninstallAll();

// ── ASI 导出约定 ────────────────────────────────────────────────────────
// Ultimate ASI Loader 加载 .asi 后调 DllMain，然后 GetProcAddress
// ("InitializeASI") 并调用（若存在）。**必须导出这个名字**。
// 见 dsound.dll(UAL 9.7.4) 内的 "InitializeASI" 导出。
extern "C" __declspec(dllexport) void InitializeASI();
extern "C" __declspec(dllexport) bool ArmyMenCHS_Install();
extern "C" __declspec(dllexport) void ArmyMenCHS_Uninstall();
