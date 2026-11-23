# usage: python slots.py <dir containing ztl2022.py> <list of .ztl paths> <84|92>
# Prints, per attachment kind, how many zero flag bytes precede it and follow it.
import sys,struct,collections,mmap; sys.path.insert(0,sys.argv[1]); import ztl2022 as zconv
files=[l.strip() for l in open(sys.argv[2],encoding='utf-8') if l.strip()]
mt=int(sys.argv[3]); sig=zconv.TAG+bytes([mt,0]); C=collections.Counter(); ex={}
for p in files:
    try: fh=open(p,'rb'); d=mmap.mmap(fh.fileno(),0,access=mmap.ACCESS_READ)
    except Exception: continue
    for i in zconv._iter_find(d,sig,0x5c):
        if d[i+6:i+10]==b'\0\0\0\0': continue
        z=struct.unpack_from('<I',d,i+6)[0]; e=i+z
        if z<200 or e>len(d) or d[e-4:e]!=zconv.END: continue
        if mt==92 and not zconv._is_mesh(d,i): continue
        if mt==84 and not (d[i+10:i+12]!=b'' ): continue
        # find last 'END END' before attachments: search for END+END+flags
        k=d.rfind(zconv.END+zconv.END, i, e-8)
        # walk back to the END END that is followed only by flag bytes and chunks
        cs=zconv._child_chain_start(d,i+10+(45 if mt==92 else 0)+0x16C,e)
        if cs is None: continue
        k=d.rfind(zconv.END+zconv.END,i,cs)
        flags=bytes(d[k+8:cs])
        kinds=[]; p2=cs; q,_=zconv._chain(d,cs,e)
        while p2<q: t,s=zconv._hdr(d,p2,e); kinds.append(t); p2+=s
        tr=bytes(d[q:e-4])
        key=(tuple(kinds),len(flags),flags.count(1),len(tr),tr.count(1))
        C[key]+=1; ex.setdefault(key,p)
    d.close()
for k,v in C.most_common(): print(v,'kinds',k[0],'flags-before',k[1],'ones',k[2],'after',k[3],'ones',k[4])
