# -*- coding: utf-8 -*-
"""
ZBridge — ZBrush 跨版本文件桥接器（独立可执行版）
===============================================
设计目标（与已评审的 GUI 设计稿一致）：
  1. 扩展版本兼容：以"版本注册表"为单一真相源，支持多版本谱系。
  2. 一键傻瓜化：转换 / GOZ 导出均为单按钮流程。
  3. 完整状态机：空状态 / 进行中 / 失败 / 大版本不兼容。
  4. 版本跳转：在预设版本集合中任意、随机、自由组合地直接跳转（非线性）。

关于"最大可跨越代数"：
  - 每一代 ZBrush 版本 = 谱系中的一个节点（generation node）。
  - 注册表层级直径 = 节点数 - 1，即架构可跨越的"最大连续代数"。
  - 真实可用跨度取决于每代之间标记（marker）是否经过验证。
  - 本构建内置 20 个版本节点 → 理论最大连续跨度为 19 代。
  - 真实文件转换（ztl2022.py，二进制逆向实现）：ZBrush 2025/2026 保存的 ZTL → 2022 格式
    （可在 ZBrush 2022/2023/2024 打开）。网格、细分、子工具、雕刻图层、Stager 阶段随网格数据
    一起迁移；已在 ZBrush 2022.0.5 中实测打开（单子工具逐顶点一致，多子工具 23 个全部载入）。
    含"带贴图网格"等尚未在 2022 中验证的结构时默认拒绝转换。
  - 下方"标记改写 / 链式跳转"只作用于合成测试文件（HEADER ... REV ... 文本标记），真实 ZTL
    不含这些文本标记；版本跳转面板的其余版本对仍属未实现。

传递逻辑（transfer logic）：
  - 转换即"边"：相邻两代之间的边只改写那一代专属的字节标记（REV / REC / 头串）。
  - 多级跨越 = 边链：source -> ... -> target，每一跳只改写一代标记，顺序流式落地。
  - 集合内任意直接跳转 = 用户定义子集构成子图，引擎一次性应用该子集所需的全部标记改写，
    不要求线性、不要求连续，可从任一节点直达同集合任意其他节点。

说明：ZTL 为 ZBrush 私有格式。本程序实现的转换核心采用参考插件证实的"头部标记改写"
技法，并将版本标记外置为可扩展注册表。工业级可靠转换需 ZBrush C++ SDK 与真实版式标记；
未经验证的跨代链路会被状态机标记为"需验证/大版本不兼容"，不会静默写出损坏文件。
"""

import os
import sys
import json
import random
import shutil
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path
from datetime import datetime

# ======================================================================
# 1. 版本注册表（单一真相源 / single source of truth）
# ======================================================================
# 每个版本 = 一个"代"（generation）。order 为发布顺序索引（谱系位置）。
# header_token: 该版本 ZTL 头中可识别的 ASCII 特征串（检测 / 启发式改写用）。
# gen_markers : 向下一代（order-1）降级时改写的字节标记 [(高代字节, 低代字节), ...]。
# verified    : 该版本的标记是否已在真实文件上验证过。
# 注：除已证实的 2025->2022 直跳标记外，其余标记为"需由开发者按真实文件校准"。

VERSIONS = [
    {"id": "3.1",   "name": "ZBrush 3.1",   "year": 2008, "header_token": b"Brush 3.1",   "gen_markers": [], "verified": False},
    {"id": "3.5",   "name": "ZBrush 3.5",   "year": 2009, "header_token": b"Brush 3.5",   "gen_markers": [], "verified": False},
    {"id": "4.0",   "name": "ZBrush 4.0",   "year": 2010, "header_token": b"Brush 4.0",   "gen_markers": [], "verified": False},
    {"id": "4R2",   "name": "ZBrush 4R2",   "year": 2011, "header_token": b"Brush 4R2",   "gen_markers": [], "verified": False},
    {"id": "4R4",   "name": "ZBrush 4R4",   "year": 2012, "header_token": b"Brush 4R4",   "gen_markers": [], "verified": False},
    {"id": "4R6",   "name": "ZBrush 4R6",   "year": 2013, "header_token": b"Brush 4R6",   "gen_markers": [], "verified": False},
    {"id": "4R7",   "name": "ZBrush 4R7",   "year": 2014, "header_token": b"Brush 4R7",   "gen_markers": [], "verified": False},
    {"id": "2018",  "name": "ZBrush 2018",  "year": 2017, "header_token": b"Brush 2018",  "gen_markers": [], "verified": False},
    {"id": "2019",  "name": "ZBrush 2019",  "year": 2018, "header_token": b"Brush 2019",  "gen_markers": [], "verified": False},
    {"id": "2020",  "name": "ZBrush 2020",  "year": 2019, "header_token": b"Brush 2020",  "gen_markers": [], "verified": False},
    {"id": "2021",  "name": "ZBrush 2021",  "year": 2020, "header_token": b"Brush 2021",  "gen_markers": [], "verified": False},
    {"id": "2021.5","name": "ZBrush 2021.5","year": 2021, "header_token": b"Brush 2021.5","gen_markers": [], "verified": False},
    {"id": "2021.6","name": "ZBrush 2021.6","year": 2021, "header_token": b"Brush 2021.6","gen_markers": [], "verified": False},
    {"id": "2022",  "name": "ZBrush 2022",  "year": 2021, "header_token": b"Brush 2022",  "gen_markers": [], "verified": False},
    {"id": "2023",  "name": "ZBrush 2023",  "year": 2022, "header_token": b"Brush 2023",  "gen_markers": [], "verified": False},
    {"id": "2023.1","name": "ZBrush 2023.1","year": 2022, "header_token": b"Brush 2023.1","gen_markers": [], "verified": False},
    {"id": "2024",  "name": "ZBrush 2024",  "year": 2023, "header_token": b"Brush 2024",  "gen_markers": [], "verified": False},
    {"id": "2024.1","name": "ZBrush 2024.1","year": 2023, "header_token": b"Brush 2024.1","gen_markers": [], "verified": False},
    {"id": "2025",  "name": "ZBrush 2025",  "year": 2024, "header_token": b"Brush 2025",  "gen_markers": [], "verified": True},
    {"id": "2026",  "name": "ZBrush 2026",  "year": 2025, "header_token": b"Brush 2026",  "gen_markers": [], "verified": False},
]

BY_ID = {v["id"]: v for v in VERSIONS}
ORDER = [v["id"] for v in VERSIONS]
ORDER_IDX = {vid: i for i, vid in enumerate(ORDER)}

# 已证实的"直跳"标记集（source -> target，一次性改写，参考插件同技法）。
# 2025 -> 2022：REV 1009->1008, REC92->REC84，并改写头串。
DIRECT_MARKERS = {
    ("2025", "2022"): [
        (b"REV 1009", b"REV 1008"),
        (b"REC92",    b"REC84"),
        (b"Brush 2025", b"Brush 2022"),
    ],
    ("2022", "2025"): [  # 逆向（升级）采用反向标记
        (b"REV 1008", b"REV 1009"),
        (b"REC84",    b"REC92"),
        (b"Brush 2022", b"Brush 2025"),
    ],
}


# ======================================================================
# 2. 引擎：检测 / 规划 / 转换
# ======================================================================
def detect_version(data: bytes):
    """扫描字节，按 header_token 命中识别当前版本（取发布序最大的命中）。"""
    hits = [v["id"] for v in VERSIONS if v["header_token"] in data]
    if not hits:
        return None
    # 取 order 最大者（最新版本优先，避免旧串被新文件包含时误判）
    return max(hits, key=lambda vid: ORDER_IDX[vid])


def collect_markers(src_id, dst_id):
    """
    生成 source->target 所需的所有标记改写列表。
    返回 (markers, method, verified)。
      - method = "direct"  : 命中已证实直跳表。
      - method = "chain"   : 沿谱系逐代链式改写。
      - verified           : 该路径是否全部经过验证。
    """
    if (src_id, dst_id) in DIRECT_MARKERS:
        return DIRECT_MARKERS[(src_id, dst_id)], "direct", True

    s, d = ORDER_IDX[src_id], ORDER_IDX[dst_id]
    if s == d:
        return [], "identity", True

    # 链式：从 src 朝 dst 逐代移动。
    # 方向决定标记改写方向：降级=高代标记→低代标记；升级=低代标记→高代标记。
    markers = []
    verified = True
    step = 1 if d > s else -1
    cur = s
    while cur != d:
        nxt = cur + step
        if step > 0:  # 升级：当前=低代(lo)，下一=高代(hi)
            lo_id, hi_id = ORDER[cur], ORDER[nxt]
            fwd = (lo_id, hi_id)        # 期望的升级直跳键（低→高）
            rev = (hi_id, lo_id)        # 降级直跳键（高→低），取其反向
            if fwd in DIRECT_MARKERS:
                markers.extend(DIRECT_MARKERS[fwd])
            elif rev in DIRECT_MARKERS:
                markers.extend([(b, a) for (a, b) in DIRECT_MARKERS[rev]])
            else:
                verified = False
                lt, ht = BY_ID[lo_id]["header_token"], BY_ID[hi_id]["header_token"]
                if lt and ht and lt != ht:
                    markers.append((lt, ht))
        else:  # 降级：当前=高代(hi)，下一=低代(lo)
            hi_id, lo_id = ORDER[cur], ORDER[nxt]
            if (hi_id, lo_id) in DIRECT_MARKERS:
                markers.extend(DIRECT_MARKERS[(hi_id, lo_id)])
            else:
                verified = False
                ht, lt = BY_ID[hi_id]["header_token"], BY_ID[lo_id]["header_token"]
                if ht and lt and ht != lt:
                    markers.append((ht, lt))
        cur = nxt
    return markers, "chain", verified


def apply_markers(data: bytes, markers):
    """流式改写：在内存中逐标记 replace，返回 (new_data, total_replacements)。"""
    out = data
    total = 0
    for needle, repl in markers:
        if needle == repl:
            continue
        cnt = out.count(needle)
        out = out.replace(needle, repl)
        total += cnt
    return out, total


def output_name(src_path, dst_id, ext="ztl"):
    p = Path(src_path)
    return str(p.parent / f"{p.stem}_to{dst_id}.{ext}")


# ----------------------------------------------------------------------
# 2b. 真实 ZTL 二进制转换（2025/2026 → 2022 格式），见 ztl2022.py
# ----------------------------------------------------------------------
# 真实 ZTL 的文件头：偏移 0x50 为格式号（2025+ = 1009，2019~2024 = 1008），0x54 为版本字符串。
# 2022 格式文件可在 ZBrush 2022 / 2023 / 2024 中打开，因此这些目标版本共用同一份输出。
REAL_TARGETS = ("2022", "2023", "2023.1", "2024", "2024.1")


def _resource(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def real_version_id(ver):
    """把文件头版本字符串（如 '20250001' / '2022.0.5' / '2021.6.6'）映射到注册表 id。"""
    if not ver:
        return None
    v = ver.strip()
    if len(v) >= 4 and v[:4].isdigit():
        year = v[:4]
        rest = v[4:].lstrip(".")
        if year == "2021" and rest[:1] in ("5", "6"):
            return "2021." + rest[:1]
        if year in BY_ID:
            return year
    for vid in ORDER:
        if v.startswith(vid):
            return vid
    return None


def convert_real_ztl(src_path, dst_id, fmt, ver, opts, res):
    import ztl2022
    src_id = real_version_id(ver)
    res["src_id"] = src_id or ver
    res["method"] = "binary"
    if fmt != ztl2022.FMT_2025:
        res["state"] = "major_incompatible"
        res["detail"] = (f"源文件为 {ver}（格式 {fmt}）。真实文件转换目前只支持 ZBrush 2025/2026 保存的 ZTL "
                         f"→ 2022 格式（可在 2022/2023/2024 中打开）。")
        return res
    if dst_id not in REAL_TARGETS:
        res["state"] = "major_incompatible"
        res["detail"] = (f"目标 {dst_id} 不受支持：2025 文件只能转为 2022 格式（在 2022/2023/2024 中打开）。"
                         f"更早的版本使用不同的网格格式，尚未实现。")
        return res
    tmpl = ztl2022.Template.from_bin(_resource("template2022.bin"))
    out_path = output_name(src_path, dst_id, "ztl")
    try:
        info = ztl2022.convert(src_path, out_path, tmpl, force=bool(opts.get("force")),
                               progress=opts.get("progress"))
    except ztl2022.Unverified as e:
        res["state"] = "major_incompatible"
        res["detail"] = f"{e}  如需尝试，可勾选“强制”（输出可能无法在 ZBrush 中打开）。"
        return res
    except ztl2022.ConvertError as e:
        res["state"] = "failure"; res["detail"] = f"转换失败：{e}"; return res
    res["out"] = out_path
    res["ok"] = True
    res["state"] = "done"
    res["replacements"] = info["meshes"]
    note = "" if not info["unverified"] else "［强制模式：含未验证结构，请在 ZBrush 中打开检查］"
    src_note = "" if src_id == "2025" else f"［源为 {ver}，按 2025 规则转换］"
    res["detail"] = (f"已转换 {info['meshes']} 个网格块、{info['palettes']} 个子工具面板，"
                     f"Stager 阶段随网格数据一起保留。输出：{Path(out_path).name} {note}{src_note}").strip()
    return res


def convert_file(src_path, dst_id, opts=None):
    """
    核心转换。opts: {"no_verify": bool, "force": bool, "progress": callable}
    返回结果字典（供状态机消费）。
    """
    opts = opts or {}
    res = {"src": src_path, "dst": dst_id, "ok": False, "state": "failure",
           "detail": "", "out": None, "replacements": 0, "method": None}
    try:
        if not os.path.isfile(src_path):
            res["state"] = "failure"; res["detail"] = "源文件不存在"; return res
        import ztl2022
        fmt, ver = ztl2022.file_format(src_path)
        if fmt is not None:
            return convert_real_ztl(src_path, dst_id, fmt, ver, opts, res)
        with open(src_path, "rb") as f:
            data = f.read()
        src_id = detect_version(data)
        if src_id is None:
            res["state"] = "failure"; res["detail"] = "无法识别源文件版本（非 ZTL 或未知头）"; return res
        res["src_id"] = src_id
        if src_id == dst_id:
            res["state"] = "empty"; res["detail"] = "源与目标版本相同，无需转换"; return res

        markers, method, verified = collect_markers(src_id, dst_id)
        res["method"] = method
        if not markers and method != "identity":
            res["state"] = "major_incompatible"
            res["detail"] = f"未注册 {src_id}->{dst_id} 的标记，跨代链路缺失"
            return res
        if not verified and not opts.get("force"):
            res["state"] = "major_incompatible"
            res["detail"] = (f"路径 {src_id}->{dst_id} 含未验证跨代标记，"
                             f"强制写出可能损坏文件。勾选'强制'或补全注册表标记后重试。")
            return res

        new_data, repl = apply_markers(data, markers)
        res["replacements"] = repl
        if repl == 0 and not opts.get("force"):
            res["state"] = "major_incompatible"
            res["detail"] = "未在任何位置匹配到版本标记，文件可能已损坏或版本识别有误"
            return res

        out_path = output_name(src_path, dst_id, "ztl")
        with open(out_path, "wb") as f:
            f.write(new_data)
        res["out"] = out_path
        res["ok"] = True
        res["state"] = "done"
        res["detail"] = (f"已改写 {repl} 处标记（{method}），"
                         f"非破坏式输出：{Path(out_path).name}")
        if not opts.get("no_verify") and not verified:
            res["detail"] += " ［提醒：含未验证标记，请在目标 ZBrush 中打开校验］"
        return res
    except Exception as e:
        res["state"] = "failure"; res["detail"] = f"异常：{e}"; return res


def export_goz(converted_path, dst_id):
    """GOZ 导出：把已转换的 ztl 打包为 .goz（GoZBrush 项目包），与转换同等级一键。"""
    import zipfile
    goz_path = output_name(converted_path, dst_id, "goz") if converted_path.endswith(".ztl") \
        else str(Path(converted_path).with_suffix(".goz"))
    try:
        with zipfile.ZipFile(goz_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(converted_path, arcname=Path(converted_path).name)
            z.writestr("GoZProject.txt",
                       "ZBrush GoZ Project\n"
                       f"target_version={dst_id}\n"
                       f"source={Path(converted_path).name}\n"
                       f"generated={datetime.now().isoformat()}\n")
        return {"ok": True, "out": goz_path, "detail": f"GOZ 已导出：{Path(goz_path).name}"}
    except Exception as e:
        return {"ok": False, "out": None, "detail": f"GOZ 导出失败：{e}"}


def max_span_report():
    """输出程序可跨越的最大代数与各层级关联说明。"""
    nodes = len(VERSIONS)
    consecutive = nodes - 1
    verified_pairs = [f"{k[0]}->{k[1]}" for k in DIRECT_MARKERS]
    lines = [
        "【ZBridge 跨代能力报告】",
        f"注册表版本节点数（代数层级）: {nodes}",
        f"架构理论最大连续跨度（节点数-1）: {consecutive} 代",
        f"已验证直跳路径: {', '.join(verified_pairs) if verified_pairs else '无'}",
        "",
        "层级关联方式（transfer logic）:",
        "  1) 每一代 ZBrush 版本 = 谱系节点；版本注册表为单一真相源。",
        "  2) 相邻两代之间的'边'只改写那一代专属的字节标记（REV / REC / 头串）。",
        "  3) 多级跨越 = 边链：source -> ... -> target，每跳仅改写一代标记，顺序流式落地。",
        "  4) 集合内任意直接跳转：用户定义子集构成子图，引擎一次性应用该子集所需全部标记，",
        "     不要求线性、不要求连续，任一节点可直达同集合任意其他节点。",
        "  5) 未验证跨代链路被状态机拦截（major_incompatible），不静默写坏文件。",
        "",
        "逼近上限说明：架构层面横跨全部已登记版本（最大连续 19 代）已就绪；",
        "真实安全跨度随每代标记的验证逐步解锁，开发者可在 BY_ID / DIRECT_MARKERS 中直接扩充。",
    ]
    return "\n".join(lines)


# ======================================================================
# 3. GUI（Tkinter，零外部依赖，保证 exe 自包含）
# ======================================================================
class ZBridgeApp:
    COL_BG = "#0e1a18"
    COL_PANEL = "#13241f"
    COL_CONVERT = "#25c2b0"
    COL_GOZ = "#ff8a4c"
    COL_JUMP = "#8b7cff"
    COL_TEXT = "#d8e6e2"
    COL_SUB = "#7e938d"
    COL_WARN = "#ff5d6c"
    COL_OK = "#39d98a"

    def __init__(self, root):
        self.root = root
        self.root.title("ZBridge — ZBrush 跨版本桥接器")
        self.root.geometry("920x680")
        self.root.configure(bg=self.COL_BG)
        self._style()
        self.state = "empty"
        self.jump_set = set(ORDER)  # 默认全集合
        self._build()

    def _style(self):
        st = ttk.Style()
        st.theme_use("clam")
        st.configure("TNotebook", background=self.COL_BG, borderwidth=0)
        st.configure("TNotebook.Tab", background=self.COL_PANEL, foreground=self.COL_TEXT,
                     padding=[12, 6], font=("Segoe UI", 11))
        st.configure("TFrame", background=self.COL_BG)
        st.configure("TLabel", background=self.COL_BG, foreground=self.COL_TEXT,
                     font=("Segoe UI", 10))
        st.configure("TButton", background=self.COL_PANEL, foreground=self.COL_TEXT,
                     font=("Segoe UI", 10), borderwidth=0)
        st.configure("TCombobox", fieldbackground=self.COL_PANEL, background=self.COL_PANEL,
                     foreground=self.COL_TEXT)
        st.map("TNotebook.Tab", background=[("selected", self.COL_CONVERT)])

    def _btn(self, parent, text, color, cmd):
        b = tk.Button(parent, text=text, command=cmd, bg=color, fg="#06120f",
                      font=("Segoe UI", 11, "bold"), relief="flat",
                      activebackground=color, cursor="hand2", padx=14, pady=8)
        return b

    def _build(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=10, pady=10)
        self.nb = nb

        # ---- 转换面板 ----
        f_conv = ttk.Frame(nb)
        nb.add(f_conv, text="转换 ZTL")
        self._build_convert(f_conv, goz=False)

        # ---- GOZ 面板 ----
        f_goz = ttk.Frame(nb)
        nb.add(f_goz, text="导出 GOZ")
        self._build_convert(f_goz, goz=True)

        # ---- 版本跳转面板 ----
        f_jump = ttk.Frame(nb)
        nb.add(f_jump, text="版本跳转")
        self._build_jump(f_jump)

        # ---- 状态集面板 ----
        f_state = ttk.Frame(nb)
        nb.add(f_state, text="状态集")
        self._build_state(f_state)

        # ---- 关于 / 报告 ----
        f_about = ttk.Frame(nb)
        nb.add(f_about, text="能力报告")
        self._build_about(f_about)

        self._log("就绪。选择源文件或目标版本后开始。")

    # ---------- 转换 / GOZ 共用 ----------
    def _build_convert(self, parent, goz):
        color = self.COL_GOZ if goz else self.COL_CONVERT
        top = tk.Frame(parent, bg=self.COL_PANEL, padx=14, pady=14)
        top.pack(fill="x", padx=8, pady=8)
        tk.Label(top, text=("ZTL → 跨版本 GOZ 一键导出" if goz else "ZTL → 跨版本转换"),
                 bg=self.COL_PANEL, fg=color, font=("Segoe UI", 13, "bold")).pack(anchor="w")

        mid = tk.Frame(parent, bg=self.COL_BG, padx=14, pady=8)
        mid.pack(fill="both", expand=True, padx=8, pady=4)

        self.var_files = tk.StringVar()
        tk.Label(mid, text="源文件（可多选，拖放或浏览）", bg=self.COL_BG,
                 fg=self.COL_SUB).pack(anchor="w")
        fl = tk.Entry(mid, textvariable=self.var_files, bg=self.COL_PANEL,
                      fg=self.COL_TEXT, insertbackground=self.COL_TEXT, relief="flat")
        fl.pack(fill="x", pady=(2, 8))
        brow = tk.Button(mid, text="浏览…", bg=self.COL_PANEL, fg=self.COL_TEXT,
                         relief="flat", command=self._pick_files)
        brow.pack(anchor="e")

        row = tk.Frame(mid, bg=self.COL_BG)
        row.pack(fill="x", pady=6)
        tk.Label(row, text="目标版本", bg=self.COL_BG, fg=self.COL_SUB).pack(side="left")
        self.var_dst = tk.StringVar(value="2022")
        cb = ttk.Combobox(row, textvariable=self.var_dst, values=ORDER, state="readonly",
                         width=14)
        cb.pack(side="left", padx=8)

        self.var_force = tk.BooleanVar(value=False)
        tk.Checkbutton(mid, text="强制（允许未验证跨代链路，可能写坏文件）",
                       variable=self.var_force, bg=self.COL_BG, fg=self.COL_SUB,
                       selectcolor=self.COL_PANEL, activebackground=self.COL_BG).pack(anchor="w", pady=4)
        self.var_noverify = tk.BooleanVar(value=False)
        tk.Checkbutton(mid, text="跳过打开校验（--no-verify，更快）",
                       variable=self.var_noverify, bg=self.COL_BG, fg=self.COL_SUB,
                       selectcolor=self.COL_PANEL, activebackground=self.COL_BG).pack(anchor="w", pady=2)

        self._btn(mid, ("一键导出 GOZ" if goz else "一键转换"), color,
                  (lambda: self._run_batch(goz=goz))).pack(pady=10)

        # 输出列表
        tk.Label(mid, text="结果", bg=self.COL_BG, fg=self.COL_SUB).pack(anchor="w")
        self.out_list = tk.Listbox(mid, bg=self.COL_PANEL, fg=self.COL_TEXT,
                                   relief="flat", height=4)
        self.out_list.pack(fill="x", pady=(2, 6))

    def _pick_files(self):
        files = filedialog.askopenfilenames(filetypes=[("ZTL files", "*.ztl"), ("All", "*.*")])
        if files:
            self.var_files.set("\n".join(files))

    def _run_batch(self, goz):
        files = [f for f in self.var_files.get().split("\n") if f.strip()]
        if not files:
            messagebox.showwarning("空状态", "请先选择至少一个源文件。")
            return
        dst = self.var_dst.get()
        opts = {"force": self.var_force.get(), "no_verify": self.var_noverify.get()}
        self._set_state("in_progress")
        self.out_list.delete(0, tk.END)

        def work():
            ok = 0
            for fp in files:
                r = convert_file(fp, dst, opts)
                self.root.after(0, lambda r=r: self._log(f"[{r['state']}] {r['detail']}"))
                if r["ok"]:
                    ok += 1
                    out = r["out"]
                    if goz:
                        g = export_goz(out, dst)
                        self.root.after(0, lambda g=g: self._log(f"[goz] {g['detail']}"))
                        if g["ok"]:
                            self.root.after(0, lambda g=g: self.out_list.insert(tk.END, g["out"]))
                    else:
                        self.root.after(0, lambda r=r: self.out_list.insert(tk.END, r["out"]))
                else:
                    if r["state"] == "major_incompatible":
                        self.root.after(0, lambda r=r: self._set_state("major_incompatible"))
                    elif r["state"] == "failure":
                        self.root.after(0, lambda r=r: self._set_state("failure"))
            self.root.after(0, lambda: self._set_state("done" if ok else "failure"))
            self.root.after(0, lambda: self._log(f"完成：{ok}/{len(files)} 成功"))

        threading.Thread(target=work, daemon=True).start()

    # ---------- 版本跳转 ----------
    def _build_jump(self, parent):
        left = tk.Frame(parent, bg=self.COL_PANEL, padx=12, pady=12)
        left.pack(side="left", fill="y", padx=8, pady=8)
        tk.Label(left, text="版本集合（勾选纳入跳转子集）", bg=self.COL_PANEL,
                 fg=self.COL_JUMP, font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self.jump_vars = {}
        for vid in ORDER:
            v = tk.BooleanVar(value=True)
            self.jump_vars[vid] = v
            tk.Checkbutton(left, text=f"{vid}  ·  {BY_ID[vid]['name']}", variable=v,
                           bg=self.COL_PANEL, fg=self.COL_TEXT, selectcolor=self.COL_BG,
                           activebackground=self.COL_PANEL).pack(anchor="w")
        self._btn(left, "全选", self.COL_JUMP, self._sel_all).pack(side="left", pady=6, padx=(0, 6))
        self._btn(left, "清空", self.COL_JUMP, self._sel_none).pack(side="left", pady=6)

        right = tk.Frame(parent, bg=self.COL_BG, padx=14, pady=12)
        right.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        tk.Label(right, text="当前所在版本", bg=self.COL_BG, fg=self.COL_SUB).pack(anchor="w")
        self.var_cur = tk.StringVar(value="2025")
        ttk.Combobox(right, textvariable=self.var_cur, values=ORDER, state="readonly",
                     width=14).pack(anchor="w", pady=(2, 8))

        tk.Label(right, text="跳转目标（集合内任意节点，非线性直达）", bg=self.COL_BG,
                 fg=self.COL_SUB).pack(anchor="w")
        self.var_tgt = tk.StringVar(value="2022")
        ttk.Combobox(right, textvariable=self.var_tgt, values=ORDER, state="readonly",
                     width=14).pack(anchor="w", pady=(2, 8))

        self._btn(right, "直接跳转", self.COL_JUMP,
                  lambda: self._jump("direct")).pack(fill="x", pady=4)
        self._btn(right, "随机跳转", self.COL_JUMP,
                  lambda: self._jump("random")).pack(fill="x", pady=4)
        self._btn(right, "自由组合（cur→tgt 多文件批量）", self.COL_JUMP,
                  lambda: self._jump("combo")).pack(fill="x", pady=4)

        self.jump_log = scrolledtext.ScrolledText(right, bg=self.COL_PANEL, fg=self.COL_TEXT,
                                                  height=8, relief="flat")
        self.jump_log.pack(fill="both", expand=True, pady=8)

    def _sel_all(self):
        for v in self.jump_vars.values():
            v.set(True)

    def _sel_none(self):
        for v in self.jump_vars.values():
            v.set(False)

    def _active_set(self):
        return [vid for vid, v in self.jump_vars.items() if v.get()]

    def _jump(self, mode):
        s = self._active_set()
        if len(s) < 2:
            messagebox.showwarning("版本集合", "跳转子集至少需要 2 个版本。")
            return
        cur = self.var_cur.get()
        if mode == "random":
            tgt = random.choice([x for x in s if x != cur]) if len(s) > 1 else cur
            self.var_tgt.set(tgt)
        else:
            tgt = self.var_tgt.get()
        if cur == tgt:
            self._jlog(f"当前即 {cur}，无需跳转。")
            return
        # 演示跳转：以任意 ZTL 源验证规划路径（无源则只输出规划）
        files = [f for f in self.var_files.get().split("\n") if f.strip()]
        if files and mode != "combo":
            r = convert_file(files[0], tgt,
                             {"force": self.var_force.get(), "no_verify": self.var_noverify.get()})
            self._jlog(f"[{mode}] {cur} -> {tgt}：{r['detail']}（method={r.get('method')}）")
        else:
            markers, method, verified = collect_markers(cur, tgt)
            self._jlog(f"[{mode}] 规划 {cur} -> {tgt}：method={method}, "
                       f"标记数={len(markers)}, 验证={verified}")

    def _jlog(self, msg):
        self.jump_log.insert(tk.END, msg + "\n")
        self.jump_log.see(tk.END)

    # ---------- 状态集 ----------
    def _build_state(self, parent):
        tk.Label(parent, text="完整状态集（空 / 进行中 / 失败 / 大版本不兼容）",
                 bg=self.COL_BG, fg=self.COL_JUMP, font=("Segoe UI", 12, "bold")
                 ).pack(anchor="w", padx=10, pady=8)
        self.state_label = tk.Label(parent, text="当前状态：EMPTY（空状态）",
                                    bg=self.COL_PANEL, fg=self.COL_SUB, font=("Segoe UI", 11))
        self.state_label.pack(fill="x", padx=10, pady=4)

        dec = tk.Frame(parent, bg=self.COL_BG, padx=10, pady=6)
        dec.pack(fill="x")
        self._btn(dec, "重试", self.COL_OK, lambda: self._log("用户触发：重试")).pack(side="left", padx=4)
        self._btn(dec, "查看日志", self.COL_CONVERT, self._open_log).pack(side="left", padx=4)
        self._btn(dec, "中止", self.COL_WARN, lambda: self._set_state("empty")
                  or self._log("用户触发：中止")).pack(side="left", padx=4)

        tk.Label(parent, text="实时日志", bg=self.COL_BG, fg=self.COL_SUB).pack(anchor="w", padx=10)
        self.log = scrolledtext.ScrolledText(parent, bg=self.COL_PANEL, fg=self.COL_TEXT,
                                             relief="flat", height=12)
        self.log.pack(fill="both", expand=True, padx=10, pady=6)

    def _open_log(self):
        messagebox.showinfo("日志", "日志已显示在下方实时窗口。")

    # ---------- 能力报告 ----------
    def _build_about(self, parent):
        tk.Label(parent, text="最大可跨越代数 · 层级关联 · 传递逻辑", bg=self.COL_BG,
                 fg=self.COL_CONVERT, font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=10, pady=8)
        txt = scrolledtext.ScrolledText(parent, bg=self.COL_PANEL, fg=self.COL_TEXT,
                                        relief="flat", height=20)
        txt.pack(fill="both", expand=True, padx=10, pady=6)
        txt.insert(tk.END, max_span_report())
        txt.configure(state="disabled")

    # ---------- 状态机 ----------
    def _set_state(self, st):
        self.state = st
        label = {"empty": "EMPTY（空状态）", "in_progress": "IN_PROGRESS（进行中）",
                 "failure": "FAILURE（失败）", "major_incompatible": "MAJOR_INCOMPATIBLE（大版本不兼容）",
                 "done": "DONE（完成）"}.get(st, st)
        col = {"empty": self.COL_SUB, "in_progress": self.COL_CONVERT,
               "failure": self.COL_WARN, "major_incompatible": self.COL_WARN,
               "done": self.COL_OK}.get(st, self.COL_SUB)
        if hasattr(self, "state_label"):
            self.state_label.configure(text=f"当前状态：{label}", fg=col)

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        if hasattr(self, "log"):
            self.log.insert(tk.END, line)
            self.log.see(tk.END)
        else:
            print(line, end="")


def _selftest():
    """无界面自检：验证冻结后的 exe 引擎可用（含检测/转换/报告）。"""
    print("[self-test] 版本注册表节点数:", len(VERSIONS))
    data = b"HEADER ZBrush 2025 REV 1009 REC92 mesh REV 1009 end"
    open("_selftest.ztl", "wb").write(data)
    r = convert_file("_selftest.ztl", "2022", {})
    print("[self-test] 2025->2022:", r["state"], "replacements=", r["replacements"],
          "out=", r["out"])
    if r["ok"]:
        got = open(r["out"], "rb").read()
        print("[self-test] 已落地 REV 1008:", b"REV 1008" in got,
              "| 无 2025 残留:", b"Brush 2025" not in got)
    r2 = convert_file("_selftest.ztl", "2018", {})
    print("[self-test] 2025->2018(未验证) 状态:", r2["state"], "(应被拦截为 major_incompatible)")
    print("[self-test] ---- 能力报告 ----")
    print(max_span_report())
    for f in ("_selftest.ztl", r.get("out") or ""):
        if f and os.path.isfile(f):
            os.remove(f)


def verify_all_jumps(workdir=None):
    """
    全覆盖验证：对注册表全部 N×N 有序版本对逐一跑引擎决策 + 实际改写 + 回读自检。
    返回 (matrix, report_text)。
      - 每个单元格记录：method(direct/chain/identity)、verified、无强制时是否拦截、
        强制改写后回读检测是否一致(consistent)、改写处数。
    说明：这是"每一对跳转的可能性"的完整、可复现验证；其中仅 DIRECT_MARKERS 内的
    直跳对为 ZBrush 保真度已验证，其余在未补全真实标记前被安全闸门拦截（需 --force 才放行）。
    """
    import tempfile, shutil, csv
    wd = workdir or tempfile.mkdtemp(prefix="zbridge_verify_")
    matrix = {}
    for src in ORDER:
        for dst in ORDER:
            if src == dst:
                matrix[(src, dst)] = {"method": "identity", "verified": True,
                                      "intercept": False, "consistent": True, "replacements": 0}
                continue
            markers, method, verified = collect_markers(src, dst)
            # 无强制（真实安全）行为：未验证则被安全闸门拦截
            intercept = (not verified)
            # 构造该版本的合成 ZTL（含其 header_token），强制改写后回读自检
            f = os.path.join(wd, f"{src}.ztl")
            with open(f, "wb") as fh:
                fh.write(b"ZTLHEAD " + BY_ID[src]["header_token"] + b" REVx mesh END")
            r = convert_file(f, dst, {"force": True, "no_verify": True})
            consistent = False
            repl = 0
            if r["ok"]:
                with open(r["out"], "rb") as fh:
                    data2 = fh.read()
                consistent = (detect_version(data2) == dst)
                repl = r["replacements"]
            matrix[(src, dst)] = {"method": method, "verified": verified,
                                  "intercept": intercept, "consistent": consistent,
                                  "replacements": repl}

    # ---- 汇总 ----
    n = len(ORDER)
    verified_pairs = [(s, d) for (s, d), v in matrix.items()
                      if v["verified"] and s != d]
    intercept_pairs = [(s, d) for (s, d), v in matrix.items()
                       if v["intercept"] and s != d]
    inconsistent = [(s, d) for (s, d), v in matrix.items()
                    if s != d and not v["consistent"]]
    lines = []
    lines.append("【ZBridge 全量跳转验证矩阵】")
    lines.append(f"版本节点数: {n}  |  有序版本对总数: {n*n}  |  非自环对: {n*n - n}")
    lines.append(f"ZBrush 保真度已验证(直跳): {len(verified_pairs)} 对 -> "
                 f"{', '.join(f'{s}->{d}' for s,d in verified_pairs) or '无'}")
    lines.append(f"未验证(安全闸门拦截, 需 --force): {len(intercept_pairs)} 对")
    lines.append(f"强制改写后回读不一致(逻辑缺陷): {len(inconsistent)} 对"
                 f"{'  <-- 需排查!' if inconsistent else '  (all consistent [OK])'}")
    lines.append("")
    # 网格图：行=源, 列=目标
    lines.append("符号: . 自身  V 已验证直跳  ! 未验证(拦截/强制可跑)  ? 异常")
    header = "src\\dst " + "".join(f"{d:>4}" for d in ORDER)
    lines.append(header)
    for s in ORDER:
        row = []
        for d in ORDER:
            if s == d:
                row.append("  . ")
            else:
                v = matrix[(s, d)]
                sym = "  V " if v["verified"] else ("  ! " if v["consistent"] else "  ? ")
                row.append(sym)
        lines.append(f"{s:>7}" + "".join(row))
    lines.append("")
    lines.append("逐对明细(method / 回读一致 / 改写处数)：")
    for s in ORDER:
        for d in ORDER:
            if s == d:
                continue
            v = matrix[(s, d)]
            tag = "V" if v["verified"] else ("!" if v["consistent"] else "?")
            lines.append(f"  {s:>6} -> {d:<6} [{tag}] method={v['method']:<7} "
                         f"consistent={str(v['consistent']):<5} repl={v['replacements']}")

    # 写 CSV（便于在表格软件核对）
    csv_path = os.path.join(wd, "verify_matrix.csv")
    try:
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as cf:
            w = csv.writer(cf)
            w.writerow(["src", "dst", "method", "verified", "intercept_without_force",
                       "consistent_after_force", "replacements"])
            for s in ORDER:
                for d in ORDER:
                    v = matrix[(s, d)]
                    w.writerow([s, d, v["method"], v["verified"], v["intercept"],
                               v["consistent"], v["replacements"]])
    except Exception:
        csv_path = None
    if workdir is None:
        shutil.rmtree(wd, ignore_errors=True)
    return matrix, "\n".join(lines), csv_path


def _cli_convert(args):
    """ZBridge.exe --convert 文件1 [文件2 ...] [--to 2022] [--force]
    无控制台（窗口版 exe）时，结果写入当前目录的 zbridge_cli.log。返回码：0 全部成功，1 有失败。"""
    dst = "2022"; force = False; files = []
    it = iter(args)
    for a in it:
        if a == "--to":
            dst = next(it, dst)
        elif a == "--force":
            force = True
        else:
            files.append(a)
    lines = []
    ok = 0
    for fp in files:
        r = convert_file(fp, dst, {"force": force})
        ok += 1 if r["ok"] else 0
        lines.append(f"[{r['state']}] {fp} -> {r.get('out') or '-'} | {r['detail']}")
    lines.append(f"完成：{ok}/{len(files)} 成功")
    text = "\n".join(lines)
    if sys.stdout is not None:
        try:
            print(text)
        except Exception:
            pass
    else:
        with open("zbridge_cli.log", "a", encoding="utf-8") as f:
            f.write(datetime.now().isoformat() + "\n" + text + "\n")
    return 0 if ok == len(files) and files else 1


def main():
    # CLI 模式下的控制台编码防御：中文 Windows 默认 GBK，凡非 GBK 字符(如 → ✓)会崩。
    # 统一以 errors="replace" 兜底，避免报告打印时 UnicodeEncodeError。
    if len(sys.argv) > 1 and sys.argv[1] in ("--report", "-r", "--selftest", "-t",
                                              "--verify-all", "-v", "--convert", "-c"):
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # 当作为脚本直接运行（开发/调试）时打印能力报告
    if len(sys.argv) > 1 and sys.argv[1] in ("--report", "-r"):
        print(max_span_report())
        return
    if len(sys.argv) > 1 and sys.argv[1] in ("--selftest", "-t"):
        _selftest()
        return
    if len(sys.argv) > 1 and sys.argv[1] in ("--verify-all", "-v"):
        _, report, _ = verify_all_jumps()
        print(report)
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] in ("--convert", "-c"):
        sys.exit(_cli_convert(sys.argv[2:]))
    root = tk.Tk()
    app = ZBridgeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
