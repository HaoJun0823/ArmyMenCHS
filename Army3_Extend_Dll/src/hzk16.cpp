#include "pch.h"
#include "hzk16.h"
#include "log.h"

#include <cstdio>
#include <cstring>

// ────────────────────────────────────────────────────────────────────────
// 官方公式（AM2 中文版 exe sub_426DB0 逐字还原）：
//     v2 = height * ((width + 7) >> 3) * (trail + 94*lead - 15295) - 9688;
//     if (v2 < 0) v2 += 9776;
//     return base + v2;
//
// 已验证：(202966 - 16) / 26 = 7805.77，与"数据自 0x694C 起、6768 字形"吻合。
//
// 3 代：这套公式我们**自己**用来定位点阵，不依赖 3 代 exe（它不含该字库）。
// ────────────────────────────────────────────────────────────────────────

static const DWORD MAGIC_RSE = 0x1A455352;   // 'R','S','E',0x1A 小端

Hzk16Font::Hzk16Font() {}
Hzk16Font::~Hzk16Font() {
    if (m_data) { free(m_data); m_data = nullptr; }
}

static WORD rd16(const BYTE* p) { WORD v; memcpy(&v, p, 2); return v; }
static DWORD rd32(const BYTE* p) { DWORD v; memcpy(&v, p, 4); return v; }

// GBK -> UTF-8（仅用于日志可读；内部比较一律用原始 GBK 字节）
static std::string GbkToUtf8(const char* s, size_t n) {
    if (!s || n == 0) return {};
    int nw = MultiByteToWideChar(936, 0, s, (int)n, nullptr, 0);
    if (nw <= 0) return {};
    std::wstring w(nw, L'\0');
    MultiByteToWideChar(936, 0, s, (int)n, &w[0], nw);
    int nu = WideCharToMultiByte(CP_UTF8, 0, w.c_str(), nw, nullptr, 0, nullptr, nullptr);
    if (nu <= 0) return {};
    std::string u(nu, '\0');
    WideCharToMultiByte(CP_UTF8, 0, w.c_str(), nw, &u[0], nu, nullptr, nullptr);
    return u;
}

bool Hzk16Font::Load(const wchar_t* path) {
    if (m_data) { free(m_data); m_data = nullptr; }

    HANDLE h = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, nullptr,
                           OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) {
        Log("Hzk16: 打不开 %ls (err=%lu)", path, GetLastError());
        return false;
    }
    LARGE_INTEGER li;
    if (!GetFileSizeEx(h, &li) || li.QuadPart <= 0) {
        Log("Hzk16: 取大小失败");
        CloseHandle(h);
        return false;
    }
    m_size = (DWORD)li.QuadPart;
    m_data = (BYTE*)malloc(m_size);
    if (!m_data) { Log("Hzk16: 分配 %u 字节失败", m_size); CloseHandle(h); return false; }

    DWORD got = 0;
    BOOL ok = ReadFile(h, m_data, m_size, &got, nullptr);
    CloseHandle(h);
    if (!ok || got != m_size) {
        Log("Hzk16: 读取不完整 got=%u/%u", got, m_size);
        free(m_data); m_data = nullptr;
        return false;
    }

    if (m_size < 0x5C) {
        Log("Hzk16: 文件太小 (%u)", m_size);
        free(m_data); m_data = nullptr;
        return false;
    }

    DWORD magic = rd32(m_data);
    if (magic != MAGIC_RSE) {
        Log("Hzk16: 魔数不符 期望 'RSE\\x1a' 实得 %08X", magic);
        free(m_data); m_data = nullptr;
        return false;
    }

    // ── 读文件头 ──────────────────────────────────────────────────────
    // ★ 字段宽度必须按实测来，不能想当然：
    //   0x48 是 DWORD（数据起始偏移 0x694C）
    //   0x50 是 **WORD**（26 = 每字形字节数）
    //   0x52 是 **WORD**（6768 = 字形总数）
    //   2 代曾把 0x50/0x52 都当 DWORD 读，结果 bpg 读成了 0x1A70001A
    //   （两个相邻 WORD 被重叠读出），几何校验失败、字库被误判为不可用。
    int hw = rd16(m_data + 0x14);
    int hh = rd16(m_data + 0x16);
    m_rangeLo = rd16(m_data + 0x18);
    m_rangeHi = rd16(m_data + 0x1C);
    m_dataStart = rd32(m_data + 0x48);
    m_bpg = (int)rd16(m_data + 0x50);
    m_glyphCount = (DWORD)rd16(m_data + 0x52);

    // 字体名（GBK，NUL 结尾）
    {
        const char* nm = (const char*)(m_data + 0x20);
        size_t maxn = 0x48 - 0x20;
        size_t n = strnlen(nm, maxn);
        m_faceName.assign(nm, n);
    }

    m_width = hw; m_height = hh;

    // ── 用官方公式反推几何，与文件头交叉校验 ─────────────────────────
    //  官方是硬编码 13x13 -> 2 字节/行 -> 26 字节/字形。
    //  若文件头的 w/h/bpg 与此不符，说明这不是那份字库，
    //  此时**拒绝加载**而不是猜（避免渲染出垃圾）。
    int rowBytes = (m_width + 7) >> 3;
    int formulaBpg = rowBytes * m_height;
    m_headerTrusted = (m_width == 13 && m_height == 13 && m_bpg == 26 &&
                       formulaBpg == m_bpg);

    Log("Hzk16: 载入 %u 字节  宽=%d 高=%d bpg=%d 字形数=%u 数据起=%#x 名='%s' 范围=%04X-%04X",
        m_size, m_width, m_height, m_bpg, m_glyphCount, m_dataStart,
        GbkToUtf8(m_faceName.c_str(), m_faceName.size()).c_str(), m_rangeLo, m_rangeHi);

    if (!m_headerTrusted) {
        // 硬编码公式要求 13x13；官方渲染器也是按 13x13 写死的。
        // 不满足就禁用，宁可退化成英文也不画错。
        Log("Hzk16: !! 几何与官方硬编码(13x13/26B)不符，禁用中文字形");
        free(m_data); m_data = nullptr;
        return false;
    }

    // 数据区必须放得下声明的字形数
    ULONGLONG need = (ULONGLONG)m_dataStart + (ULONGLONG)m_glyphCount * m_bpg;
    if (need > m_size) {
        Log("Hzk16: !! 数据区越界，需要 %llu 实有 %u（头信息可能不可信）", need, m_size);
        // 不致命：官方公式可能访问不到那么远。但记下来。
    }

    Log("Hzk16: OK（与官方公式自洽）");
    return true;
}

const BYTE* Hzk16Font::Glyph(BYTE lead, BYTE trail) const {
    if (!m_data) return nullptr;
    // 官方公式
    long long idx = (long long)trail + 94LL * (long long)lead - 15295LL;
    long long off = (long long)m_bpg * idx - 9688LL;
    if (off < 0) off += 9776LL;
    if (off < 0) return nullptr;
    if ((unsigned long long)off + m_bpg > m_size) return nullptr;
    return m_data + off;
}

bool Hzk16Font::TestBit(const BYTE* glyph, int x, int y, int bytesPerRow) {
    if (!glyph || x < 0 || y < 0) return false;
    int rowBytes = bytesPerRow;
    const BYTE* row = glyph + y * rowBytes;
    int byteIdx = x >> 3;
    int bit = 7 - (x & 7);
    return (row[byteIdx] & (1 << bit)) != 0;
}

int Hzk16Font::SelfTest(std::string& report) const {
    if (!m_data) { report = "未加载"; return -1; }

    // 用一组已知汉字验证：每个字的墨迹量应落在合理区间
    // （13x13=169 像素，正常汉字墨迹约 15~80 像素）
    static const char* kTests[] = {
        "\xD6\xD0",   // 中
        "\xCA\xBF",   // 士
        "\xC3\xFC",   // 命
        "\xC1\xEE",   // 令
        "\xCD\xE6",   // 玩
        "\xBE\xDF",   // 具
        "\xB1\xF8",   // 兵
        "\xBF\xAA",   // 开
        "\xCA\xBC",   // 始
        "\xD1\xA1",   // 选
        "\xCF\xEE",   // 项
        "\xCD\xCB",   // 退
        "\xB3\xF6",   // 出
    };
    int rowBytes = (m_width + 7) >> 3;
    int nOk = 0, nBad = 0;
    char buf[256];
    std::string detail;

    for (const char* t : kTests) {
        BYTE lead = (BYTE)t[0], trail = (BYTE)t[1];
        const BYTE* g = Glyph(lead, trail);
        if (!g) {
            snprintf(buf, sizeof(buf), "  %02X%02X: 越界\n", lead, trail);
            detail += buf; nBad++;
            continue;
        }
        int ink = 0;
        for (int y = 0; y < m_height; y++)
            for (int x = 0; x < m_width; x++)
                if (TestBit(g, x, y, rowBytes)) ink++;
        bool ok = (ink >= 8 && ink <= 110);
        snprintf(buf, sizeof(buf), "  %02X%02X: 墨迹=%3d %s\n",
                 lead, trail, ink, ok ? "OK" : "<-- 可疑");
        detail += buf;
        if (ok) nOk++; else nBad++;
    }

    snprintf(buf, sizeof(buf),
             "自检: %d/%d 通过, %d 可疑\n", nOk, nOk + nBad, nBad);
    report = std::string(buf) + detail;
    return nBad == 0 ? 0 : 1;
}

std::string Hzk16Font::Describe() const {
    if (!m_data) return "Hzk16: <未加载>";
    char buf[256];
    snprintf(buf, sizeof(buf),
             "Hzk16: %ux%u, %d B/字形, %u 字形, data@%#x, face='%s'",
             m_width, m_height, m_bpg, m_glyphCount, m_dataStart,
             GbkToUtf8(m_faceName.c_str(), m_faceName.size()).c_str());
    return buf;
}
