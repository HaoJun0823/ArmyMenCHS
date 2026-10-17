#include "pch.h"
#include "renderer.h"
#include "target.h"     // RenderKind
#include "hzk16.h"
#include "log.h"

#include <cstring>
#include <cstdio>

// ════════════════════════════════════════════════════════════════════════
//  热路径诊断日志开关
//
//  排查崩溃/花屏时加的 DiagLogText 与逐字形 ink 日志，位于 RenderCore
//  /DrawCjk 这些**每帧每个字符串/每个汉字都会进入**的热路径上。
//
//  后果（4 代实测）：控制设置界面的主循环每秒重绘上万个字符串，每 200 次
//  渲染调用就做一次完整的 Log() = fopen + fwrite + fclose + vsnprintf，
//  累积成每秒数十次磁盘 IO，把渲染循环拖卡顿。
//
//  处置：正式游玩时置 1（关闭热路径日志），仅保留初始化/安装的一次性日志
//  （Detect / Hzk16 / InstallAll 那些，单次执行、无卡顿）。
//  排障时改回 0 即可重新获得逐字形诊断。
#define CHS_DISABLE_HOTLOGGING 1

// ════════════════════════════════════════════════════════════════════════
//  Army Men: Air Tactics —— 文字渲染接管（本作）
//
//  全部结论来自本轮 IDA 逆向（反编译 + disasm 逐字节）。
//  本作函数的地址、参数形态、序言与 patchLen 依据见 src\target.cpp 的档位表；
//  完整证据见 docs/15-am5-reverse-findings.md。
//
//  ── 本作文字函数的真实语义（已还原，逐条对应反编译）───────────────
//
//   LEFT   sub_488640(int x, int y, char* Str, int font, int a5, char color)
//            if (!dword_63C64C) return;             // 表面未锁定 -> 整函数返回
//            x = clamp(x, 0, 790); y = clamp(y, 0, 590);   // ★ LEFT 独有
//            循环:
//              '^' + 非末字节 -> color = 下一字节, 跳过 2 字节
//              否则:
//                glyph = atlasBase[font] + atlasOffset[262*font + c]
//                w = glyph[0]; h = glyph[1];
//                desc = {0,0,w,h}
//                if (!rect(desc, &rcSrc2, &x, &y, out)) return;  // ★ 裁光则整函数返回
//                if (locked == primary) { x += rc.left; y += rc.top; }
//                blit(...)
//                x += w                                 // ★ 按**宽**推进
//            返回最后一次的字符索引 + 1（**调用方不消费**）
//
//   DIALOG sub_4887F0(x, y, Str, font, l, t, r, b, color)
//            ★ **无** 坐标 clamp
//            两级 rect：先 rcSrc2，再把结果与调用方 RECT {l,t,r,b} 求交
//            裁光 -> **跳过该字形**（不是整个返回）
//            x += w                                     // ★ 按**宽**推进
//
//   GRADIENT sub_488B90(x, y, Str, font?, l, t, r, b, unknown)
//            ★ 用的是**另一套单字节字体表** word_C87E5C / dword_C8805C，
//              与 C86DFC / C86FFC **完全无关**（全文件各只有 1 处引用）。
//            逐字用 sub_488A60 算渐变颜色（按坐标分段变色）。
//            中文永远不会走到这里 -> **不接管绘制**，仅保留识别校验。
//
//   MEASURE  sub_4885B0(char* Str, int font, int* out) -> int
//            for c: '^' -> 跳过 2; else if (c >= 0x1F) result += glyph[0]
//            if (out) { out[0] = result; out[1] = 空格字形的 gh[1]; }
//            ★ out[1] 原版取自 word_C86E3C[262*font]（= atlasOffset[262*font + 32]，
//              即**空格**的字形偏移），再 +base 后取 WORD[1] = 行高。
//
//   MEASURE_H sub_488CF0(char* Str, int font) -> int
//            for c: '^' -> 跳过 2; else if (c >= 0x1F) result += glyph[1] - 3
//
//  ── 与 2/3/4 代的决定性差异（决定了本文件不能照搬）──────────────
//
//   ① **没有 CENTER**（4/3 代都有）。全部渲染器都沿 x 累加，
//      本文件因此没有 axisY 分支。
//
//   ② 返回值是 int，但语义是"字符索引残值"，**不是** 2 代那种
//      "文本结束后的 x"。所有调用点都不消费它（实测 23 个 xref，
//      全是 `call` 后立刻画下一段固定文本）。
//      -> 我们返回已处理字符数，与"残值"同构，且绝不返回 0
//         （2 代曾因 `return 0` 导致"创建玩家档案输入不了"）。
//
//   ③ patchLen 与 4 代不同（DIALOG 14 vs 15），见 target.h。
//
//  ── 策略：ASCII 转调 stub，CJK 自绘 ──────────────────────────────────
// ════════════════════════════════════════════════════════════════════════

// ════════════════════════════════════════════════════════════════════════
//  sub_455BA0 的真实签名（★ 这里曾经写错，是本作"中文不显示"的根因）
// ════════════════════════════════════════════════════════════════════════
//
//  反汇编实测（amat.exe 0x455BA0）：
//      ecx = [esp+4]  = desc
//      eax = desc[0] + x      ;  左边界
//      edx = desc[2] + x      ;  右边界
//      edi = desc[1] + y      ;  上边界
//      ebx = desc[3] + y      ;  下边界
//      esi = clip[0] ... 与上面四个比较、求交
//      → 返回 1 并把存活部分写进 out
//
//  ★★ 三个必须同时满足的语义（错一个就是"中文一个字都不画"）★★
//
//   ① x / y 是**按值传的整数**，不是指针。
//      我最初按 3/4 代的习惯写成 `int* px, int* py`，于是把 &x/&y 传进去，
//      游戏拿到的"坐标"是栈地址（≈0x001AFC80，一千多万），
//      裁剪框怎么算都落空 → 每个汉字都被判为"裁光"。
//
//   ② desc 的语义是 {left, top, right, bottom}，其中 right/bottom 是
//      **相对同一原点的坐标**，不是宽高。
//      官方 ASCII 传 {0, 0, w, h}，因为 left/top 都是 0，
//      所以 w/h 恰好等价于 right/bottom —— 这个巧合曾让人误以为它们是宽高。
//
//   ③ out 的语义同样是**相对 (x, y) 的坐标**：
//          out[0], out[1] = 存活区左上角相对 (x,y) 的偏移
//          out[2], out[3] = 存活区右下角相对 (x,y) 的坐标
//      所以落笔位置 = (x + out[0], y + out[1])，
//      可见尺寸 = (out[2]-out[0], out[3]-out[1])。
//      ★ 官方 DIALOG 的第二次裁剪就是把第一次的 out 当 desc 再传一次、
//        并且**仍然传原来的 x/y** —— 因为 out 本来就是相对 x/y 的。
//        我当初以为要传 0 才不重复累加，那个方向是错的。
typedef int (__cdecl *PFN_rect)(const void* desc, void* rcSrc,
                                int x, int y, void* outRect);
typedef void (__fastcall *PFN_blit)(int src, int x, int y, int w, int h, char color);

extern Hzk16Font* g_pFont;      // 定义在 hooks.cpp

static RendererEnv g_env;

struct Installed {
    BYTE* target = nullptr;
    BYTE  orig[16] = {0};
    int   len = 0;
    int   kind = 0;
};
static Installed g_hooks[8];
static int  g_hookCount = 0;

static volatile LONG g_measureCalls = 0;
static volatile LONG g_measureHCalls = 0;
static volatile LONG g_calls = 0;
static volatile LONG g_cjkGlyphs = 0;
static volatile LONG g_asciiFail = 0;
static volatile LONG g_noSurface = 0;
static volatile LONG g_clampHits = 0;

void RendererSetEnv(const RendererEnv& env) { g_env = env; }
bool RendererIsInstalled() { return g_hookCount > 0; }

void RendererStats(LONG* calls, LONG* cjk, LONG* asciiFail) {
    if (calls)     *calls = g_calls;
    if (cjk)       *cjk = g_cjkGlyphs;
    if (asciiFail) *asciiFail = g_asciiFail;
}

static inline BYTE* ImageBase() { return (BYTE*)GetModuleHandleA(nullptr); }

// ── 地址语义（摔过两次的坑，改动前务必读完）──────────────────────────
//
//  下面所有 VA 字段都是**绝对虚拟地址**（IDA 里显示的值），
//  读取时**必须原样当地址用，绝不能再加 ImageBase**。
//
//  2 代崩溃证据（dump 0x188028）：
//      *(BYTE**)(ImageBase() + 0x4FE1A8) = *(BYTE**)(0x008FE1A8)  ← 野地址
//  而正确的目标正是 ECX 里的 0x4FE1A8。
//
//  ★ 唯一的例外是 atlasBase：那个全局的**内容**是 malloc 的堆指针，
//    取出来也要原样当指针用 —— 这两处的"正确做法"恰好一致：
//    **不要加 ImageBase**。
static inline BYTE* VaToPtr(DWORD va) { return (BYTE*)(DWORD_PTR)va; }

static inline BYTE* SurfacePtr() {
    // 目标像素缓冲指针（每次调用重读：DirectDraw 表面可能被重建）
    return *(BYTE**)VaToPtr(g_env.surfaceVA);
}
static inline int Pitch() {
    return *(int*)VaToPtr(g_env.pitchVA);
}
// atlas 基址：全局内容 = malloc 出的堆指针，原样用
static inline BYTE* AtlasBase(int font) {
    DWORD v = *(DWORD*)VaToPtr(g_env.atlasBaseVA + 4 * font);
    return v ? (BYTE*)(DWORD_PTR)v : nullptr;
}
static inline WORD* AtlasOffset(int font) {
    return (WORD*)VaToPtr(g_env.atlasOffsetVA + 262 * font * 2);
}

// ★★ 此处刻意**没有** CharWidth(font) 辅助函数 ★★
//
//   它应读 g_env.charWidthVA(0xC86E3C)，而该地址与 atlasOffsetVA(0xC86DFC)
//   只差 0x40 == 32 个 WORD，即
//       CharWidth(font)[c]  ≡  atlasOffset(font)[c + 32]
//   —— **根本不是宽度表，是字形偏移表右移 32 项**。
//
//   实测 3 代 font=2 的值序列：0, 60, 134, 206, 294, 386, 486, 574, … , 3540，
//   是逐字递增的图集字节偏移。当宽度用会让累加器一步跳出裁剪框，
//   症状是"中英混排从第一个 ASCII 字符起整段消失"。
//   保留这个函数只会招来下一次误用，故不写。
//   推进量一律走 SafeGlyphHeader。

// ★★ 本作的**推进量来源**（stub 返回值不可用，这里靠字形头）
//
//   字形头 = atlasBase[font] + atlasOffset[262*font + c]
//     glyph[0] = 字形宽 -> 横向前进量
//     glyph[1] = 字形高 -> 也是行高（本作实测 cy 恰好等于 CreateFontA 的 height）
//
//   ★ atlasBase 为 0 说明图集尚未构建（首次绘制时才建），
//     此时返回 0，由调用方退回经验值，保证循环终止。
static inline WORD* GlyphHeader(int font, BYTE c) {
    BYTE* base = AtlasBase(font);
    if (!base) return nullptr;
    WORD* offs = AtlasOffset(font);
    if (!offs) return nullptr;
    return (WORD*)(base + offs[c]);
}

// ★★ 加固版字形头（3 代实机崩溃修复：RVA 0x4D5C 空指针读）
//
//  原 GlyphHeader 的缺陷：`base + offs[c]` 里的 offs[c] 是引擎在
//  图集"正在重建/半更新"状态下写入的异常值，加法结果会落到一片
//  不可读的页上；直接返回后外层 `movzx eax,[eax]` 就会空读 AV
//  （3 代实测 EAX=0，异常地址 ASI+0x4D5C）。
//
//  这里在解引用前先用 VirtualQuery 验证目标页存在且可读：
//    - 页不存在 / 未提交 / 不可读   -> 返回 nullptr（调用方安全回退）
//    - 可读                         -> 返回字形头
//  每次 ASCII 字符调用一次 VirtualQuery 的开销可忽略；
//  渲染仍是热的，但推进量的"取字形头"是唯一空读来源，必须钉死。
static inline WORD* SafeGlyphHeader(int font, BYTE c) {
    BYTE* base = AtlasBase(font);
    if (!base) return nullptr;
    WORD* offs = AtlasOffset(font);
    if (!offs) return nullptr;

    WORD* glyph = (WORD*)(base + offs[c]);

    MEMORY_BASIC_INFORMATION mbi;
    if (VirtualQuery(glyph, &mbi, sizeof(mbi)) == 0)
        return nullptr;
    if (mbi.State != MEM_COMMIT)
        return nullptr;
    if (!(mbi.Protect & (PAGE_READONLY | PAGE_READWRITE |
                         PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE |
                         PAGE_EXECUTE_WRITECOPY)))
        return nullptr;

    return glyph;
}

// ── 全局裁剪矩形 rcSrc2 ────────────────────────────────────────────────
//
// ★★ "文字渐显时花屏"的成因（2 代用户反馈，且明确指出"之前版本没有"）
//
//   (a) 最初只判屏幕边界；
//   (b) 上一轮改用调用方的 clip 矩形裁剪 —— 但 LEFT 只有 6 个参数、
//       **没有**裁剪矩形，传进来的 clip 全是 0 -> hasClip==false ->
//       整个上界判断被短路，只挡住"小于 0"的一侧。
//       文字向右/向下越过表面下界时不再被拦，直接写出缓冲区 -> 花屏。
//       渐显/滚动恰好让文字部分越界，所以"出现时花屏、全显示后正常"。
//
//   修法：恢复上界，并补上原版真正使用的裁剪来源 rcSrc2。
//   本作实测同样是每个字形先走 rcSrc2：
//       sub_455BA0(&desc, &stru_510A38, &x, &y, out)
struct ClipRect { int l, t, r, b; bool valid; };

static ClipRect GlobalClip()
{
    ClipRect c{0, 0, 0, 0, false};
    if (!g_env.clipRectVA) return c;
    const int* p = (const int*)VaToPtr(g_env.clipRectVA);
    c.l = p[0]; c.t = p[1]; c.r = p[2]; c.b = p[3];
    // 只接受"非空正矩形"（仅用于日志可读性；裁剪本身交给游戏函数）
    c.valid = (c.r > c.l) && (c.b > c.t);
    return c;
}

// ★ 直接把 rcSrc2 的地址交给游戏自己的 rect 函数（sub_455BA0）。
//   官方就是这么做的：rect(desc, &rcSrc2, ...) —— 由游戏决定怎么解读。
//   我不再自己判断"矩形是否有效"：0 矩形就该裁光一切，这是原版语义。
static void* GlobalClipPtr()
{
    if (!g_env.clipRectVA) return nullptr;
    return (void*)VaToPtr(g_env.clipRectVA);
}

// ── 落笔原点偏移 rc（原版在 blit 前做，2 代最初漏了）──────────────────
//
// 本作实测（sub_488640 / sub_4887F0 内联，不是函数调用）：
//     mov eax, dword_651850      ; 当前表面
//     cmp eax, dword_64119C      ; 主表面
//     jnz skip
//     add x, rc.left ; add y, rc.top
//
// rc 由窗口消息更新（WM_SIZE/WM_MOVE → GetClientRect + ClientToScreen，
// 见 sub_40E540 case 3/5），含义是"后备缓冲在主表面中的左上角"。
//
// ★ 这解释了 2 代"首次进入正常、后续花屏"：
//   首次进入某界面时 rc 往往是 (0,0)，之后窗口/分辨率变化使 rc 非零，
//   字形整体偏移 -> 花屏。
static inline void GetRcOrigin(int* ox, int* oy)
{
    *ox = 0; *oy = 0;
    if (!g_env.rcVA || !g_env.lockedSurfVA || !g_env.primarySurfVA) return;
    const DWORD locked = *(const DWORD*)VaToPtr(g_env.lockedSurfVA);
    const DWORD primary = *(const DWORD*)VaToPtr(g_env.primarySurfVA);
    if (locked != primary) return;
    const int* rc = (const int*)VaToPtr(g_env.rcVA);
    *ox = rc[0];   // rc.left
    *oy = rc[1];   // rc.top
}

// 显示区尺寸（只作像素写入的**内存安全上界**；语义裁剪仍由 rcSrc2 决定）
static int DisplayW()
{
    if (!g_env.dispWVA) return 0;
    int v = *(const int*)VaToPtr(g_env.dispWVA);
    return (v >= 160 && v <= 4096) ? v : 0;
}
static int DisplayH()
{
    if (!g_env.dispHVA) return 0;
    int v = *(const int*)VaToPtr(g_env.dispHVA);
    return (v >= 120 && v <= 4096) ? v : 0;
}

// ── CJK 几何 ────────────────────────────────────────────────────────────
//
// ★ 本作与 3/4 代的一个**实测差异**，决定了这里不能照抄：
//   3/4 代的 CJK 逻辑盒固定 15（因为那两作的字体逻辑尺寸一致）。
//   本作有 **9 个字体档**（sub_446AA0: for i<9），实测 GDI 字符单元高度
//   分别是 8 / 12 / 15 / 18 / 18 / 24 / 12 / 14 / 16 —— **跨度 3 倍**。
//   若固定用 15，小字号会严重溢出（8 的档位），大字号会缩成一小点（24 的档位）。
//
//   正确做法：**逐字体档从字形头取盒子高度**（gh[1]）。
//   与原版 ASCII 的推进量同源，混排时基线与步进自动对齐。
//   ★ gh[1] 与 CreateFontA 传入的 height 完全相等（已用 GDI 实测复现，
//     9 档全部吻合：8/12/15/18/18/24/12/14/16），
//     所以这个取法不是"猜"，是把引擎自己的度量拿来用。
//
//   ★ 点阵本身固定 13x13（Hzk16 的规格），**不缩放**：
//     与 2/3/4 代一致，放大缩小会造成笔画断裂。
//     因此当 box != 13 时，点阵与逻辑盒的关系必须显式定义：
//       - box >= 13：点阵顶格放置（与 ASCII 一样从单元格顶部开始），
//                    汉字底部会留白 —— 视觉上偏上，但**基线一致**
//       - box <  13：点阵会超出逻辑盒。此时按"水平居中于盒宽、
//                    垂直取盒内可见部分"处理，避免把邻居的字盖掉。
//     选这个策略而不是缩放，是因为游戏 9 档字体里有 8px 的极小档，
//     13x13 点阵压到 8x8 后基本不可读。
static const int CJK_INK_W = 13;   // 点阵实际列数
static const int CJK_INK_H = 13;   // 点阵实际行数

// ★★ 本作 9 个字体档的字形单元高（GDI 实测，不是猜的）★★
//
//  用 CreateFontA 按 sub_4883A0 的原参数（face/height/weight）在本机重建，
//  再 GetTextExtentPoint32A 逐字符量，得到 cy 与 CreateFontA 传入的 height
//  **完全相等**：
//      idx : face             height : 实测 cy
//       0  : <默认>              8   :   8
//       1  : <默认>             12   :  12
//       2  : Arial Narrow       15   :  15
//       3  : Arial Black        18   :  18
//       4  : <默认>             18   :  18
//       5  : Arial Black        24   :  24
//       6  : Times New Roman    12   :  12
//       7  : Times New Roman    14   :  14
//       8  : Times New Roman    16   :  16
//
//  所以正常情况下直接读字形头 gh[1] 就能拿到正确值。
//  只有当**图集尚未构建**（atlasBase[font]==0，例如首次绘制前）时读不到，
//  这时按下面这张表兜底 —— 比一律用 15 准确得多
//  （本作有 24px 档，用 15 会让汉字只有该档的 62% 高）。
static const int CJK_BOX_BY_FONT[9] = { 8, 12, 15, 18, 18, 24, 12, 14, 16 };
static const int CJK_FALLBACK_BOX = 15;   // 档位越界时的最后兜底

// 取该字体档的 CJK 逻辑盒高度（优先字形头，其次实测表）
static inline int CjkBox(int font) {
    WORD* gh = SafeGlyphHeader(font, (BYTE)'A');
    if (gh) {
        int h = (int)gh[1];
        if (h >= 6 && h <= 64) return h;
    }
    if (font >= 0 && font < 9) return CJK_BOX_BY_FONT[font];
    return CJK_FALLBACK_BOX;
}

// 绘制结果三态 —— 对应官方两处不同的失败处理
enum CjkResult {
    CJK_OK    = 0,   // 已绘制
    CJK_SKIP  = 1,   // 被裁光，跳过该字形（DIALOG 语义）
    CJK_ABORT = 2,   // 被裁光，**整个函数返回**（LEFT 语义）
};

// 画一个 13x13 汉字点阵，裁剪完全走游戏自己的 rect 函数（官方同路）。
//   hasClip —— 是否有"调用方裁剪矩形"（仅 DIALOG 有）
//   *ink    —— 出参：写入像素数
static CjkResult DrawCjk(const Hzk16Font& f, BYTE lead, BYTE trail,
                         int dx, int dy, BYTE color, int pitch,
                         int clipL, int clipT, int clipR, int clipB,
                         bool hasClip, int box, int* ink)
{
    if (ink) *ink = 0;
    const BYTE* g = f.Glyph(lead, trail);
    if (!g) return CJK_SKIP;

    PFN_rect rectFn = (PFN_rect)VaToPtr(g_env.rectVA);
    if (!rectFn) return CJK_SKIP;

    // 官方：desc = {0, 0, w, h}，汉字取方块盒 w = h = box
    //   ★ desc 的 right/bottom 是相对同一原点的坐标；因为 left/top 都是 0，
    //     所以 w/h 恰好等于 right/bottom（见 PFN_rect 处的说明②）。
    int desc[4] = { 0, 0, box, box };
    int srcRect[4] = { 0, 0, 0, 0 };

    // ① 全局裁剪 rcSrc2 —— 官方第一步。
    //    LEFT 失败 -> 整个函数返回；DIALOG 失败 -> 跳过该字形。
    //    ★ x/y 按值传（不是指针），见 PFN_rect 处的说明①。
    if (!rectFn(desc, GlobalClipPtr(), dx, dy, srcRect))
        return hasClip ? CJK_SKIP : CJK_ABORT;

    // ② 调用方裁剪矩形 —— 官方第二步（仅 DIALOG），失败只跳过该字形
    //
    //    ★ 官方做法：把第一步的 out（srcRect）当 desc，**仍传原来的 x/y**。
    //      因为 srcRect 里的坐标本来就是相对 (x,y) 的（见说明③），
    //      这样两次求交才是同一个坐标系里的运算。
    int visRect[4] = { srcRect[0], srcRect[1], srcRect[2], srcRect[3] };
    if (hasClip) {
        // ★ 用局部数组而非 &clipL：不依赖"4 个形参在栈上连续"这一实现细节
        int clip[4] = { clipL, clipT, clipR, clipB };
        int dstRect[4] = { 0, 0, 0, 0 };
        if (!rectFn(visRect, clip, dx, dy, dstRect))
            return CJK_SKIP;
        visRect[0] = dstRect[0]; visRect[1] = dstRect[1];
        visRect[2] = dstRect[2]; visRect[3] = dstRect[3];
    }

    // ③ rc 原点偏移 —— 官方在裁剪**之后**加，且仅当画到主表面
    //    ★ 下面写像素时统一用 (dx + advX + ox, dy + advY + oy)，
    //      所以这里只准备 ox/oy，不再预先算 drawX/drawY。
    int ox, oy;
    GetRcOrigin(&ox, &oy);

    // ④ 逐像素写点阵。官方此处不再做语义裁剪（全靠上面的 rect 把关），
    //    我们额外加一道**内存安全网**：夹到显示区 nWidth x nHeight。
    //    正常情况永不触发；触发说明 rcSrc2 越出了显示区（即游戏自身异常），
    //    此时不打日志刷屏，只累加计数。
    BYTE* surface = SurfacePtr();
    if (!surface || pitch <= 0) { InterlockedIncrement(&g_noSurface); return CJK_SKIP; }

    int boundW = DisplayW();
    int boundH = DisplayH();
    const int rowBytes = (f.Width() + 7) >> 3;

    int n = 0;

    // ★ 可见区（相对 (dx,dy)）：横纵各夹到 [lo, hi)。
    //   点阵索引 i/j 与屏幕坐标的关系是 px = dx + adv，其中 adv 是相对偏移。
    //   visRect 里存的正是"相对 (dx,dy) 的存活坐标"，所以直接用。
    const int advX0 = visRect[0], advX1 = visRect[2];
    const int advY0 = visRect[1], advY1 = visRect[3];

    for (int j = 0; j < CJK_INK_H; j++) {           // 纵向
        const int advY = j;                          // 相对 dy 的偏移
        if (advY < advY0 || advY >= advY1) continue; // 语义裁剪（裁剪框外不画）
        const int py = dy + advY + oy;
        if (py < 0) continue;
        if (boundH > 0 && py >= boundH) { InterlockedIncrement(&g_clampHits); continue; }
        // ★ 不越过逻辑盒下界：box < 13 时只画 box 行
        if (box < CJK_INK_H && advY >= box) continue;
        BYTE* dst = surface + (long)py * pitch;
        for (int i = 0; i < CJK_INK_W; i++) {        // 横向
            const int advX = i;                      // 相对 dx 的偏移
            if (advX < advX0 || advX >= advX1) continue;
            const int px = dx + advX + ox;
            if (px < 0) continue;
            if (boundW > 0 && px >= boundW) { InterlockedIncrement(&g_clampHits); continue; }
            // ★ 不越过逻辑盒右界
            if (box < CJK_INK_W && advX >= box) continue;
            if (!Hzk16Font::TestBit(g, i, j, rowBytes)) continue;
            dst[px] = color;
            n++;
        }
    }
    if (ink) *ink = n;
    return CJK_OK;
}

// ── 安装时自检：把所有全局量解引用一遍 ────────────────────────────────
//
// ★ 存在的理由：本项目在"地址语义"上摔了两次
//   （一处少加、一处多加 ImageBase），两次都只能靠实机/回捞 dump 才发现。
//   这个函数在**安装阶段**就把每个全局量读一遍并检查合理性：
//     * 声明的 VA 是否落在本模块映像范围内（最有力的语义检查）
//     * pitch / surface 解引用后是否合理
//   任何一项异常 -> 判定环境不可用 -> 不装 hook -> 游戏保持英文但**不崩**。
bool RendererValidateEnv(std::string* report) {
    std::string r;
    char buf[256];

    BYTE* base = ImageBase();
    IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(base +
        ((IMAGE_DOS_HEADER*)base)->e_lfanew);
    DWORD imgBase = nt->OptionalHeader.ImageBase;
    DWORD imgSize = nt->OptionalHeader.SizeOfImage;

    // 我们填的是**绝对 VA**，所以必须落在 [imgBase, imgBase+imgSize)。
    // 落在外面 = 地址语义搞错（例如把 RVA 当 VA，或反过来）。
    // ★ VA=0 的语义是"该档位不需要 / 尚未测量这项"，不是错误。
    struct Chk { const char* nm; DWORD va; bool required; };
    Chk checks[] = {
        {"surface",   g_env.surfaceVA,      true},
        {"pitch",     g_env.pitchVA,        true},
        {"atlasBase", g_env.atlasBaseVA,    true},
        {"atlasOffs", g_env.atlasOffsetVA,  true},
        // ★ charWidthVA 刻意**不再自检**：它不是宽度表（见 CharWidth 处的
        //   说明），代码里已无任何读取点。字段与 profile 保留仅为地址备查，
        //   列在自检里反而暗示它"可用"，是不必要的误导。
        {"clipRect",  g_env.clipRectVA,     true},   // 裁剪必须转调它
        {"rect",      g_env.rectVA,         true},   // 裁剪函数本体
        {"rc",        g_env.rcVA,           true},   // 落笔原点偏移
        {"lockedSurf",g_env.lockedSurfVA,   true},
        {"primary",   g_env.primarySurfVA,  true},
        {"enabled",   g_env.enabledVA,      true},   // 表面锁标志
        {"dispW",     g_env.dispWVA,        false},  // 显示区宽（安全网用）
        {"dispH",     g_env.dispHVA,        false},  // 显示区高（安全网用）
        {"blit",      g_env.blitVA,         false},  // 本作不调用，登记备查
    };
    bool ok = true;
    snprintf(buf, sizeof(buf), "\n  模块映像: %#010x .. %#010x",
             imgBase, imgBase + imgSize);
    r += buf;
    for (auto& c : checks) {
        if (c.va == 0) {
            snprintf(buf, sizeof(buf), "\n  %-10s VA=0        %s", c.nm,
                     c.required ? "<!! 未填写（本档位必需）" : "(未填，可接受)");
            if (c.required) ok = false;
            r += buf;
            continue;
        }
        bool inImage = (c.va >= imgBase && c.va < imgBase + imgSize);
        snprintf(buf, sizeof(buf), "\n  %-10s VA=%#010x  %s", c.nm, c.va,
                 inImage ? "OK" : "<!! 不在映像内");
        if (!inImage) ok = false;
        r += buf;
    }
    if (!ok) {
        r += "\n  >>> 这些字段必须是**绝对 VA**（IDA 显示值），读取时不得加减 ImageBase；"
             "\n      必需项为空说明该档位还没配全，拒绝安装。";
        if (report) *report = r;
        return false;
    }

    // 解引用并做基本合理性检查
    DWORD pitch = *(DWORD*)VaToPtr(g_env.pitchVA);
    DWORD surf = *(DWORD*)VaToPtr(g_env.surfaceVA);
    snprintf(buf, sizeof(buf), "\n  pitch=%d  surface=%#010x", (int)pitch, surf);
    r += buf;
    if ((int)pitch < 0 || (int)pitch > 8192) {
        snprintf(buf, sizeof(buf), "\n  [FAIL] pitch=%d 不合理", (int)pitch);
        r += buf;
        if (report) *report = r;
        return false;
    }
    if (surf && surf < 0x10000) {
        snprintf(buf, sizeof(buf), "\n  [FAIL] surface=%#010x 不合理", surf);
        r += buf;
        if (report) *report = r;
        return false;
    }

    DWORD a0 = *(DWORD*)VaToPtr(g_env.atlasBaseVA);
    snprintf(buf, sizeof(buf), "\n  atlas[0]=%#010x  %s", a0,
             a0 ? "(已构建)" : "(尚未构建，首次绘制时建)");
    r += buf;

    {
        int w = DisplayW(), h = DisplayH();
        snprintf(buf, sizeof(buf), "\n  nWidth=%d nHeight=%d  %s", w, h,
                 (w && h) ? "(已取到，作为像素写入安全上界)" : "(暂为 0，安全网禁用)");
        r += buf;
    }

    if (report) *report = r;
    return true;
}

// ── 原始函数副本（stub）的函数指针类型与实例 ───────────────────────────
//
//  ★ 本作原型（全部 __cdecl，**返回 int**）：
//     LEFT   int (int x, int y, const char* Str, int font, int a5, char color)
//     DIALOG int (int x, int y, const char* Str, int font,
//                 int l, int t, int r, int b, char color)
//     MEASURE   int (const char* Str, int font, int* out)
//     MEASURE_H int (const char* Str, int font)
//
//  ★ 这几个变量必须在 RenderCore 之前声明：RenderCore 里会转调它们。
typedef int (__cdecl *PFN_render_left)(int, int, const char*, int, int, char);
typedef int (__cdecl *PFN_render_dlg)(int, int, const char*, int,
                                      int, int, int, int, char);
typedef int (__cdecl *PFN_measure)(const char*, int, int*);
typedef int (__cdecl *PFN_measure_h)(const char*, int);
static PFN_render_left g_origLeft = nullptr;
static PFN_render_dlg  g_origDialog = nullptr;
static PFN_measure     g_origMeasure = nullptr;
static PFN_measure_h   g_origMeasureH = nullptr;

// 前置声明：RenderCore 会用它，定义在本文件稍后处
static void DiagLogText(int kind, int x, int y, const char* str, int font);

// ── 通用渲染主体 ────────────────────────────────────────────────────────
//
// ★ 返回值为 int：与原函数同型。语义是"已处理的字节数"，
//   与官方"字符索引残值"同构；调用方不消费它（实测 23 个 xref 全是丢弃）。
//   ★ 绝不返回 0：那是 2 代"创建玩家档案输入不了"的直接原因。
static int RenderCore(int kind, int x, int y, const char* str, int font,
                      int color, int clipL, int clipT, int clipR, int clipB)
{
    InterlockedIncrement(&g_calls);
    if (!str) return 0;

    // ★ 官方每个渲染器的第一句：表面未锁定 -> 一个字都不画。
    //   本作实测：`if (dword_63C64C)` 包住整个函数体（LEFT 是 jz 到函数尾）。
    if (g_env.enabledVA && *(const DWORD*)VaToPtr(g_env.enabledVA) == 0)
        return 0;

    // surface/pitch 在 unlock 时会被清零，所以每次重新读（不缓存）
    if (!SurfacePtr() || Pitch() <= 0) return 0;

    // 字体档越界保护：本作实测 9 档（0..8）
    int fontMax = (g_env.fontCount > 0 && g_env.fontCount < 32)
                  ? g_env.fontCount - 1 : 8;
    if (font < 0 || font > fontMax) font = 0;

    const unsigned char* s = (const unsigned char*)str;

    // ── 快速路径：整串 ASCII -> 整串转调原函数（零行为差异）──
    //   ★ 判据只看"有没有 >0xA0 的字节"，不看它是不是完整汉字：
    //     只要出现了高位字节，就必须走我们自己的循环 ——
    //     哪怕它是渐显中途的**孤立首字节**。
    //     若把孤立首字节放行到原函数，它会去查 ASCII 宽度表越界取值
    //     -> 伪造字形指针 -> blit 出大段垃圾 = 花屏。
    bool hasCjk = false;
    for (const unsigned char* p = s; *p; ++p) {
        if (*p > 0xA0) { hasCjk = true; break; }
    }
    if (!hasCjk) {
        if (kind == RK_LEFT && g_origLeft)
            g_origLeft(x, y, str, font, clipL, (char)color);
        else if (kind == RK_DIALOG && g_origDialog)
            g_origDialog(x, y, str, font, clipL, clipT, clipR, clipB, (char)color);
        return (int)strlen(str);
    }

    // ── 混合串：ASCII 逐字转调原函数，汉字自绘 ────────────────────────
    //
    // ★ 本作**没有 CENTER**，所有渲染器都沿 x 累加。
    //   官方只有 DIALOG 带"调用方裁剪矩形"；LEFT 只有全局 rcSrc2。
    int acc = x;                           // x 累加器
    const int yFix = y;                    // y 固定
    BYTE curColor = (BYTE)color;
    const bool hasClip = (kind != RK_LEFT);
    const int box = CjkBox(font);          // 本字体档的 CJK 逻辑盒（见 CjkBox 注释）
    int processed = 0;

    DiagLogText(kind, x, y, str, font);    // 有界诊断（见其说明）

    while (*s) {
        // '^' 颜色转义（官方条件：后面还有字节才算转义）
        if (*s == 0x5E && s[1] != 0) { curColor = (BYTE)s[1]; s += 2; processed += 2; continue; }

        // ★★★ 花屏的**真正根因**（2 代定位，本作同样成立）★★★
        //
        //  原来的条件是 `*s > 0xA0 && s[1] != 0` —— 多了一个 "s[1] != 0"。
        //  看起来是"防止把孤立首字节当汉字"，实际造成相反后果：
        //  当串以**孤立首字节**结尾时（s[1] == 0），条件不成立，
        //  于是掉进下面的 ASCII 分支，把这个汉字首字节当 ASCII 字符
        //  交给原版渲染器。原版随即去查 ASCII 宽度表
        //      word_C86DFC[262*font + 0xBF]
        //  这是表区间之外的位置，取到**别的字符的数据**当字形偏移，
        //  再 blit —— 把随机字节当 RLE 游程长度，往屏幕刷大段颜色 = 花屏。
        //
        //  为什么现象是"首次正常、后续花屏"：
        //    这些界面的文字是**逐字节渐显**的。2 代日志实证：
        //      len=1  51次  c4                    ← 孤立首字节
        //      len=3  32次  b1 dc bf              ← 完整字 + 孤立首字节
        //      len=24 304次 b1 dc ... b0 b2       ← 完整串（正常）
        //    渐显过程每两步就产生一个奇数长度串，于是**全程都在花屏**。
        //
        //  修法：与官方一致 —— 只判断首字节，不要求尾字节存在。
        //  孤立首字节按"半个汉字"处理：跳过、不画、推进一个步进。
        if (*s > 0xA0) {
            const bool havePair = (s[1] != 0);
            if (havePair && g_pFont && g_pFont->IsLoaded()) {
                int ink = 0;
                CjkResult r = DrawCjk(*g_pFont, s[0], s[1], acc, yFix, curColor,
                                      Pitch(), clipL, clipT, clipR, clipB,
                                      hasClip, box, &ink);
                if (ink > 0) InterlockedIncrement(&g_cjkGlyphs);

                // ★ 官方 LEFT：rcSrc2 裁光则**整个函数返回**（其余字不再画）
                if (r == CJK_ABORT) return processed;
            }
            // 推进：完整汉字走 2 字节；孤立首字节（渐显中途）只走 1 字节，
            // 且**绝不落到 ASCII 分支**（那正是花屏根因）。
            acc += box;
            s += havePair ? 2 : 1;
            processed += havePair ? 2 : 1;
            continue;
        }

        // ── ASCII：单字转调原函数 ──
        //    ★ 推进量必须自己取（stub 返回值是"字符索引残值"，不能用）：
        //      字形头 gh[0] = 字形宽，与原版 `a1 += v19` 逐字节等价。
        {
            char tmp[2] = { (char)*s, 0 };
            if (kind == RK_LEFT && g_origLeft)
                g_origLeft(acc, yFix, tmp, font, clipL, (char)curColor);
            else if (kind == RK_DIALOG && g_origDialog)
                g_origDialog(acc, yFix, tmp, font, clipL, clipT, clipR, clipB,
                             (char)curColor);

            // ★★ 这里**绝不能**改用 charWidthVA（3 代实测的 bug，现象：
            //    中英混排的字符串**从第一个 ASCII 字符起整段消失**）★★★
            //   charWidthVA 与 atlasOffsetVA 只差 0x40 == 32 个 WORD，
            //   是**字形偏移表右移 32 项**，取到的是数百~数千的图集字节偏移。
            //   原版从来没查过这张表，它用的就是字形头：
            //       v14 = atlasBase[font] + atlasOffset[262*font + c];
            //       v15 = *v14;   ...   x += v15;
            int adv = 0;
            WORD* gh = SafeGlyphHeader(font, *s);
            if (gh) adv = (int)gh[0];             // 页校验后的字形宽（原版同路）
            if (adv <= 0) {
                // 兜底：保证循环推进（控制在合理范围，绝不一步跳出裁剪框）
                adv = (box > 0 && box <= 32) ? box / 2 : 6;
                if (adv <= 0) adv = 6;
                InterlockedIncrement(&g_asciiFail);
            }
            acc += adv;
            s += 1;
            processed += 1;
        }
    }
    return processed;
}

// ── 诊断（"首次正常、后续花屏"无法本地复现，故输出有界状态快照）──────
static volatile LONG g_diagCount = 0;

static void DiagLogText(int kind, int x, int y, const char* str, int font)
{
#if CHS_DISABLE_HOTLOGGING
    (void)kind; (void)x; (void)y; (void)str; (void)font;   // 热路径全关：零开销
#else
    LONG n = InterlockedIncrement(&g_diagCount);
    if (n > 40 && (n % 200) != 0) return;

    DWORD locked = g_env.lockedSurfVA ? *(DWORD*)VaToPtr(g_env.lockedSurfVA) : 0;
    DWORD primary = g_env.primarySurfVA ? *(DWORD*)VaToPtr(g_env.primarySurfVA) : 0;
    int ox, oy;
    GetRcOrigin(&ox, &oy);
    ClipRect gc = GlobalClip();
    BYTE* surf = SurfacePtr();
    int pitch = Pitch();

    // 只打前 24 字节，避免日志爆炸
    char head[25];
    int i = 0;
    for (; i < 24 && str[i]; i++) head[i] = str[i];
    head[i] = 0;

    Log("diag#%ld kind=%d xy=(%d,%d) font=%d box=%d surf=%p pitch=%d "
        "lock=%#x prim=%#x %s rc=(%d,%d) clip=%s(%d,%d,%d,%d) \"%s\"",
        n, kind, x, y, font, CjkBox(font), (void*)surf, pitch, locked, primary,
        (locked == primary) ? "SAME(补rc偏移)" : "diff(不加)",
        ox, oy, gc.valid ? "on" : "off", gc.l, gc.t, gc.r, gc.b, head);
#endif
}

// ── stub 构造 ──────────────────────────────────────────────────────────
//
// ★ N 必须等于实际覆盖长度（ins.len == patchLen），且该长度已落在
//   指令边界上（本作分别是 10 / 14 / 11 / 14，见 target.cpp）。
//   2 代曾硬编码 5，一旦 patchLen 不是 5 就会把下一条指令的前半也复制
//   进去、再 jmp 到 +N —— 等于跳过半条指令执行，必崩。
bool RendererBuildStubs()
{
    for (int i = 0; i < g_hookCount; i++) {
        Installed& ins = g_hooks[i];
        if (!ins.target || ins.len < 5) continue;

        const int N = ins.len;

        BYTE* stub = (BYTE*)VirtualAlloc(nullptr, 64, MEM_COMMIT | MEM_RESERVE,
                                         PAGE_EXECUTE_READWRITE);
        if (!stub) {
            Log("Renderer: stub 分配失败");
            return false;
        }
        memcpy(stub, ins.orig, N);
        stub[N] = 0xE9;                     // jmp rel32
        DWORD from = (DWORD)(DWORD_PTR)(stub + N + 5);
        DWORD to = (DWORD)(DWORD_PTR)(ins.target + N);
        DWORD rel = to - from;
        memcpy(stub + N + 1, &rel, 4);
        FlushInstructionCache(GetCurrentProcess(), stub, N + 5);

        if (ins.kind == RK_LEFT)      g_origLeft = (PFN_render_left)stub;
        if (ins.kind == RK_DIALOG)    g_origDialog = (PFN_render_dlg)stub;
        if (ins.kind == RK_MEASURE)   g_origMeasure = (PFN_measure)stub;
        if (ins.kind == RK_MEASURE_H) g_origMeasureH = (PFN_measure_h)stub;
        Log("Renderer: stub[%d] = %p -> 原函数 %p +%d (kind=%d)", i, (void*)stub,
            (void*)ins.target, N, (int)ins.kind);
    }
    return (g_origLeft || g_origDialog);
}

// ── 文本测量 hook A：宽（sub_4885B0）──────────────────────────────────
//
// ★ 为什么必须 hook 它（2 代本轮的根因，本作同理）：
//   英文版对**每个字节**都查 ASCII 表：
//       result += *(WORD*)(atlas + offs[262*font + c] + 0);   // 取 [0] 即宽
//   汉字是双字节（如 "中" = D6 D0），第一字节 0xD6 会去查
//   `word_C86DFC[262*font + 0xD6]` —— 表里 ASCII 区间之外的位置，
//   取到的是**别的字符的数据**，算出来的宽度是垃圾。
//   调用方先调它算宽度，再拿宽度当裁剪矩形交给绘制函数 ->
//   宽度算错 -> 裁剪矩形错 -> 文字被切碎/错位 = 花屏。
//
// ★ 正确做法：汉字固定 +box（该字体档的字符单元高，方块字），
//   ASCII 逐字转调原实现。
//
// ★ 原版第三参 out：out[0] = 累计宽，out[1] = **空格**字形的高。
//   我们**完整转发**给 stub（纯 ASCII 串时），出参语义 100% 保真；
//   含汉字时自己填自洽的值。
extern "C" int __cdecl Hook_MEASURE(const char* str, int font, int* out)
{
    if (!str) return 0;

    int fontMax = (g_env.fontCount > 0 && g_env.fontCount < 32)
                  ? g_env.fontCount - 1 : 8;
    if (font < 0 || font > fontMax) font = 0;

    // ★★ 这里**绝不能**加"表面锁标志"判断（3 代实测的 bug，现象：所有
    //   checkbox / 单选项的标签全部不显示）★★
    //
    //   原版 sub_4885B0 反编译（IDA 确认）函数体里只有 strlen 循环，
    //   **没有** dword_63C64C 检查 —— 扫描该全局的 38 处引用也证明：
    //   引用者是 4 个绘制函数 + 加锁/解锁对，**不含任何测量函数**。
    //
    //   为什么加了会毁掉 UI 布局：
    //     dword_63C64C 只在 lock -> unlock 之间为 1，即**仅绘制那一瞬**。
    //     而控件宽度是在**布局期**算的，那一刻不在锁内。
    //     我们返回 0 -> 控件矩形塌陷 -> 标签被裁光，一个像素都不画。
    //
    //   测量是**纯几何计算**，不写任何像素，本来就不需要表面锁。
    int w = 0;
    bool hasCjk = false;
    const unsigned char* s = (const unsigned char*)str;

    // ★ CjkBox 内部要做一次 VirtualQuery（见 SafeGlyphHeader），
    //   必须**在循环外取一次**。放在循环里就是"每个汉字一次 VirtualQuery"，
    //   而测量函数在布局期会被上千次调用 -> 明显的卡顿来源。
    const int box = CjkBox(font);

    while (*s) {
        if (*s == 0x5E) {                     // '^' 颜色转义：跳过 2 字节
            if (s[1] == 0) break;
            s += 2;
            continue;
        }
        // ★ 与官方一致：只看首字节，**不要求尾字节存在**。
        //   之前写 `&& s[1] != 0`，遇到"渐显中途的孤立首字节"会掉进
        //   ASCII 分支去查 ASCII 宽度表 -> 取到表外垃圾 -> 宽度错乱。
        if (*s > 0xA0) {
            hasCjk = true;
            w += box;                         // 汉字固定 = 该档字符单元高
            s += (s[1] != 0) ? 2 : 1;         // 孤立首字节只推进 1，防死循环
            continue;
        }
        // ★ 官方条件：c >= 0x1F 才计入（控制字符不计宽）
        if (*s < 0x1F) { s += 1; continue; }

        // ASCII：逐字符转调原实现（原版是累加式的，故传单字符串取其和）
        {
            char tmp[2] = { (char)*s, 0 };
            int r = g_origMeasure ? g_origMeasure(tmp, font, nullptr) : 0;
            if (r <= 0) {
                // ★★ 这里**绝不能**退回 charWidthVA ★★
                //   它不是宽度表，是字形偏移表右移 32 项。取到的是数百~数千的
                //   图集偏移，会让测量宽度虚高，进而把控件矩形撑大 / 行高算错。
                //   正确来源与原版一致：字形头 gh[0]。
                int adv = 0;
                WORD* gh = SafeGlyphHeader(font, *s);
                if (gh) adv = (int)gh[0];
                r = (adv > 0 ? adv : 6);
            }
            w += r;
            s += 1;
        }
    }

    // ★ 出参：**唯一的安全做法见下**
    //
    //   原实现 sub_4885B0 对**每个字节**都查表。汉字是双字节，首字节 0xD6
    //   会去查 offs[262*font + 0xD6] —— 表里 ASCII 区间之外的位置，取到别的
    //   字符的偏移，再加到 atlasBase 上解引用 —— 那是**野指针读取**。
    //
    //   ★ 所以：**含汉字时绝不能把整串转发给原实现**。
    //     纯 ASCII 串才转发（此时原实现行为完全正确，包括它填的 out[1]）。
    if (out) {
        if (!hasCjk) {
            // 纯 ASCII：原实现全权处理，出参语义 100% 保真
            if (g_origMeasure) g_origMeasure(str, font, out);
        } else {
            // 含汉字：自己填一个自洽的出参
            //   out[0] = 我们累加出的宽
            //   out[1] = 行高。原版取的是 `atlasOffset[262*font + 32]` 那个
            //            （即**空格**字形）的 WORD[1]，我们照同一语义取。
            //   ★ 用加页校验的 SafeGlyphHeader：图集半更新时空读会崩
            WORD* gh = SafeGlyphHeader(font, (BYTE)' ');
            out[0] = w;
            out[1] = gh ? (int)gh[1] : CjkBox(font);
        }
    }

#if !CHS_DISABLE_HOTLOGGING
    {
        LONG n = InterlockedIncrement(&g_measureCalls);
        if (n <= 30 || (n % 500) == 0) {
            char head[33];
            int i = 0;
            for (; i < 32 && str[i]; i++) head[i] = str[i];
            head[i] = 0;
            Log("meas#%ld font=%d w=%d cjk=%d out1=%d len=%d \"%s\"",
                n, font, w, (int)hasCjk, out ? out[1] : -1, i, head);
        }
    }
#else
    (void)g_measureCalls;
#endif
    return w;
}

// ── 文本测量 hook B：高-3（sub_488CF0）────────────────────────────────
//
//   本作原版：
//       for each c: if (c == '^') skip 2;
//                   else if (c >= 0x1F) result += glyph[1] - 3;
//   即累加**字形高 - 3**。10 个调用点（多行文本算总行高）。
//
//   漏 hook 它 -> 多行文字拿到错误总高 -> 垂直居中错位 / 裁剪矩形算错。
//   汉字按（box - 3）计，与原式同构。
extern "C" int __cdecl Hook_MEASURE_H(const char* str, int font)
{
    if (!str) return 0;

    int fontMax = (g_env.fontCount > 0 && g_env.fontCount < 32)
                  ? g_env.fontCount - 1 : 8;
    if (font < 0 || font > fontMax) font = 0;

    // ★ 同 Hook_MEASURE：**绝不能**加表面锁判断 ★★
    //   原版 sub_488CF0 函数体里没有 dword_63C64C 检查。
    int h = 0;
    const unsigned char* s = (const unsigned char*)str;

    // ★ 同 Hook_MEASURE：CjkBox 只取一次（内含 VirtualQuery）
    const int box = CjkBox(font);

    while (*s) {
        if (*s == 0x5E) {
            if (s[1] == 0) break;
            s += 2;
            continue;
        }
        if (*s > 0xA0) {
            int adv = box - 3;                 // 汉字：box - 3
            if (adv <= 0) adv = 3;
            h += adv;
            s += (s[1] != 0) ? 2 : 1;
            continue;
        }
        if (*s < 0x1F) { s += 1; continue; }
        {
            char tmp[2] = { (char)*s, 0 };
            int r = g_origMeasureH ? g_origMeasureH(tmp, font) : 0;
            if (r <= 0) {
                // ★ 用加页校验的 SafeGlyphHeader
                WORD* gh = SafeGlyphHeader(font, *s);
                r = gh ? ((int)gh[1] - 3) : 6;
                if (r <= 0) r = 6;
            }
            h += r;
            s += 1;
        }
    }

#if !CHS_DISABLE_HOTLOGGING
    {
        LONG n = InterlockedIncrement(&g_measureHCalls);
        if (n <= 30 || (n % 500) == 0) {
            char head[33];
            int i = 0;
            for (; i < 32 && str[i]; i++) head[i] = str[i];
            head[i] = 0;
            Log("measH#%ld font=%d h=%d len=%d \"%s\"", n, font, h, i, head);
        }
    }
#else
    (void)g_measureHCalls;
#endif
    return h;
}

// ── 两个绘制 hook（与原函数同签名、同调用约定、同返回类型 int）────────

// LEFT：6 参，**无**调用方裁剪矩形
extern "C" int __cdecl Hook_LEFT(int x, int y, const char* str,
                                 int font, int a5, char color)
{
    // ★ 第 5 参 a5：本作 LEFT 原版**完全不使用**它（反编译里只有 arg_C=font、
    //   arg_14=color 被读）。原样透传给 RenderCore 的 clipL 槽位只是为了
    //   与"无调用方裁剪"的语义一致 —— RenderCore 里 RK_LEFT 的 hasClip=false，
    //   所以它不会被当成裁剪矩形使用。
    return RenderCore(RK_LEFT, x, y, str, font, (int)(BYTE)color,
                      a5, 0, 0, 0);
}

// DIALOG：9 参，第 5~8 参就是调用方裁剪 RECT 的 left/top/right/bottom
//   （原版 `if (sub_455BA0(&v23, &stru_510A38, ...) && sub_455BA0(v27, &a5, ...))`，
//    即直接把 &a5 当 RECT 用 —— 与 3 代同一个把戏）
extern "C" int __cdecl Hook_DIALOG(int x, int y, const char* str, int font,
                                   int l, int t, int r, int b, char color)
{
    return RenderCore(RK_DIALOG, x, y, str, font, (int)(BYTE)color, l, t, r, b);
}

// ── 安装 ────────────────────────────────────────────────────────────────
bool RendererInstallAt(DWORD targetRVA, int kind, const BYTE* /*expect*/,
                       int /*expectLen*/, int patchLen)
{
    if (g_hookCount >= (int)(sizeof(g_hooks) / sizeof(g_hooks[0]))) {
        Log("Renderer: hook 槽位已满");
        return false;
    }
    if (patchLen < 5 || patchLen > (int)sizeof(g_hooks[0].orig)) {
        Log("Renderer: patchLen=%d 不合理", patchLen);
        return false;
    }

    BYTE* base = ImageBase();
    IMAGE_DOS_HEADER* dos = (IMAGE_DOS_HEADER*)base;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return false;
    IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(base + dos->e_lfanew);
    if (targetRVA + (DWORD)patchLen > nt->OptionalHeader.SizeOfImage) {
        Log("Renderer: 目标 RVA %#x 超出映像", targetRVA);
        return false;
    }

    BYTE* target = base + targetRVA;

    void* ours = (kind == RK_DIALOG)    ? (void*)&Hook_DIALOG
               : (kind == RK_MEASURE)   ? (void*)&Hook_MEASURE
               : (kind == RK_MEASURE_H) ? (void*)&Hook_MEASURE_H
                                        : (void*)&Hook_LEFT;

    BYTE patch[16];
    memset(patch, 0x90, sizeof(patch));
    patch[0] = 0xE9;                                    // jmp rel32
    DWORD from = targetRVA + 5;
    DWORD to = (DWORD)((BYTE*)ours - base);
    DWORD rel = to - from;
    memcpy(patch + 1, &rel, 4);

    DWORD oldProt = 0;
    if (!VirtualProtect(target, patchLen, PAGE_EXECUTE_READWRITE, &oldProt)) {
        Log("Renderer: VirtualProtect 失败 (%lu)", GetLastError());
        return false;
    }

    Installed& ins = g_hooks[g_hookCount];
    memcpy(ins.orig, target, patchLen);
    ins.target = target;
    ins.len = patchLen;
    ins.kind = kind;

    memcpy(target, patch, patchLen);
    DWORD tmp = 0;
    VirtualProtect(target, patchLen, oldProt, &tmp);
    FlushInstructionCache(GetCurrentProcess(), target, patchLen);

    g_hookCount++;
    Log("Renderer: hook #%d RVA=%#x kind=%d ours=%p patchLen=%d "
        "原字节=%02X %02X %02X %02X %02X %02X %02X %02X",
        g_hookCount, targetRVA, kind, ours, patchLen,
        ins.orig[0], ins.orig[1], ins.orig[2], ins.orig[3],
        ins.orig[4], ins.orig[5], ins.orig[6], ins.orig[7]);
    return true;
}

void RendererUninstall()
{
    for (int i = 0; i < g_hookCount; i++) {
        Installed& ins = g_hooks[i];
        if (!ins.target) continue;
        DWORD oldProt = 0;
        if (VirtualProtect(ins.target, ins.len, PAGE_EXECUTE_READWRITE, &oldProt)) {
            memcpy(ins.target, ins.orig, ins.len);
            DWORD tmp = 0;
            VirtualProtect(ins.target, ins.len, oldProt, &tmp);
            FlushInstructionCache(GetCurrentProcess(), ins.target, ins.len);
        }
    }
    g_hookCount = 0;
    g_origLeft = nullptr;
    g_origDialog = nullptr;
    g_origMeasure = nullptr;
    g_origMeasureH = nullptr;
}

// ★ probeOnly 档位：**只做识别校验，不写任何内存**。
//   读字节比对就已经完成证明（见 Target::VerifySignature），
//   这里只复述一遍并写日志。
bool RendererProbeAt(DWORD targetRVA, const BYTE* expectOrig, int expectLen)
{
    if (!expectOrig || expectLen <= 0 || expectLen > 16) return false;
    BYTE* base = ImageBase();
    if (!base) return false;
    const BYTE* p = base + targetRVA;
    for (int i = 0; i < expectLen; i++) {
        if (p[i] != expectOrig[i]) {
            Log("RendererProbe: @+%d 期望 %02X 实得 %02X（未做任何改动）",
                i, expectOrig[i], p[i]);
            return false;
        }
    }
    Log("RendererProbe: %d 字节全部一致（未做任何改动）", expectLen);
    return true;
}
