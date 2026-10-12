#include "pch.h"
#include "ini_reader.h"
#include <algorithm>
#include <cstdlib>

static std::string ltrim(const std::string& s) {
    size_t i = 0;
    while (i < s.size() && (unsigned char)s[i] <= ' ') i++;
    return s.substr(i);
}

static std::string rtrim(const std::string& s) {
    size_t n = s.size();
    while (n > 0 && (unsigned char)s[n - 1] <= ' ') n--;
    return s.substr(0, n);
}

std::string ini_trim(const std::string& s) {
    return rtrim(ltrim(s));
}

// 兼容：类内静态实现转发到自由函数
bool ini_parseHex(const std::string& s, unsigned long& out) {
    std::string t = ini_trim(s);
    if (t.size() > 2 && t[0] == '0' && (t[1] == 'x' || t[1] == 'X'))
        t = t.substr(2);
    if (t.empty()) return false;
    out = 0;
    for (char c : t) {
        int v;
        if (c >= '0' && c <= '9') v = c - '0';
        else if (c >= 'a' && c <= 'f') v = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F') v = c - 'A' + 10;
        else return false;
        out = out * 16 + v;
    }
    return true;
}

// 用 Windows API 读 INI（文件需为 ANSI/UTF-16；UTF-8 用默认读法可能乱码，
// 因此这里改为手工解析 UTF-8，避免中文乱码）
bool IniReader::load(const std::wstring& path, IniBlock& out) {
    std::ifstream f(path);
    if (!f.is_open()) return false;

    std::string section;
    std::string line;
    while (std::getline(f, line)) {
        // 去 BOM
        static bool firstLine = true;
        if (firstLine) {
            firstLine = false;
            if (line.size() >= 3 &&
                (unsigned char)line[0] == 0xEF &&
                (unsigned char)line[1] == 0xBB &&
                (unsigned char)line[2] == 0xBF) {
                line = line.substr(3);
            }
        }
        if (!line.empty() && line.back() == '\r') line.pop_back();

        std::string t = ini_trim(line);
        if (t.empty() || t[0] == ';' || t[0] == '#') continue;

        if (t[0] == '[') {
            size_t e = t.find(']');
            if (e != std::string::npos) section = t.substr(1, e - 1);
            continue;
        }

        size_t eq = t.find('=');
        if (eq == std::string::npos) continue;
        std::string key = ini_trim(t.substr(0, eq));
        std::string val = ini_trim(t.substr(eq + 1));

        if (section == "Meta") {
            out.meta[key] = val;
            if (key == "BaseRVA") out.baseRVA = val;
            else if (key == "Encoding") out.encoding = val;
            else if (key == "Layout") out.layout = val;
            else if (key == "Count") out.count = atoi(val.c_str());
            continue;
        }

        if (section == "Entries" || section == "Explicit") {
            // 值里可能含 "; 英文原文 [备注] cap=N"
            std::string zh = val;
            std::string comment;
            size_t semi = val.find(" ; ");
            if (semi != std::string::npos) {
                zh = ini_trim(val.substr(0, semi));
                comment = val.substr(semi + 3);
            }

            IniEntry e;
            e.rva = 0;
            e.capacity = 0;
            if (section == "Explicit") {
                // key 形如 "0x000D0714"
                e.rva = (DWORD)strtoul(key.c_str(), nullptr, 16);
                e.index = 0;
            } else {
                e.index = atoi(key.c_str());
            }
            e.zh = zh;

            // 解析 comment: "English [note] cap=N"
            std::string c = comment;
            size_t capPos = c.find("cap=");
            if (capPos != std::string::npos) {
                size_t capEnd = c.find_first_of(" \t", capPos);
                std::string capStr = c.substr(capPos + 4, capEnd == std::string::npos
                                              ? std::string::npos : capEnd - capPos - 4);
                e.capacity = atoi(capStr.c_str());
                c = c.substr(0, capPos);
            }
            size_t br = c.find('[');
            if (br != std::string::npos) {
                e.en = ini_trim(c.substr(0, br));
                size_t be = c.find(']', br);
                if (be != std::string::npos) e.note = c.substr(br + 1, be - br - 1);
                else e.note = c.substr(br + 1);
            } else {
                e.en = ini_trim(c);
            }

            out.entries.push_back(e);
        }
    }
    return true;
}
