// mpunlock.h —— 多人联机解锁（Army Men: Toys in Space / 3 代）
//
// 背景（来源：GOG 论坛 "Restore Multiplayer Menu Patch"，
// 归档见 I:\LocalGames\Army Men\多人菜单恢复补丁.md）：
//
//   GOG 版 exe 用一个字节把主菜单的 Multiplayer 项关掉了：
//       文件偏移 0x5886F：EB 41  ->  74 41
//   语义：该处前面是
//       ...  test eax,eax                    ; 85 C0
//            mov  dword ptr [ebp-4], 4       ; C7 45 FC 04 00 00 00
//            jmp  short +0x41                ; EB 41   <-- GOG 改过的
//   原版是 `jz short +0x41`（74 41）：CD/注册表检查失败时**跳过**
//   安装 Multiplayer 菜单项；GOG 把条件跳改成无条件跳，于是该项永远
//   被跳过 -> 主菜单没有「多人游戏」。
//
//   ★ 本 DLL 的做法与 2 代一致：**不改 exe 文件**，只在进程内存里把这个
//     字节改回 74。退出即消失，撤掉 DLL 即恢复原状。
//
// 地址核算（本机实测，见 I:\LocalGames\Army Men\_am3_mp_*.py）：
//   .text 段 PointerToRawData(0x1000) == VirtualAddress(0x1000)
//   -> 文件 0x5886F == RVA 0x5886F == VA 0x45886F（ImageBase 0x400000）
//   该点与 5 个渲染 hook 点（RVA 0x450E3A..0x451267）相距 0x76xx，无冲突。
#pragma once

#include <windows.h>

// 安装多人菜单解锁补丁（幂等；在目标识别成功后调用）。
// 返回 true 表示"当前进程内存里该字节已是 74 41"（原本就是或刚刚改好）。
bool MpUnlockInstall();

// 恢复为 EB 41（仅 FreeLibrary 显式卸载时调用）
void MpUnlockRemove();
