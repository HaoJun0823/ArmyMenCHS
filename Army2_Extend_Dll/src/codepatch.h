// codepatch.h —— 代码段字节补丁（解锁被封锁的功能）
//
// 与 strings.h 的区别：
//   strings 改的是**数据**（.data 里的字符串）
//   codepatch 改的是**代码**（.text 里的指令字节）
// 后者风险更高，因此校验更严：多字节原文 + 显式长度 + 不匹配绝不写。
//
// ★ 第一个用例：解锁《玩具兵大战2》被封锁的多人游戏模式
//
//   原版（Steam 1999-02-03）在 RVA 0x4D8FE 处是 `EB 55`：
//       mov  esi, eax          ; operator new(0x78) 的返回值
//       cmp  esi, ebx          ; ebx == 0
//       mov  [esp+0x38], 3
//       jmp  0x4D955           ; ★ 无条件跳过 —— 多人按钮从不创建
//   0x4D900..0x4D954 那段引用的正是
//       03_101_00_multiplay.bmp / _01_ / _02_
//   即**多人游戏按钮**。
//
//   把它改成 `74 55`（JZ，仅当 esi==0 即分配失败时跳过），
//   就恢复了"分配成功 -> 构建多人菜单"的正常分支。
//
//   这是发行方当年刻意封锁（把 JZ 改成 JMP），本补丁将其还原。
#pragma once

#include <string>

// 应用所有代码段补丁。返回成功应用的条数（0 表示都没成功）。
int CodePatchesApplyAll();

// 恢复（严格按记录的原始字节写回）
void CodePatchesRestoreAll();

// 供日志/自检：当前配置里声明了多少条代码补丁
int CodePatchesCount();
