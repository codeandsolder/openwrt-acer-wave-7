#!/usr/bin/env python3
"""Reproduce the exact approved NAND baseline, build only 0494, verify ELF."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile

REPO=Path(__file__).resolve().parents[5]
PROD=Path("/home/jan/build/wave7/prod-integrated")
SOURCE=PROD/"build_dir/target-aarch64_cortex-a53_musl/linux-qualcommbe_ipq53xx/linux-6.18.60"
STAGING=PROD/"staging_dir"
ENV={**os.environ, "PATH":":".join([str(STAGING/"host/bin"),str(STAGING/"toolchain-aarch64_cortex-a53_gcc-14.4.0_musl/bin"),os.environ["PATH"]]),
     "STAGING_DIR":str(STAGING/"target-aarch64_cortex-a53_musl"),
     "SCCACHE_NO_AUTO_START_SERVER":"1","SCCACHE_START_SERVER":"0"}
OLD_SHA="927351279da9ca3fd29891d8a6a2b1e95fba5a7497a086711d09665985ca0950"
CONFIG_SHA="541c909b5c40aeb38d418d0f2b1fbd1e166b2dc2ac357d420b50958df1615987"
SYMS_SHA="e850879b87726135c25faf20f095a640563b3e5883a67aa2708d0d0aa1ea0c81"

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def run(argv, **kw):
    print(argv,flush=True)
    subprocess.run(argv,check=True,env=ENV,**kw)

def normalize(data):
    # Compare every byte except normal linker note and default initramfs
    # mtime fields. Require unique correctly formatted locations.
    out=bytearray(data)
    notes=list(re.finditer(rb"\x04\x00\x00\x00\x14\x00\x00\x00\x03\x00\x00\x00GNU\x00",data))
    assert len(notes)==1, f"unexpected GNU build-id notes: {[m.start() for m in notes]}, image size={len(data)}"
    start=notes[0].end(); out[start:start+20]=bytes(20)
    names=[]
    for m in re.finditer(rb"070701[0-9a-fA-F]{104}",data):
        h=m.group()
        size=int(h[94:102],16)
        name=data[m.end():m.end()+size]
        names.append(name)
        if name in (b"dev\0",b"dev/console\0",b"root\0"):
            out[m.start()+46:m.start()+54]=b"00000000"
    assert names==[b"dev\0",b"dev/console\0",b"root\0",b"TRAILER!!!\0"]
    return out

def tables(elf):
    # AArch64 ET_EXEC: resolve named OBJECT symbols into file offsets.
    data=elf.read_bytes()
    hdr=struct.unpack_from("<16sHHIQQQIHHHHHH",data)
    assert hdr[0][:7]==b"\x7fELF\x02\x01\x01" and hdr[2]==183
    shoff,entsize,count=hdr[6],hdr[11],hdr[12]
    sections=[struct.unpack_from("<IIQQQQIIQQ",data,shoff+i*entsize) for i in range(count)]
    syms,=[s for s in sections if s[1]==2]
    strs=sections[syms[6]]
    strings=data[strs[4]:strs[4]+strs[5]]
    result={}
    for off in range(syms[4],syms[4]+syms[5],syms[9]):
        n,info,other,ndx,value,size=struct.unpack_from("<IBBHQQ",data,off)
        name=strings[n:strings.index(b"\0",n)].decode()
        if name not in ("nss_cc_parent_data_1","nss_cc_parent_data_2",
                        "nss_cc_parent_map_1","nss_cc_parent_map_2"): continue
        assert name not in result and info&15==1
        sec=sections[ndx]
        pos=sec[4]+value-sec[3]
        assert sec[4]<=pos and pos+size<=sec[4]+sec[5]
        raw=data[pos:pos+size]
        if "_data_" in name:
            # struct clk_parent_data: three pointers, int index, padding
            assert size==6*32
            entries=list(struct.iter_unpack("<QQQi4x",raw))
            assert all(x[:3]==(0,0,0) for x in entries)
            result[name]=[x[3] for x in entries]
        else:
            assert size==12
            result[name]=list(struct.iter_unpack("<BB",raw))
    assert len(result)==4
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("accepted_build",type=Path)
    p.add_argument("output",type=Path)
    a=p.parse_args()
    old,out=a.accepted_build.resolve(),a.output.resolve()
    assert not out.exists() and out.parent.is_dir()
    assert not subprocess.check_output(["git","-C",str(REPO),"status","--porcelain"])
    assert shutil.disk_usage(out.parent).free>3*1024**3
    config=old/"linked/.config"
    exports=old/"linked/vmlinux.symvers"
    image=old/"fit/candidate.Image"
    fit=old/"fit/candidate.itb"
    assert (sha(config),sha(exports),sha(image))==(CONFIG_SHA,SYMS_SHA,OLD_SHA)
    patches=REPO/"target/linux/qualcommbe/patches-6.18"
    patch=patches/"0494-clk-qcom-nsscc-ipq5332-match-dt-rx-tx-order.patch"
    phy=patches/"0491-net-phy-qca8081-test-stock-status-poll-fifo-level.patch"
    argv=json.loads((old/"build-argv.json").read_text())
    assert argv[0]=="make" and argv[2]=="-C" and argv[-1]=="Image"
    with tempfile.TemporaryDirectory(prefix=".nsscc-kernel-",dir=out.parent) as tmp:
        work=Path(tmp)
        k=work/"kernel"
        dest=work/"publish"
        dest.mkdir()
        run(["cp","-a","--reflink=always",str(SOURCE),str(k)])
        shutil.copyfile(config,k/".config")
        argv[3]=str(k)
        argv=argv[:-1]+["HOSTCC=sccache gcc"]
        run(["patch","-p1","--fuzz=0","-i",str(phy)],cwd=k)
        assert (k/"drivers/net/phy/qcom/qca808x.c").read_bytes()==(old/"qca808x.c").read_bytes()
        run([*argv,"olddefconfig"])
        def verify():
            assert sha(k/".config")==CONFIG_SHA
            assert sha(k/"vmlinux.symvers")==SYMS_SHA
        check=Path(__file__).with_name("check-parent-order.py")
        run([sys.executable,str(check),str(k),str(fit),"--expect","swapped"])
        run([*argv,"Image"])
        verify()
        raw=k/"arch/arm64/boot/Image"
        rebuilt, expected=raw.read_bytes(),image.read_bytes()
        diffs=[i for i,(a,b) in enumerate(zip(rebuilt,expected)) if a!=b] if len(rebuilt)==len(expected) else []
        print("BASELINE_DIFF",len(rebuilt),len(expected),len(diffs),[hex(i) for i in diffs[:80]],flush=True)
        assert normalize(rebuilt)==normalize(expected),"baseline payload differs"
        before=tables(k/"vmlinux")
        assert before==tables(old/"linked/vmlinux")
        assert before["nss_cc_parent_data_1"]==[7,2,4,3,1,0]
        assert before["nss_cc_parent_data_2"]==[7,2,6,5,1,0]
        print("EXACT_BASELINE_NORMALIZED_PASS",before,flush=True)
        assert shutil.disk_usage(work).free>3*1024**3
        run(["patch","-p1","--fuzz=0","-i",str(patch)],cwd=k)
        run([sys.executable,str(check),str(k),str(fit),"--expect","correct"])
        run([*argv,"Image"])
        verify()
        after=tables(k/"vmlinux")
        assert after["nss_cc_parent_data_1"]==[7,2,3,4,1,0]
        assert after["nss_cc_parent_data_2"]==[7,2,5,6,1,0]
        for n in ("nss_cc_parent_map_1","nss_cc_parent_map_2"):
            assert after[n]==before[n]
        assert normalize(raw.read_bytes())!=normalize(image.read_bytes())
        shutil.copyfile(raw,dest/"candidate.Image")
        # Keep proof of the changed compiled tables, not the entire ELF.
        report={"baseline_raw_sha256":OLD_SHA,"baseline_normalized":True,
                "candidate_raw_sha256":sha(raw),"config_sha256":CONFIG_SHA,
                "exports_sha256":SYMS_SHA,"patch_sha256":sha(patch),
                "before":before,"after":after,
                "builder_commit":subprocess.check_output(["git","-C",str(REPO),"rev-parse","HEAD"],text=True).strip()}
        (dest/"report.json").write_text(json.dumps(report,indent=2)+"\n")
        (dest/"SHA256SUMS").write_text("".join(f"{sha(f)}  {f.name}\n" for f in sorted(dest.iterdir())))
        dest.rename(out)
        print("NSSCC_KERNEL_BUILD_PASS",json.dumps(report),flush=True)
if __name__=="__main__":
    if not __debug__: raise RuntimeError("assertions required")
    main()
