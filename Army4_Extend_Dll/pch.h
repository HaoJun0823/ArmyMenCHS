// pch.h: 这是预编译标头文件。
// 下方列出的文件仅编译一次，提高了将来生成的生成性能。
// 这还将影响 IntelliSense 性能，包括代码完成和许多代码浏览功能。
// 但是，如果此处列出的文件中的任何一个在生成之间有更新，它们全部将被重新编译。
// 请勿在此处添加要频繁更新的标头。

#ifndef PCH_H
#define PCH_H

// 添加要在此处预编译的标头
#include "framework.h"

// ★ 本项目的源文件全部是 UTF-8（含大量中文注释）。
//   MSVC 在无 BOM 时按当前代码页解释源文件，会报 C4819 或产生乱码字符串。
//   工程里统一加了 /utf-8（见 vcxproj），这里再 include 常用头。
#include <cstdio>
#include <cstdarg>
#include <cstring>
#include <string>
#include <vector>

#endif //PCH_H
