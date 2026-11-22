import struct
HDR_END=0x5C
class Node:
    __slots__=('ver','typ','prefix','children','trailer','raw')
    def size(self):
        if self.children is None: return 10+len(self.raw)
        return 10+len(self.prefix)+sum(c.size() for c in self.children)+len(self.trailer)
    def bytes(self):
        out=bytearray(struct.pack('<HHHI',0x8003,self.ver,self.typ,self.size()))
        if self.children is None: out+=self.raw
        else:
            out+=self.prefix
            for c in self.children: out+=c.bytes()
            out+=self.trailer
        return bytes(out)
def _hdr(d,o,end):
    if o+10>end: return None
    tag,ver,typ,size=struct.unpack_from('<HHHI',d,o)
    if tag!=0x8003 or size<10 or o+size>end: return None
    return ver,typ,size
def _run(d,p,end):
    q=p;k=0
    while True:
        h=_hdr(d,q,end)
        if not h: return q,k
        q+=h[2];k+=1
def parse_seq(d,o,end,depth=0):
    nodes=[]
    while True:
        h=_hdr(d,o,end)
        if not h: return nodes,o
        ver,typ,size=h; s=o+10; e=o+size
        n=Node(); n.ver=ver; n.typ=typ
        best=None
        p=s
        while depth<12:
            i=d.find(b'\x03\x80',p,e-10)
            if i<0: break
            if _hdr(d,i,e):
                q,k=_run(d,i,e)
                if k>=1 and (q==e or e-q<64): best=i; break
            p=i+1
        if best is None:
            n.children=None; n.raw=d[s:e]
        else:
            n.prefix=d[s:best]
            n.children,q=parse_seq(d,best,e,depth+1)
            n.trailer=d[q:e]; n.raw=None
        nodes.append(n); o=e
def load(path):
    d=open(path,'rb').read()
    nodes,q=parse_seq(d,HDR_END,len(d))
    return d[:HDR_END],nodes,d[q:]
def dump(head,nodes,tail):
    return head+b''.join(n.bytes() for n in nodes)+tail
def walk(nodes,parents=()):
    for n in nodes:
        yield n,parents
        if n.children is not None: yield from walk(n.children,parents+(n,))
