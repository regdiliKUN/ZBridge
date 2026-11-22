import sys
def load(p): return sorted(tuple(map(float,l.split()[1:4])) for l in open(p) if l.startswith('v '))
def d(a,b):
    A,B=load(a),load(b)
    if len(A)!=len(B): return 'count %d vs %d'%(len(A),len(B))
    return max(max(abs(p[i]-q[i]) for i in range(3)) for p,q in zip(A,B))
for a,b in zip(sys.argv[1::2], sys.argv[2::2]): print(f"{a:18s} vs {b:18s}", d(a,b))
