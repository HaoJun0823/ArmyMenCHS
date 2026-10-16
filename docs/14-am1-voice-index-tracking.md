# Army Men 1 · 中文语音索引错引用：根因与重打包方案

> 状态：**已解决** — 根因查清，中文 1.0 语音资产已重打包为英文 1.2 ID 体系
> 最后更新：2026-10-17
> 相关提交：`96ce1aa`（重打包）、`328b83b` / `7306188`（回滚两次错误修复）
> 相关文件：`Army1_NEW_CHS/Audio/voices.asd`、`voices.ast`
> 工具：`Tools/asd_tool/asd_tool.py`

## 0. 结论摘要

玩家反馈的"任务失败播出成功台词"等现象，根因**不是**素材损坏、**不是**
索引写错、也**不是**越界读取，而是：

> **Steam 版是 1.2，中文代理版是 1.0。两个版本的 exe 各自内置一份
> ID→名字 表，编号体系不同。把 1.0 编号的中文语音包直接放进 1.2 游戏，
> 游戏按自己（英文）的 ID 表查表，必然大面积错位。**

修复方式：中文音频字节一字不动，只按符号名重建 `中文ID → 英文ID`
映射并重写索引表，产出 1.2 体系的中文语音包。

本文件同时记录此前两次**错误修复**的经过——它们的错误前提值得留档。

---

## 1. 文件格式（源码 + 反编译双向确认）

`ArmyMenSourceCode/src/SND.H`：

```c
typedef struct {
    char          version[4];               // "V0.0"
    unsigned long numberOfSounds;           // 238
    SND_ENTRY     sounds[ SND_MAX_SOUNDS ]; // 固定 256 槽，不是 count 个
    SND_ENTRY     endOfTable;               // 实为 ASCII "THE  END"
} SND_HEADER;                               // 恒为 2064 (0x810) 字节

typedef struct {
    unsigned long soundID;
    unsigned long offset;
} SND_ENTRY;                                // 8 字节
```

- 头部固定 **2064 字节**；音频正文从 2064 起，每条为裸 IFF（`fmt ` + `data`），
  8bit / 11025Hz / mono，**条目之间无填充字节** → 可字节级回包。
- 未使用槽位填 `0xFF`。
- 反编译中文 exe `sub_4673F0` 确认：`malloc(0x810u); fread(v3, 0x810u, 1u)`
  → **中文 1.0 的结构与源码完全一致，没有变体。**

### 曾踩的坑（都是我自己的错误假设，非文件缺陷）

| 错误假设 | 实际 |
|---|---|
| 首个 offset 应等于表尾（1912） | 头部是固定 2064，非"表尾" |
| `endOfTable` 是 `0xFFFFFFFF` | 是 ASCII `"THE  END"`（两个空格） |

---

## 2. 根因：1.0 与 1.2 的 ID 表不同

两个 exe 都在 `.data` 段内嵌一份 `{u32 id; char name[68]}` 表，stride 72：

| 版本 | exe | 大小 | 表 VA | 条目 | ID 范围 |
|---|---|---|---|---|---|
| 中文 1.0 | `玩具兵大战1/Armymen.exe` | 742912 B | `0x479DF0` | 238 | 4000–4225 + 5000–**5011** |
| 英文 1.2 | `Army Men I STEAM/Armymen.exe` | 993280 B | `0x4BFBC0` | 238 | 4000–4198 + 5000–**5038** |

查表函数 `voiceGetOffset`（源码 `Voice.cpp:3229`，中文 exe 中为
`sub_4689C0`，调用方 `sub_4674B0`）**线性匹配 soundID**。

关键反编译结论：调用方**检查了返回值**：

```
if ( v25 == -1 ) goto LABEL_22;      // 找不到 → 放弃播放（静音）
```

所以**请求不存在的 ID 只会静音，不会播出别的语音**。这一点推翻了
"越界读导致错引用"的旧结论——错位的真正来源是编号体系不匹配：
1.2 的 ID 在 1.0 包里存在，但指向的是**另一句话**。

---

## 3. 两版编号的差异结构

以符号名为锚比较两版：

| 类型 | 数量 |
|---|---|
| 两版都有、ID 相同 | 66 |
| 两版都有、ID 不同 | 144 |
| 仅中文有（28 个 `XXX2`） | 28 |
| 仅英文有（28 个 `XXX`） | 28 |

差异规律：

1. **中文 1.0 在 4055 之前插入了 4 个条目** → 其后 111 个 ID 统一 `+4`。
2. **28 条符号名带 `2` 后缀**（`ATTACKING_TANK2` 等）。经 `.ast` 台词逐条
   比对，确认它们与英文的 `ATTACKING_TANK` **语义一一对应**，是同一句话，
   只是 1.0 时期加了后缀。**不是新增条目。**
3. **尾部 ID 体系完全不同**：中文 4203–4225 对应英文 5014–5038。
4. 两处跨段移动：`SARGE_LOW_HEALTH` / `HEAL_SARGE`
   英文 5011/5012 → 中文 4055/4056。

**两版都是同一套 238 条内容**，没有任何一方真正多出或缺失素材。

---

## 4. 解决方案：按符号名重编号并重打包

音频字节全部保留，只重写索引表的 `soundID`：

1. 用 `asd_tool.py --exe-names --exe-va 0` 从两个 exe 各提取内置名字表
   （自动搜索特征串 `(u32)4000 + "THERE_HE_IS"` 定位 VA）。
2. 以符号名为锚建立 `中文ID → 英文ID` 映射：中文名带 `2` 后缀时去掉后缀
   再匹配英文名。**不再用任何算术偏移猜测。**
3. `remap` 子命令按映射重写索引，`pack` 重新打包 `.asd` 与 `.ast`。

### 映射校验

```
中文 238 条 -> 英文 238 条：可映射 238/238，无法映射 0
双射检查：映射值重复 0，英文 ID 未覆盖 0
remap 统计：改 172 / 未变 66 / 失败 0
```

### 产物验证（全部通过）

| 项 | 结果 |
|---|---|
| 音频正文 vs 中文原包（逐 slot SHA256） | 相同 **238/238** |
| ID 被 1.2 exe 表识别 | **238/238** |
| ID 集合 == 1.2 表集合 / 无重复 | ✅ |
| 模拟 1.2 全部 238 个 ID 查找 | 失败 **0** |
| 偏移单调递增 / 每条以 `fmt ` 开头 | ✅ |
| `pack(unpack(x)) == x` 字节还原 | ✅ |
| `.ast` 160 条中文字幕按映射搬运 | **160/160**，全部可对应 1.2 表 |

字幕保留中文（游戏已移植 1.0 字库，GBK 渲染无问题）。

---

## 5. 错误修复留档（重要教训）

两次基于**错误前提**的提交，均已回滚：

### `c1ac75a`（已回滚 `7306188`）

假设"中文把 5000 段整体重编号为 4199–4225"，按 `5000+(slot-199)` 改写
slot 199–237。**错误原因**：该推断仅来自英文 `voices.dat` 的自洽性，
未经音频内容验证。实际 slot 226–236（ID 5000–5010）与英文逐字节相同、
ID 本来就对，改写反而改坏了 11 项。

### `05e0d35`（已回滚 `328b83b`）

把 slot 237 的 ID 从 5011 改为 5013，理由是"5011 应为 SARGE_LOW_HEALTH"。
**错误原因**：中文 exe 定义 `SPLASH=5010`、`DESTROYED_SCRIPT=5011`、
`HEAL_SARGE=4056`——**5011 在中文 ID 空间里是合法的**。用英文编号判断
中文编号是否"越界"，前提就错了。

### 教训

> 拿**另一个版本**的 ID 表当权威去"校准"本版本，方向从根上就是错的。
> 判断归属必须用**该版本自己的**符号表，且映射依据应是符号名，
> 不是偏移量或编号算式的自洽性。

---

## 6. 复现 / 验证方法

```python
import struct
d = open('voices.asd', 'rb').read()
c = struct.unpack_from('<I', d, 4)[0]          # 238
ids = [(struct.unpack_from('<I', d, 8+8*i)[0],
        struct.unpack_from('<I', d, 8+8*i+4)[0]) for i in range(c)]
assert d[:4] == b'V0.0'
assert d[8+256*8:8+256*8+8] == b'THE  END'
assert ids[0][1] == 2064
```

工具自带自检：

```bash
python Tools/asd_tool/asd_tool.py selftest
```

覆盖 `voices.asd` 与 `sounds.asd`，验证 `pack(unpack(x)) == x`。

### 工具用法

```bash
# 解包（各版本用自己的 exe 取名字表；--exe-va 0 = 自动搜索）
python asd_tool.py unpack voices.asd out/ --ast voices.ast \
       --exe-names Armymen.exe --exe-va 0

# 重编号（音频不动）
python asd_tool.py remap out/ --map id_map_zh2en.json --exe-names Armymen.exe

# 重新打包
python asd_tool.py pack out/ new.asd --ast new.ast
```

---

## 7. 遗留事项

1. **`sounds.asd` 未处理**。它也有中英两份，可能同样存在 ID 体系差异，
   需同样方式核查（本次只处理了 `voices.asd`/`.ast`）。
2. **需进游戏实测**。建议优先确认此前必定播错的三条：
   `HEAL_SARGE`（原 4056 → 现 5012）、`SARGE_GETTOMED`（原 4224 → 现 5037）、
   `D31BAD`（原 4211 → 现 5022）。
3. 备份位置：`Army1_Object_CHS/_bak_voice_zh_*`、
   `_trash/audio_pre_zh12_*`，可回退。

---

**下一步**：进游戏实测中文配音是否已正确对应；确认后按同样方法处理
`sounds.asd`。
