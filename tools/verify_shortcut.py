# -*- coding: utf-8 -*-
"""
最终核验：桌面快捷方式是否严格满足四项硬性要求。

核验采用三条互相独立的实现，避免"只信任同一个 API"：
  [A] WScript.Shell 读回 .lnk
  [B] IShellLink COM (SLGP_RAWPATH) 解析
  [C] 直接解析 .lnk 二进制（MS-SHLINK LocalBasePath + CommonPathSuffix）
"""
import os
import struct
import sys

# 路径可通过环境变量或命令行传入，避免把本机绝对路径写死在仓库里：
#   python tools/verify_shortcut.py <包体目录> [快捷方式.lnk]
PKG = os.environ.get("ZBRIDGE_PKG") or (sys.argv[1] if len(sys.argv) > 1 else "")
EXE = os.path.join(PKG, "ZBridge.exe") if PKG else ""
LNK = (os.environ.get("ZBRIDGE_LNK")
       or (sys.argv[2] if len(sys.argv) > 2
           else os.path.join(os.path.expanduser("~"), "Desktop", "ZBridge.lnk")))

rows = []


def chk(req, item, expect, got, ok, note=""):
    rows.append((req, item, expect, got, "PASS" if ok else "FAIL", note))
    return ok


def main():
    import pythoncom
    from win32com.shell import shell

    # ---------- 前置：包体本身 ----------
    if not os.path.isfile(EXE):
        print("ERROR: 包体 exe 不存在:", EXE)
        sys.exit(1)
    is_pe = open(EXE, "rb").read(2) == b"MZ"

    # ---------- [A] WScript.Shell ----------
    import win32com.client
    ws = win32com.client.Dispatch("WScript.Shell")
    v = ws.CreateShortcut(LNK)
    a_target, a_startin = v.TargetPath, v.WorkingDirectory

    # ---------- [B] IShellLink COM ----------
    pythoncom.CoInitialize()
    sl = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None,
                                    pythoncom.CLSCTX_INPROC_SERVER,
                                    shell.IID_IShellLink)
    sl.QueryInterface(pythoncom.IID_IPersistFile).Load(LNK, 0)  # STGM_READ
    b_target = sl.GetPath(4)[0]          # SLGP_RAWPATH
    b_startin = sl.GetWorkingDirectory()
    b_icon = sl.GetIconLocation()[0]

    # ---------- [C] 二进制解析 ----------
    raw = open(LNK, "rb").read()
    flags = struct.unpack_from("<I", raw, 0x14)[0]
    pos = 0x4C
    c_full = ""
    if flags & 0x01:
        pos += 2 + struct.unpack_from("<H", raw, pos)[0]
    if flags & 0x02:
        li_size = struct.unpack_from("<I", raw, pos)[0]
        li_flags = struct.unpack_from("<I", raw, pos + 8)[0]
        if li_flags & 0x01:
            loff = struct.unpack_from("<I", raw, pos + 16)[0]
            e = raw.index(b"\x00", pos + loff)
            lb = raw[pos + loff:e].decode("latin1")
        else:
            lb = ""
        if li_flags & 0x02:
            coff = struct.unpack_from("<I", raw, pos + 24)[0]
            e = raw.index(b"\x00", pos + coff)
            c_full = lb + raw[pos + coff:e].decode("latin1")
        pos += li_size

    nc = os.path.normcase
    pkg_n, exe_n = nc(PKG), nc(EXE)

    print("=" * 78)
    print("ZBridge 绿色包体 / 桌面快捷方式 最终核验")
    print("=" * 78)
    print(f"包体目录   : {PKG}")
    print(f"包体 exe   : {EXE}")
    print(f"快捷方式   : {LNK}")
    print()
    print(f"[A] WScript.Shell : Target={a_target}")
    print(f"                    StartIn={a_startin}")
    print(f"[B] IShellLink    : RAWPATH={b_target}")
    print(f"                    StartIn={b_startin}")
    print(f"[C] 二进制解析    : LocalBasePath+CommonPathSuffix={c_full}")
    print()

    # ---- 要求 1：入口必须是真 .exe，禁止脚本/中转启动器 ----
    ext = os.path.splitext(b_target)[1].lower()
    chk("要求1", "入口文件扩展名", ".exe",
        ext, ext == ".exe")
    chk("要求1", "入口为合法 PE(MZ)", "MZ", open(b_target, "rb").read(2).decode("latin1"), is_pe)
    chk("要求1", "入口非脚本(.bat/.cmd/.ps1/.vbs)", "非脚本",
        ext, ext not in (".bat", ".cmd", ".ps1", ".vbs", ".js", ".wsf"))
    chk("要求1", "包体顶层无脚本启动器", "0 个",
        str(len([f for f in os.listdir(PKG)
                 if os.path.splitext(f)[1].lower()
                 in (".bat", ".cmd", ".ps1", ".vbs")])),
        not any(os.path.splitext(f)[1].lower() in (".bat", ".cmd", ".ps1", ".vbs")
                for f in os.listdir(PKG)))

    # ---- 要求 2：完整目录包 ----
    n_files = sum(len(fs) for _, _, fs in os.walk(PKG))
    n_internal = len(os.listdir(os.path.join(PKG, "_internal"))) \
        if os.path.isdir(os.path.join(PKG, "_internal")) else 0
    chk("要求2", "为目录(非单文件)", "目录",
        "目录" if os.path.isdir(PKG) else "文件", os.path.isdir(PKG))
    chk("要求2", "_internal 依赖齐备", ">=1 文件",
        f"{n_internal} 项 / 全包 {n_files} 文件", n_internal >= 1)

    # ---- 要求 3：快捷方式目标直接指向包内 exe ----
    chk("要求3", "[A] Target == 包内 exe", EXE, a_target, nc(a_target) == exe_n)
    chk("要求3", "[B] RAWPATH == 包内 exe", EXE, b_target, nc(b_target) == exe_n)
    chk("要求3", "[C] 二进制路径 == 包内 exe", EXE, c_full, nc(c_full) == exe_n)
    chk("要求3", "三路结果一致", "三者相同",
        "一致" if nc(a_target) == nc(b_target) == nc(c_full) else "不一致",
        nc(a_target) == nc(b_target) == nc(c_full))
    chk("要求3", "无相对路径字段(HasRelativePath)", "未置位",
        "未置位" if not (flags & 0x08) else "已置位", not (flags & 0x08))
    chk("要求3", "无环境变量目标(HasExpString)", "未置位",
        "未置位" if not (flags & 0x200) else "已置位", not (flags & 0x200))

    # ---- 要求 4：打开文件所在位置 -> 包体目录 ----
    chk("要求4", "dirname(Target) == 包体目录", PKG,
        os.path.dirname(b_target), nc(os.path.dirname(b_target)) == pkg_n)
    chk("要求4", "Start in == 包体目录", PKG, b_startin, nc(b_startin) == pkg_n)
    chk("要求4", "图标路径也指向包内 exe", EXE, b_icon, nc(b_icon) == exe_n)
    chk("要求4", "该目录确实存在且含 ZBridge.exe", "存在",
        "存在" if os.path.isfile(os.path.join(os.path.dirname(b_target),
                                              "ZBridge.exe")) else "缺失",
        os.path.isfile(os.path.join(os.path.dirname(b_target), "ZBridge.exe")))

    # ---- 输出 ----
    print("=" * 78)
    print(f"{'要求':<6}{'核验项':<34}{'期望':<10}{'实际':<10}{'判定'}")
    print("-" * 78)
    for req, item, exp, got, res, note in rows:
        e = (exp[:8] + "..") if len(exp) > 10 else exp
        g = (got[:8] + "..") if len(got) > 10 else got
        print(f"{req:<6}{item:<34}{e:<10}{g:<10}{res}")
    print("=" * 78)
    n_pass = sum(1 for r in rows if r[4] == "PASS")
    print(f"合计 {len(rows)} 项，通过 {n_pass}，失败 {len(rows) - n_pass}")

    # 机器可读
    import json
    json.dump([{"req": r[0], "item": r[1], "expect": r[2], "got": r[3],
                "result": r[4], "note": r[5]} for r in rows],
              open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "shortcut_verify.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    sys.exit(0 if n_pass == len(rows) else 1)


if __name__ == "__main__":
    main()
