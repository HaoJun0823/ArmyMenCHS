// mpunlock.h —— 多人联机解锁（Army Men: World War / 4 代）
//
// 背景（来源：GOG 论坛 "Restore Multiplayer Menu Patch"，
// 归档见 I:\LocalGames\Army Men\多人菜单恢复补丁.md）：
//
//   GOG 版 exe 用一个字节把主菜单的 Multiplayer 项关掉了：
//       文件偏移 0x6F270：EB 55  ->  74 55
//   语义：该处前面是
//       ...  cmp  esi, ebx                       ; 3B F3
//            mov  dword ptr [esp+38h], 4         ; C7 44 24 38 04 00 00 00
//            jmp  short +0x55                    ; EB 55   <-- GOG 改过的
//   原版是 `jz short +0x55`（74 55）：CD/注册表检查失败时**跳过**
//   安装 Multiplayer 菜单项；GOG 把条件跳改成无条件跳，于是该项永远
//   被跳过 -> 主菜单没有「多人游戏」。
//
//   ★ 本 DLL 的做法与 2/3 代一致：**不改 exe 文件**，只在进程内存里把
//     这个字节改回 74。退出即消失，撤掉 DLL 即恢复原状。
//
// 地址核算（本机实测，见 I:\LocalGames\Army Men\_agent_scripts\_amww_pe_check.py）：
//   .text 段 PointerToRawData(0x1000) == VirtualAddress(0x1000)
//   -> 文件 0x6F270 == RVA 0x6F270 == VA 0x46F270（ImageBase 0x400000）
//   该点与 5 个渲染 hook 点（RVA 0x66290..0x66810）相距 ~0x8000，无冲突。
//
// ★ 与 3 代的对照（别把两代的数字搞混）：
//     3 代 armymentis.exe : RVA 0x5886F，EB 41 -> 74 41，槽位 [ebp-4]
//     4 代 amww.exe       : RVA 0x6F270，EB 55 -> 74 55，槽位 [esp+38h]
#pragma once

#include <windows.h>

// 安装多人菜单解锁补丁（幂等；在目标识别成功后调用）。
// 返回 true 表示"当前进程内存里该字节已是 74 55"（原本就是或刚刚改好）。
bool MpUnlockInstall();

// 恢复为 EB 55（仅 FreeLibrary 显式卸载时调用）
void MpUnlockRemove();
