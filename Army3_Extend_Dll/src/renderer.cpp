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
//  /DrawCjk13 这些**每帧每个字符串/每个汉字都会进入**的热路径上。
//
//  后果（本轮实测）：控制设置界面的主循环每秒重绘上万个字符串，每 200 次
//  渲染调用就做一次完整的 Log() = fopen + fwrite + fclose + vsnprintf，
//  累积成每秒数十次磁盘 IO，把渲染循环拖卡顿。
//
//  处置：正式游玩时置 1（关闭热路径日志），仅保留初始化/安装的一次性日志
//  （Detect / Hzk16 / InstallAll 那些，单次执行、无卡顿）。
//  排障时改回 0 即可重新获得逐字形诊断。
#define CHS_DISABLE_HOTLOGGING 1

// ════════════════════════════════════════════════════════════════════════
//  Army Men: Toys in Space —— 文字渲染接管（3 代）
//
//  全部结论来自本轮 IDA 逆向（反编译 + disasm 逐字节）。
//  3 代四个函数的地址、参数形、序言与 patchLen 依据见 src\target.cpp 的档位表；
//  文本载体与翻译范围见 docs/08-am3-i18n-inventory.md。
//
//  ── 3 代四个函数的真实语义（已还原）──────────────────────────────────
//
//   LEFT   sub_450EA7(int x, int y, char* Str, int font, int, char color)
//            v18 = a1;                              // x 累加器
//            glyph = atlasBase[font] + atlasOffset[262*font + c]
//            v15 = glyph[0](宽); v12 = glyph[1](高)
//            desc = {0,0,v15,v12}
//            if (!rect(desc, &rcSrc2, &x, &y, out)) return;   // ★ 裁光则整个函数返回
//            if (locked == primary) { x += rc.left; y += rc.top; }
//            blit(...)
//            v18 += v15;                            // ★ 按**宽**推进
//            return;                                // ★★ 返回 void！
//
//   DIALOG sub_450FCF(x, y, Str, font, l, t, r, b, color)
//            两步 rect：先 rcSrc2，再调用方裁剪 {l,t,r,b}
//            裁光 -> **跳过该字形**（不是整个返回）
//            v23 += glyph[0]                        // ★ 按**宽**推进
//
//   CENTER sub_451114(x, y, Str, font, l, t, r, b, color)
//            v27 = a1 - glyph[0]/2                  // ★ 按**宽**水平居中
//            v25 += glyph[1] - 3                    // ★ 沿 **y** 按**高-3** 推进
//
//   MEASURE  sub_450E3A(char* Str, int font, int* out) -> int
//            result += glyph[0]                         // 累加**宽**
//            if (out) { out[0] = result; out[1] = glyph[1] of c=0; }
//
//   MEASURE_H sub_451267(char* Str, int font) -> int     ★ 2 代没有这个函数
//            result += glyph[1] - 3                     // 累加**高-3**
//
//  ── 与 2 代的决定性差异（决定了本文件不能照搬 2 代）──────────────────
//
//   ① 2 代渲染器返回"文本结束后的 x"，AM2 的 RenderCore 靠 stash 返回值
//      推进 ASCII 光标。3 代返回 **void**，那个契约不存在。
//      -> 本文件改为从**字形头**取推进量（GlyphWidth / GlyphHeight），
//         这正是原函数内部的做法，逐字节等价。
//
//   ② patchLen 不能沿用 2 代的 5（详见 target.h）。
//
//   ③ 多一个测量函数 RK_MEASURE_H。
//
//  ── 策略：ASCII 转调 stub，CJK 自绘 ──────────────────────────────────
//
//   2 代曾试图**完整复刻** ASCII 绘制，连摔四轮：
//      blit 参数序写错 / font 硬编码 / 返回值契约错 / 编辑框输入不了。
//   根因都是"重造游戏自己的逻辑"。现在的做法是最小化介入：
//      ASCII 段 -> 逐字转调**未被覆盖的原始函数副本**（stub），
//                  字体/裁剪/颜色/几何全部自动正确
//      CJK  段 -> 自己画（13x13 点阵直接写表面）
//   代价：ASCII 每字符一次函数调用（文本量小，可接受）。
// ════════════════════════════════════════════════════════════════════════

typedef int  (__cdecl *PFN_rect)(const void* desc, void* rcSrc,
                                 int* px, int* py, void* outRect);

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
static volatile LONG g_inkDiag = 0;
static volatile LONG g_inkCalls = 0;
static volatile LONG g_calls = 0;
static volatile LONG g_cjkGlyphs = 0;
static volatile LONG g_asciiFail = 0;

void RendererSetEnv(const RendererEnv& env) { g_env = env; }
bool RendererIsInstalled() { return g_hookCount > 0; }

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
// ★★ 此处曾有一个 CharWidth(font) 辅助函数，已删除 ★★
//
//   它读 g_env.charWidthVA(0x698DAC)，而该地址与 atlasOffsetVA(0x698D6C)
//   只差 0x40 == 32 个 WORD，即
//       CharWidth(font)[c]  ≡  atlasOffset(font)[c + 32]
//   —— **根本不是宽度表，是字形偏移表右移 32 项**。
//
//   实测 font=2 的值序列：0, 60, 134, 206, 294, 386, 486, 574, … , 3540，
//   是逐字递增的图集字节偏移。当宽度用会让累加器一步跳出裁剪框，
//   症状是"中英混排从第一个 ASCII 字符起整段消失"。
//
//   保留这个函数只会招来下一次误用，故连同 RendererValidateEnv 里的
//   charWidthVA 自检项一起移除。推进量一律走 SafeGlyphHeader。

// ★★ 3 代的**推进量来源**（2 代靠 stub 返回值，这里靠字形头）
//
//   字形头 = atlasBase[font] + atlasOffset[262*font + c]
//     glyph[0] = 字形宽 -> LEFT/DIALOG 的横向前进量
//     glyph[1] = 字形高 -> CENTER 的纵向前进量（还要 -3）
//   这两条对应原函数里的 `v18 += v15` 与 `v25 += v15 - 3`。
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

// ★★ 加固版字形头（崩溃修复：RVA 0x4D5C 空指针读）
//
//  原 GlyphHeader 的缺陷：`base + offs[c]` 里的 offs[c] 是引擎在
//  图集"正在重建/半更新"状态下写入的异常值，加法结果会落到一片
//  不可读的页上；直接返回后外层 `movzx eax,[eax]` 就会空读 AV
//  （实测 EAX=0，异常地址 ASI+0x4D5C）。
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

    // 验证 glyph 所在页已提交且可读。
    //   VirtualQuery 对"空指针/低值野指针"返回 len 0，可一并兜住。
    MEMORY_BASIC_INFORMATION mbi;
    if (VirtualQuery(glyph, &mbi, sizeof(mbi)) == 0)
        return nullptr;
    if (mbi.State != MEM_COMMIT)
        return nullptr;
    if (!(mbi.Protect & (PAGE_READONLY | PAGE_READWRITE |
                         PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE |
                         PAGE_EXECUTE_WRITECOPY | PAGE_READWRITE)))
        return nullptr;

    return glyph;
}

// ── 全局裁剪矩形 rcSrc2 ────────────────────────────────────────────────
//
// ★★ "文字渐显时花屏"的成因（2 代用户反馈，且明确指出"之前版本没有"）
//
//   这是我引入的**回归**，不是原版行为。两次改动叠加：
//   (a) 最初只判屏幕边界（有上下界，不越界）；
//   (b) 上一轮改用调用方的 clip 矩形裁剪 —— 但 LEFT 只有 6 个参数、
//       **没有**裁剪矩形，传进来的 clip 全是 0 -> hasClip==false ->
//       整个上界判断被短路，只挡住"小于 0"的一侧。
//       文字向右/向下越过表面下界时不再被拦，直接写出缓冲区 -> 花屏。
//       渐显/滚动恰好让文字部分越界，所以"出现时花屏、全显示后正常"。
//
//   修法：恢复上界，并补上原版真正使用的裁剪来源 rcSrc2。
//   3 代实测同样是每个字形先走 rcSrc2：
//       sub_435EDE(&desc, &rcSrc2, &x, &y, out)
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

// ★ 直接把 rcSrc2 的地址交给游戏自己的 rect 函数（sub_435EDE）。
//   官方就是这么做的：rect(desc, &rcSrc2, ...) —— 由游戏决定怎么解读。
//   我不再自己判断"矩形是否有效"：0 矩形就该裁光一切，这是原版语义。
//   （2 代曾把 0 矩形当"未设定"而忽略，导致本该被裁掉的字形照画 -> 花屏）
static void* GlobalClipPtr()
{
    if (!g_env.clipRectVA) return nullptr;
    return (void*)VaToPtr(g_env.clipRectVA);
}

// ── 落笔原点偏移 rc（原版在 blit 前做，2 代最初漏了）──────────────────
//
// 3 代原版三个渲染器都一样（实测反汇编）：
//     mov eax, dword_52BE78      ; ★ 单次解引用
//     cmp eax, dword_527824
//     jnz skip
//     add x, rc.left ; add y, rc.top
//     blit(...)
//
// rc 由窗口消息更新（WM_SIZE/WM_MOVE → GetClientRect + ClientToScreen），
// 含义是"后备缓冲在主表面中的左上角"。画到主表面时要补这个偏移。
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
// 2 代官方中文版对汉字一律用 15x15 作为**逻辑尺寸**（desc 与步进都用它），
// 而点阵本身只有 13x13。这两个数都不能改：
//   * desc 必须 15x15，否则 rect 裁剪边界与原版差 2px
//   * 步进必须 15，否则每字少走 2px，长串累积偏移 -> 越界写出 -> 花屏
//
// 3 代沿用同样的 15（引擎同源，字体逻辑尺寸一致）。
//   ★ CENTER 的纵向步进用 CJK_BOX - 3：因为 3 代 CENTER 的原生推进是
//     `glyph[1] - 3`（高-3），我们用 15 当"高"，故 15-3 = 12，与原式同构。
//     ★ 这一项是**推断**（非实测），首次实机需重点观察居中菜单的行距。
static const int CJK_BOX   = 15;   // 逻辑尺寸：desc / 横向步进
static const int CJK_INK_W = 13;   // 点阵实际列数
static const int CJK_INK_H = 13;   // 点阵实际行数
static const int CJK_ADV_Y = CJK_BOX - 3;   // CENTER 的纵向步进（见上）

// 绘制结果三态 —— 对应官方两处不同的失败处理
enum CjkResult {
    CJK_OK    = 0,   // 已绘制
    CJK_SKIP  = 1,   // 被裁光，跳过该字形（DIALOG/CENTER 语义）
    CJK_ABORT = 2,   // 被裁光，**整个函数返回**（LEFT 语义）
};

static volatile LONG g_clampHits = 0;

// 画一个 13x13 汉字点阵，裁剪完全走游戏自己的 rect 函数（官方同路）。
//   hasClip —— 是否有"调用方裁剪矩形"（仅 DIALOG/CENTER 有）
//   *ink    —— 出参：写入像素数
static CjkResult DrawCjk13(const Hzk16Font& f, BYTE lead, BYTE trail,
                           int dx, int dy, BYTE color, int pitch,
                           int clipL, int clipT, int clipR, int clipB,
                           bool hasClip, int* ink)
{
    if (ink) *ink = 0;
    const BYTE* g = f.Glyph(lead, trail);
    if (!g) return CJK_SKIP;

    PFN_rect rectFn = (PFN_rect)VaToPtr(g_env.rectVA);
    if (!rectFn) return CJK_SKIP;

    // 官方：desc = {0, 0, 15, 15}（汉字逻辑尺寸恒为 15）
    int desc[4] = { 0, 0, CJK_BOX, CJK_BOX };
    int x = dx, y = dy;
    int srcRect[4] = { 0, 0, 0, 0 };

    // ① 全局裁剪 rcSrc2 —— 官方第一步。
    //    LEFT 失败 -> 整个函数返回；DIALOG/CENTER 失败 -> 跳过该字形。
    if (!rectFn(desc, GlobalClipPtr(), &x, &y, srcRect))
        return hasClip ? CJK_SKIP : CJK_ABORT;

    // ② 调用方裁剪矩形 —— 官方第二步（仅 DIALOG/CENTER），失败只跳过该字形
    int drawX = x, drawY = y;
    if (hasClip) {
        // ★ 用局部数组而非 &l：不依赖"4 个形参在栈上连续"这一实现细节
        int clip[4] = { clipL, clipT, clipR, clipB };
        int dstRect[4] = { 0, 0, 0, 0 };
        if (!rectFn(srcRect, clip, &drawX, &drawY, dstRect))
            return CJK_SKIP;
    }

    // ③ rc 原点偏移 —— 官方在裁剪**之后**加，且仅当画到主表面
    int ox, oy;
    GetRcOrigin(&ox, &oy);
    drawX += ox;
    drawY += oy;

    // ④ 逐像素写点阵。官方此处不再做语义裁剪（全靠上面的 rect 把关），
    //    我们额外加一道**内存安全网**：夹到显示区 nWidth x nHeight。
    //    正常情况永不触发；触发说明 rcSrc2 越出了显示区（即游戏自身异常），
    //    此时不打日志刷屏，只累加计数。
    BYTE* surface = SurfacePtr();
    if (!surface || pitch <= 0) return CJK_SKIP;

    int boundW = DisplayW();
    int boundH = DisplayH();
    const int rowBytes = (f.Width() + 7) >> 3;

    int n = 0;
    for (int j = 0; j < CJK_INK_H; j++) {           // 官方 v19：纵向
        const int py = drawY + j;
        if (py < 0) continue;
        if (boundH > 0 && py >= boundH) { InterlockedIncrement(&g_clampHits); continue; }
        BYTE* dst = surface + (long)py * pitch;
        for (int i = 0; i < CJK_INK_W; i++) {       // 官方 i：横向
            const int px = drawX + i;
            if (px < 0) continue;
            if (boundW > 0 && px >= boundW) { InterlockedIncrement(&g_clampHits); continue; }
            if (!Hzk16Font::TestBit(g, i, j, rowBytes)) continue;
            dst[px] = color;
            n++;
        }
    }
    if (ink) *ink = n;

#if !CHS_DISABLE_HOTLOGGING
    // ★ 有界诊断：记录**实际**写入的坐标范围与裁剪结果。
    //   若 drawX/drawY 越出显示区，就是写出表面 = 花屏。
    //   （热路径逐字形日志，正常游玩由 CHS_DISABLE_HOTLOGGING 关掉）
    {
        LONG c = InterlockedIncrement(&g_inkCalls);
        if (c <= 30 || (c % 500) == 0) {
            LONG d = InterlockedIncrement(&g_inkDiag);
            Log("ink#%ld lead=%02X trail=%02X req=(%d,%d) draw=(%d,%d) "
                "ink=%d clip=(%d,%d,%d,%d) surf=%p pitch=%d",
                d, lead, trail, dx, dy, drawX, drawY, n,
                clipL, clipT, clipR, clipB,
                (void*)surface, pitch);
        }
    }
#endif
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
        {"blit",      g_env.blitVA,         false},  // 3 代不调用，登记备查
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
//  ★ 3 代原型（全部 __cdecl，**返回 void**）：
//     LEFT   void (int x,int y,const char* Str,int font,int a5,char color)
//     DIALOG void (int x,int y,const char* Str,int font,
//                  int l,int t,int r,int b,char color)
//     CENTER 同 DIALOG
//     MEASURE   int (const char* Str,int font,int* out)   ← 只有它返回值
//     MEASURE_H int (const char* Str,int font)            ← 只有它返回值
//
//  ★ 这几个变量必须在 RenderCore 之前声明：RenderCore 里会转调它们。
//    （stub 的实际构造在文件后部，见 RendererBuildStubs。）
typedef void (__cdecl *PFN_render_left)(int, int, const char*, int, int, char);
typedef void (__cdecl *PFN_render_dlg)(int, int, const char*, int,
                                       int, int, int, int, char);
typedef int  (__cdecl *PFN_measure)(const char*, int, int*);    // 宽（第三参出参）
typedef int  (__cdecl *PFN_measure_h)(const char*, int);        // 高-3
static PFN_render_left g_origLeft = nullptr;
static PFN_render_dlg  g_origDialog = nullptr;
static PFN_render_dlg  g_origCenter = nullptr;
static PFN_measure     g_origMeasure = nullptr;
static PFN_measure_h   g_origMeasureH = nullptr;

// 前置声明：RenderCore 会用它，定义在本文件稍后处
static void DiagLogText(int kind, int x, int y, const char* str, int font);

// ── 通用渲染主体 ────────────────────────────────────────────────────────
//
// ★★ 与 2 代的根本差异：**本函数返回 void**
//
//   2 代三个渲染器返回"文本结束后的 x"，调用方（编辑框、列表）靠这个
//   返回值定位光标、判断能否继续追加字符。3 代实测全部返回 void，
//   调用方不消费任何返回值 —— 因此这里也不再需要维护/返回 acc 契约。
//   （2 代曾因 `return 0` 导致"创建玩家档案输入不了"，那个坑在 3 代**不存在**。）
//
//   但 acc 仍必须维护：它是**混合串里 ASCII 与汉字交错的定位基准**。
//   ASCII 推进量取自字形头（见 GlyphHeader），因为 stub 不返回任何东西。
static void RenderCore(int kind, int x, int y, const char* str, int font,
                       int color, int clipL, int clipT, int clipR, int clipB)
{
    InterlockedIncrement(&g_calls);
    if (!str) return;

    // ★ 官方每个渲染器的第一句：表面未锁定 -> 一个字都不画。
    //   3 代实测：`if (dword_521D2C)` 包住整个函数体（LEFT 是 jz 到函数尾）。
    if (g_env.enabledVA && *(const DWORD*)VaToPtr(g_env.enabledVA) == 0)
        return;

    // surface/pitch 在 unlock 时会被清零，所以每次重新读（不缓存）
    if (!SurfacePtr() || Pitch() <= 0) return;
    if (font < 0 || font > 16) font = 0;

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
        // ★ 3 代渲染器返回 void —— stub 调用不再取返回值。
        if (kind == RK_LEFT && g_origLeft)
            g_origLeft(x, y, str, font, clipL, (char)color);
        else if (kind == RK_DIALOG && g_origDialog)
            g_origDialog(x, y, str, font, clipL, clipT, clipR, clipB, (char)color);
        else if (kind == RK_CENTER && g_origCenter)
            g_origCenter(x, y, str, font, clipL, clipT, clipR, clipB, (char)color);
        return;
    }

    // ── 混合串：ASCII 逐字转调原函数，汉字自绘 ────────────────────────
    //
    // ★ 两个轴必须分开（3 代 disasm 实测）：
    //     LEFT / DIALOG ：沿 x 累加，y 固定 = 传入的 y
    //     CENTER        ：每字水平居中（x = anchor - 宽/2），
    //                     沿 **y** 累加（原式 `y += 高 - 3`）
    const bool axisY = (kind == RK_CENTER);
    int acc = axisY ? y : x;               // 沿各自轴的累加器
    const int anchor = x;                  // CENTER 的居中基准（原始 x）
    BYTE curColor = (BYTE)color;

    // 官方只有 DIALOG/CENTER 带"调用方裁剪矩形"
    const bool hasClip = (kind != RK_LEFT);

    DiagLogText(kind, x, y, str, font);    // 有界诊断（见其说明）

    while (*s) {
        // '^' 颜色转义（官方条件：后面还有字节才算转义）
        if (*s == 0x5E && s[1] != 0) { curColor = (BYTE)s[1]; s += 2; continue; }

        // ★★★ 花屏的**真正根因**（2 代定位，3 代同样成立）★★★
        //
        //  原来的条件是 `*s > 0xA0 && s[1] != 0` —— 多了一个 "s[1] != 0"。
        //  看起来是"防止把孤立首字节当汉字"，实际造成相反后果：
        //  当串以**孤立首字节**结尾时（s[1] == 0），条件不成立，
        //  于是掉进下面的 ASCII 分支，把这个汉字首字节当 ASCII 字符
        //  交给原版渲染器。原版随即去查 ASCII 宽度表
        //      word_698D6C[262*font + 0xBF]
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
                // CENTER 要自己算居中（原函数只替 ASCII 算）
                int hx = axisY ? (anchor - CJK_BOX / 2) : acc;
                int hy = axisY ? acc : y;

                int ink = 0;
                CjkResult r = DrawCjk13(*g_pFont, s[0], s[1], hx, hy, curColor,
                                        Pitch(), clipL, clipT, clipR, clipB,
                                        hasClip, &ink);
                if (ink > 0) InterlockedIncrement(&g_cjkGlyphs);

                // ★ 官方 LEFT：rcSrc2 裁光则**整个函数返回**（其余字不再画）
                if (r == CJK_ABORT) return;
            }
            // 推进：完整汉字走 2 字节；孤立首字节（渐显中途）只走 1 字节，
            // 且**绝不落到 ASCII 分支**（那正是花屏根因）。
            acc += axisY ? CJK_ADV_Y : CJK_BOX;
            s += havePair ? 2 : 1;
            continue;
        }

        // ── ASCII：单字转调原函数 ──
        //    ★★ 推进量必须自己取（3 代 stub 不返回值）：
        //       LEFT / DIALOG : 字形**宽**  glyph[0]
        //       CENTER        : 字形**高-3** glyph[1] - 3
        //
        //    ★ CENTER 必须传**原始 anchor**：原函数内部会做 a1 - w/2，
        //      我若预先减了 w/2 就成双重居中。
        {
            char tmp[2] = { (char)*s, 0 };
            if (kind == RK_LEFT && g_origLeft)
                g_origLeft(acc, y, tmp, font, clipL, (char)curColor);
            else if (kind == RK_DIALOG && g_origDialog)
                g_origDialog(acc, y, tmp, font, clipL, clipT, clipR, clipB, (char)curColor);
            else if (kind == RK_CENTER && g_origCenter)
                g_origCenter(anchor, acc, tmp, font, clipL, clipT, clipR, clipB, (char)curColor);

            // ★★ 推进量计算（唯一正确来源：字形头）
            //
            // ★★★ 这里**绝不能**改用 charWidthVA（曾经的 bug，现象：
            //    中英混排的字符串**从第一个 ASCII 字符起整段消失**）★★★
            //
            //   charWidthVA(0x698DAC) 与 atlasOffsetVA(0x698D6C) 只差
            //   0x40 == 32 个 WORD，即：
            //       CharWidth(font)[c]  ≡  atlasOffset(font)[c + 32]
            //   它**不是宽度表，而是字形偏移表右移 32 项**。实机实测
            //   font=2 的值序列为
            //       0, 60, 134, 206, 294, 386, 486, 574, … , 3540
            //   —— 逐字递增的**图集字节偏移**，不是像素宽。
            //
            //   把它当步进宽用会怎样（实测）：
            //     串 "-- 电台 --" 里的那个空格 (0x20)，
            //     cw[0x20] 取到 0x0DD4 == **3540**
            //   于是 acc 一步跳出裁剪框，其后所有字符都画在框外，
            //   视觉上就是"到空格为止，后面全没了"。
            //
            //   而且旧代码的回退条件是 `if (adv <= 0)` —— 偏移值恒为正，
            //   **回退分支永远进不去**，SafeGlyphHeader 根本没机会执行。
            //   两个缺陷叠加，才让这个 bug 一直躲过自检。
            //
            //   原版 sub_450EA7 从来没查过这张表，它用的就是字形头：
            //       v11 = atlasBase[font] + atlasOffset[262*font + c];
            //       v15 = *v11;   ...   v18 += v15;
            //
            //   防御顺序（任何一步异常都安全回退，绝不空读）：
            //   LEFT/DIALOG（横向 = 宽）：
            //     ① SafeGlyphHeader 宽（加页校验后读）—— 与原版逐字等价
            //     ② 经验值 8
            //   CENTER（纵向 = 高-3）：
            //     ① SafeGlyphHeader 高-3（页校验后读）
            //     ② CJK_ADV_Y（= 15-3，官方对汉字的同名推进）
            int adv = 0;
            if (axisY) {
                WORD* gh = SafeGlyphHeader(font, *s);
                if (gh) {
                    adv = (int)gh[1] - 3;             // 高-3，与原式 v25 += v15-3 一致
                    if (adv <= 0) adv = CJK_ADV_Y;
                } else {
                    adv = CJK_ADV_Y;                  // 兜底，保证循环推进
                }
            } else {
                WORD* gh = SafeGlyphHeader(font, *s);
                if (gh) adv = (int)gh[0];             // ① 页校验后的字形宽（原版同路）
                if (adv <= 0) adv = 8;                // ② 经验值兜底，保证循环推进
            }
            acc += adv;
            s += 1;
        }
    }
    return;
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

    Log("diag#%ld kind=%d xy=(%d,%d) font=%d surf=%p pitch=%d lock=%#x prim=%#x %s"
        " rc=(%d,%d) clip=%s(%d,%d,%d,%d) \"%s\"",
        n, kind, x, y, font, (void*)surf, pitch, locked, primary,
        (locked == primary) ? "SAME(补rc偏移)" : "diff(不加)",
        ox, oy, gc.valid ? "on" : "off", gc.l, gc.t, gc.r, gc.b, head);
#endif
}

// ── stub 构造 ──────────────────────────────────────────────────────────
//
// ★ N 必须等于实际覆盖长度（ins.len == patchLen），且该长度已落在
//   指令边界上（3 代分别是 6 / 6 / 6 / 5 / 8，见 target.cpp）。
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

        if (ins.kind == RK_LEFT)         g_origLeft = (PFN_render_left)stub;
        if (ins.kind == RK_DIALOG)       g_origDialog = (PFN_render_dlg)stub;
        if (ins.kind == RK_CENTER)       g_origCenter = (PFN_render_dlg)stub;
        if (ins.kind == RK_MEASURE)      g_origMeasure = (PFN_measure)stub;
        if (ins.kind == RK_MEASURE_H)    g_origMeasureH = (PFN_measure_h)stub;
        Log("Renderer: stub[%d] = %p -> 原函数 %p +%d (kind=%d)", i, (void*)stub,
            (void*)ins.target, N, (int)ins.kind);
    }
    return (g_origLeft || g_origDialog || g_origCenter);
}

// ── 文本测量 hook A：宽（sub_450E3A）──────────────────────────────────
//
// ★ 为什么必须 hook 它（2 代本轮的根因，3 代同理）：
//   英文版对**每个字节**都查 ASCII 表：
//       result += *(WORD*)(atlas + offs[262*font + c] + 0);   // 3 代取 [0] 即宽
//   汉字是双字节（如 "避" = B1 DC），第一字节 0xB1 会去查
//   `word_698D6C[262*font + 0xB1]` —— 表里 ASCII 区间之外的位置，
//   取到的是**别的字符的数据**，算出来的宽度是垃圾。
//   调用方先调它算宽度，再拿宽度当裁剪矩形交给绘制函数 ->
//   宽度算错 -> 裁剪矩形错 -> 文字被切碎/错位 = 花屏。
//   而 rcSrc2 是全局的，一旦被污染，退出该窗口也跟着花屏。
//
// ★ 正确做法：汉字固定 +15（2 代官方值），ASCII 逐字转调原实现。
//
//   ★ 与 2 代的一个差异：2 代这个函数是 `(char*, int)` 两参；
//     3 代是 `(char*, int, int*)` 三参（第三参出参，其 [1] 是行高）。
//     我们**完整转发第三参**给 stub —— 出参必须由原实现填，
//     否则调用方拿到的行高是垃圾（那正是"裁剪矩形算错"的另一半）。
extern "C" int __cdecl Hook_MEASURE(const char* str, int font, int* out)
{
    if (!str) return 0;
    if (font < 0 || font > 16) font = 0;

    // ★★ 这里**绝不能**加"表面锁标志"判断（曾经的 bug，现象：所有
    //    checkbox / 单选项的标签全部不显示）★★
    //
    //   原版 sub_450E3A 反编译（IDA 确认）函数体里只有 strlen 循环，
    //   **没有** dword_521D2C 检查 —— 扫描该全局的 12 处引用也证明：
    //   引用者是 3 个绘制函数（0x450EAF / 0x450FDC / 0x451121）和
    //   加锁/解锁对（sub_42078A / sub_420810），**不含任何测量函数**。
    //
    //   为什么加了会毁掉 UI 布局：
    //     dword_521D2C 只在 sub_42078A(lock) -> sub_420810(unlock) 之间
    //     为 1，即**仅绘制那一瞬**。而控件宽度是在**布局期**算的，
    //     那一刻不在锁内：
    //         sub_43A889 @0x43A8FC
    //             v13 = sub_450E3A(label, 2, nullptr) + 19;
    //             sub_435EAE(rc, x, y, v13, 13);      // 宽度 = 文本宽 + 19
    //     我们返回 0 -> 宽度只剩 19（复选框方框本身）-> 控件矩形塌陷。
    //     而绘制函数把文字画在 rect.left + 19，裁剪框正是这个矩形：
    //         sub_45E078 -> sub_450FCF(rect.left + 19, ...)
    //     于是 x == rcDst.right -> sub_435EDE 第一步就 `>=` 判失败
    //     -> 整个标签被裁光，**一个像素都不画**。
    //
    //   实测佐证（本轮）：所有 checkbox 的宽度字段 this+0x0C 都是 19，
    //   捕获到的裁剪矩形 {59,116,78,129} 满足 78 == 59 + 19。
    //
    //   测量是**纯几何计算**，不写任何像素，本来就不需要表面锁。
    int w = 0;
    bool hasCjk = false;
    const unsigned char* s = (const unsigned char*)str;

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
            w += CJK_BOX;                     // 汉字固定 15
            s += (s[1] != 0) ? 2 : 1;         // 孤立首字节只推进 1，防死循环
            continue;
        }
        // ASCII：逐字符转调原实现（原版是累加式的，故传单字符串取其和）
        {
            char tmp[2] = { (char)*s, 0 };
            int r = g_origMeasure ? g_origMeasure(tmp, font, nullptr) : 0;
            if (r <= 0) {
                // 兜底：原实现返回 0（例如 c < 31 的控制字符）时给个合理步进
                //
                // ★★ 这里**绝不能**退回 charWidthVA ★★
                //   它不是宽度表，是字形偏移表右移 32 项（0x698DAC 与
                //   atlasOffsetVA 0x698D6C 相差 0x40 == 32 个 WORD）。
                //   取到的是数百~数千的图集偏移，会让测量宽度虚高，
                //   进而把控件矩形撑大 / 行高算错。详见 RenderCore 里
                //   ASCII 推进量处的长注释。
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

    // ★ 出参：**唯一的安全做法见下**，这里先说为什么不能图省事：
    //
    //   原实现 `sub_450E3A(str, font, out)` 的做法是
    //       for each 字节 c: result += *(WORD*)(atlasBase + offs[262*font + c]);
    //   它对**每个字节**都查表。汉字是双字节，首字节 0xB1 会去查
    //   offs[262*font + 0xB1] —— 表里 ASCII 区间之外的位置，取到别的
    //   字符的偏移，再加到 atlasBase 上解引用 —— 那是**野指针读取**，
    //   最好的情况是读到垃圾、最坏直接崩。
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
            //   out[1] = 字形高（对应原实现 a3[1] 的语义，用 'A' 的头取）
            //   ★ 用加页校验的 SafeGlyphHeader：图集半更新时空读会崩
            //     （崩溃修复：RVA 0x4D5C 同源），故绝不能直接解引用。
            WORD* gh = SafeGlyphHeader(font, (BYTE)'A');
            out[0] = w;
            out[1] = gh ? (int)gh[1] : CJK_BOX;
        }
    }

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
    return w;
}

// ── 文本测量 hook B：高-3（sub_451267）★ 2 代没有这个函数 ──────────────
//
//   3 代原版：
//       for each c: if (c == '^') skip 2; else if (c >= 0x1F) result += glyph[1] - 3;
//   即累加**字形高 - 3**。3 个调用点（居中菜单算总行高）。
//
//   漏 hook 它 -> 居中菜单拿到错误高度 -> 垂直居中错位 / 裁剪矩形算错。
//   汉字按 CJK_ADV_Y（= 15 - 3）计，与原式同构。
extern "C" int __cdecl Hook_MEASURE_H(const char* str, int font)
{
    if (!str) return 0;
    if (font < 0 || font > 16) font = 0;

    // ★★ 同 Hook_MEASURE：**绝不能**加表面锁判断 ★★
    //   原版 sub_451267 反编译确认函数体里没有 dword_521D2C 检查。
    //   加了会让居中菜单在布局期量到高度 0 -> 总行高为 0 ->
    //   垂直居中错位 / 裁剪矩形算错。详见 Hook_MEASURE 处的长注释。

    int h = 0;
    const unsigned char* s = (const unsigned char*)str;

    while (*s) {
        if (*s == 0x5E) {
            if (s[1] == 0) break;
            s += 2;
            continue;
        }
        if (*s > 0xA0) {
            h += CJK_ADV_Y;                   // 汉字：15 - 3
            s += (s[1] != 0) ? 2 : 1;
            continue;
        }
        {
            char tmp[2] = { (char)*s, 0 };
            int r = g_origMeasureH ? g_origMeasureH(tmp, font) : 0;
            if (r <= 0) {
                // ★ 用加页校验的 SafeGlyphHeader（崩溃修复：RVA 0x4D5C 同源）
                WORD* gh = SafeGlyphHeader(font, *s);
                r = gh ? ((int)gh[1] - 3) : 6;
                if (r <= 0) r = 6;
            }
            h += r;
            s += 1;
        }
    }

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
    return h;
}

// ── 三个绘制 hook（与原函数同签名、同调用约定、同返回类型 void）────────

// LEFT：6 参，**无**调用方裁剪矩形
extern "C" void __cdecl Hook_LEFT(int x, int y, const char* str,
                                  int font, int, char color)
{
    RenderCore(RK_LEFT, x, y, str, font, (int)(BYTE)color, 0, 0, 0, 0);
}

// ★ 第 4 参 a4 是 **font**（各调用点传 1 或 2，不固定）。
//   原实现把它当字体索引用（dword_698F6C[131*a4]），必须原样传递。
// ★ 第 5~8 参就是调用方裁剪 RECT 的 left/top/right/bottom
//   （原版 `sub_435EDE(v15, &a5, ...)` 直接把 &a5 当 RECT 用）。
extern "C" void __cdecl Hook_DIALOG(int x, int y, const char* str, int font,
                                    int l, int t, int r, int b, char color)
{
    RenderCore(RK_DIALOG, x, y, str, font, (int)(BYTE)color, l, t, r, b);
}

// CENTER：与 DIALOG 同签名，但 a1(x) 只用于居中、沿 y 累加
extern "C" void __cdecl Hook_CENTER(int x, int y, const char* str, int font,
                                    int l, int t, int r, int b, char color)
{
    RenderCore(RK_CENTER, x, y, str, font, (int)(BYTE)color, l, t, r, b);
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
               : (kind == RK_CENTER)    ? (void*)&Hook_CENTER
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
    Log("Renderer: hook #%d RVA=%#x kind=%d ours=%p patchLen=%d 原字节=%02X %02X %02X %02X %02X %02X",
        g_hookCount, targetRVA, kind, ours, patchLen,
        ins.orig[0], ins.orig[1], ins.orig[2], ins.orig[3], ins.orig[4], ins.orig[5]);
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
        ins.target = nullptr;
    }
    if (g_hookCount) Log("Renderer: 已恢复 %d 处原始字节", g_hookCount);
    g_hookCount = 0;
}

void RendererStats(LONG* calls, LONG* cjk, LONG* asciiFail)
{
    if (calls) *calls = g_calls;
    if (cjk) *cjk = g_cjkGlyphs;
    if (asciiFail) *asciiFail = g_asciiFail;
}

// ── probeOnly：只识别、不改内存 ────────────────────────────────────────
//
// ★ 与 2 代的区别（见 renderer.h 的说明）：
//   2 代的探针标记靠"序言恰好是 5 字节 mov eax,[imm32]"这一形状。
//   3 代序言是 `push ebp; mov ebp,esp; sub esp,38h`，没有那个形状，
//   硬套会破坏栈帧 -> 必崩。
//   而"验证档位表正确"这件事，**读字节比对**就已经完成了
//   （Target::VerifySignature 已做），所以这里只读、只记日志。
bool RendererProbeAt(DWORD targetRVA, const BYTE* expectOrig, int expectLen)
{
    if (!expectOrig || expectLen < 5) { Log("Probe: 参数不合法"); return false; }
    Log("Probe: RVA %#x 前 %d 字节 = %02X %02X %02X %02X %02X（只读，不改内存）",
        targetRVA, expectLen, expectOrig[0], expectOrig[1], expectOrig[2],
        expectOrig[3], expectOrig[4]);
    return true;
}
