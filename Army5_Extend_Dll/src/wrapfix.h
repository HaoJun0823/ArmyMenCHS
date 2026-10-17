// wrapfix.h —— 字幕/长文本自动换行的汉字边界修复
//
// ════════════════════════════════════════════════════════════════════════
//  症状
//    长中文文本自动换行后，第二行起整行乱码（典型：第一行正常，
//    第二行从半个汉字开始，整行错位成生僻字）。
//
//  根因（amat.exe sub_42EF50 反编译 + 逐字节反汇编实测）
//
//    这个函数负责把一段长文本按显示宽度切成多行，存进一个
//    **每行 129 字节 × 16 行** 的数组（this+0xD9 起，见 sub_42DEB0 清零循环
//    `lea ecx,[esi+0xD9] / add ecx,0x81 / 16 次`）。
//
//    核心循环：
//        while (*src) {
//            *dst++ = *src++;                       // ★ 逐【字节】复制
//            if (--count ... ) 
//            if (sub_4885B0(buf, font, 0) < maxWidth) continue;   // 未超宽
//            // 超宽 -> 回退到最近的空白字符
//            do {
//                --src; --dst; --count;
//                if (count < 0) goto done;          // 0x42F02E
//            } while (!isspace(*src));
//        done:
//            *dst = 0;                              // ★ 在此按字节截断
//            strcpy(&lines[128*n + n + 88], buf);
//        }
//
//    ★ 英文没问题：单词之间必有空格，回退总能停在空格上。
//    ★ 中文会坏：整句没有空格，回退循环一路退到 count<0，
//      然后在“任意字节”上截断 —— 那个位置极可能落在某个 GBK 汉字的
//      **两个字节中间**。下一轮从该汉字的后半字节开始读，
//      于是整行被解释成完全不同的字，视觉上就是乱码。
//
//  修法
//    只改「回退」这一步：回退一格后，若当前字节是 **GBK 尾字节**
//    （即前一个字节是 0x81..0xFE 的首字节），就再退一格，
//    保证 src 永远停在字符边界上。这样截断点必然对齐汉字，
//    每行都是完整字符，不会再出现半个汉字。
//
//  ★ 为什么改这里而不是改测量函数 sub_4885B0：
//    换行判断用的是 “测量宽度 < maxWidth”。即使测量更准，
//    回退循环本身仍会按字节走，截断点仍可能落在汉字中间。
//    必须让**回退**具备字符边界意识。
//
//  ★ 为什么不动 sub_42EF50 的其他部分：
//    该函数还负责插入 '^' + 颜色字节 的前缀、行数上限滚动等逻辑，
//    改动面越大风险越高。这里只替换 0x42F019 起的 21 字节回退块，
//    入参/出参寄存器（ebx/esi/edi）与原逻辑完全一致。
#pragma once

#include <windows.h>
#include <string>

struct WrapFixConfig {
    DWORD  rollbackVA = 0;      // 0x42F019：回退循环起点（要被替换）
    DWORD  doneVA     = 0;      // 0x42F02E：回退结束的落点（trampoline 跳这里）
    int    patchLen   = 0;      // 覆盖字节数（21）
    BYTE   sig[64] = {0};       // 期望的原始字节
    BYTE   sigMask[64] = {0};
    int    sigLen = 0;
    std::string logTag;

    // ── 诊断（临时）：sub_42EF50 内部状态 ──────────────────────────
    //   行数组：this+88 起，每行 129 字节，共 16 行
    DWORD  lineBaseVA  = 0;     // 0x42EF50 里 this+88 对应的绝对地址基准（用 this 实算）
    DWORD  fnEntryVA   = 0;     // sub_42EF50 入口（用于下"调用前/后"诊断钩子）
    DWORD  fnAfterVA   = 0;     // sub_42EF50 的 ret 之后（用于 dump 行数组）
    bool   diag        = false; // 是否开启诊断
};

// 安装：把回退循环替换成"感知 GBK 字符边界"的版本
bool WrapFixInstall(const struct WrapFixConfig& cfg);

// 卸载：恢复原始字节
void WrapFixRemove();

bool WrapFixIsActive();
