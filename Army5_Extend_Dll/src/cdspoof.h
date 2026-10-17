// cdspoof.h —— CD-ROM 校验屏蔽（本作 sub_447450）
//
// ════════════════════════════════════════════════════════════════════════
//  本作为什么需要 CD：
//     启动早期 _WinMain 调 sub_447450：
//         ① GetLogicalDriveStringsA 枚举盘符
//         ② GetDriveTypeA(盘符) == DRIVE_CDROM(5)
//         ③ GetVolumeInformationA 取卷标，必须等于 "AMAT PC"
//         ④ 命中 -> sprintf(byte_671288, "%s_Setup\\", 盘符)
//                   dword_6713B0 = 1
//         ⑤ 最后 sub_43F4A0("audio/music") 探测能否切到音频目录
//            探不到 -> MessageBoxA("Please insert the ... CD.") -> return 0
//         ⑥ _WinMain: test eax,eax / jz 退出  -> 返回 0 直接结束进程
//
//  ★ ⑤ 那一步的探测方式是 `_chdir`（不是 fopen），所以只要
//    `<cwd>\audio\music` 或 `<byte_671288>audio\music` 任一能切进去就算通过。
//    本作安装版把音频放在硬盘上，这一步在无光盘时失败 —— 这正是弹框的成因。
//
// ════════════════════════════════════════════════════════════════════════
//  为什么不能只把 sub_447450 改成 return 1：
//
//    byte_671288 与 dword_6713B0 是**全局回退路径**，被 40 处目录切换共用：
//        sub_43F4A0 / sub_4400B0 都是
//            if (_chdir("<cwd>\\<子目录>")) {
//                if (dword_6713B0) _chdir(byte_671288 + 子目录);
//            }
//    若只返回 1 而不设这两个量，dword_6713B0 恒为 0，
//    凡是"本地目录不存在、本应从光盘取"的资源都会静默失败（音乐最典型）。
//
//  → 所以本模块做两件事：
//       ① 安装前把 byte_671288 填成 "<exe目录>\"、dword_6713B0 置 1
//          （等价于"在一张根目录下有全部资源的盘上找到了数据"）
//       ② 再把 sub_447450 入口改成"直接返回 1"
//    这样 40 处回退全部落到 exe 目录，彻底不依赖光驱。
//
//  安全性：
//    * 只改进程内存，不写 exe、不碰注册表，退出即还原
//    * 全程 fail-closed：签名不符则不装，游戏保持原样（仍要光盘）
//    * 安装前校验 11 字节指纹（push ecx/ebx/ebp/esi/edi + mov edi,ds:...），
//      该指纹在本作 exe 里全文件**唯一**命中 sub_447450
#pragma once

#include <windows.h>
#include <string>

// 与 target.h 的 SIG_MAX 保持一致（这里不 include target.h 以免循环依赖，
// 用 static_assert 在实际使用处保证两者相同）
#define CDSPOOF_SIG_MAX 64

struct CdSpoofConfig {
    DWORD  detectVA = 0;        // sub_447450 入口（要改成 return 1）
    DWORD  rootBufVA = 0;       // byte_671288：256 字节 "根路径\" 缓冲
    DWORD  readyFlagVA = 0;     // dword_6713B0：1 = 根路径可用
    DWORD  readyFlag2VA = 0;    // dword_6713BC：原版与上面同时置 1
    int    patchLen = 0;        // 覆盖字节数（指令边界）
    int    rootBufSize = 256;   // byte_671288 的容量
    std::string logTag;

    // 入口处的期望字节（fail-closed：不符则不改写）
    BYTE   cdDetectSig[CDSPOOF_SIG_MAX] = {0};
    BYTE   cdDetectSigMask[CDSPOOF_SIG_MAX] = {0};
    int    cdDetectSigLen = 0;
};

// 安装：填根路径缓冲 + 置标志 + 改写 detectVA 为 return 1
// 返回 true 表示补丁已生效（或已被判定为无需安装）
bool CdSpoofInstall(const struct CdSpoofConfig& cfg);

// 卸载：恢复被改写的字节（根路径缓冲与标志位保持不变——
//       它们是 .data 里的普通变量，进程退出即消失，且恢复反而会让
//       后续仍在运行的代码走回光盘路径）
void CdSpoofRemove();

// 查询状态（写日志用）
bool CdSpoofIsActive();
