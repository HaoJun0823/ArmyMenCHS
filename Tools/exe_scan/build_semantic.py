"""
语义配对：以英文 exe 为准，为每个英文串找中文译文。

背景：中文版(v0.1.0.0) 与 Steam 版(v0.1.2.0) 的串表**顺序不完全一致**
（例如中文版在 Attack 后多一个「跟随」，英文版没有）。
因此不能按序号盲目配对，必须以英文为基准做语义映射。

用法：
    python build_semantic.py <steam.exe> --en-off 0xBB4E0 --count 76
                             [--csv out.csv]

内置一张 英文 -> 中文 的语义词典（人工校对过）。
未在词典中的英文串会标 TODO。
"""

import sys
import struct
import csv

# 人工校对的语义词典：英文 -> 中文
# 来源：中文官方 exe 的译文；官方未译/误译的已重译
DICT = {
    # 单位指令
    "End Boot Camp": "退出新兵营",
    "Unit Scroll": "循环选择部队",
    "Send": "发送",
    "Fast Defend": "快速防御",
    "Fast Attack": "快速进攻",
    "Recon": "侦察",
    "Air Drop": "空投",
    "Air Strike": "空中打击",
    "Defend": "防御",
    "Attack": "进攻",
    "Drop Item": "丢弃物品",
    "Enter Vehicle": "上车",
    "Prone": "趴下",
    "Kneel": "跪下",
    "Stand": "站立",
    "Lower Position": "降低体势",
    "Raise Position": "抬高体势",
    "Roll Right": "向右翻",
    "Roll Left": "向左翻",
    "Dive": "前扑",
    "Special Item": "特殊武器",      # 注意：此处是武器，非对象名"特殊物品"
    "Heavy Weapon": "重武器",
    "Main Weapon": "主武器",
    "Slow": "减速",
    "Stop/Brake": "停下/刹车",
    "Fire": "开火",
    "Turret Left": "炮台左转",
    "Turret Right": "炮台右转",
    "Walk Backward": "向后退",
    "Walk Forward": "向前走",
    "Run Forward": "向前跑",
    "Rotate Left": "向左转",
    "Rotate Right": "向右转",

    # 菜单
    "Joystick Buttons": "摇杆按钮",
    "Basic Game Actions": "基本游戏动作",
    "Sarge Actions": "中士动作",
    "MISSION WON": "任务成功",
    "MISSION COMPLETE": "任务完成",
    "ANY KEY TO CONTINUE": "按任意键继续",
    "MISSION FAILED": "任务失败",
    "Voice Volume": "语音音量",
    "Music Volume": "音乐音量",
    "SFX Volume": "音效音量",
    "Audio Options": "音响选项",
    "Control Options": "控制选项",
    "Game Options": "游戏选项",
    "Campaign Select": "选择战役",
    "Player Callsign": "玩家代号",
    "Player vs. Computer": "玩家vs.电脑",
    "Game Start": "游戏开始",

    # 对象名（PillBox 官方误译"医疗箱"，此处按源码语义重译）
    "Special Itme": "特殊物品",
    "Overpass": "立交桥",
    "Miscellaneous": "其它各类",
    "Radar Building": "雷达站",
    "Wall Gate": "大墙门",
    "Fence Gate": "栅栏门",
    "Power Plant": "能量工厂",
    "PillBox": "碉堡",
    "Building": "建筑",
    "Prison Camp": "战俘营",
    "Heli Pad": "停机坪",
    "Air Strip": "简易机场",
    "Auxbase": "副基地",
    "Base": "基地",
    "AA Gun": "AA炮",
    "Gun Turret": "炮塔",
    "Explosive": "炸药",
    "Foot Bridge": "步行桥",
    "Bridge": "桥",
    "Wall": "墙",
    "Fence": "栅栏",
    "Fallen Tree": "倒下的树",
    "Big Tree": "巨树",
    "Tree": "树木",
    "Bush": "灌木",
    "Rock": "岩石",

    # 单位/武器（中文官方未译，此处补译）
    "Sarge": "中士",
    "Truck": "卡车",
    "HalfTrack": "半履带车",
    "Tank": "坦克",
    "Jeep": "吉普车",
    "No Vehicle": "无车辆",
    "No Weapon": "无武器",
    "Tower Rifle": "塔步枪",
    "Mine": "地雷",
    "Detonator": "起爆器",
    "Mine Sweeper": "扫雷器",
    "Auto Rifle": "自动步枪",
    "Rifle": "步枪",
    "Mortar": "迫击炮",
    "Bazooka": "火箭筒",
    "Grenade": "手榴弹",
    "Flame Thrower": "火焰喷射器",
    "Heavy Machine Gun": "重机枪",
    "Medium Machine Gun": "中机枪",
    "Light Machine Gun": "轻机枪",
    "Large Cannon": "大口径炮",
    "No Item": "无物品",
    "Unknown Item Type": "未知物品类型",
    "Null Item": "空物品",
}


def parse_pe(path):
    with open(path, "rb") as f:
        buf = f.read()
    pe_off = struct.unpack_from("<I", buf, 0x3C)[0]
    nsec = struct.unpack_from("<H", buf, pe_off + 6)[0]
    opt_size = struct.unpack_from("<H", buf, pe_off + 20)[0]
    opt_off = pe_off + 24
    magic = struct.unpack_from("<H", buf, opt_off)[0]
    image_base = (struct.unpack_from("<I", buf, opt_off + 28)[0]
                  if magic == 0x10B else
                  struct.unpack_from("<Q", buf, opt_off + 24)[0])
    sec_off = opt_off + opt_size
    sections = []
    for i in range(nsec):
        p = sec_off + i * 40
        sections.append({
            "name": buf[p:p + 8].rstrip(b"\0").decode("ascii", "replace"),
            "vaddr": struct.unpack_from("<I", buf, p + 12)[0],
            "vsize": struct.unpack_from("<I", buf, p + 8)[0],
            "rsize": struct.unpack_from("<I", buf, p + 16)[0],
            "roff": struct.unpack_from("<I", buf, p + 20)[0],
        })
    return {"image_base": image_base, "sections": sections, "buf": buf}


def read_slots(buf, off, count):
    out = []
    p = off
    for _ in range(count):
        start = p
        raw = bytearray()
        while p < len(buf) and buf[p] != 0:
            raw.append(buf[p])
            p += 1
        nxt = p + 1
        nxt += (4 - (nxt % 4)) % 4
        out.append({"off": start,
                    "text": raw.decode("ascii", "replace"),
                    "cap": nxt - start})
        p = nxt
    return out


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    path = args[0]
    en_off = 0xBB4E0
    count = 76
    csv_out = None
    i = 1
    while i < len(args):
        a = args[i]
        if a == "--en-off" and i + 1 < len(args):
            en_off = int(args[i + 1], 16)
        elif a == "--count" and i + 1 < len(args):
            count = int(args[i + 1])
        elif a == "--csv" and i + 1 < len(args):
            csv_out = args[i + 1]
        i += 1

    pe = parse_pe(path)
    # 由 file off 推 RVA
    en_rva = None
    for s in pe["sections"]:
        if s["roff"] <= en_off < s["roff"] + s["rsize"]:
            en_rva = s["vaddr"] + (en_off - s["roff"])
            break

    slots = read_slots(pe["buf"], en_off, count)

    print(f"base RVA = 0x{en_rva:08X}  (file off 0x{en_off:08X})")
    print()
    rows = []
    todo = 0
    for i, sl in enumerate(slots):
        rva = en_rva + (sl["off"] - en_off)
        en = sl["text"]
        zh = DICT.get(en, "")
        if not zh:
            todo += 1
        rows.append([i, f"0x{rva:08X}", f"0x{sl['off']:08X}",
                     en, sl["cap"], zh, "" if zh else "TODO"])
        print(f"{i:>3}  0x{rva:08X} cap={sl['cap']:3d}  {en:<22} -> {zh}"
              f"{'' if zh else '  <<TODO>>'}")

    if csv_out:
        with open(csv_out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["index", "en_rva", "en_fileoff", "english",
                        "capacity", "chinese", "status"])
            w.writerows(rows)
        print(f"\nCSV -> {csv_out}")

    print(f"\n已译: {len(rows) - todo} / {len(rows)}   待补: {todo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
