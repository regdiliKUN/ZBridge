# -*- coding: utf-8 -*-
"""
创建桌面快捷方式，指向绿色包体内的真 .exe。
入口始终是 ZBridge.exe 本身（不使用任何 BAT/CMD/PS1/VBS 中转启动器）。

核验方式（两条独立路径，避免只信任同一个 API）：
  A) 用 Shell API 读回 .lnk 的 TargetPath / WorkingDirectory
  B) 直接解析 .lnk 二进制，确认其中写入的路径字符串就是包体路径
"""
import os
import sys

# 路径可通过环境变量或命令行传入：
#   python tools/create_shortcut.py <包体目录>
PKG = os.environ.get("ZBRIDGE_PKG") or (sys.argv[1] if len(sys.argv) > 1 else "")
EXE = os.path.join(PKG, "ZBridge.exe") if PKG else ""


def get_desktop():
    try:
        from win32com.shell import shell, shellcon
        return shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOP, 0, 0)
    except Exception:
        return os.path.join(os.path.expanduser("~"), "Desktop")


def main():
    import win32com.client

    if not EXE or not os.path.isfile(EXE):
        print("ERROR: 包体 exe 不存在:", EXE or "(未指定)")
        print("用法: python tools/create_shortcut.py <ZBridge_Portable 目录>")
        sys.exit(1)

    desktop = get_desktop()
    lnk = os.path.join(desktop, "ZBridge.lnk")

    ws = win32com.client.Dispatch("WScript.Shell")
    sc = ws.CreateShortcut(lnk)
    sc.TargetPath = EXE
    sc.WorkingDirectory = PKG
    sc.Description = "ZBridge - ZBrush 跨版本桥接器（绿色版）"
    sc.IconLocation = f"{EXE},0"
    sc.Save()
    print("快捷方式已创建:", lnk)

    # ---- A) Shell API 读回 ----
    v = ws.CreateShortcut(lnk)
    target = v.TargetPath
    startin = v.WorkingDirectory

    # ---- B) 直接解析 .lnk 二进制 ----
    raw = open(lnk, "rb").read()
    u16 = raw.decode("utf-16-le", "ignore")
    raw_has_exe = EXE.lower() in u16.lower()
    raw_has_pkg = PKG.lower() in u16.lower()

    # ---- 目标文件本体核验 ----
    is_pe = open(target, "rb").read(2) == b"MZ" if os.path.isfile(target) else False

    print()
    print("=" * 74)
    print("快捷方式核验结果")
    print("=" * 74)
    print(f"包体目录          : {PKG}")
    print(f"包体 exe          : {EXE}")
    print(f"桌面目录          : {desktop}")
    print(f"快捷方式          : {lnk}")
    print()
    print(f"[A] Target         : {target}")
    print(f"[A] Start in       : {startin}")
    print()
    print(f"判定 目标==包内exe           : {target == EXE}")
    print(f"判定 目标所在目录==包体目录  : {os.path.dirname(target) == PKG}")
    print(f"判定 StartIn==包体目录       : {startin == PKG}")
    print(f"判定 目标文件存在            : {os.path.isfile(target)}")
    print(f"判定 目标为合法PE(MZ)        : {is_pe}")
    print(f"判定 目标非脚本(非 .bat/.cmd/.ps1/.vbs) : "
          f"{os.path.splitext(target)[1].lower() == '.exe'}")
    print()
    print(f"[B] .lnk 二进制内含 exe 路径 : {raw_has_exe}")
    print(f"[B] .lnk 二进制内含 包体路径 : {raw_has_pkg}")
    print("=" * 74)

    ok = all([
        target == EXE,
        os.path.dirname(target) == PKG,
        startin == PKG,
        os.path.isfile(target),
        is_pe,
        os.path.splitext(target)[1].lower() == ".exe",
        raw_has_exe,
        raw_has_pkg,
    ])
    print("总体结论:", "全部核验通过 ✓" if ok else "存在未通过项 ✗")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
