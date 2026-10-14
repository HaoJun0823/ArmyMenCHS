// strings.h —— 内存字符串补丁（把游戏 .data/.rdata 里的英文串换成中文）
//
// 设计承接 1 代（docs/00-porting-map.md 决定 B）：**译文外置为 INI**，
// DLL 只是"读表 -> 写内存"的引擎，改译文不需要重编译。
//
// 数据格式（scripts\strings\am2_strings.ini，UTF-8）：
//
//     [Strings]
//     ; RVA=英文原文|中文译文
//     0x476A20=Sarge|中士
//     0x476A9C=HT:|身高
//
//   ★ 用 '|' 分隔而不是"字段位置"：
//     译文长度可变，只有原文能作为安全闸门。
//
// 安全闸门（1 代坑 2 的教训）：
//   写入前必须比对**内存现状 == INI 声明的英文原文**。
//   不一致说明 RVA 错了或版本不对，**绝不写入**。
//
// ★ 可译性判定：翻译前必须确认该串不是 strcmp / 路径拼接用途。
//   INI 里用 `; XREF:` 注释记录判定依据（1 代 keyname_block.ini 的做法）。
#pragma once

// 应用所有字符串补丁。返回是否至少成功写入一条。
bool StringsApplyAll();

// 恢复（把原始英文写回）
void StringsRestoreAll();
