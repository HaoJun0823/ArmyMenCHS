// log.h —— 日志（同时写 OutputDebugString 与同目录文件）
//
// 为什么必须有文件日志：1 代踩过"补丁完全没加载、游戏却无任何报错"的坑
// （Army2 docs/02-pitfalls.md 坑 11）。实机验证的唯一判据就是日志文件出现。
//
// 文件名按作区分：ArmyMenTISCHS.log
#pragma once

#include <windows.h>

// 在 DllMain 里记录自身模块句柄（决定日志/配置的目录）
void LogSetModule(HMODULE h);

// 设置当前作的标识（用于日志文件名），在检测到目标后调用
void LogSetGameTag(const char* tag);

// 写一行日志。支持 printf 风格。
void Log(const char* fmt, ...);

// 取 DLL 所在目录（不含结尾反斜杠）
bool LogGetDllDir(wchar_t* out, size_t cch);
