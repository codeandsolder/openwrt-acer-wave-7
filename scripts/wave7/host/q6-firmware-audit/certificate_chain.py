#!/usr/bin/env python3
"""Find complete DER X.509 certificates embedded in Qualcomm signed split B01s."""
import subprocess,sys,re
from pathlib import Path

def certs(path):
    b=path.read_bytes()
    found={}
    for i in range(len(b)-4):
        if b[i:i+2]!=b"\x30\x82": continue
        n=int.from_bytes(b[i+2:i+4],"big")+4
        if n<500 or i+n>len(b):continue
        blob=b[i:i+n]
        p=subprocess.run(["openssl","x509","-inform","DER","-noout","-subject","-issuer",
                          "-fingerprint","-sha256","-dates"],input=blob,stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL)
        if p.returncode==0:
            x=p.stdout.decode()
            fingerprint=re.search(r"sha256 Fingerprint=([A-F0-9:]+)",x,re.I)
            if fingerprint:
                found[fingerprint.group(1)]=(i,n,x.strip())
    return found
for f in map(Path,sys.argv[1:]):
    print(f"\n== {f} ==")
    result=certs(f)
    print("CERTIFICATES",len(result))
    for sha,(offset,n,info) in result.items():
        print("OFFSET",offset,"SIZE",n,"SHA256_FINGERPRINT",sha)
        print(info)
