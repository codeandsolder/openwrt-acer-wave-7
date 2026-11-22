#!/usr/bin/env python3
"""Reproduce 0491/0495/0496, then build the 0497 NAND kernel and PCS module."""
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
    p.add_argument("instant_build",type=Path)
    p.add_argument("worker_build",type=Path)
    p.add_argument("output",type=Path)
    a=p.parse_args()
    old,out=a.accepted_build.resolve(),a.output.resolve()
    assert not out.exists() and out.parent.is_dir()
    instant=a.instant_build.resolve()/"candidate.Image"
    instant_sha="df864a78bf864f56e609320c3c8f08fbbd6fecef3722a5d6fbae2bce7f747eef"
    assert sha(instant)==instant_sha
    worker_image=a.worker_build.resolve()/"candidate.Image"
    worker_sha="5489c8ce35ec79a551c58054fd50e691682751893612ed4682c007f56f16d09c"
    assert sha(worker_image)==worker_sha
    pcs_sha="74bd3fddd9e35f543100073a4f7a85ebfe7aca503e5c48191dd3c2ee8190b473"
    pcs_target="drivers/net/pcs/pcs-qcom-ipq9574.ko"
    assert not subprocess.check_output(["git","-C",str(REPO),"status","--porcelain"])
    assert shutil.disk_usage(out.parent).free>3*1024**3
    config=old/"linked/.config"
    exports=old/"linked/vmlinux.symvers"
    image=old/"fit/candidate.Image"
    assert (sha(config),sha(exports),sha(image))==(CONFIG_SHA,SYMS_SHA,OLD_SHA)
    patches=REPO/"target/linux/qualcommbe/patches-6.18"
    patch=patches/"0495-net-phy-qca8081-test-instantaneous-fifo-link.patch"
    worker=patches/"0496-net-phy-qca8081-test-independent-fifo-poll.patch"
    down=patches/"0497-net-phy-pcs-wave7-test-warm-down-mode-prepare.patch"
    phy=patches/"0491-net-phy-qca8081-test-stock-status-poll-fifo-level.patch"
    argv=json.loads((old/"build-argv.json").read_text())
    assert argv[0]=="make" and argv[2]=="-C" and argv[-1]=="Image"
    with tempfile.TemporaryDirectory(prefix=".down-mode-kernel-",dir=out.parent) as tmp:
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

        run([*argv,"Image"])
        verify()
        # Kbuild's generic Image rule retains .notes; OpenWrt NAND
        # packaging explicitly removes it, along with these sections.
        raw=work/"nand.Image"
        def nand_image():
            run(["aarch64-openwrt-linux-musl-objcopy","-O","binary",
                 "-R",".reginfo","-R",".notes","-R",".note","-R",".comment",
                 "-R",".mdebug","-R",".note.gnu.build-id","-S",str(k/"vmlinux"),str(raw)])
        nand_image()
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
        run([sys.executable,str(Path(__file__).parents[1]/"test-instant-fifo.py"),str(k)])
        run([*argv,"Image"])
        verify()
        nand_image()
        assert normalize(raw.read_bytes())==normalize(instant.read_bytes()), "0495 baseline differs"
        print("EXACT_0495_NORMALIZED_PASS",flush=True)
        run(["patch","-p1","--fuzz=0","-i",str(worker)],cwd=k)
        run([sys.executable,str(Path(__file__).parents[1]/"test-independent-fifo.py"),str(k)])
        run([*argv,"Image"])
        verify()
        nand_image()
        after=tables(k/"vmlinux")
        assert after==before, "unrelated NSSCC tables changed"
        assert b"wave7-diag: fifo-instant ss=%04x phylib=%u copper=%u" in (k/"vmlinux").read_bytes()
        assert b"wave7-diag: fifo-instant" not in (old/"linked/vmlinux").read_bytes()
        assert b"wave7-diag: fifo-worker tick=%u edge=%u ss=%d phylib=%u result=%d" in (k/"vmlinux").read_bytes()
        assert b"wave7-diag: fifo-worker" not in instant.read_bytes()
        assert normalize(raw.read_bytes())==normalize(worker_image.read_bytes()), "0496 baseline differs"
        print("EXACT_0496_NORMALIZED_PASS",flush=True)
        def build_pcs(path):
            run([*argv,pcs_target])
            verify()
            shutil.copyfile(k/pcs_target,path)
            run(["env","CROSS=aarch64-openwrt-linux-musl-","NO_RENAME=1",
                 str(REPO/"scripts/strip-kmod.sh"),str(path)])
            return set((k/"Module.symvers").read_text().splitlines())
        base_module=work/"baseline-pcs.ko"
        base_symbols=build_pcs(base_module)
        assert sha(base_module)==pcs_sha, "0496 PCS baseline differs"
        assert sorted(l for l in base_symbols if l.split("\t")[2]=="vmlinux")==sorted(exports.read_text().splitlines())
        print("EXACT_0496_PCS_PASS",flush=True)
        run(["patch","-p1","--fuzz=0","-i",str(down)],cwd=k)
        run([sys.executable,str(Path(__file__).with_name("test-policy.py")),str(k)])
        run([*argv,"Image"])
        verify()
        nand_image()
        assert tables(k/"vmlinux")==before
        assert normalize(raw.read_bytes())!=normalize(worker_image.read_bytes())
        kernel=(k/"vmlinux").read_bytes()
        for marker in (b"wave7-diag: down-mode PHY",b"wave7-diag: down-mode host prepare",b"wave7-diag: down-mode host result"):
            assert marker in kernel and marker not in worker_image.read_bytes()
        candidate=dest/"pcs-qcom-ipq9574.ko"
        assert build_pcs(candidate)==base_symbols
        assert sha(candidate)!=pcs_sha
        for marker in (b"wave7-diag: down-mode PCS prepared",b"wave7-diag: down-mode PCS reuse"):
            assert marker in candidate.read_bytes() and marker not in base_module.read_bytes()
        def modinfo(f):
            return subprocess.check_output(["modinfo",str(f)],text=True).splitlines()[1:]
        assert modinfo(candidate)==modinfo(base_module)
        shutil.copyfile(raw,dest/"candidate.Image")
        # Keep proof of the isolated PHY experiment, not the entire ELF.
        report={"baseline_raw_sha256":OLD_SHA,"baseline_normalized":True,
                "candidate_raw_sha256":sha(raw),"config_sha256":CONFIG_SHA,
                "exports_sha256":SYMS_SHA,"patch_sha256":sha(patch),
                "before":before,"after":after,"instant_fifo_fixture_pass":True,
                "instant_baseline_sha256":instant_sha,"instant_baseline_normalized":True,
                "worker_patch_sha256":sha(worker),"worker_fixture_pass":True,
                "worker_baseline_sha256":worker_sha,"worker_baseline_normalized":True,
                "down_mode_patch_sha256":sha(down),"down_mode_fixture_pass":True,
                "pcs_baseline_sha256":pcs_sha,"pcs_baseline_byte_identical":True,
                "pcs_candidate_sha256":sha(candidate),"pcs_module_metadata_identical":True,
                "kernel_and_module_exports_identical":True,
                "builder_commit":subprocess.check_output(["git","-C",str(REPO),"rev-parse","HEAD"],text=True).strip()}
        (dest/"report.json").write_text(json.dumps(report,indent=2)+"\n")
        (dest/"SHA256SUMS").write_text("".join(f"{sha(f)}  {f.name}\n" for f in sorted(dest.iterdir())))
        dest.rename(out)
        print("DOWN_MODE_KERNEL_AND_PCS_BUILD_PASS",json.dumps(report),flush=True)
if __name__=="__main__":
    if not __debug__: raise RuntimeError("assertions required")
    main()
