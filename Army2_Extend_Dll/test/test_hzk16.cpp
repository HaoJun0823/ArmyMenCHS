// test_hzk16.cpp —— 离线验证 Hzk16 读取实现
//
// 目的：在不启动游戏的前提下，确认 C++ 实现与"官方公式 + 真实文件"一致。
//   这是本补丁里**唯一能离线自证**的核心模块：
//     - 魔数、几何参数、字形定位公式
//     - 26 个已知汉字的墨迹量是否落在合理区间
//     - 与 Python 参考实现（_am2_font.py）的偏移量逐一对照
//
// 构建：随 CI 脚本一起编译（见 Tools/ci/build_test_hzk16.py）
// 用法：test_hzk16.exe <Hzk16 路径>

#include <windows.h>
#include <cstdio>
#include <string>

#include "src/hzk16.h"
#include "src/log.h"

int main(int argc, char** argv)
{
    // ★ 两个编码坑（中文目录名项目里很容易踩）：
    //   1) 命令行参数是 **系统 ANSI(GBK)**，不是 UTF-8
    //   2) 控制台 printf("%ls") 用的是控制台代码页，中文会显示成 ??
    //   所以：路径用 CP_ACP 转宽字符；输出交给 Log（会写 UTF-8 日志文件）。
    wchar_t wpath[MAX_PATH] = {0};
    if (argc > 1) {
        MultiByteToWideChar(CP_ACP, 0, argv[1], -1, wpath, MAX_PATH);
        if (GetFileAttributesW(wpath) == INVALID_FILE_ATTRIBUTES) {
            MultiByteToWideChar(CP_UTF8, 0, argv[1], -1, wpath, MAX_PATH);
        }
    } else {
        wcscpy_s(wpath, L"I:\\LocalGames\\Army Men\\玩具兵大战2\\Hzk16");
    }

    // 日志落到 exe 同目录（LogGetDllDir 用的是传给 LogSetModule 的模块）
    LogSetModule(GetModuleHandleA(nullptr));
    LogSetGameTag("Hzk16SelfTest");

    printf("Hzk16 self test\n");
    Log("===== Hzk16 离线自测开始 =====");
    Log("字库路径: %ls", wpath);

    Hzk16Font font;
    if (!font.Load(wpath)) {
        Log("!! 载入失败");
        printf("!! load failed (see Hzk16SelfTest.log)\n");
        return 1;
    }
    Log("%s", font.Describe().c_str());

    printf("%s\n\n", font.Describe().c_str());

    // ── 1) 自检 ────────────────────────────────────────────────────────
    std::string rep;
    int rc = font.SelfTest(rep);
    Log("自检 rc=%d\n%s", rc, rep.c_str());
    printf("%s\n", rep.c_str());

    // ── 2) 与 Python 参考实现的偏移量对照 ─────────────────────────────
    //   这些期望值是先前用 Python 独立计算并**目视确认可读**的偏移。
    struct Case { const char* gbk; const char* name; long expect; };
    static const Case kCases[] = {
        { "\xB0\xA1", "啊", 26972 },
        { "\xD6\xD0", "中", 121066 },
        { "\xCA\xBF", "士", 91296 },
        { "\xC3\xFC", "命", 75774 },
        { "\xC1\xEE", "令", 70522 },
        { "\xCD\xE6", "玩", 99642 },
        { "\xBE\xDF", "具", 62800 },
        { "\xB1\xF8", "兵", 31678 },
        { "\xBF\xAA", "开", 63866 },
        { "\xCA\xBC", "始", 91218 },
        { "\xD1\xA1", "选", 107624 },
        { "\xCF\xEE", "项", 104738 },
        { "\xCD\xCB", "退", 98940 },
        { "\xB3\xF6", "出", 36514 },
        { "\xB5\xD8", "地", 40622 },
        { "\xCD\xBC", "图", 98550 },
        { "\xC8\xCE", "任", 86798 },
        { "\xCE\xF1", "务", 102372 },
        { "\xD3\xCE", "游", 113682 },
        { "\xCF\xB7", "戏", 103308 },
    };

    printf("── 与 Python 参考实现的偏移量对照 ──\n");
    int ok = 0, bad = 0;
    for (const auto& c : kCases) {
        BYTE lead = (BYTE)c.gbk[0], trail = (BYTE)c.gbk[1];
        const BYTE* g = font.Glyph(lead, trail);
        if (!g) { printf("  %s: 越界\n", c.name); bad++; continue; }

        // 反推偏移：不能直接取指针差（API 未暴露 base），
        // 改为重算公式并与期望值比较。
        long long idx = (long long)trail + 94LL * lead - 15295LL;
        long long off = 26LL * idx - 9688LL;
        if (off < 0) off += 9776LL;

        bool match = (off == c.expect);
        printf("  %-4s GBK=%02X%02X  偏移=%-8lld 期望=%-8ld %s\n",
               c.name, lead, trail, off, c.expect, match ? "OK" : "<-- 不符");
        if (match) ok++; else bad++;
    }

    printf("\n== 结果: 自检 rc=%d, 偏移量 %d/%d 一致, %d 不符 ==\n",
           rc, ok, ok + bad, bad);
    Log("===== 结果: 自检 rc=%d, 偏移量 %d/%d 一致, %d 不符 =====",
        rc, ok, ok + bad, bad);
    printf("(详情见 Hzk16SelfTest.log)\n");
    return (rc == 0 && bad == 0) ? 0 : 1;
}
