#!/usr/bin/env python3
"""Reproduce the exact approved 0491 modules, then build only patch0492.

The prepared production tree is never modified. Uses the existing managed
OpenWrt cross-GCC sccache wrapper, exact accepted NAND config and Kbuild
argv; only a private reflink clone and temporary files are used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PARENT_SHA="3ad42acf6fd9765dc9f92f937e5472bb2e19987d92896ce3e8994810e22badd9"
MODULE_SHA={
    "pcs-qcom-ipq9574.ko":"74bd3fddd9e35f543100073a4f7a85ebfe7aca503e5c48191dd3c2ee8190b473",
    "qcom-ppe.ko":"1ff7a7d590f7ef45bdaf794a3e5dfeb66ffe9a0f9eed24cf4dd8df5a7c0b5fc0",
}
ADDED={"ipq_pcs_wave7_relink_invalidate","ipq_pcs_wave7_relink_enable",
       "ipq_pcs_wave7_mac_prepare","ipq_pcs_wave7_mac_finish"}
TARGETS=["drivers/net/pcs/pcs-qcom-ipq9574.ko","drivers/net/ethernet/qualcomm/ppe/qcom-ppe.ko"]
REPO=Path(__file__).resolve().parents[5]
PROD=Path("/home/jan/build/wave7/prod-integrated")
SOURCE=PROD/"build_dir/target-aarch64_cortex-a53_musl/linux-qualcommbe_ipq53xx/linux-6.18.60"
STAGING=PROD/"staging_dir"
CROSS="aarch64-openwrt-linux-musl-"
ENV={**os.environ,"PATH":":".join([str(STAGING/"host/bin"),str(STAGING/"toolchain-aarch64_cortex-a53_gcc-14.4.0_musl/bin"),os.environ["PATH"]]),
     "STAGING_DIR":str(STAGING/"target-aarch64_cortex-a53_musl"),"SCCACHE_NO_AUTO_START_SERVER":"1","SCCACHE_START_SERVER":"0"}

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def run(a,**kw):
    print(a,flush=True)
    subprocess.run(a,check=True,env=ENV,**kw)

def main():
    if not __debug__:
        raise RuntimeError("assertions required")
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("parent",type=Path)
    p.add_argument("accepted_build",type=Path)
    p.add_argument("output",type=Path)
    a=p.parse_args()
    old=a.accepted_build.resolve()
    out=a.output.resolve()
    assert not out.exists() and out.parent.is_dir()
    assert sha(a.parent)==PARENT_SHA
    assert not subprocess.check_output(["git","-C",str(REPO),"status","--porcelain"])
    assert shutil.disk_usage(out.parent).free>3*1024**3
    patches=REPO/"target/linux/qualcommbe/patches-6.18"
    phy_patch=patches/"0491-net-phy-qca8081-test-stock-status-poll-fifo-level.patch"
    patch=patches/"0492-net-pcs-qcom-ipq9574-test-stock-warm-sgmii-preservation.patch"
    config=old/"linked/.config"
    kernel_exports=(old/"linked/vmlinux.symvers").read_text().splitlines()
    argv=json.loads((old/"build-argv.json").read_text())
    assert argv[0]=="make" and argv[-1]=="Image" and argv[2]=="-C"
    with tempfile.TemporaryDirectory(prefix=".relink-module-",dir=out.parent) as work_:
        work=Path(work_)
        k=work/"kernel"
        publish=work/"publish"
        publish.mkdir()
        run(["cp","-a","--reflink=always",str(SOURCE),str(k)])
        shutil.copyfile(config,k/".config")
        argv[3]=str(k)
        argv=argv[:-1]+["HOSTCC=sccache gcc"]
        run(["patch","-p1","--fuzz=0","-i",str(phy_patch)],cwd=k)
        assert (k/"drivers/net/phy/qcom/qca808x.c").read_bytes()==(old/"qca808x.c").read_bytes()
        run([*argv,"olddefconfig"])
        assert (k/".config").read_bytes()==config.read_bytes()
        def build(dest):
            assert shutil.disk_usage(work).free>3*1024**3
            run([*argv,*TARGETS])
            assert (k/".config").read_bytes()==config.read_bytes()
            sym=(k/"Module.symvers").read_text().splitlines()
            assert sorted(l for l in sym if l.split("\t")[2]=="vmlinux")==sorted(kernel_exports)
            dest.mkdir()
            shutil.copyfile(k/"Module.symvers",dest/"Module.symvers")
            for t in TARGETS:
                f=dest/Path(t).name
                shutil.copyfile(k/t,f)
                run(["env",f"CROSS={CROSS}","NO_RENAME=1",str(REPO/"scripts/strip-kmod.sh"),str(f)])
                info=subprocess.check_output(["modinfo",str(f)],text=True)
                assert "intree:         Y" in info and "6.18.60 SMP mod_unload aarch64" in info
            return set(sym)
        base=work/"baseline"
        before=build(base)
        assert {n:sha(base/n) for n in MODULE_SHA}==MODULE_SHA
        run(["patch","-p1","--fuzz=0","-i",str(patch)],cwd=k)
        run([sys.executable,str(Path(__file__).with_name("test-policy.py")),str(k)])
        candidate=publish/"modules"
        after=build(candidate)
        assert before<=after
        assert {l.split("\t")[1] for l in after-before}==ADDED
        for n in MODULE_SHA:
            def info(f):
                return subprocess.check_output(["modinfo",str(f)],text=True).splitlines()[1:]
            assert info(base/n)==info(candidate/n)
        report={"parent_image_sha256":PARENT_SHA,"accepted_module_sha256":MODULE_SHA,
                "candidate_module_sha256":{n:sha(candidate/n) for n in MODULE_SHA},
                "nand_config_sha256":sha(config),"kernel_exports_sha256":sha(old/"linked/vmlinux.symvers"),
                "kernel_export_count":len(kernel_exports),"additional_exports":sorted(ADDED),
                "baseline_byte_identical":True,"patch_sha256":sha(patch),
                "builder_commit":subprocess.check_output(["git","-C",str(REPO),"rev-parse","HEAD"],text=True).strip()}
        (publish/"report.json").write_text(json.dumps(report,indent=2)+"\n")
        (publish/"SHA256SUMS").write_text("".join(f"{sha(f)}  {f.relative_to(publish)}\n" for f in sorted(publish.rglob("*")) if f.is_file() and f.name!="SHA256SUMS"))
        publish.rename(out)
        print("IN_TREE_MODULE_BUILD_PASS",json.dumps(report),flush=True)
if __name__=="__main__":
    main()
