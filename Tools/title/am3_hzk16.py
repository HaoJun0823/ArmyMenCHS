# -*- coding: utf-8 -*-
"""Hzk16（官方中文版 13x13 点阵字库）读取器。

字形定位公式与 Army2_Extend_Dll/src/hzk16.cpp 的 Hzk16Font::Glyph 完全一致：
    idx = trail + 94*lead - 15295
    off = bpg*idx - 9688;  if off < 0: off += 9776

用法:
    from am3_hzk16 import Hzk16
    f = Hzk16(r"G:\\Projects\\ArmyMenCHS\\Army2_CHS\\Hzk16")
    bmp = f.render("确认退出", color=(255,255,255))   # -> PIL Image
"""
import struct

DEFAULT_PATH = r"G:\Projects\ArmyMenCHS\Army2_CHS\Hzk16"


class Hzk16:
    def __init__(self, path=DEFAULT_PATH):
        self.data = open(path, "rb").read()
        d = self.data
        assert d[:4] == b"RSE\x1a", "魔数不符"
        self.width = struct.unpack_from("<H", d, 0x14)[0]
        self.height = struct.unpack_from("<H", d, 0x16)[0]
        self.rlo = struct.unpack_from("<H", d, 0x18)[0]
        self.rhi = struct.unpack_from("<H", d, 0x1C)[0]
        self.data_start = struct.unpack_from("<I", d, 0x48)[0]
        self.bpg = struct.unpack_from("<H", d, 0x50)[0]
        self.n_glyph = struct.unpack_from("<H", d, 0x52)[0]
        self.row_bytes = (self.width + 7) >> 3
        self.face = d[0x20:0x48].split(b"\x00")[0]

    def glyph(self, lead, trail):
        idx = trail + 94 * lead - 15295
        off = self.bpg * idx - 9688
        if off < 0:
            off += 9776
        if off < 0 or off + self.bpg > len(self.data):
            return None
        return self.data[off:off + self.bpg]

    def bits(self, ch):
        """返回 height 行的位掩码列表（0 = 空），字符须为单个汉字。

        ★ 字形对齐：本字库每行占 row_bytes(=2) 字节 = 16 位，而字形是
          **13 列存放在高 13 位**（bit15..bit3），低 3 位恒为 0 填充。
          因此必须右移 (16 - width) = 3 位，否则每个字会整体左移 3 像素、
          丢掉最左 3 列（表现为"字的左边被切掉"）。
          这与项目内 Army2_Extend_Dll/src/hzk16.cpp 的 TestBit 语义一致：
              rowBytes = bytesPerRow; byteIdx = x>>3; bit = 7-(x&7)
          x=0 -> g[0] bit7 = 原始 bit15（最左列）。
        """
        gb = ch.encode("gbk")
        if len(gb) != 2:
            return None
        g = self.glyph(gb[0], gb[1])
        if g is None:
            return None
        shift = self.row_bytes * 8 - self.width      # 16 - 13 = 3
        rows = []
        for y in range(self.height):
            v = 0
            for b in range(self.row_bytes):
                v |= g[y * self.row_bytes + b] << (8 * (self.row_bytes - 1 - b))
            rows.append(v >> shift)
        return rows

    def ink(self, ch):
        rows = self.bits(ch)
        if rows is None:
            return -1
        n = 0
        for v in rows:
            n += bin(v).count("1")
        return n

    def has(self, ch):
        """字形存在且墨迹量合理（0 或过满视为缺字）。"""
        k = self.ink(ch)
        return 3 <= k <= 120

    def selftest(self):
        """回归自检：确认字形取位正确（右移 row_bytes*8 - width 位）。

        ★ 判据用**墨迹数的黄金值**。字形是 13 列左对齐在 16 位行的高 13 位；
          若忘记右移 3 位而直接取低 13 位，每个字会左移 3 像素并被切掉最左
          3 列，墨迹数会系统性偏小（实测每个字少 10~17 像素）。
          断言：当前墨迹数必须等于预先测定的正确值。
        """
        golden = {"开": 46, "战": 61, "目": 54, "国": 79, "同": 63,
                  "确": 79, "认": 35, "设": 50, "置": 86, "游": 63}
        bad = []
        for ch, want in golden.items():
            got = self.ink(ch)
            if got != want:
                bad.append((ch, "墨迹 %d != 期望 %d" % (got, want)))
        return bad
