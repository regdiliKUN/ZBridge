# usage: genload.sh <ztl file name in stg2> <tag>
f=$1; t=$2
{ echo "[VarDef,logname,\"real_$t.log\"]"; cat common.inc; cat <<EOS
[VarDef,nst,0]
[VarDef,k,0]
[If,1,
[RoutineCall,Lg,[StrMerge,"ZBrush ",[ZBrushInfo,0]]]
[IPress,Tool:Sphere3D]
[FileNameSetNext,[StrMerge,lgDir,"$f"]]
[IPress,Tool:Load Tool]
[VarSet,nst,[SubToolGetCount]]
[RoutineCall,Lg,[StrMerge,"LOADED subtools=",nst," title=",[IGetTitle,Tool:Item Info]]]
[Loop,nst,
[SubToolSelect,k]
[RoutineCall,St,[StrMerge,"SUB ",k," ",[IGetTitle,Tool:Item Info]]]
[VarSet,k,k+1]
,k2]
[RoutineCall,Lg,"DONE"]
]
EOS
} > real_$t.txt
