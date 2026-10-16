# -*- coding: utf-8 -*-
"""4 代产物校验器的对抗性验证：注入错误 -> 必须被拦下 -> 恢复后回绿。

沿用 docs/10 §5.3 的做法（3 代做过 7 项，全部拦下）。
"""
import os
import shutil
import subprocess
import sys
import zipfile

R = r"G:\Projects\ArmyMenCHS"
PY = os.path.join(R, "venv311", "Scripts", "python.exe")
STAGE = os.path.join(R, "stage_am4")
VERIFY = os.path.join(R, "Tools", "ci", "verify_release_am4.py")


def find_zip():
    for f in sorted(os.listdir(STAGE)):
        if f.endswith(".zip"):
            return os.path.join(STAGE, f)
    raise SystemExit("找不到 zip")


Z = find_zip()
BAK = Z + ".orig"


def run_verify():
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run([PY, VERIFY, STAGE], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def rewrite(mutate):
    """按 mutate(name, data) -> data|None 重写 zip（None = 删除该条目）。"""
    with zipfile.ZipFile(Z) as zi:
        items = [(i, zi.read(i.filename)) for i in zi.infolist()]
    with zipfile.ZipFile(Z, "w", zipfile.ZIP_DEFLATED) as zo:
        for info, data in items:
            out = mutate(info.filename, data)
            if out is None:
                continue
            zo.writestr(info.filename, out)


CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


@case("删 必读说明.txt")
def _(n, d):
    return None if n == "必读说明.txt" else d


@case("删 License.txt")
def _(n, d):
    return None if n == "License.txt" else d


@case("License.txt 剥掉 cnc-ddraw 声明")
def _(n, d):
    if n == "License.txt":
        t = d.decode("utf-8", "replace").replace("github.com/FunkyFr3sh", "X")
        return t.encode("utf-8")
    return d


@case("删 1 个配音 wav")
def _(n, d):
    return None if n == "update/audio/vos/Aah.wav" else d


@case("删 ddraw.dll（包根）")
def _(n, d):
    return None if n == "ddraw.dll" else d


@case("代理 dinput.dll 改名（换掉导出名）")
def _(n, d):
    if n == "dinput.dll":
        return d.replace(b"DirectInputCreateA", b"X" * len(b"DirectInputCreateA"))
    return d


@case("ASI 落错后缀（.dll 而不是 .asi）")
def _(n, d):
    return None if n == "scripts/Army4_Extend_Dll.asi" else d


@case("ASI 换成 3 代产物（导出名不对）")
def _(n, d):
    if n == "scripts/Army4_Extend_Dll.asi":
        p = os.path.join(R, "Army3_Extend_Dll", "Release",
                         "Army3_Extend_Dll.dll")
        return open(p, "rb").read()
    return d


@case("strings.txt 截到 100 行（低于 320 闸门）")
def _(n, d):
    if n == "update/strings/strings.txt":
        return b"\r\n".join(d.split(b"\r\n")[:100]) + b"\r\n"
    return d


@case("title.dat 中部砍 24 字节（总长变，偏移全错）")
def _(n, d):
    if n == "update/title.dat":
        return d[:200000] + d[200024:]
    return d


@case("title.dat 砍尾部 24 字节")
def _(n, d):
    if n == "update/title.dat":
        return d[:-24]
    return d


@case("必读说明.txt 去掉 BOM")
def _(n, d):
    if n == "必读说明.txt":
        return d[3:]
    return d


@case("必读说明.txt 混入 3 代标题")
def _(n, d):
    if n == "必读说明.txt":
        return d + "《太空玩具》".encode("utf-8")
    return d


@case("update/ 混入可执行文件")
def _(n, d):
    extra = None
    return d


def main():
    shutil.copyfile(Z, BAK)
    print("=" * 74)
    print("4 代产物校验器对抗性验证")
    print("=" * 74)

    code, out = run_verify()
    if code != 0:
        print("!! 基线不是绿的，先修好再谈对抗验证")
        print(out[-2000:])
        return 1
    print("基线：verify 通过（退出码 0）\n")

    results = []
    try:
        for name, fn in CASES:
            shutil.copyfile(BAK, Z)
            if name == "update/ 混入可执行文件":
                with zipfile.ZipFile(Z, "a") as z:
                    z.writestr("update/evil.dll", b"MZ" + b"\0" * 100)
            else:
                rewrite(fn)
            code, out = run_verify()
            ok = code != 0
            results.append((name, ok))
            print("  %-38s %s" % (name, "拦下 OK" if ok else "!! 未拦下（假绿）"))
            if not ok:
                print("      ---- 校验器输出尾部 ----")
                print("      " + "\n      ".join(out.strip().splitlines()[-12:]))
    finally:
        shutil.copyfile(BAK, Z)
        os.remove(BAK)

    code, out = run_verify()
    print()
    print("恢复原样后：退出码 %d (%s)" % (code, "回绿 OK" if code == 0 else "!! 未回绿"))
    bad = [n for n, ok in results if not ok]
    print()
    print("=" * 74)
    print("共 %d 项，拦下 %d，漏 %d" % (len(results), len(results) - len(bad), len(bad)))
    if bad:
        print("!! 漏掉的：")
        for n in bad:
            print("   - %s" % n)
        return 1
    print("全部拦下。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
