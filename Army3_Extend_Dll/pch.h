// pch.h: 预编译标头。
//
// ★ 为什么把 <string>/<vector> 放进 pch：
//   hooks.cpp / target.cpp 都用到，且 /MT 静态 CRT 下反复包含会显著拖慢编译。

#ifndef PCH_H
#define PCH_H

#include "framework.h"

#include <string>
#include <vector>

#endif //PCH_H
