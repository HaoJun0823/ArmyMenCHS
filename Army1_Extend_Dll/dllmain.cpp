// dllmain.cpp : 定义 DLL 应用程序的入口点。
//
// ArmyMenCHS —— 《玩具兵大战》Steam 版汉化补丁
//
// 设计要点：
//   1. 翻译数据外置（ArmyMenCHS.ini + strings\*.ini），DLL 不含任何硬编码译文
//   2. 不修改 exe 文件本身，全部通过 IAT Hook 切入（安全、可回退）
//   3. 字体：游戏源码 Text.cpp 硬编码 ANSI_CHARSET，中文会乱码；
//      这里 Hook CreateFontA/CreateFontIndirectA 改为 GB2312_CHARSET + 宋体
//   4. 文本：Hook TextOutA/ExtTextOutA，按字典替换英文->中文(GBK)

#include "pch.h"
#include "src/hooks.h"

// 保存自身模块句柄，供读取同目录配置使用
extern "C" BOOL APIENTRY DllMain(HMODULE hModule,
                                 DWORD   ul_reason_for_call,
                                 LPVOID  lpReserved)
{
    switch (ul_reason_for_call)
    {
    case DLL_PROCESS_ATTACH:
        DisableThreadLibraryCalls(hModule);
        SetModuleHandle(hModule);
        // 注意：此处不要做复杂初始化（loader lock）。
        // 真正的安装由导出函数 ArmyMenCHS_Install() 调用。
        break;

    case DLL_THREAD_ATTACH:
    case DLL_THREAD_DETACH:
        break;

    case DLL_PROCESS_DETACH:
        RemoveHooks();
        break;
    }
    return TRUE;
}
