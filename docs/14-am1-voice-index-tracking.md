# Army Men 1 · 中文语音错引用追踪

> 状态：**部分解决** — 索引错标已修，27 条语音内容缺失待定
> 最后更新：2026-10-17
> 相关文件：`Army1_NEW_CHS/Audio/voices.asd`

## 1. 现象

玩家反馈：中文代理版存在语音错引用，典型表现为**任务失败时播出成功台词**。

## 2. 文件格式（源码确认）

`ArmyMenSourceCode/src/SND.H:189-201`：

```c
typedef struct {
    char          version[4];              // "V0.0"
    unsigned long numberOfSounds;          // 238
    SND_ENTRY     sounds[ SND_MAX_SOUNDS ]; // 固定 256 槽，不是 count 个
    SND_ENTRY     endOfTable;              // 实为 ASCII "THE  END"
} SND_HEADER;                              // 恒为 2064 字节

typedef struct {
    unsigned long soundID;   // 音效逻辑 ID
    unsigned long offset;    // 文件内偏移
} SND_ENTRY;
```

未使用的槽位填 `0xFF`。音频正文从第 2064 字节开始，每条为裸 WAV。

`voices.dat`（`ArmyMenSourceCode/src/`）是 ID 权威表，共 238 项，
两段：4000–4198（199 条）、**5000–5038**（39 条），中间 4199–4999 有意留空。

## 3. 错引用机制

`ArmyMenSourceCode/src/Voice.cpp:3229 voiceGetOffset()`：

```c
while ( (VOICEsndHeader->sounds[index].soundID != nSndID) && (index < maxIndex) )
    ++index;
if ( VOICEsndHeader->sounds[index].soundID != nSndID )
    TRACE("ERROR: snd ID (%d) not in .snd file");   // ← 注意
id_ptr = VOICEsndHeader->sounds[index].offset;        // ← 仍在使用
```

**关键点**：第二个 `if` 判读发生在 `index` 已等于 `maxIndex` 时，
即越界读 `sounds[238]`（落在 0xFF 填充区/邻接内存），
返回的不是 `SND_NULL_SND_ID` 而是**无关偏移**。

因此：请求一个表里不存在的 ID → 不静音、不报错 → **播出别的语音**。
这就是"失败台词播成成功台词"的根因，也解释了为什么错的是语义相近的句子。

## 4. 已修复

提交 `05e0d35`（前序 `c1ac75a` 因误判被 `7306188` 回滚）。

slot 237 的音频经 SHA256 逐字节比对，确认等于英文 `DESTROYED_SCRIPT`(5013)，
但索引标成了 `SARGE_LOW_HEALTH`(5011)。已改回 5013。

变更范围：仅 slot 237 的 `soundID` 一个 4 字节字段。
其余 237 项 ID、全部 238 个 offset、9,722,104 字节正文均未动。
校验：`sha256 c8bfb929...`，可字节判定的 12 项标签全部正确，无重复 ID。

## 5. 待解决：27 条语音内容缺失

中文包实际只有 211 个不同 ID，相对 `voices.dat` 缺失 27 个：

```
5011 SARGE_LOW_HEALTH     5012 HEAL_SARGE          5014 DS2M1B
5015 DS3M1B               5016 DS3M2B              5017 AS4M1_1
5018 AS4M1_2              5019 AS4M1_3             5020 BS3M1MID
5021 D12MID               5022 D31BAD              5023 BAYOU1_1M
5024 BAYOU3_1M            5025 BAYOU3_2M           5026 BAYOU4_1M
5027 DESERT1_2M           5028 DESERT2_2M          5029 ALPINE1_1M
5030 ALPINE2_1M           5031 ALPINE3_1SARGE      5032 ALPINE3_1M
5033 ALPINE4_2SARGE       5034 ALPINE1_1M2         5035 ALPINE3_1M2
5036 ALPINE3_1M3          5037 SARGE_GETTOMED      5038 SARGE_DONTLEAVE
```

**注意**：这不是本章第 4 节那种标签错标。这些 ID 在中文包里
既找不到音频、也找不到对应内容，是**真正的素材缺失**。

其中 `Sarge.cpp:1822` 与 `Sarge.cpp:2964` 会调用 `MsgBroadcast(HEAL_SARGE)`，
即 5012 会在正常游戏流程中被触发，属于必现缺失。

### 为什么不能靠重编号解决

最初假设"中文把 5000 段重编号为 4199–4225"，试图整体改写 ID 表
（提交 `c1ac75a`）。**该假设已被字节比对证伪**：

- slot 226–236 的内容与英文 5000–5010 逐字节相同（未配音音效），ID 原本正确；
  整体重编号反而把这 11 项改坏了（`c1ac75a` 已回滚 `7306188`）。
- slot 199–225 的长度与英文候选完全不吻合
  （中文 49792/14592/13280 vs 英文 32224/30688/18560），
  无法用长度推断归属。

剩 226 条重新配音的语音波形与英文不同，**没有字节或元数据可供自动对应**。

## 6. 后续方案

按优先级：

1. **听音辨认（当前推荐）**
   把 27 条中文候选解包成 WAV，对照 `voices.ast` 里的 27 条中文字幕
   （GBK 可读，含"前进至Ａ５区"等带明确坐标的句子），人工确认归属后改 ID。
2. **频谱指纹**
   对疑似同源不同配音版本的条目做 chromaprint 相似度比对，或可自动匹配一部分。
3. **重新补录**
   若确认素材本身不在任何已知版本里，只能补录这 27 句，或接受其保持英文。

### 为什么不做全量解包重打包

尚无必要：现有 211 条已经能对上使用，只有 27 条缺失；
而全量重打包会牵动所有 238 条，风险远大于收益。
若后续方案 1/2 都走不通、且确认素材彻底不存在，再考虑。

## 7. 复现 / 验证方法

```python
# 索引表：第 8 + i*8 字节为 soundID，+4 字节为 offset
import struct
d = open('voices.asd','rb').read()
c = struct.unpack_from('<I', d, 4)[0]
[(struct.unpack_from('<I', d, 8+8*i)[0],
  struct.unpack_from('<I', d, 8+8*i+4)[0]) for i in range(c)]
```

对照 `Army1_Original/audio/voices.asd`（英文原版）做 SHA256 逐条比对，
可找出所有"未配音、可直接确定 ID"的条目。

---

**下一步**：待杨浩钧决定如何处理这 27 条缺失素材——先试听音辨认 /
频谱指纹，还是直接标记为"保持英文"。本文件持续更新直到问题关闭。
