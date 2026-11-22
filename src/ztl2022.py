# -*- coding: utf-8 -*-
"""ZTL 2025+ (format 1009) -> ZBrush 2022 (format 1008) converter.

Reverse-engineered from paired files saved by ZBrush 2025.0.1 and 2022.0.5, and checked
against a survey of ~200 real 2025 files and ~50 real 2019-2024 files.

Chunk: tag u16 0x8003 | ver u16 | type u16 | size u32 (includes the 10-byte header).
Containers end with the marker 03 88 00 00.

Rules
  * file header 0x00..0x5C            -> 2022 template (format 1008, "2022.0.5")
  * top-level document chunks          -> 2022 template (document image / thumbnail)
  * mesh chunk, type 92 -> 84:
        drop payload[0:45]  (36-char GUID, NUL, 8 bytes)
        drop 8 bytes at payload offset 0x16C (after the first drop): u32 in {0,1}, u32 == 1
        trailer after the attachment chunks:
            attachments (13,4) / (13,3): drop 4 zero bytes     [load-tested / matches 2022 samples]
            attachments (7,)           : unchanged             [matches 2022 samples]
            attachments (14,)          : drop 1 zero byte      [matches 2022 samples]
            anything else              : UNVERIFIED -> refused unless force=True
  * tool-palette chunk (type 10, payload starts 0b000000 0a000000), one per subtool:
        rebuilt from the 2022 palette template; items with the same name and size keep the
        source value.
  * every enclosing chunk gets its size recomputed.
The source file is never modified; output is verified after writing.
"""
import mmap
import os
import struct
import bisect

TAG = b'\x03\x80\x01\x00'
END = b'\x03\x88\x00\x00'
HDR_END = 0x5C
FMT_2025 = 1009
FMT_2022 = 1008

VERIFIED_KINDS = {(13, 4): 4, (13, 3): 4, (7,): 0, (14,): 1}
# best guess for structures not yet seen in a 2022 file (used only with force=True)
GUESS_KINDS = {(12, 1, 10): 0}


class ConvertError(Exception):
    pass


class Unverified(ConvertError):
    pass


def _hdr(d, o, end):
    if o + 10 > end or d[o:o + 4] != TAG:
        return None
    typ, size = struct.unpack_from('<HI', d, o + 4)
    if size < 10 or o + size > end:
        return None
    return typ, size


def _chain(d, p, end):
    q = p; k = 0
    while True:
        h = _hdr(d, q, end)
        if not h:
            return q, k
        q += h[1]; k += 1


def _child_chain_start(d, s, e):
    p = s
    while True:
        i = d.find(TAG, p, e - 10)
        if i < 0:
            return None
        if _hdr(d, i, e):
            q, k = _chain(d, i, e)
            if k >= 1 and e - q < 64:
                return i
        p = i + 1


def _iter_find(d, needle, start=0, end=None):
    end = len(d) if end is None else end
    i = start
    while True:
        i = d.find(needle, i, end)
        if i < 0:
            return
        yield i
        i += 1


def _is_mesh(d, i):
    return d[i:i + 6] == TAG + b'\x5c\x00' and d[i + 18:i + 19] == b'-' and d[i + 46] == 0


def _is_palette(d, i):
    return d[i:i + 6] == TAG + b'\x0a\x00' and d[i + 10:i + 18] == b'\x0b\x00\x00\x00\x0a\x00\x00\x00'


def _iter_wellformed(d, start, end, skip_ranges=()):
    """All chunks (any type) that fit and end with the END marker."""
    sr = sorted(skip_ranges); starts = [a for a, b in sr]
    for i in _iter_find(d, TAG, start, end):
        if i + 10 > end:
            return
        if sr:
            k = bisect.bisect_right(starts, i) - 1
            if k >= 0 and sr[k][0] < i < sr[k][1]:
                continue
        typ, size = struct.unpack_from('<HI', d, i + 4)
        if size >= 14 and i + size <= end and d[i + size - 4:i + size] == END:
            yield i, size


# ---------------- palette ----------------
def _palette_items(p):
    import re
    items = []; i = 0
    while True:
        i = p.find(TAG + b'\x05\x00', i)
        if i < 0:
            return items
        size = struct.unpack_from('<I', p, i + 6)[0]
        if size < 10 or i + size > len(p):
            i += 1; continue
        blk = p[i:i + size]
        names = [m.group() for m in re.finditer(rb'[A-Za-z][ -~]{2,}', blk)]
        items.append((i, size, b'|'.join(names)))
        i += size


def _merged_palette(src, tmpl):
    src_items = {}
    for (o, s, n) in _palette_items(src):
        if n and n not in src_items:
            src_items[n] = src[o:o + s]
    out = bytearray(tmpl); kept = 0
    for (o, s, n) in _palette_items(tmpl):
        b = src_items.get(n)
        if n and b is not None and len(b) == s:
            out[o:o + s] = b; kept += 1
    return bytes(out), kept


# ---------------- template ----------------
class Template:
    """header + top-level doc chunks + one tool palette, all from a file saved by ZBrush 2022."""

    def __init__(self, header, docs, palette):
        self.header, self.docs, self.palette = header, docs, palette

    @classmethod
    def from_ztl(cls, path):
        t = open(path, 'rb').read()
        if struct.unpack_from('<I', t, 80)[0] != FMT_2022:
            raise ConvertError('template is not a 2022-format file')
        o = HDR_END; docs = []
        while True:
            typ, size = _hdr(t, o, len(t))
            if typ == 1004:
                break
            docs.append(t[o:o + size]); o += size
        i = next(i for i in _iter_find(t, TAG + b'\x0a\x00') if _is_palette(t, i))
        size = struct.unpack_from('<I', t, i + 6)[0]
        return cls(t[:HDR_END], b''.join(docs), t[i:i + size])

    def to_bin(self, path):
        with open(path, 'wb') as f:
            for part in (self.header, self.docs, self.palette):
                f.write(struct.pack('<I', len(part))); f.write(part)

    @classmethod
    def from_bin(cls, path):
        b = open(path, 'rb').read(); parts = []; o = 0
        for _ in range(3):
            n = struct.unpack_from('<I', b, o)[0]; parts.append(b[o + 4:o + 4 + n]); o += 4 + n
        return cls(*parts)


# ---------------- analysis ----------------
def file_format(path):
    with open(path, 'rb') as f:
        h = f.read(96)
    if len(h) < 92 or not h.startswith(b'ZBrush File'):
        return None, None
    fmt = struct.unpack_from('<I', h, 80)[0]
    ver = h[84:92].split(b'\0')[0].decode('latin1', 'replace')
    return fmt, ver


def plan(d, force=False):
    """Return (edits, info). edits: list of (start, end, replacement_bytes)."""
    if len(d) < 0x60 or struct.unpack_from('<I', d, 80)[0] != FMT_2025:
        raise ConvertError('不是 ZBrush 2025 及以后版本保存的 ZTL（格式号不是 1009）')
    o = HDR_END; tops = []
    while o < len(d):
        h = _hdr(d, o, len(d))
        if not h:
            break
        tops.append((o, h[0], h[1])); o += h[1]
    if o != len(d) or not tops or tops[-1][1] != 1004 or sum(1 for t in tops if t[1] == 1004) != 1:
        raise ConvertError('文件顶层结构异常：%s' % [t[1] for t in tops])
    zs = tops[-1][0]
    edits = []; info = {'meshes': 0, 'palettes': 0, 'kinds': {}, 'unverified': [], 'zs': zs}
    for i in _iter_find(d, TAG + b'\x5c\x00', zs):
        if not _is_mesh(d, i):
            continue
        size = struct.unpack_from('<I', d, i + 6)[0]
        s, e = i + 10, i + size
        if e > len(d) or d[e - 4:e] != END:
            raise ConvertError('网格块 @%x 缺少结束标记' % i)
        f = s + 45 + 0x16C
        if d[f + 4:f + 8] != b'\x01\x00\x00\x00' or d[f:f + 4] not in (b'\0\0\0\0', b'\x01\0\0\0'):
            raise ConvertError('网格块 @%x 的 0x16C 字段不符合预期：%s' % (i, bytes(d[f:f + 8]).hex()))
        cs = _child_chain_start(d, f + 8, e)
        if cs is None:
            raise ConvertError('网格块 @%x 找不到附属数据块' % i)
        q, _ = _chain(d, cs, e)
        kinds = []; p = cs
        while p < q:
            typ, sz = _hdr(d, p, e); kinds.append(typ); p += sz
        kind = tuple(kinds)
        info['kinds'][kind] = info['kinds'].get(kind, 0) + 1
        if kind in VERIFIED_KINDS:
            drop = VERIFIED_KINDS[kind]
        else:
            info['unverified'].append((i, kind))
            if not force:
                continue
            drop = GUESS_KINDS.get(kind, 0)
        if d[q:q + drop] != b'\0' * drop:
            raise ConvertError('网格块 @%x 尾部字段非零' % i)
        edits.append((i + 4, i + 6, b'\x54\x00'))
        edits.append((s, s + 45, b''))
        edits.append((f, f + 8, b''))
        if drop:
            edits.append((q, q + drop, b''))
        info['meshes'] += 1
    if info['unverified'] and not force:
        ks = sorted({k for _, k in info['unverified']})
        raise Unverified('文件含尚未在 ZBrush 2022 中验证过的网格结构 %s（共 %d 处），为避免写出 ZBrush 无法打开的文件，已停止。'
                         % (', '.join(str(k) for k in ks), len(info['unverified'])))
    if info['meshes'] == 0:
        raise ConvertError('没有找到网格数据块')
    return edits, info


def convert(src, dst, template, force=False, progress=None):
    """Convert src (2025+ ZTL) to dst (ZBrush 2022 ZTL). Returns info dict. Never touches src."""
    if os.path.abspath(src) == os.path.abspath(dst):
        raise ConvertError('输出文件不能覆盖源文件')
    with open(src, 'rb') as fh:
        d = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            edits, info = plan(d, force)
            zs = info['zs']
            pals = []
            for i in _iter_find(d, TAG + b'\x0a\x00', zs):
                if _is_palette(d, i):
                    size = struct.unpack_from('<I', d, i + 6)[0]
                    if d[i + size - 4:i + size] != END:
                        raise ConvertError('工具面板块 @%x 缺少结束标记' % i)
                    new, _ = _merged_palette(bytes(d[i:i + size]), template.palette)
                    pals.append((i, i + size))
                    edits.append((i, i + size, new))
            info['palettes'] = len(pals)
            edits.sort()
            for a, b in zip(edits, edits[1:]):
                if a[1] > b[0]:
                    raise ConvertError('改写区域重叠 @%x/@%x' % (a[0], b[0]))
            es = [a for a, _, _ in edits]
            cum = [0]
            for (a, b, r) in edits:
                cum.append(cum[-1] + len(r) - (b - a))
            fixes = []; n_in = 0
            for (c, z) in _iter_wellformed(d, zs, len(d), pals):
                n_in += 1
                lo = bisect.bisect_left(es, c + 10)
                hi = bisect.bisect_right(es, c + z - 1)
                dl = cum[hi] - cum[lo]
                if dl:
                    fixes.append((c + 6, c + 10, struct.pack('<I', z + dl)))
            allr = sorted(edits + fixes)
            for a, b in zip(allr, allr[1:]):
                if a[1] > b[0]:
                    raise ConvertError('改写区域重叠 @%x/@%x' % (a[0], b[0]))
            tmp = dst + '.part'
            with open(tmp, 'wb') as out:
                out.write(template.header); out.write(template.docs)
                pos = zs; done = 0; total = len(d)
                for (a, b, r) in allr:
                    _copy(d, pos, a, out); out.write(r); pos = b
                    if progress and a - done > 64 << 20:
                        done = a; progress(0.8 * a / total)
                _copy(d, pos, len(d), out)
        finally:
            d.close()
    try:
        _verify(tmp, len(template.header) + len(template.docs), n_in, info)
    except Exception:
        os.remove(tmp); raise
    os.replace(tmp, dst)
    if progress:
        progress(1.0)
    return info


def _copy(d, a, b, out, step=16 << 20):
    while a < b:
        n = min(step, b - a); out.write(d[a:a + n]); a += n


def _verify(path, body_start, n_in, info):
    with open(path, 'rb') as fh:
        r = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            if struct.unpack_from('<I', r, 80)[0] != FMT_2022:
                raise ConvertError('校验失败：文件头')
            o = HDR_END
            while o < len(r):
                h = _hdr(r, o, len(r))
                if not h:
                    break
                o += h[1]
            if o != len(r):
                raise ConvertError('校验失败：顶层块未对齐到文件末尾')
            if not info['unverified'] and any(_is_mesh(r, i) for i in _iter_find(r, TAG + b'\x5c\x00', body_start)):
                raise ConvertError('校验失败：仍有 2025 格式网格块')
            pals = []
            for i in _iter_find(r, TAG + b'\x0a\x00', body_start):
                if _is_palette(r, i):
                    pals.append((i, i + struct.unpack_from('<I', r, i + 6)[0]))
            n_out = sum(1 for _ in _iter_wellformed(r, body_start, len(r), pals))
            if n_out != n_in or len(pals) != info['palettes']:
                raise ConvertError('校验失败：数据块数量 %d -> %d，面板块 %d -> %d'
                                   % (n_in, n_out, info['palettes'], len(pals)))
            info['chunks'] = n_out
        finally:
            r.close()


if __name__ == '__main__':
    import sys
    tm = Template.from_ztl(sys.argv[3]) if sys.argv[3].lower().endswith('.ztl') else Template.from_bin(sys.argv[3])
    print(convert(sys.argv[1], sys.argv[2], tm, force='--force' in sys.argv))
