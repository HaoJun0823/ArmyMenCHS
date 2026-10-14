#include "pch.h"
#include "renderer.h"
#include "target.h"     // RenderKind
#include "hzk16.h"
#include "log.h"

#include <cstring>
#include <cstdio>

// ════════════════════════════════════════════════════════════════════════
//  背景（全部经 IDA 反编译实测）
//
//  AM2 有 **3 个独立的文字渲染器**（不是 1 个）：
//
//    LEFT   sub_446930(int x, int y, str, font, p5, color)
//             逐字符 x += 字宽
//    DIALOG sub_446AB0(x, y, str, font, ch, l, t, r, b)   带裁剪矩形
//             逐字符 x += 字宽
//    CENTER sub_446C50(x, y, str, font, ch, l, t, r, b)
//             首字符 x -= 字宽/2；逐字符 x += 字宽 - 3
//
//  三者共同点：都查同一套表
//     dword_659AD4[131*font]  ← 字形图集**堆绝对指针**（malloc 得来）
//     word_6598D4 [262*font + c] ← 字形在该图集内的**偏移**
//     word_659914 [262*font + c] ← 字符**步进宽度**（我最初漏了这张表）
//  字形头部 2 个 WORD = (宽, 高)，随后是 1bpp RLE。
//
//  ⚠️ 三个坑（实机验证时逐个暴露）：
//   1. atlasBase 是**绝对指针**不是 RVA，写成 imageBase+v 会全取不到字形
//   2. 只 hook 一个渲染器 -> 别的路径的文字（尤其对话框）完全不显示
//   3. 漏了宽度表 -> ASCII 步进错、且 CJK 不会换行
// ════════════════════════════════════════════════════════════════════════

typedef int  (__cdecl *PFN_rect)(const void* desc, void* rcSrc,
                                 int* px, int* py, void* outRect);
// ★★ blit 原型（IDA 实测，sub_41C710）
//
//   函数第一句就是铁证：
//       v8 = (char *)(dword_4FE1A8 + a1 + dword_502AD0 * a2);
//   其中 dword_4FE1A8 = 目标表面、dword_502AD0 = 行距(pitch)。
//   所以：a1 = x（横向），a2 = y（纵向），a3 = 字形数据指针。
//
//   调用点 sub_446930 / sub_446AB0 / sub_446C50 的入栈顺序也一致：
//       push a9(color); push arg_C; push arg_0(x); push var_4/8/C; push esi(y/glyph)
//   → 实际参数序为 (x, y, glyph, r0, r1, r2, r3, color)
//
//   我之前写成 (glyph, w, h, dx, dy, ...)，把 x/y 和 glyph 全错位了。
typedef void (__cdecl *PFN_blit)(int x, int y, int glyph,
                                 int r0, int r1, int r2, int r3, char color);

extern Hzk16Font* g_pFont;      // 定义在 hooks.cpp

static RendererEnv g_env;

// 已安装的 hook（最多 4 个）
struct Installed {
    BYTE* target = nullptr;
    BYTE  orig[16] = {0};
    int   len = 0;
    int   kind = 0;
};
static Installed g_hooks[8];
static int  g_hookCount = 0;

static volatile LONG g_calls = 0;
static volatile LONG g_cjkGlyphs = 0;
static volatile LONG g_asciiFail = 0;
static volatile LONG g_advances = 0;


void RendererSetEnv(const RendererEnv& env) { g_env = env; }
bool RendererIsInstalled() { return g_hookCount > 0; }

static inline BYTE* ImageBase() { return (BYTE*)GetModuleHandleA(nullptr); }

// ════════════════════════════════════════════════════════════════════════
//  ★★★ 地址语义（摔过两次的坑，改动前务必读完）
//
//  下面所有 VA 字段都是**绝对虚拟地址**（IDA 里显示的值），
//  读取时**必须原样当地址用，绝不能再加 ImageBase**。
//
//  dump 0x188028 的崩溃就是这里：
//      *(BYTE**)(ImageBase() + 0x4FE1A8)
//    = *(BYTE**)(0x400000 + 0x4FE1A8)
//    = *(BYTE**)(0x008FE1A8)   ← 野地址，读崩
//  而正确的目标正是 ECX 里的 0x4FE1A8。
//
//  ★ 唯一的例外是 atlasBase：那个全局的**内容**是 malloc 的堆指针，
//    取出来也要原样当指针用 —— 这两处的"正确做法"恰好一致：
//    **不要加 ImageBase**。
// ════════════════════════════════════════════════════════════════════════
static inline BYTE*  VaToPtr(DWORD va) { return (BYTE*)(DWORD_PTR)va; }

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
static inline WORD* CharWidth(int font) {
    if (!g_env.charWidthVA) return nullptr;
    return (WORD*)VaToPtr(g_env.charWidthVA + 262 * font * 2);
}


// ── 全局裁剪矩形 rcSrc2 ────────────────────────────────────────────────
//
// ★★ "文字渐显时花屏"的成因（用户第 4 项反馈，且明确指出"之前版本没有"）
//
//   这是我引入的**回归**，不是原版行为。两次改动叠加：
//
//   (a) 最初版本只判屏幕边界：
//           if (curX >= 0 && curX + w <= 640 && y >= 0 && y + 13 <= 480)
//       —— 有上下界，不会写出表面。
//
//   (b) 上一轮为了修"部分显示"问题，改成用调用方的 clipL/T/R/B 裁剪：
//           const bool hasClip = (clipR > clipL) && (clipB > clipT);
//           if (py < 0) continue;                 // 只挡上/左
//           if (hasClip && (py < clipT || py >= clipB)) continue;
//       ★ 问题：LEFT 渲染器（sub_446930）只有 6 个参数、**没有**裁剪矩形，
//         传进来的 clipL/T/R/B 全是 0 → hasClip == false →
//         整个上界判断被短路，只挡住了"小于 0"的一侧。
//         文字向右/向下越过表面下界时**不再被拦**，直接写出缓冲区 → 花屏。
//         渐显/滚动恰好让文字部分越界，所以"出现时花屏、全显示后正常"。
//
//   修法：恢复上界，并补上原版真正使用的裁剪来源 rcSrc2。
//
//   rcSrc2 的依据（IDA 实测）：原版每个字形都做两步裁剪
//       sub_42E220(&v23, &rcSrc2, &a4, &a1, v27);   // ① 全局 rcSrc2
//       sub_42E220(v27, &a5,   &a4, &a1, &v23);     // ② 调用方矩形
//   它由上层在绘制文本前设定（渐显、滚动、部分可见列表项都靠它限定可见区），
//   且**每帧变化**。LEFT 渲染器唯一依赖的就是它。
struct ClipRect { int l, t, r, b; bool valid; };

static ClipRect GlobalClip()
{
    ClipRect c{0, 0, 0, 0, false};
    if (!g_env.clipRectVA) return c;
    const int* p = (const int*)VaToPtr(g_env.clipRectVA);
    c.l = p[0]; c.t = p[1]; c.r = p[2]; c.b = p[3];
    // 只接受"非空正矩形"，否则认为未设定（避免读到 0 矩形把文字全裁掉）
    c.valid = (c.r > c.l) && (c.b > c.t);
    return c;
}

// ★ 直接把 rcSrc2 的地址交给游戏自己的 rect 函数（sub_42E220）。
//   官方就是这么做的：rect(desc, &rcSrc2, ...) —— 由游戏决定怎么解读。
//   我不再自己判断"矩形是否有效"：0 矩形就该裁光一切，这是原版语义。
//   （此前我把 0 矩形当"未设定"而忽略，导致本该被裁掉的字形照画 -> 花屏）
static void* GlobalClipPtr()
{
    if (!g_env.clipRectVA) return nullptr;
    return (void*)VaToPtr(g_env.clipRectVA);
}


// ── 落笔原点偏移 rc（原版在 blit 前做，我最初漏了）────────────────────
//
// 原版三个渲染器都一样：
//     if (dword_507128 == dword_502AD4) {   // 当前锁定的就是主表面
//         x += rc.left;                     // ★ 加 rc 原点
//         y += rc.top;
//     }
//     sub_41C710(x, y, glyph, ...);
//
// rc 由窗口消息更新（WM_SIZE/WM_MOVE → GetClientRect + ClientToScreen），
// 含义是"后备缓冲在主表面中的左上角"。画到主表面时要补这个偏移。
//
// ★ 这解释了"首次进入正常、后续花屏"：
//   首次进入某界面时 rc 往往是 (0,0)（刚切场景、坐标未变），
//   之后窗口/分辨率/界面变化使 rc 变成非零，我的字形就整体偏移 -> 花屏。
static inline void GetRcOrigin(int* ox, int* oy)
{
    *ox = 0; *oy = 0;
    if (!g_env.rcVA || !g_env.lockedSurfVA || !g_env.primarySurfVA) return;
    // 只在"当前锁定的是主表面"时补偏移（与原版条件一致）
    const DWORD locked = *(const DWORD*)VaToPtr(g_env.lockedSurfVA);
    const DWORD primary = *(const DWORD*)VaToPtr(g_env.primarySurfVA);
    if (locked != primary) return;
    const int* rc = (const int*)VaToPtr(g_env.rcVA);
    *ox = rc[0];   // rc.left
    *oy = rc[1];   // rc.top
}


// ── CJK：完全照官方中文版 sub_446B00 的路径 ──────────────────────────
//
// ★ 每一句都对应官方实现（IDA 实测 sub_446B00 / sub_446D40 / sub_446FB0）。
//   之前连摔三次，根因都是"我自己复刻裁剪 + 用错逻辑尺寸"。
//
// 官方对汉字一律用 15x15 作为**逻辑尺寸**（desc 与步进都用它），
// 而点阵本身只有 13x13。这两个数都不能改：
//   * desc 必须 15x15，否则 rect 裁剪边界与原版差 2px
//   * 步进必须 15，否则每字少走 2px，长串累积偏移 -> 越界写出 -> 花屏
// 显示区尺寸（0x4852D8 / 0x4852DC）。官方只用它设置显示模式，
// 我们拿它当"像素写入的内存安全上界"——语义裁剪仍由 rcSrc2 决定。
static volatile LONG g_clampHits = 0;

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

static const int CJK_BOX   = 15;   // 逻辑尺寸：desc / 步进 / 行高
static const int CJK_INK_W = 13;   // 点阵实际列数
static const int CJK_INK_H = 13;   // 点阵实际行数

// 绘制结果三态 —— 对应官方两处不同的失败处理
enum CjkResult {
    CJK_OK      = 0,   // 已绘制
    CJK_SKIP    = 1,   // 被裁光，跳过该字形（DIALOG/CENTER 语义）
    CJK_ABORT   = 2,   // 被裁光，**整个函数返回**（LEFT 语义）
};

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
    //
    // ★ VA=0 的语义是"该档位不需要 / 尚未测量这项"，不是错误：
    //   例如 TIS 档位只做 probeOnly（不接管渲染），rc/locked/primary 都没填。
    //   但**真正会用到**的项缺了就是错误 —— 见 REQUIRED 标记。
    struct Chk { const char* nm; DWORD va; bool required; };
    Chk checks[] = {
        {"surface",   g_env.surfaceVA,      true},
        {"pitch",     g_env.pitchVA,        true},
        {"atlasBase", g_env.atlasBaseVA,    true},
        {"atlasOffs", g_env.atlasOffsetVA,  true},
        {"charWidth", g_env.charWidthVA,    true},
        {"clipRect",  g_env.clipRectVA,     true},   // 裁剪必须转调它
        {"rect",      g_env.rectVA,         true},   // 裁剪函数本体
        {"rc",        g_env.rcVA,           true},   // 落笔原点偏移
        {"lockedSurf",g_env.lockedSurfVA,   true},
        {"primary",   g_env.primarySurfVA,  true},
        {"enabled",   g_env.enabledVA,      true},   // 表面锁标志
        {"dispW",     g_env.dispWVA,        false},  // 显示区宽（安全网用）
        {"dispH",     g_env.dispHVA,        false},  // 显示区高（安全网用）
        {"blit",      g_env.blitVA,         false},  // 仅 ASCII 直绘时用
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

    if (report) *report = r;
    return true;
}


// ── 通用渲染主体 ────────────────────────────────────────────────────────
//
// ★★ 返回值契约（这是"创建玩家档案输入不了"的根因）
//
//   原版三个渲染器都返回 **文本绘制结束后的 x 坐标**：
//       sub_446AB0:  result = a1;  ...  result = 字宽 + v21;  v21 = result;
//       sub_446C50:  同上（末尾 -3）
//   调用方（编辑框、列表）靠这个返回值定位光标、判断能否继续追加字符。
//
//   我最初 `return 0` —— 调用方以为"文本没有宽度"，
//   sub_44D520 里的宽度检查失败 -> 按键被拒 -> **输入不了任何内容**。
//
//   所以这里必须忠实返回结束 x，不能图省事返回 0。
// ════════════════════════════════════════════════════════════════════════
//  ★★ 策略变更（第 5 轮实机"创建玩家档案输入不了"之后）
//
//  之前我**完整复刻**了 ASCII 绘制（自己调 rect + blit），结果连续踩坑：
//    * blit 参数序写错（x/y 与 glyph 互换）
//    * DIALOG 的 font 参数硬编码成 1
//    * 返回值契约（结束 x）被我返回成 0
//    * 编辑框依赖返回值定位光标 -> 输入不了
//
//  这些都源于"我在重造游戏自己的逻辑"。更稳的做法是**最小化介入**：
//
//      ASCII 段  → 逐个转调**未被覆盖的原始函数副本**（stub），
//                  原实现的所有细节（字体、裁剪、返回值）自动正确
//      CJK 段    → 自己画（13x13 点阵直接写表面，已离线+实机验证可行）
//
//  代价：ASCII 每字符一次函数调用（文本量小，可接受）。
//  收益：不再需要猜任何 ASCII 相关的语义。
// ════════════════════════════════════════════════════════════════════════

// 原始函数副本（stub）：把被 jmp 覆盖前的 7 字节搬过来 + 跳回原处 +8
// 由 RendererInstallAt 为每个 hook 生成。
typedef int (__cdecl *PFN_render_left)(int, int, const char*, int, int, int);
typedef int (__cdecl *PFN_render_dlg)(int, int, const char*, int,
                                      int, int, int, int, int);
static PFN_render_left g_origLeft = nullptr;
static PFN_render_dlg  g_origDialog = nullptr;
static PFN_render_dlg  g_origCenter = nullptr;

// ── 诊断（"首次正常、后续花屏"无法本地复现，故输出有界状态快照）──────
//
// 策略：前 40 次混合串绘制每次都记，之后每 200 次记一次。
// 每条包含：表面/pitch/是否锁主表面/rc 原点/rcSrc2/坐标，
// 足以判定到底是"越界写出"、"rc 偏移没加"、还是"裁剪矩形异常"。
static volatile LONG g_diagCount = 0;

static void DiagLogText(int kind, int x, int y, const char* str, int font)
{
    LONG n = InterlockedIncrement(&g_diagCount);
    if (n > 40 && (n % 200) != 0) return;

    BYTE* base = ImageBase();
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
}

static int RenderCore(int kind, int x, int y, const char* str, int font,
                      int color, int clipL, int clipT, int clipR, int clipB)
{
    InterlockedIncrement(&g_calls);
    if (!str) return x;

    // ★ 官方每个渲染器的第一句：表面未锁定 -> 一个字都不画。
    if (g_env.enabledVA && *(const DWORD*)VaToPtr(g_env.enabledVA) == 0)
        return x;

    // surface/pitch 在 unlock 时会被清零，所以每次重新读（不缓存）
    if (!SurfacePtr() || Pitch() <= 0) return x;
    if (font < 0 || font > 16) font = 0;

    const BYTE* s = (const BYTE*)str;

    // ── 快速路径：整串 ASCII -> 整串转调原函数（零行为差异）──
    bool hasCjk = false;
    for (const BYTE* p = s; *p; ++p) {
        if (*p > 0xA0) { hasCjk = true; break; }
    }
    if (!hasCjk) {
        if (kind == RK_LEFT && g_origLeft)
            return g_origLeft(x, y, str, font, clipL, color);
        if (kind == RK_DIALOG && g_origDialog)
            return g_origDialog(x, y, str, font, clipL, clipT, clipR, clipB, color);
        if (kind == RK_CENTER && g_origCenter)
            return g_origCenter(x, y, str, font, clipL, clipT, clipR, clipB, color);
        return x;
    }

    // ── 混合串：ASCII 逐字转调原函数，汉字自绘 ────────────────────────
    //
    // ★ 两个轴必须分开（官方实测）：
    //     LEFT / DIALOG ：沿 x 累加，y 固定 = 传入的 y
    //     CENTER        ：x 每字独立居中（由原函数/我们按各自字形宽算），
    //                     沿 **y** 累加（官方 v21 += h - 3）
    //   我之前一律沿 x 推进并对 CENTER 减了 3 —— 轴错了，减 3 也错了。
    const bool axisY = (kind == RK_CENTER);
    int acc = axisY ? y : x;               // 沿各自轴的累加器
    const int anchor = x;                  // CENTER 的居中基准（原始 x）
    BYTE curColor = (BYTE)color;

    // 官方只有 DIALOG/CENTER 带"调用方裁剪矩形"
    const bool hasClip = (kind != RK_LEFT);

    DiagLogText(kind, x, y, str, font);    // 有界诊断（见其说明）

    while (*s) {
        // '^' 颜色转义（官方条件：后面还有字节）
        if (*s == 0x5E && s[1] != 0) { curColor = (BYTE)s[1]; s += 2; continue; }

        if (*s > 0xA0 && s[1] != 0) {
            // ── 汉字：官方 desc/步进恒用 15 ──
            if (g_pFont && g_pFont->IsLoaded()) {
                // CENTER 要自己算居中（原函数只替 ASCII 算）
                int hx = axisY ? (anchor - CJK_BOX / 2) : acc;
                int hy = axisY ? acc : y;

                int ink = 0;
                CjkResult r = DrawCjk13(*g_pFont, s[0], s[1], hx, hy, curColor,
                                        Pitch(), clipL, clipT, clipR, clipB,
                                        hasClip, &ink);
                if (ink > 0) InterlockedIncrement(&g_cjkGlyphs);

                // ★ 官方 LEFT：rcSrc2 裁光则**整个函数返回**（其余字不再画）
                if (r == CJK_ABORT) return acc;
            }
            acc += CJK_BOX;               // 汉字步进 = 15
            s += 2;
            continue;
        }

        // ── ASCII：单字转调原函数 ──
        //    CENTER 必须传**原始 anchor**：原函数内部会做 a1 - w/2，
        //    我若预先减了 w/2 就成双重居中。
        {
            char tmp[2] = { (char)*s, 0 };
            int ax = axisY ? anchor : acc;
            int ay = axisY ? acc : y;
            int r = acc;

            if (kind == RK_LEFT && g_origLeft)
                r = g_origLeft(ax, ay, tmp, font, clipL, curColor);
            else if (kind == RK_DIALOG && g_origDialog)
                r = g_origDialog(ax, ay, tmp, font, clipL, clipT, clipR, clipB, curColor);
            else if (kind == RK_CENTER && g_origCenter)
                r = g_origCenter(ax, ay, tmp, font, clipL, clipT, clipR, clipB, curColor);

            // 原函数返回"下一个位置"。CENTER 沿 y 推进，故 r 是新的 y；
            // LEFT/DIALOG 沿 x 推进，r 是新的 x。
            if (r > acc) {
                acc = r;
            } else {
                WORD* cw = CharWidth(font);
                int adv = cw ? cw[(BYTE)*s] : 0;
                acc += (adv > 0 ? adv : 8);   // 兜底，保证循环终止
            }
            s += 1;
        }
    }
    return acc;
}



// ── 导出给各 hook 的 thunk（签名与原函数一致）────────────────────────
//
// ★ 真实参数序（IDA 实测调用点）：
//   sub_446930(x, y, str, font, p5, color)                 6 参
//   sub_446AB0(x, y, str, 1, left, top, right, bottom, color)  9 参
//        —— 见 sub_4569A0：sub_446AB0(*v3, y, v11, 1,
//                                     rcSrc1.left, .top, .right, .bottom, v9)
//        ★ 第 5 个参数是 left，最后一个才是 color。
//          我之前把 b 当 color、把 color 当 b，正好反了。
//   sub_446C50(x, y, str, font, ?, l, t, r, b)             9 参（同 DIALOG 形）
// ── stub 构造 ──────────────────────────────────────────────────────────
//
//  布局： [原始 N 字节] [jmp rel32 -> 原函数+N]
//  这样"调用 stub" 完全等价于"调用未被 hook 的原函数"。
//
//  ★ 注意：原函数前 N 字节必须构成**完整的指令**，否则跳转后会执行到
//    半条指令上。我们在安装时已确保 patchLen=7 且前 5 字节是
//    `A1 xx xx xx xx`（mov eax,[imm32]，5 字节完整指令），
//    第 6、7 字节是下一条指令的开头，不能用 7 字节做 stub 边界 ——
//    所以这里**只用前 5 字节**（一条完整指令），再 jmp 到 +5。
bool RendererBuildStubs()
{
    for (int i = 0; i < g_hookCount; i++) {
        Installed& ins = g_hooks[i];
        if (!ins.target || ins.len < 5) continue;

        const int N = 5;                    // 一条完整指令（A1 imm32）
        BYTE* stub = (BYTE*)VirtualAlloc(nullptr, 32, MEM_COMMIT | MEM_RESERVE,
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

        if (ins.kind == RK_LEFT)   g_origLeft = (PFN_render_left)stub;
        if (ins.kind == RK_DIALOG) g_origDialog = (PFN_render_dlg)stub;
        if (ins.kind == RK_CENTER) g_origCenter = (PFN_render_dlg)stub;
        Log("Renderer: stub[%d] = %p -> 原函数 %p +%d", i, (void*)stub,
            (void*)ins.target, N);
    }
    return (g_origLeft || g_origDialog || g_origCenter);
}

extern "C" int __cdecl Hook_LEFT(int x, int y, const char* str,
                                 int font, int, int color)
{
    return RenderCore(RK_LEFT, x, y, str, font, color, 0, 0, 0, 0);
}

// ★ 第 4 参 a4 是 **font**（编辑框传 this+92，不一定等于 1）。
//   原实现把它当字体索引用（dword_659AD4[131*a4]），必须原样传递。
extern "C" int __cdecl Hook_DIALOG(int x, int y, const char* str, int font,
                                   int l, int t, int r, int b, int color)
{
    return RenderCore(RK_DIALOG, x, y, str, font, color, l, t, r, b);
}

extern "C" int __cdecl Hook_CENTER(int x, int y, const char* str, int font,
                                   int l, int t, int r, int b, int color)
{
    return RenderCore(RK_CENTER, x, y, str, font, color, l, t, r, b);
}

// ── 安装 ────────────────────────────────────────────────────────────────
bool RendererInstallAt(DWORD targetRVA, int kind, const BYTE* expect,
                       int expectLen, int patchLen)
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

    // ★ 安装前再校验一次原始字节（Detect 与 Install 之间可能被别的补丁改过）
    if (expect && expectLen > 0 && memcmp(target, expect, expectLen) != 0) {
        Log("Renderer: !! RVA %#x 安装前重校验失败，放弃", targetRVA);
        return false;
    }

    void* ours = (kind == RK_DIALOG) ? (void*)&Hook_DIALOG
               : (kind == RK_CENTER) ? (void*)&Hook_CENTER
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
    Log("Renderer: hook #%d RVA=%#x kind=%d ours=%p 原字节=%02X %02X %02X %02X %02X",
        g_hookCount, targetRVA, kind, ours,
        ins.orig[0], ins.orig[1], ins.orig[2], ins.orig[3], ins.orig[4]);
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

// ── probeOnly：无副作用标记（给未验证的档位用）────────────────────────
static volatile DWORD g_probeSentinel = 0x414D4348;   // 'HCMA'

bool RendererProbeAt(DWORD targetRVA, BYTE* expectOrig, int expectLen)
{
    if (expectLen < 5 || !expectOrig) { Log("Probe: 参数不合法"); return false; }
    BYTE* base = ImageBase();
    DWORD size = ((IMAGE_NT_HEADERS*)(base +
                  ((IMAGE_DOS_HEADER*)base)->e_lfanew))->OptionalHeader.SizeOfImage;
    if (targetRVA + 6 > size) { Log("Probe: 目标越界"); return false; }
    if (expectOrig[0] != 0xA1) {
        Log("Probe: 序言不是 A1（实得 %02X），拒绝标记", expectOrig[0]);
        return false;
    }

    DWORD imm = (DWORD)(DWORD_PTR)&g_probeSentinel;
    BYTE patch[6];
    patch[0] = 0xA1;
    memcpy(patch + 1, &imm, 4);
    patch[5] = 0xC3;                      // ret

    DWORD oldProt = 0;
    if (!VirtualProtect(expectOrig, 6, PAGE_EXECUTE_READWRITE, &oldProt)) {
        Log("Probe: VirtualProtect 失败 (%lu)", GetLastError());
        return false;
    }
    Log("Probe: 原字节 = %02X %02X %02X %02X %02X %02X",
        expectOrig[0], expectOrig[1], expectOrig[2],
        expectOrig[3], expectOrig[4], expectOrig[5]);
    memcpy(expectOrig, patch, 6);
    DWORD tmp = 0;
    VirtualProtect(expectOrig, 6, oldProt, &tmp);
    FlushInstructionCache(GetCurrentProcess(), expectOrig, 6);

    Log("Probe: 已在 RVA %#x 挂上无副作用标记（哨兵=%p），未接管渲染",
        targetRVA, (void*)&g_probeSentinel);
    return true;
}
