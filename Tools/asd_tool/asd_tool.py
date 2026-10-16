#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Army Men 1 · 语音容器 (.asd / .ast) 解包与打包工具
=================================================

格式依据（均来自 ArmyMenSourceCode 源码，非逆向猜测）
----------------------------------------------------
`src/SND.H:189-201`：

    typedef struct {
        char          version[4];              // "V0.0"
        unsigned long numberOfSounds;          // 实际条目数
        SND_ENTRY     sounds[ SND_MAX_SOUNDS ]; // 固定 256 槽，不是 count 个
        SND_ENTRY     endOfTable;              // 实为 ASCII "THE  END"
    } SND_HEADER;                              // 恒为 4+4+256*8+8 = 2064 字节

    typedef struct {
        unsigned long soundID;   // 逻辑音效 ID
        unsigned long offset;    // 文件内绝对偏移
    } SND_ENTRY;                 // 8 字节

未使用的槽位填 0xFF。音频正文自第 2064 字节起，每条为裸 8bit/11025Hz/mono
WAV 片段（fmt + data 两个 IFF chunk，实测无填充字节）。

`src/Voice.cpp:3511 voiceLoadText()` 读同名的 .ast 文件：

    CPYR{chunkSize, 文本"ArmyMen-3DO COMPANY (C)1997"}
    VTXT{size, voiceID u32, len u32, GBK文本}  × N

注意 .asd 有 238 条音频，.ast 只有 160 条文本（非语音条目没有台词）。

用法
----
    # 解包
    python asd_tool.py unpack <in.asd> <out_dir> [--ast <in.ast>] [--prefix NAME]

    # 打包
    python asd_tool.py pack <dir> <out.asd> [--ast <out.ast>]

解包产物
--------
    out_dir/
      0000_4000_THERE_HE_IS.wav            # 序号_ID_名称.wav
      0000_4000_THERE_HE_IS.txt            # 若提供 --ast，同名 .txt 存台词(utf-8)
      ...
      _index.json                          # 完整索引，含未使用槽位信息

 `_index.json` 是打包的唯一依据，里面保留了 voiceID 原始编号，
打包时会原样写回，因此支持人工校正 ID 后重新打包。

作者注：本工具只做容器级无损拆装，不重编码音频，
因此 pack(unpack(x)) == x 可保证字节完全一致（见 selftest）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys

HEADER_SIZE = 4 + 4 + 256 * 8 + 8      # 2064
STRIDE = 8
MAX_SOUNDS = 256
END_MARKER = b'THE  END'
COUNT_OFFSET = 4
TABLE_OFFSET = 8


# --------------------------------------------------------------------------
# 读取
# --------------------------------------------------------------------------

def read_header(blob: bytes) -> dict:
    """校验并解析 SND_HEADER。返回 dict，非法时抛 ValueError。"""
    if len(blob) < HEADER_SIZE:
        raise ValueError('文件过短：%d < %d' % (len(blob), HEADER_SIZE))
    version = blob[0:4]
    if version != b'V0.0':
        raise ValueError('magic 不是 "V0.0"：%r' % version)
    count = struct.unpack_from('<I', blob, COUNT_OFFSET)[0]
    if count > MAX_SOUNDS:
        raise ValueError('count=%d 超过 SND_MAX_SOUNDS=%d' % (count, MAX_SOUNDS))
    marker = blob[TABLE_OFFSET + MAX_SOUNDS * STRIDE:
                  TABLE_OFFSET + MAX_SOUNDS * STRIDE + STRIDE]
    if marker != END_MARKER:
        raise ValueError('endOfTable 标记异常：%r（应为 %r）' % (marker, END_MARKER))
    return {'version': version, 'count': count}


def read_entries(blob: bytes, count: int) -> list[dict]:
    """读出 count 个有效条目及其字节范围。"""
    out = []
    for i in range(count):
        sid = struct.unpack_from('<I', blob, TABLE_OFFSET + STRIDE * i)[0]
        off = struct.unpack_from('<I', blob, TABLE_OFFSET + STRIDE * i + 4)[0]
        nxt = struct.unpack_from('<I', blob, TABLE_OFFSET + STRIDE * (i + 1) + 4)[0] \
            if i + 1 < count else len(blob)
        if off < HEADER_SIZE or nxt < off:
            raise ValueError('条目 %d 偏移异常：off=%d nxt=%d' % (i, off, nxt))
        out.append({'slot': i, 'voiceID': sid, 'offset': off,
                    'length': nxt - off, 'data': blob[off:nxt]})
    return out


def _ascii_ratio(s: str) -> float:
    """字符串里 ASCII 字符占比，用于判断是英文还是中文台词。"""
    if not s:
        return 1.0
    return sum(1 for ch in s if ord(ch) < 128) / len(s)


def read_unused_slots(blob: bytes, count: int) -> list[bytes]:
    """未使用槽位的原始 8 字节（正常应为 0xFF 填充）。"""
    return [blob[TABLE_OFFSET + STRIDE * i: TABLE_OFFSET + STRIDE * (i + 1)]
            for i in range(count, MAX_SOUNDS)]


def read_ast(path: str) -> dict[int, str]:
    """解析 .ast，返回 {voiceID: GBK文本}。严格复刻 Voice.cpp:voiceLoadText。"""
    d = open(path, 'rb').read()
    if d[0:4] != b'CPYR':
        raise ValueError('%s 缺少 CPYR 块' % path)
    size = struct.unpack_from('<I', d, 4)[0]
    pos = 8 + size
    out = {}
    while True:
        nxt = d.find(b'VTXT', pos)
        if nxt < 0:
            break
        p = nxt + 4
        n_size = struct.unpack_from('<I', d, p)[0]; p += 4
        vid = struct.unpack_from('<I', d, p)[0]; p += 4
        ln = struct.unpack_from('<I', d, p)[0]; p += 4
        raw = d[p:p + ln]
        try:
            txt = raw.decode('gbk')
        except UnicodeDecodeError:
            txt = raw.decode('latin1')     # 容错：不因个别条目失败
        out[vid] = txt
        pos = p + ln
    return out


# --------------------------------------------------------------------------
# 打包 / 解包
# --------------------------------------------------------------------------

def _wav_bytes(payload: bytes) -> bytes:
    """给裸 chunk 数据套一个合法 RIFF/WAVE 头，便于播放器打开。

    原始 .asd 里每条本身就是 fmt+data，没有 RIFF 外壳，
    所以加壳时不需要也不可能重编码，纯套头。
    """
    riff = b'WAVE' + payload
    return b'RIFF' + struct.pack('<I', len(riff)) + riff


def _strip_riff(wav: bytes) -> bytes:
    """去掉 RIFF 外壳，还原为 fmt+data 裸数据（打包前调用）。"""
    if wav[0:4] != b'RIFF':
        return wav                        # 已是裸数据
    size = struct.unpack_from('<I', wav, 4)[0]
    if wav[8:12] != b'WAVE':
        raise ValueError('RIFF 但不是 WAVE 格式')
    return wav[12:12 + size - 4] if size else wav[12:]


def unpack(asd_path: str, out_dir: str, ast_path: str | None = None,
           names: dict[int, str] | None = None) -> dict:
    """解包 .asd 到目录，并写出 _index.json。"""
    blob = open(asd_path, 'rb').read()
    hdr = read_header(blob)
    ents = read_entries(blob, hdr['count'])
    unused = read_unused_slots(blob, hdr['count'])

    texts = read_ast(ast_path) if ast_path and os.path.exists(ast_path) else {}

    # 【重要】文件名的语义来源优先级：
    #   1) 同名 .ast 自带的台词  —— 与本 .asd 同源，最可靠
    #   2) 传入的 names 表        —— 可能来自另一套版本，会张冠李戴
    # 二者冲突时一律以 .ast 为准，并在 index 里记下差异便于人工核对。
    conflict = 0
    for e in ents:
        vid = e['voiceID']
        own = texts.get(vid)            # 本文件 .ast 里的台词
        ext = (names or {}).get(vid)    # 外部名字表里的符号名
        if own is not None and ext and _ascii_ratio(own) < 0.5:
            # .ast 有中文台词，同时外部表给了不同来源的名字 -> 记录冲突
            conflict += 1
        e['_own_text'] = own
        e['_ext_name'] = ext

    os.makedirs(out_dir, exist_ok=True)

    index = {
        'source': os.path.basename(asd_path),
        'source_sha256': hashlib.sha256(blob).hexdigest(),
        'version': 'V0.0',
        'count': hdr['count'],
        'max_sounds': MAX_SOUNDS,
        'header_size': HEADER_SIZE,
        'ast_source': os.path.basename(ast_path) if ast_path else None,
        'ast_text_count': len(texts),
        'entries': [],
    }

    for e in ents:
        vid = e['voiceID']
        # 文件名 = slot + voiceID（两者源自本文件，不会张冠李戴）。
        # 只有当该 voiceID 能在传入的名字表里查到时才补符号名，
        # 查不到就保持纯数字——绝不猜测。
        # 给中文包起名务必用 --exe-names（中文 1.0 exe 内置表）；
        # 用英文 voices.dat 会造成 144 个符号名的 ID 对不上。
        nm = (names or {}).get(vid, '')
        stem = '%04d_%d%s' % (e['slot'], vid, ('_' + nm) if nm else '')
        wav_name = stem + '.wav'
        open(os.path.join(out_dir, wav_name), 'wb').write(_wav_bytes(e['data']))

        txt = texts.get(vid)
        if txt is not None:
            open(os.path.join(out_dir, stem + '.txt'), 'w',
                 encoding='utf-8').write(txt)

        rec = {'slot': e['slot'], 'voiceID': vid, 'length': e['length'],
               'file': wav_name,
               'sha256': hashlib.sha256(e['data']).hexdigest()}
        if txt is not None:
            rec['text'] = txt
        else:
            # 该 slot 在本文件的 .ast 里没有台词——这是真实信息，显式标记
            rec['text_missing'] = True
            if e['_ext_name']:
                # 仅供参考：来自外部名字表，因编号体系可能不同，不可当真
                rec['ext_name_ref'] = e['_ext_name']
        index['entries'].append(rec)

    n_missing = sum(1 for r in index['entries'] if r.get('text_missing'))
    index['text_missing_count'] = n_missing
    index['naming_conflicts'] = conflict

    # 未使用槽位原样保留，保证回包字节一致
    index['unused_slots_b64'] = [
        hashlib.sha256(u).hexdigest() for u in unused]
    index['unused_all_ff'] = all(set(u) == {0xFF} for u in unused)

    open(os.path.join(out_dir, '_index.json'), 'w', encoding='utf-8').write(
        json.dumps(index, ensure_ascii=False, indent=2))
    return index


def remap(index_dir: str, id_map: dict[int, int], names: dict[int, str] | None = None
          ) -> dict:
    """按 {旧voiceID: 新voiceID} 重写索引，并同步重命名文件。

    用于把中文 1.0 的资源重编号为英文 1.2 的 ID 体系（Steam 1.2 的 exe
    按自己的表查找，直接放 1.0 编号会错位）。音频字节完全不动。
    """
    idx = json.load(open(os.path.join(index_dir, '_index.json'),
                         encoding='utf-8'))
    stats = {'changed': 0, 'unchanged': 0, 'unmapped': 0, 'renamed': 0}
    for rec in idx['entries']:
        old = rec['voiceID']
        new = id_map.get(old)
        if new is None:
            stats['unmapped'] += 1
            continue
        if new == old:
            stats['unchanged'] += 1
        else:
            stats['changed'] += 1
        rec['voiceID'] = new
        rec['old_voiceID'] = old

        # 文件重命名：保持 slot 序号，换 ID 与名字
        nm = (names or {}).get(new, '')
        stem_new = '%04d_%d%s' % (rec['slot'], new, ('_' + nm) if nm else '')
        old_file = rec['file']
        stem_old = old_file[:-4]
        for ext in ('.wav', '.txt'):
            p_old = os.path.join(index_dir, stem_old + ext)
            p_new = os.path.join(index_dir, stem_new + ext)
            if os.path.exists(p_old):
                os.replace(p_old, p_new)
        rec['file'] = stem_new + '.wav'
        stats['renamed'] += 1

    idx['remapped'] = True
    idx['remap_stats'] = stats
    open(os.path.join(index_dir, '_index.json'), 'w', encoding='utf-8').write(
        json.dumps(idx, ensure_ascii=False, indent=2))
    return stats


def pack(index_dir: str, asd_path: str, ast_path: str | None = None) -> bytes:
    """依据 _index.json 重新打包 .asd（及可选 .ast）。"""
    idx = json.load(open(os.path.join(index_dir, '_index.json'),
                         encoding='utf-8'))
    ents = idx['entries']

    payloads = []
    for rec in ents:
        raw = open(os.path.join(index_dir, rec['file']), 'rb').read()
        payloads.append(_strip_riff(raw))

    count = len(ents)
    table = bytearray()
    offset = HEADER_SIZE
    for rec, pay in zip(ents, payloads):
        table += struct.pack('<II', rec['voiceID'], offset)
        offset += len(pay)

    head = bytearray()
    head += b'V0.0'
    head += struct.pack('<I', count)
    head += table
    head += bytes([0xFF]) * (MAX_SOUNDS - count) * STRIDE
    head += END_MARKER
    assert len(head) == HEADER_SIZE, len(head)

    blob = bytes(head) + b''.join(payloads)
    open(asd_path, 'wb').write(blob)

    if ast_path:
        ast = build_ast({r['voiceID']: r.get('text')
                         for r in ents if r.get('text') is not None})
        open(ast_path, 'wb').write(ast)
    return blob


def build_ast(texts: dict[int, str],
              copyright_text: str = 'ArmyMen-3DO COMPANY (C)1997') -> bytes:
    """按 voiceLoadText 的布局生成 .ast。"""
    cbytes = copyright_text.encode('latin1')
    out = bytearray(b'CPYR' + struct.pack('<I', len(cbytes)) + cbytes)
    for vid in sorted(texts):
        raw = texts[vid].encode('gbk')
        out += b'VTXT' + struct.pack('<III', 8 + len(raw), vid, len(raw)) + raw
    return bytes(out)


# --------------------------------------------------------------------------
# 自检：证明 pack(unpack(x)) == x
# --------------------------------------------------------------------------

def selftest() -> int:
    import tempfile
    tmp = tempfile.mkdtemp(prefix='asd_selftest_')
    ok = True
    try:
        for label, src in [
            ('voices.asd', r'G:\Projects\ArmyMenCHS\Army1_Original\audio\voices.asd'),
            ('sounds.asd', r'G:\Projects\ArmyMenCHS\Army1_Original\audio\sounds.asd'),
        ]:
            if not os.path.exists(src):
                print('跳过（源文件不存在）：%s' % label); continue
            orig = open(src, 'rb').read()
            d = os.path.join(tmp, label.replace('.', '_'))
            unpack(src, d)
            repacked = os.path.join(tmp, 're_' + label)
            pack(d, repacked)
            same = open(repacked, 'rb').read() == orig
            print('%-12s pack(unpack(x)) == x  : %s' % (label, 'PASS' if same else 'FAIL'))
            ok = ok and same
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def load_names(dat_path: str | None) -> dict[int, str]:
    """从 voices.dat 读 {id: NAME}。

    注意：voices.dat 来自英文 1.2 源码，其编号与中文 1.0 的 exe 不同
    （实测 144 个符号名 ID 有差异）。给中文包起名请用 --exe-names。
    """
    if not dat_path or not os.path.exists(dat_path):
        return {}
    import re
    txt = open(dat_path, encoding='latin1').read()
    return {int(v): k for k, v in re.findall(
        r'\{\s*([A-Z0-9_]+)\s*,\s*"[A-Z0-9_]*"\s*\}\s*,\s*//\s*(\d+)', txt)}


# ---- 从游戏主程序提取内置 SND_NAMES 表 ----------------------------------
# 中文 1.0 的 Armymen.exe 自带一份名字表，那才是中文语音包真正匹配的编号。
# 结构（IDA 实测 0x479DF0）：
#     { unsigned long id; char name[68]; }   stride = 72
# 表以 id == 0xFFFFFFFF 的哨兵结束。
EXE_TABLE_VA = 0x479DF0       # 中文 1.0 Armymen.exe 中 SND_NAMES 起始 VA
EXE_STRIDE = 72
EXE_NAMELEN = 68


def _find_table_va(exe_path: str) -> int:
    """在 exe 里搜索 (u32)4000 + 'THERE_HE_IS' 特征，返回其 VA。"""
    d = open(exe_path, 'rb').read()
    pe_off = struct.unpack_from('<I', d, 0x3C)[0]
    nsec = struct.unpack_from('<H', d, pe_off + 6)[0]
    opt_size = struct.unpack_from('<H', d, pe_off + 20)[0]
    sec_off = pe_off + 24 + opt_size
    imagebase = struct.unpack_from('<I', d, pe_off + 24 + 28)[0]
    secs = []
    for i in range(nsec):
        o = sec_off + 40 * i
        vaddr = struct.unpack_from('<I', d, o + 12)[0]
        vsize = struct.unpack_from('<I', d, o + 8)[0]
        roff = struct.unpack_from('<I', d, o + 20)[0]
        rsize = struct.unpack_from('<I', d, o + 16)[0]
        secs.append((vaddr, vsize, roff, rsize))

    pat = struct.pack('<I', 4000) + b'THERE_HE_IS'
    pos = d.find(pat)
    if pos < 0:
        raise ValueError('未找到 SND_NAMES 表特征串')
    for vaddr, vsize, roff, rsize in secs:
        if roff <= pos < roff + rsize:
            return imagebase + vaddr + (pos - roff)
    raise ValueError('表特征串不在任何节内')


def load_names_from_exe(exe_path: str, va: int = EXE_TABLE_VA) -> dict[int, str]:
    """从 Armymen.exe 的 .data 段读出内置 {id: NAME} 表。

    不同版本 exe 的表地址不同：
        中文 1.0  Armymen.exe (742912 B) -> 0x479DF0, 末 ID 5011
        STEAM 1.2 Armymen.exe (993280 B) -> 0x4BFBC0, 末 ID 5038
    可用 --exe-va 覆盖，或传 0 自动搜索特征串。
    """
    import re as _re

    if va == 0:
        va = _find_table_va(exe_path)

    d = open(exe_path, 'rb').read()
    pe_off = struct.unpack_from('<I', d, 0x3C)[0]
    if d[pe_off:pe_off + 4] != b'PE\0\0':
        raise ValueError('不是有效的 PE 文件：%s' % exe_path)
    nsec = struct.unpack_from('<H', d, pe_off + 6)[0]
    opt_size = struct.unpack_from('<H', d, pe_off + 20)[0]
    sec_off = pe_off + 24 + opt_size
    imagebase = struct.unpack_from('<I', d, pe_off + 24 + 28)[0]

    secs = []
    for i in range(nsec):
        o = sec_off + 40 * i
        vaddr = struct.unpack_from('<I', d, o + 12)[0]
        vsize = struct.unpack_from('<I', d, o + 8)[0]
        roff = struct.unpack_from('<I', d, o + 20)[0]
        rsize = struct.unpack_from('<I', d, o + 16)[0]
        secs.append((vaddr, vsize, roff, rsize))

    def va2off(v):
        rva = v - imagebase
        for vaddr, vsize, roff, rsize in secs:
            if vaddr <= rva < vaddr + max(vsize, rsize):
                return roff + (rva - vaddr)
        return None

    off = va2off(va)
    if off is None:
        raise ValueError('VA 0x%X 未落在任何节内' % va)

    out = {}
    while True:
        if off + EXE_STRIDE > len(d):
            break
        eid = struct.unpack_from('<I', d, off)[0]
        if eid == 0xFFFFFFFF or eid == 0:
            break
        raw = d[off + 4: off + 4 + EXE_NAMELEN]
        nm = raw.split(b'\x00')[0].decode('latin1')
        if nm and not _re.fullmatch(r'[A-Za-z0-9_]+', nm):
            break
        if nm:
            out[eid] = nm
        off += EXE_STRIDE
        if len(out) > 600:
            break
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description='Army Men 1 语音容器 .asd/.ast 解包与打包')
    sub = ap.add_subparsers(dest='cmd', required=True)

    u = sub.add_parser('unpack', help='解包 .asd 到目录')
    u.add_argument('asd'); u.add_argument('out_dir')
    u.add_argument('--ast', help='同名 .ast，用于导出台词')
    u.add_argument('--names', help='voices.dat 路径（英文 1.2 编号，慎用于中文包）')
    u.add_argument('--exe-names',
                   help='从游戏 exe 提取内置名字表（推荐，中英文各用自己的 exe）')
    u.add_argument('--exe-va', type=lambda s: int(s, 0), default=EXE_TABLE_VA,
                   help='名字表 VA，传 0 表示自动搜索（默认 0x479DF0=中文1.0）')

    p = sub.add_parser('pack', help='按 _index.json 重新打包')
    p.add_argument('dir'); p.add_argument('asd')
    p.add_argument('--ast', help='同时输出 .ast')

    m = sub.add_parser('remap', help='按映射表重写索引 ID（音频不动）')
    m.add_argument('dir')
    m.add_argument('--map', required=True, help='JSON 文件 {旧ID: 新ID}')
    m.add_argument('--exe-names', help='游戏 exe，用于重命名时补符号名')
    m.add_argument('--exe-va', type=lambda s: int(s, 0), default=0,
                   help='名字表 VA，0=自动搜索')

    sub.add_parser('selftest', help='验证 unpack/pack 字节可还原')

    a = ap.parse_args(argv)

    if a.cmd == 'selftest':
        return selftest()
    if a.cmd == 'unpack':
        names = {}
        if a.exe_names:
            names = load_names_from_exe(a.exe_names, a.exe_va)
            print('  名字表来源: exe 内置 (%d 条, VA 0x%X)'
                  % (len(names), a.exe_va if a.exe_va else
                     _find_table_va(a.exe_names)))
        elif a.names:
            names = load_names(a.names)
            print('  名字表来源: %s (%d 条)' % (os.path.basename(a.names), len(names)))
        idx = unpack(a.asd, a.out_dir, a.ast, names)
        print('解包 %d 条 -> %s' % (idx['count'], a.out_dir))
        n_txt = sum(1 for r in idx['entries'] if 'text' in r)
        print('  台词(.txt) : %d 条' % n_txt)
        if idx.get('text_missing_count'):
            print('  !! 无台词条目: %d 条（该 .ast 中确实没有对应台词，'
                  '名字若来自外部表不可当真）' % idx['text_missing_count'])
        if idx.get('naming_conflicts'):
            print('  !! 命名冲突: %d 条（.ast 自有台词优先，外部名字表已忽略）'
                  % idx['naming_conflicts'])
        return 0
    if a.cmd == 'pack':
        pack(a.dir, a.asd, a.ast)
        print('已打包 -> %s' % a.asd)
        return 0
    if a.cmd == 'remap':
        id_map = {int(k): v for k, v in
                  json.load(open(a.map, encoding='utf-8')).items()}
        names = load_names_from_exe(a.exe_names, a.exe_va) if a.exe_names else {}
        st = remap(a.dir, id_map, names)
        print('remap 完成: 改 %d, 未变 %d, 无法映射 %d'
              % (st['changed'], st['unchanged'], st['unmapped']))
        return 0 if st['unmapped'] == 0 else 1
    return 1


if __name__ == '__main__':
    sys.exit(main())
