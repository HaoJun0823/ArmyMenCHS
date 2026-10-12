#pragma once

#include <windows.h>

// 安装/卸载 Hook。全部走 IAT 或 inline，不修改 exe 文件本身。
//
// 设计原则（按需求）：
//   1. 翻译数据外置 INI，不写死在 DLL
//   2. 优先 Hook 切入，避免直接改 exe 字节（风险低、可回退）
//   3. 字体：Text.cpp 硬编码 ANSI_CHARSET，导致中文无法渲染，
//      必须 Hook CreateFontA/IndirectA 改为 GB2312_CHARSET + 宋体

bool InstallHooks();
void RemoveHooks();

// 供 dllmain 调用：记录自身模块句柄（用于定位同目录配置）
void SetModuleHandle(HMODULE h);

// 供 dllmain 调用：加载翻译数据
bool LoadTranslationData();

// ── ASI 导出约定 ────────────────────────────────────────────────────────
// Ultimate ASI Loader 加载 .asi 后只调 DllMain，然后尝试
// GetProcAddress(hMod, "InitializeASI") 并调用它（若存在）。
// 因此**必须**导出名为 InitializeASI 的函数，否则 Hook/补丁不会安装。
// 见 dsound.dll(UAL v9.7.4) 内的 "InitializeASI" 字符串。
extern "C" __declspec(dllexport) void InitializeASI();

// 兼容旧名（保留，便于手动/脚本调用）
extern "C" __declspec(dllexport) bool ArmyMenCHS_Install();
extern "C" __declspec(dllexport) void ArmyMenCHS_Uninstall();
