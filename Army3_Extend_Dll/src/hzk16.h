// hzk16.h —— 中文字库（RSE\x1a 容器）读取与字形提取
//
// 格式依据（2 代已实测，见 ArmyMen2-汉化可行性-逆向侦察报告.md）：
//   由 AM2 中文版 exe 的 sub_426CB0 / sub_426DB0 / sub_446B00 反编译还原，
//   并用真实 Hzk16 文件验证（26 个汉字全部正确渲染）。
//
//   文件头（实测）：
//     0x00  DWORD  魔数 'RSE\x1a'  (0x1A455352)
//     0x14  WORD   字形宽  = 13
//     0x16  WORD   字形高  = 13
//     0x18  WORD   覆盖范围起（GB2312 首字 0xB0A1）
//     0x1C  WORD   覆盖范围止（0xFEF7）
//     0x20  char[] 字体名（GBK，"宋体"）
//     0x48  DWORD  字形数据起始偏移（实测 0x694C）
//     0x50  WORD   每字形字节数（实测 26 = 13 行 × 2 字节）
//     0x52  WORD   字形总数（实测 6768）
//
//   ★ 注意：官方 exe 用的是**硬编码公式**，不是读文件头：
//       offset = height * ((width+7)>>3) * (trail + 94*lead - 15295) - 9688;
//       if (offset < 0) offset += 9776;
//     本模块默认用同一公式（保证与 2 代渲染逐像素一致），
//     同时把文件头信息读出来做交叉校验，不一致时写日志告警。
//
//   ★ 3 代复用说明：3 代英文版 exe 里**没有** Hzk16 / RSE\x1a（已全盘搜索确认），
//     它用 GDI CreateFontA("ArialBlack"/"ArialNarrow") 在运行时构建 ASCII 图集。
//     那两个字面不含 CJK 字形，所以**中文字形绝不能走 GDI**，必须由我们
//     自己喂点阵 —— 正是本模块 + renderer.cpp 里 DrawCjk13 所做的事。
//     换言之：3 代的中文与 2 代用同一份字库、同一条直写表面的路径。

#pragma once

#include <windows.h>
#include <string>

class Hzk16Font {
public:
    Hzk16Font();
    ~Hzk16Font();

    // 从文件加载。成功返回 true。
    // 失败时 GetLastError 里有可读原因（同时会写日志）。
    bool Load(const wchar_t* path);

    bool IsLoaded() const { return m_data != nullptr; }

    // 取一个 GBK 双字节字符的 13x13 位图指针（每行 2 字节，共 26 字节）。
    // 越界返回 nullptr。
    const BYTE* Glyph(BYTE lead, BYTE trail) const;

    // 字形尺寸
    int Width()  const { return m_width; }
    int Height() const { return m_height; }
    int BytesPerGlyph() const { return m_bpg; }

    // 取某位（x 列, y 行）。行优先，每行 2 字节，bit7 在左 —— 与官方渲染一致。
    static bool TestBit(const BYTE* glyph, int x, int y, int bytesPerRow);

    // 自检：把一批汉字渲染成 1bpp 缓冲并检查墨迹量是否合理。
    // 返回 0 表示通过。用于实机前的离线验证。
    int SelfTest(std::string& report) const;

    // 诊断信息
    std::string Describe() const;

private:
    BYTE* m_data = nullptr;
    DWORD m_size = 0;
    int   m_width = 13;
    int   m_height = 13;
    int   m_bpg = 26;
    DWORD m_dataStart = 0;
    DWORD m_glyphCount = 0;
    WORD  m_rangeLo = 0, m_rangeHi = 0;
    std::string m_faceName;
    bool  m_headerTrusted = false;   // 文件头是否与硬编码公式自洽
};
