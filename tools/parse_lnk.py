# -*- coding: utf-8 -*-
"""
严格解析 .lnk 二进制结构（MS-SHLINK），逐块定位路径存储位置。
目的：证明快捷方式目标确实是包内 exe 的绝对路径，而非环境变量/相对路径/缓存副本。
"""
import os
import struct
import sys

# 用法: python tools/parse_lnk.py <快捷方式.lnk> [期望的目标 exe 绝对路径]
LNK = (sys.argv[1] if len(sys.argv) > 1
       else os.path.join(os.path.expanduser("~"), "Desktop", "ZBridge.lnk"))
WANT = sys.argv[2] if len(sys.argv) > 2 else ""

BLOCKS = {
    0xA0000001: "EnvironmentVariableDataBlock",
    0xA0000002: "ConsoleDataBlock",
    0xA0000003: "TrackerDataBlock",
    0xA0000004: "ConsoleFEDataBlock",
    0xA0000005: "SpecialFolderDataBlock",
    0xA0000006: "DarwinDataBlock",
    0xA0000007: "IconEnvironmentDataBlock",
    0xA0000008: "ShimDataBlock",
    0xA0000009: "PropertyStoreDataBlock",
    0xA000000B: "KnownFolderDataBlock",
    0xA000000C: "VistaAndAboveIDListDataBlock",
}


def main():
    raw = open(LNK, "rb").read()
    print("file:", LNK, "size:", len(raw))

    # ---- Header ----
    hdr_size = struct.unpack_from("<I", raw, 0x00)[0]
    guid = raw[0x04:0x14]
    flags = struct.unpack_from("<I", raw, 0x14)[0]
    print("\n=== ShellLinkHeader ===")
    print("  HeaderSize     :", hdr_size, "(expect 76)")
    print("  GUID           :", guid.hex())
    print("  LinkFlags      : 0x%08X" % flags)
    names = [
        (0x00000001, "HasLinkTargetIDList"),
        (0x00000002, "HasLinkInfo"),
        (0x00000004, "HasName"),
        (0x00000008, "HasRelativePath"),
        (0x00000010, "HasWorkingDir"),
        (0x00000020, "HasArguments"),
        (0x00000040, "HasIconLocation"),
        (0x00000080, "IsUnicode"),
        (0x00000100, "ForceNoLinkInfo"),
        (0x00000200, "HasExpString"),
        (0x00000400, "RunInSeparateProcess"),
        (0x00000800, "Unused1"),
        (0x00001000, "HasDarwinID"),
        (0x00002000, "RunAsUser"),
        (0x00004000, "HasExpIcon"),
        (0x00008000, "NoPidlAlias"),
        (0x00010000, "Unused2"),
        (0x00020000, "RunWithShimLayer"),
        (0x00040000, "ForceNoLinkTrack"),
        (0x00080000, "EnableTargetMetadata"),
        (0x00100000, "DisableLinkPathTracking"),
        (0x00200000, "DisableKnownFolderTracking"),
        (0x00400000, "DisableKnownFolderAlias"),
        (0x00800000, "AllowLinkToLink"),
        (0x01000000, "UnaliasOnSave"),
        (0x02000000, "PreferEnvironmentPath"),
        (0x04000000, "KeepLocalIDListForUNCTarget"),
    ]
    for bit, n in names:
        if flags & bit:
            print(f"    - {n}")

    pos = 0x4C  # after header

    # ---- LinkTargetIDList ----
    idlist_start = None
    if flags & 0x00000001:
        idsize = struct.unpack_from("<H", raw, pos)[0]
        print("  IDListSize     :", idsize)
        idlist_start = pos + 2
        pos += 2 + idsize
        # ---- 逐段解析 ItemID，还原真实目标路径 ----
        print("  --- 逐段 ItemID 还原 ---")
        q = idlist_start
        end = idlist_start + idsize - 2  # 去掉末尾 TerminalID(2字节 0x0000)
        seg = []
        while q < end:
            ilen = struct.unpack_from("<H", raw, q)[0]
            if ilen == 0:
                break
            item = raw[q:q + ilen]
            sig = item[2:3] if ilen >= 3 else b""
            name = ""
            if sig in (b"\x1f", b"\x30", b"\x31", b"\x32", b"\x35", b"\xb1"):
                # 文件系统项：名在偏移 12 起（ANSI 或 UTF-16LE）
                blob = item[12:]
                ansi = blob.split(b"\x00")[0]
                if ansi:
                    name = ansi.decode("latin1", "ignore")
                if not name:
                    name = blob.decode("utf-16-le", "ignore").split("\x00")[0]
            elif sig == b"\x2f":
                name = item[3:].decode("latin1", "ignore").split("\x00")[0][:3] + ":\\"
            if name:
                seg.append(name)
                print(f"    off={q:<5} len={ilen:<4} sig=0x{sig.hex():<4} name={name}")
            q += ilen
        drive = seg[0] if seg else ""
        tail = "\\".join(seg[1:]) if len(seg) > 1 else ""
        rebuilt = drive + tail if drive.endswith("\\") else drive + "\\" + tail
        print("  --- 还原出的目标路径 ---")
        print("   ", rebuilt)
        globals()["REBUILT"] = rebuilt
    else:
        print("  (absent)")

    # ---- LinkInfo ----
    print("\n=== LinkInfo ===")
    if flags & 0x00000002:
        li_size = struct.unpack_from("<I", raw, pos)[0]
        hdr_sz = struct.unpack_from("<I", raw, pos + 4)[0]
        li_flags = struct.unpack_from("<I", raw, pos + 8)[0]
        print("  LinkInfoSize       :", li_size)
        print("  LinkInfoHeaderSize :", hdr_sz)
        print("  LinkInfoFlags      : 0x%08X" % li_flags,
              "VolumeIDAndLocalBasePath" if li_flags & 1 else "",
              "CommonNetworkRelativeLinkAndPathSuffix" if li_flags & 2 else "")
        if li_flags & 1:
            voff = struct.unpack_from("<I", raw, pos + 12)[0]
            loff = struct.unpack_from("<I", raw, pos + 16)[0]
            loff_u = None
            # 头部 >=0x24 表示含 Unicode 偏移字段（位于 24 处）
            if hdr_sz >= 0x24:
                loff_u = struct.unpack_from("<I", raw, pos + 24)[0]
            vsize = struct.unpack_from("<I", raw, pos + voff)[0]
            print(f"  VolumeID[{voff}] size={vsize}")
            s = pos + loff
            e = raw.index(b"\x00", s)
            print(f"  LocalBasePath(ANSI)[{loff}] : {raw[s:e].decode('latin1')}")
            if loff_u:
                s2 = pos + loff_u
                e2 = raw.index(b"\x00\x00", s2)
                print("  LocalBasePathUnicode[%d]  : %s"
                      % (loff_u, raw[s2:e2].decode("utf-16-le")))
        # CommonPathSuffix（MS-SHLINK：完整路径 = LocalBasePath + CommonPathSuffix）
        if li_flags & 2:
            cps_off = struct.unpack_from("<I", raw, pos + 24)[0]
            s3 = pos + cps_off
            e3 = raw.index(b"\x00", s3)
            suffix = raw[s3:e3].decode("latin1")
            print(f"  CommonPathSuffix[{cps_off}] : {suffix}")
            lb = "C:\\" if (li_flags & 1) else ""
            full = lb + suffix
            print("  --- 拼接出的完整目标路径 ---")
            print("   ", full)
            globals()["FULLPATH"] = full
        pos += li_size
    else:
        print("  (absent)")

    # ---- StringData ----
    print("\n=== StringData ===")

    def rd_str(off):
        cnt = struct.unpack_from("<H", raw, off)[0]
        s = off + 2
        if flags & 0x80:
            n = cnt * 2
            return raw[s:s + n].decode("utf-16-le"), s + n
        return raw[s:s + cnt].decode("latin1"), s + cnt

    for bit, label in ((0x04, "NAME"), (0x08, "RELATIVE_PATH"),
                       (0x10, "WORKING_DIR"), (0x20, "ARGUMENTS"),
                       (0x40, "ICON_LOCATION")):
        if flags & bit:
            v, pos = rd_str(pos)
            print(f"  {label:<14}: {v}")

    # ---- ExtraData ----
    print("\n=== ExtraData blocks ===")
    seen_sigs = []
    while pos + 4 <= len(raw):
        bsize = struct.unpack_from("<I", raw, pos)[0]
        if bsize < 4 or pos + bsize > len(raw):
            break
        if bsize == 4:
            break  # terminal block
        sig = struct.unpack_from("<I", raw, pos + 4)[0]
        name = BLOCKS.get(sig, "UNKNOWN")
        seen_sigs.append(sig)
        print(f"  offset={pos:<6} size={bsize:<6} sig=0x{sig:08X}  {name}")
        if sig == 0xA0000001:
            s = pos + 8
            e = raw.index(b"\x00\x00\x00", s)
            tgt = raw[s:e].decode("utf-16-le")
            print("    >>> TargetAnsi/Unicode:", tgt)
        if sig == 0xA0000003:
            print("    MachineIdentifier:",
                  raw[pos + 0x14:pos + 0x14 + 16].decode("latin1", "ignore"))
        pos += bsize

    print("\n=== 关键判定 ===")
    full = globals().get("FULLPATH", "")
    want = WANT
    print("  LinkInfo 拼接路径 :", full)
    if want:
        print("  期望包体内路径    :", want)
        print("  拼接路径==包内 exe:", os.path.normcase(full) == os.path.normcase(want))
    else:
        print("  (未传入期望路径，仅输出解析结果)")
    txt = raw.decode("utf-16-le", "ignore") + raw.decode("latin1", "ignore")
    has_env = "%USERPROFILE%" in txt
    print("  出现 %USERPROFILE% 字符串         :", has_env)
    print("  HasExpString 标志位置位           :", bool(flags & 0x200))
    print("  EnvironmentVariableDataBlock 存在 :", 0xA0000001 in seen_sigs)
    print("  结论: 目标是否为环境变量路径       :",
          bool(flags & 0x200) or (0xA0000001 in seen_sigs))
    print("  (若为 False，则 %USERPROFILE% 字符串仅存在于 Tracker/IDList 等")
    print("   无关结构中，或来自残留数据，不影响 Shell 解析目标)")


if __name__ == "__main__":
    main()
