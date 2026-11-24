#!/usr/bin/env python3
"""Rebuild exact analog-on-TSO parent, then the isolated TX queue fix."""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PARENT_SHA="4ec7bfdea01393023c0da53579c814a9c502e70f22475c7adf00eace79b023fc"
PCS_SHA="330c24eddf25e7605f63f2a8f6b5bb7783e3d6c9bebce3390b541a3ae7e4cb38"
PPE_SHA="6a3df3cd632e4a4aa14016b1d4ea2a72dc0adb191a483aa522f24be427bbe825"
CONFIG_SHA="541c909b5c40aeb38d418d0f2b1fbd1e166b2dc2ac357d420b50958df1615987"
EXPORTS_SHA="e850879b87726135c25faf20f095a640563b3e5883a67aa2708d0d0aa1ea0c81"
TARGET="drivers/net/ethernet/qualcomm/ppe/qcom-ppe.ko"
PCS_TARGET="drivers/net/pcs/pcs-qcom-ipq9574.ko"
REPO=Path(__file__).resolve().parents[4]
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
    serial_patch=patches/"0498-net-pcs-wave7-test-stock-serial-speed.patch"
    patch=patches/"0499-net-ethernet-qualcomm-edma-init-features-before-register.patch"
    tso_patch=patches/"0500-net-ethernet-qualcomm-edma-validate-tso-and-sg-limits.patch"
    analog_patch=patches/"0501-net-pcs-wave7-test-stock-analog-only.patch"
    queue_patch=patches/"0502-net-ethernet-qualcomm-edma-wake-own-tx-queue.patch"
    config=old/"linked/.config"
    exports=old/"linked/vmlinux.symvers"
    assert sha(config)==CONFIG_SHA and sha(exports)==EXPORTS_SHA
    kernel_exports=exports.read_text().splitlines()
    # Kconfig records rustc/LLVM versions even for this C-only module
    # rebuild. Reproduce the accepted NAND config independent of the
    # host's current default Rust toolchain.
    rustc=subprocess.check_output(["rustup","which","--toolchain",
        "nightly-2026-11-19","rustc"],text=True).strip()
    version=subprocess.check_output([rustc,"-vV"],text=True)
    assert "release: 1.102.0-nightly" in version and "LLVM version: 23.1.6" in version
    argv=json.loads((old/"build-argv.json").read_text())
    assert argv[0]=="make" and argv[-1]=="Image" and argv[2]=="-C"
    with tempfile.TemporaryDirectory(prefix=".edma-tx-queue-module-",dir=out.parent) as work_:
        work=Path(work_)
        k=work/"kernel"
        publish=work/"publish"
        publish.mkdir()
        run(["cp","-a","--reflink=always",str(SOURCE),str(k)])
        shutil.copyfile(config,k/".config")
        argv[3]=str(k)
        argv=argv[:-1]+["HOSTCC=sccache gcc",f"RUSTC={rustc}"]
        run(["patch","-p1","--fuzz=0","-i",str(phy_patch)],cwd=k)
        assert (k/"drivers/net/phy/qcom/qca808x.c").read_bytes()==(old/"qca808x.c").read_bytes()
        run([*argv,"olddefconfig"])
        if (k/".config").read_bytes()!=config.read_bytes():
            diff="".join(difflib.unified_diff(config.read_text().splitlines(True),
                (k/".config").read_text().splitlines(True),fromfile="accepted",tofile="regenerated"))
            (out.parent/"config-mismatch.diff").write_text(diff)
            raise RuntimeError("Regenerated config differs from accepted config; see config-mismatch.diff")
        def build(dest):
            assert shutil.disk_usage(work).free>3*1024**3
            run([*argv,PCS_TARGET,TARGET])
            assert (k/".config").read_bytes()==config.read_bytes()
            sym=(k/"Module.symvers").read_text().splitlines()
            assert sorted(l for l in sym if l.split("\t")[2]=="vmlinux")==sorted(kernel_exports)
            dest.mkdir()
            f=dest/Path(TARGET).name
            shutil.copyfile(k/TARGET,f)
            run(["env",f"CROSS={CROSS}","NO_RENAME=1",str(REPO/"scripts/strip-kmod.sh"),str(f)])
            # Resolve actual PCS module exports in the same modpost run and
            # verify the dependency is the exact module in the live parent.
            pcs=dest/Path(PCS_TARGET).name
            shutil.copyfile(k/PCS_TARGET,pcs)
            run(["env",f"CROSS={CROSS}","NO_RENAME=1",str(REPO/"scripts/strip-kmod.sh"),str(pcs)])
            assert sha(pcs)==PCS_SHA
            pcs.unlink()
            info=subprocess.check_output(["modinfo",str(f)],text=True)
            assert "intree:         Y" in info and "6.18.60 SMP mod_unload aarch64" in info
            return f,set(sym),info.splitlines()[1:]
        run(["patch","-p1","--fuzz=0","-i",str(serial_patch)],cwd=k)
        for applied in (patch,tso_patch,analog_patch):
            run(["patch","-p1","--fuzz=0","-i",str(applied)],cwd=k)
        base,before,base_info=build(work/"baseline")
        assert sha(base)==PPE_SHA
        print("EXACT_PARENT_PPE_PASS",flush=True)
        run(["patch","-p1","--fuzz=0","-i",str(queue_patch)],cwd=k)
        run([sys.executable,str(Path(__file__).with_name("test-queue.py")),str(k)])
        run([sys.executable,str(Path(__file__).with_name("test-policy.py")),str(k)])
        candidate,after,candidate_info=build(publish/"modules")
        assert before==after and base_info==candidate_info and sha(candidate)!=PPE_SHA
        report={"experiment":"edma-tx-queue","parent_image_sha256":PARENT_SHA,
                "accepted_ppe_sha256":PPE_SHA,"unchanged_pcs_sha256":PCS_SHA,
                "candidate_ppe_sha256":sha(candidate),"nand_config_sha256":sha(config),
                "kernel_exports_sha256":sha(exports),"kernel_export_count":len(kernel_exports),
                "module_exports_identical":True,"module_metadata_identical":True,
                "baseline_byte_identical":True,"patch_sha256":sha(patch),"tso_patch_sha256":sha(tso_patch),"analog_patch_sha256":sha(analog_patch),"queue_patch_sha256":sha(queue_patch),"fixture_pass":True,
                "builder_commit":subprocess.check_output(["git","-C",str(REPO),"rev-parse","HEAD"],text=True).strip()}
        (publish/"report.json").write_text(json.dumps(report,indent=2)+"\n")
        (publish/"SHA256SUMS").write_text("".join(f"{sha(f)}  {f.relative_to(publish)}\n" for f in sorted(publish.rglob("*")) if f.is_file() and f.name!="SHA256SUMS"))
        publish.rename(out)
        print("EDMA_TX_QUEUE_MODULE_BUILD_PASS",json.dumps(report),flush=True)
if __name__=="__main__":
    main()
