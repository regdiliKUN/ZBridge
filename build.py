# -*- coding: utf-8 -*-
"""
一键构建 ZBridge 绿色目录包。

产物 dist/ZBridge/：
    ZBridge.exe      真正的可执行入口（非任何脚本/中转启动器）
    _internal/       Python 运行时、Tkinter/Tcl-Tk、全部依赖

使用 --onedir 而非 --onefile：onefile 运行时会把依赖解压到临时目录，
快捷方式实际指向的就不是包内那个 exe；onedir 才是真正的绿色目录包。

用法:
    pip install pyinstaller
    python build.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src", "zbridge.py")
DIST = os.path.join(ROOT, "dist")


def main():
    if not os.path.isfile(SRC):
        print("ERROR: 找不到源码:", SRC)
        sys.exit(1)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",            # 目录包（不是单文件）
        "--windowed",          # 无控制台窗口
        "--name", "ZBridge",
        "--clean", "--noconfirm",
        "--distpath", DIST,
        SRC,
    ]
    print("执行命令:\n  " + " ".join(cmd) + "\n")
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        print("构建失败，退出码:", r.returncode)
        sys.exit(r.returncode)

    pkg = os.path.join(DIST, "ZBridge")
    exe = os.path.join(pkg, "ZBridge.exe")
    print()
    if os.path.isfile(exe):
        print("构建成功")
        print("  包体目录:", pkg)
        print("  主程序  :", exe)
    else:
        print("构建结束但未找到 exe:", exe)
        sys.exit(1)


if __name__ == "__main__":
    main()
