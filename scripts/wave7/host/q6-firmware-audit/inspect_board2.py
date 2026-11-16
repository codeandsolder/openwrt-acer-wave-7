#!/usr/bin/env python3
"""Read-only ath12k API2 board database inventory, matching core.c TLV rules."""
from pathlib import Path
import hashlib,struct,sys
board2=Path(sys.argv[1]).read_bytes()
magic=b"QCA-ATH12K-BOARD\x00"
assert board2.startswith(magic)
align=lambda n:(n+3)&~3

def ies(buf):
    off=0
    while off+8<=len(buf):
        kind,length=struct.unpack_from("<II",buf,off)
        start=off+8; end=start+length
        if end>len(buf):raise ValueError(f"truncated IE at {off:x} kind={kind} length={length}")
        yield kind,buf[start:end],off
        off=start+align(length)
    if off!=len(buf):raise ValueError(f"unparsed {len(buf)-off} bytes")

names=[]
for typ,data,pos in ies(board2[align(len(magic)):]):
    if typ!=0:
        print("NONBOARD_TOP_LEVEL",typ,len(data),hex(pos))
        continue
    name=None
    for k,buf,inner_off in ies(data):
        if k==0:
            name=buf.decode("ascii")
        elif k==1:
            if name is None: raise ValueError("board data without name")
            names.append((name,len(buf),hashlib.sha256(buf).hexdigest(),buf))
            name=None
        else:raise ValueError(f"unhandled inner type {k}")
assert len(names)>=10
print("COUNT",len(names))
for name,length,sha,data in names:
    print("NAME",name,"LENGTH",length,"SHA256",sha,"HEADER",data[:24].hex())
ref=Path(sys.argv[2]).read_bytes()
sha=hashlib.sha256(ref).hexdigest()
print("ACER_BOARD_LEN",len(ref),"SHA256",sha)
for name,length,sha,d in names:
    if name.endswith("board-id=83"):
        print("GL_BOARD_ID_83",name,"LEN",length,"BINARY_EQUALS_ACER",ref==d,"MATCHING_PREFIX_LENGTH",next((i for i,(a,b) in enumerate(zip(ref,d)) if a!=b),min(len(ref),len(d))))
