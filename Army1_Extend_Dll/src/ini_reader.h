#pragma once

// 极简 INI 读取（UTF-8 文件，无 section 嵌套需求）
// 只支持： [Section] / key=value / ; 注释 / key=value ; 行尾注释

#include <windows.h>
#include <string>
#include <vector>
#include <map>
#include <fstream>
#include <sstream>

struct IniEntry {
    int         index;      // 块内序号（layout=packed4 时用）
    std::string zh;         // 中文译文（UTF-8）
    std::string en;         // 英文原文（注释，用于校对）
    int         capacity;   // 槽容量（0 = 未知/不限）
    std::string note;       // 备注（如存疑标记）
    DWORD       rva;        // layout=explicit 时的显式 RVA（0 表示未用）
};

struct IniBlock {
    std::string          name;
    std::string          baseRVA;    // 十六进制字符串，如 "0x000BDA6C"
    std::string          encoding;
    std::string          layout;
    int                  count = 0;
    std::vector<IniEntry> entries;
    std::map<std::string, std::string> meta;
};

class IniReader {
public:
    // 返回是否成功加载
    bool load(const std::wstring& path, IniBlock& out);

    // 读 [Section] 下的 key
    static std::string getString(const std::wstring& path,
                                 const std::string& section,
                                 const std::string& key,
                                 const std::string& def = "");
    static int getInt(const std::wstring& path,
                      const std::string& section,
                      const std::string& key,
                      int def = 0);

private:
};

// 工具函数（自由函数，hooks.cpp 也可复用）
std::string ini_trim(const std::string& s);
bool ini_parseHex(const std::string& s, unsigned long& out);
