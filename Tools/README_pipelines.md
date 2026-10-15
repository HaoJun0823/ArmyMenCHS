# 3 代汉化管线脚本（4 代可直接复用）

> 这两套脚本原本只存在于作者本机工作区（`I:\LocalGames\Army Men\scripts\`、
> `dub_test\`），3 代完工后迁入仓库，**专供 4 代复用**。
> 迁移时修正了若干失效路径（见每节 ★）。

---

## `Tools/title/` —— dat 打包贴图的烧字汉化

把 `title.dat` 里打包的 256 色贴图上的英文**抹掉并烧入中文点阵**，
尺寸与调色板严格保持，可无损回包。

| 脚本 | 作用 |
|---|---|
| `am3_hzk16.py` | Hzk16 字库读取（含 §2.3 **13 位对齐自检** `selftest()`） |
| `am3_title_lines.py` | 文字行检测（连通域 → 同行聚类 → 按词间隙切分）→ `lines.json` |
| `am3_title_render.py` | 抹字（调色板吸附）+ 点阵渲染 |
| `am3_title_build.py` | 按译文表批量构建 |
| `am3_title_pack_verify.py` | 回包 + 往返校验 |

算法原理与踩坑详见 [`../docs/09-am3-title-bitmap-chs.md`](../docs/09-am3-title-bitmap-chs.md)。

### ★ 迁移时保留的注意点

- **字库路径**：`am3_hzk16.py` 的 `DEFAULT_PATH` 指向
  `<仓库>/Army2_CHS/Hzk16`。3 代无中文母盘，字库是从 2 代中文版复用的 ——
  同一引擎的字库格式相同，**实机渲染同源无差异**。
- **13 位对齐**：每行 2 字节 = 16 位，字形只有 13 列且存放在**高 13 位**。
  读错会让每字左移 3 像素（"每字左边第一笔不见"），**极易漏看**。
  回归用**墨迹数**判据（如 `战` 正确 61 / 错读 44），不要用"最左列是否非空"。
- **工作目录**：`am3_title_lines.py` / `am3_title_render.py` /
  `am3_title_pack_verify.py` 的 `WORK` 仍指向工作区
  `I:\LocalGames\Army Men\_am3_title_work`（中间产物，不入库）。
  换机器运行时改这三个常量即可。

---

## `Tools/tts/` —— qwen3-tts 中文配音生成

3 代无中文配音母盘，171 条台词全部由 Qwen3-TTS **独立生成，非克隆真人**。

| 脚本 | 作用 |
|---|---|
| `_dl_model.py` / `_dl_base.py` / `_dl_customvoice.py` | 下载三个 Qwen3-TTS 模型 |
| `voice_cast.py` | **角色音色档案**（12 个角色的音色描述 + 固定 seed） |
| `_gen_voice_refs.py` | 生成每角色**基础音色参考音** → `Army3_Voice_CHS/base/` |
| `dub_plan.py` | 配音方案与指令注入逻辑（含**方案对比实测**结论） |
| `_batch_dub2.py` | 全量并行生成 → `Army3_Voice_CHS/audio/vos/` |
| `_scan_tts_unfriendly.py` | 扫描 TTS 不友好的台词（拟声、生僻读音等） |

### 模型（不入库，需自行下载）

三个模型共 **12.9 GB**，已在 `.gitignore` 中排除。用 `_dl_*.py` 下载：

| 模型 | 用途 |
|---|---|
| `Qwen3-TTS-12Hz-1.7B-Base` | 音色克隆（参考音 → 跨台词音色一致） |
| `Qwen3-TTS-12Hz-1.7B-VoiceDesign` | 从文字描述生成音色（造参考音用） |
| `Qwen3-TTS-12Hz-1.7B-CustomVoice` | 内置固定音色表 + instruct 情绪控制（实测未采用） |

> 下载脚本默认走代理 `http://127.0.0.1:7890`，按需修改。

### ★ 方案选择（实测结论，别重复试错）

| 方案 | 音色一致度 | 情绪 | 结论 |
|---|---|---|---|
| VoiceDesign 直出 | 0.9565 | ✅ | 音色每次重采样会漂移 |
| 多情绪参考音 → 克隆 | 0.8159 | ✅ | **音色漂移更严重，弃用** |
| **单参考音克隆 + 逐句 instruct 注入** | **0.9911** | ✅ | ★ **最优，采用** |
| CustomVoice + instruct | — | ✅ | 内置音色表，未采用 |

**实现要点**：`qwen_tts` 高层 `generate_voice_clone()` **未暴露 `instruct` 参数**；
但底层 `Qwen3TTSForConditionalGeneration.generate()` 同时接受
`instruct_ids` 与 `voice_clone_prompt`，**绕过高层直调底层**即可
"音色锁定 + 情绪可控"。

### ★ 指标不可信（重要）

实测发现 **MFCC / 说话人编码器 / yin 基频** 在游戏用的
**11025 Hz 低质音频上均不可靠** —— 编码器判定"HQ 最一致 0.9796"，
但人耳判断相反。**故一律以试听为准，不要用指标做判据。**

其他实测要点：

- **固定每角色 seed**（`GLOBAL_SEED = 19970823`）：同一角色跨台词音色稳定。
  实测固定 seed MFCC 相似度 0.95 vs 随机 seed 0.85。
- **bf16**：与 fp32 输出质量一致（ASR 匹配度同为 0.944），
  内存 4.35 GB vs 8 GB，**快约 40%**。
- **必须加时长上限**：纯拟声台词曾生成 15.84 秒（源 1.22 秒、文本仅 4 字），
  **13 倍失控**。批量脚本里已加。
- 输出对齐游戏原始 WAV 格式（16 bit / 11025 Hz）。

### ★ 迁移时修正的两处失效路径

| 脚本 | 原值（错） | 现值（对） | 后果 |
|---|---|---|---|
| `_batch_dub2.py` | `Army3_CHS_Voice\vos` | `Army3_Voice_CHS\audio\vos` | 原名是**不存在的目录**，生成结果落在仓库外，打包拿不到新配音 |
| `_gen_voice_refs.py` | `Army3_Voice_CHS\source` | `Army3_Voice_CHS\base` | `dub_plan.py` 从 `base\` 读参考音，写错位置克隆取不到 |

> `_batch_dub2.py` 的 `OUTDIR` 必须等于 `ci_build_am3.py` 的
> `AUDIO_SRC_DEFAULT`（`Army3_Voice_CHS/audio`），否则
> **游戏能启动但配音还是英文**，且不报任何错 —— 典型静默失效。

### ★ 许可

Qwen3-TTS 为 Apache-2.0，生成物随包分发需附版权声明。
3 代已随包提供 `LICENSES/qwen3-tts.txt`，4 代同样需要。

---

## `Tools/bmp_png_tool.py` —— BMP ↔ PNG 可逆转换

`bitmaps/` 下是 **8-bit 调色板 BMP**，直接编辑会破坏调色板。
本工具做可逆往返：

```
to-png    bitmaps/     -> bitmaps_png/    （8-bit BMP -> 24-bit RGB PNG，供改图）
to-bmp    bitmaps_png/ -> bitmaps_cn/     （改好的 PNG -> 8-bit BMP，保留原调色板）
```

**设计要点（为什么不能直接用普通转换）**：

- 反向转换时**原图调色板被完整保留**（背景灰阶、青色色键 `0,255,255` 都不变）
- 只确保调色板里存在黑 `(0,0,0)` 与白 `(255,255,255)` 两个索引
  （缺失则占用一个未使用槽位；全被占用则占最少使用的槽位），**其余颜色一律不动**
- 每像素按"最近调色板色"映射：原背景灰阶像素精确命中，手画的纯黑/纯白命中黑白，
  编辑器产生的抗锯齿灰边落到最近的背景灰阶上

> ★ **不覆盖原始 `bitmaps/` 下的任何文件。**

### 与 AI 汉化的关系

实际的"AI 自动汉化"流程是：`to-png` 导出 → 交给图像模型/人工改中文 →
`to-bmp` 导回 → 走 `ci_build_am3.py` 的 `DAT_JOBS` 回包。
`Tools/audit_bmp_am2.py` / `bmp_diff_region.py` / `bmp_side_by_side.py` /
`bmp_status_am2.py` / `bmp_bands_am2.py` 是配套的**审计与对比**工具
（差异统计、并排比对、状态盘点）。
