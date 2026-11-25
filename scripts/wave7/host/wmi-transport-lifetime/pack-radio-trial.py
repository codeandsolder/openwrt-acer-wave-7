#!/usr/bin/env python3
"""Pack a firmware+radio-module trial on the exact EDMA guard8 parent.

The donor SquashFS is pinned to the vendor FIT payload extracted and audited
from the Netgear WBE700Y 13.0.0.26 distribution. Preserve Acer BDF/caldata,
all unrelated modules, policy and FIT; independently verify packed contents.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "q6-firmware-audit"))
from audit import IMAGES, inspect_family
from signing_gate import assess
from build_candidate import read_manifest, verify_special_nodes

PARENT_SHA = "e1a45ba053cd69edd2091eb4421f7af936554ed4e5f1ff3d8accbe467eed7c00"
PARENT_REV = "r0+38346-7898745869-ap-dhcp-guard8"
FIT_SHA = "c289598628e75f7a603ec127dbb5cbd1fdcf6128ba15cea6c4fe9b0aa0232b8e"
DONOR_SHA = "a637d798fc39dc5834da65b23c29aaa97f82d9e5b29fcccd05c977f2c44e3bf9"
FW_VERSION = "WLAN.WBE.1.4-01734-QCAHKSWPL_SILICONZ-1.162738.2.173996.1"
MODULES = {
    "ath12k.ko": (
        "16e9003a442e518d1dc22b40094e77c1f23bd7e7dfa204b53dc8b105f99265e9",
        "1d0190e985c7b14d22dfff5345efc63a342a06b3e39f7aa038615b52a4daf5b8"),
    "ath12k_wifi7.ko": (
        "aab8385e320f61701241d605182dc72069d7051a061cf9be144b1da6fcf038bd",
        "29cfd2fc2c4110baf17a79d643459026637d2e414c9f64473d7389344165c7e3"),
}
WMI_COMMIT = "d86c0f1c3adce6b55fef3dad229bbb7028554e80"
PRIMARY_COMMIT = "2819d40df8efedf4a740ad4ef4b0025d0fa20925"
IDENTITIES = ("etc/openwrt_version", "etc/openwrt_release", "usr/lib/os-release", "etc/banner",
              "etc/wave7-role-profile")
STEMS = (
    ("", "q6_fw0", "IPQ5332"), ("", "q6_fw1", "IPQ5332"),
    ("", "iu_fw", "IPQ5332"), ("", "q6_fw2", "IPQ5332"),
    ("", "q6_fw2", "QCN6432"), ("qcn6432", "iu_fw", "QCN6432"),
)
RADIO = Path("lib/firmware/ath12k")
MODDIR = Path("lib/modules/6.18.60")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(condition, detail):
    if not condition:
        raise RuntimeError(detail)


def cmd(*args, **kw):
    proc = subprocess.run([str(a) for a in args], text=True, capture_output=True, **kw)
    check(proc.returncode == 0, f"{args[0]}: {proc.returncode}: {proc.stdout[-3000:]} {proc.stderr[-3000:]}")
    return proc.stdout


def stage_donor(root, donor):
    permitted = set()
    for folder, stem, soc in STEMS:
        dest = root / RADIO / soc / "hw1.0"
        src = donor / folder
        pattern = re.compile(re.escape(stem) + r"\.(mdt|mbn|b[0-9]{2})$")
        old = {f.name: f for f in dest.iterdir() if pattern.fullmatch(f.name)}
        new = {f.name: f for f in src.iterdir() if pattern.fullmatch(f.name) and f.suffix != ".mbn"}
        check(f"{stem}.mdt" in new and f"{stem}.mdt" in old, f"missing MDT for {stem}")
        if f"{stem}.mbn" in old:
            new[f"{stem}.mbn"] = new[f"{stem}.mdt"]
        # This particular candidate has exactly the same file inventory as parent.
        check(old.keys() == new.keys(), f"unexpected firmware file set change {soc}/{stem}")
        for name, origin in new.items():
            target = old[name]
            check(target.is_file() and not target.is_symlink(), f"invalid target {target}")
            target.write_bytes(origin.read_bytes())
            permitted.add(target.relative_to(root).as_posix())
    return permitted


def modes(listing):
    result = {}
    for line in listing.splitlines():
        m = re.search(r" squashfs-root(?:/|$)", line)
        if m:
            path = line[m.start()+1:].split(" -> ",1)[0]
            result[path] = tuple(line.split()[:2])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--modules", type=Path, required=True)
    parser.add_argument("--baseline-modules", type=Path, required=True)
    parser.add_argument("--donor-squashfs", type=Path, required=True)
    parser.add_argument("--host-tree", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    a = parser.parse_args()
    repo = Path(__file__).resolve().parents[4]
    builder = cmd("git","-C",repo,"rev-parse","HEAD").strip()
    check(not cmd("git","-C",repo,"status","--porcelain").strip(), "dirty builder")
    cmd("git","-C",repo,"merge-base","--is-ancestor",WMI_COMMIT,builder)
    cmd("git","-C",repo,"merge-base","--is-ancestor",PRIMARY_COMMIT,builder)
    check(sha(a.parent) == PARENT_SHA, "parent hash mismatch")
    for name, (before, after) in MODULES.items():
        check(sha(a.modules/name) == after, f"unexpected candidate module {name}")
        check(sha(a.baseline_modules/name.replace(".ko","-final.ko")) == before,
              f"baseline reproduction mismatch {name}")
    if a.donor_squashfs:
        check(sha(a.donor_squashfs) == DONOR_SHA, "unverified donor payload")
    rev = "r0+38346-" + builder[:10] + "-ap-dhcp-guard8"
    tools = a.host_tree / "staging_dir/host/bin"
    unsq, mksq, fwtool = (tools / s for s in ("unsquashfs4","mksquashfs4","fwtool"))
    check(a.out.parent.is_dir() and not a.out.exists(), "output exists or parent missing")
    with tempfile.TemporaryDirectory(prefix=".radio-trial-",dir=a.out.parent) as td:
        t = Path(td)
        with tarfile.open(a.parent) as tf:
            check(tf.extractfile("sysupgrade-acer_wave7/CONTROL").read()==b"BOARD=acer_wave7\n","parent board")
            for name in ("kernel","root"):
                (t/name).write_bytes(tf.extractfile("sysupgrade-acer_wave7/"+name).read())
        check(sha(t/"kernel")==FIT_SHA,"parent FIT")
        cmd(fwtool,"-i",t/"metadata.json",a.parent)
        meta = json.loads((t/"metadata.json").read_text())
        check(meta["version"]["revision"] == PARENT_REV and "acer,wave7" in meta["supported_devices"],"parent metadata")
        verify_special_nodes(unsq,t/"root")
        old_modes = modes(cmd(unsq,"-ll",t/"root"))
        (t/"exclude").write_text("dev/console\n")
        root=t/"stage"
        old_umask=os.umask(0)
        try:
            check("created 0 devices" in cmd(unsq,"-no-progress","-d",root,"-exclude-file",t/"exclude",t/"root"),"parent extract")
        finally:
            os.umask(old_umask)
        original=read_manifest(root)
        for manifest in ("firmware.sha256","diagnostic-firmware.sha256"):
            (t/manifest).write_text(cmd("git","-C",repo,"show","HEAD:scripts/wave7/"+manifest))
            cmd("sha256sum","-c","--status",t/manifest,cwd=root/RADIO)
        allow=set(IDENTITIES)
        # 15_odhcpd commits these missing defaults on a fresh overlay.
        # Supply them in ROM so the existing exact policy gate remains valid.
        dhcp = root / "etc/config/dhcp"
        old = dhcp.read_text()
        anchor = "config odhcpd 'odhcpd'\n  option maindhcp '0'\n"
        check(old.count(anchor) == 1, "unexpected odhcpd profile")
        check("option piodir" not in old and "option hostsdir" not in old,
              "unexpected preexisting odhcpd migration defaults")
        dhcp.write_text(old.replace(anchor, anchor +
            "  option piodir '/tmp/odhcpd-piodir'\n"
            "  option hostsdir '/tmp/hosts'\n"))
        allow.add("etc/config/dhcp")
        for name,(before,after) in MODULES.items():
            p=root/MODDIR/name
            check(sha(p)==before,f"parent module {name}")
            p.write_bytes((a.modules/name).read_bytes())
            allow.add(p.relative_to(root).as_posix())
        old_family=inspect_family(root/RADIO,IMAGES,(0x4a900000,0x4ca00000))
        signing=None
        if a.donor_squashfs:
            donor=t/"donor"
            cmd(unsq,"-no-progress","-d",donor,a.donor_squashfs)
            signing=assess(root/RADIO/"IPQ5332/hw1.0/q6_fw0.b01",donor/"q6_fw0.b01")
            check(signing["root_fingerprint_equal"] and signing["intermediate_fingerprint_equal"],"donor signing chain")
            allow |= stage_donor(root,donor)
        family=inspect_family(root/RADIO,IMAGES,(0x4a900000,0x4ca00000))
        check(family["userpd_release"]==(FW_VERSION if a.donor_squashfs else old_family["userpd_release"]),"firmware release mismatch")
        for p in (root/RADIO/"IPQ5332/hw1.0").glob("q6_fw2.*"):
            if p.suffix != ".mbn":
                check(p.read_bytes()==(root/RADIO/"QCN6432/hw1.0"/p.name).read_bytes(),"PD2 alias")
        for rel in IDENTITIES[:4]:
            p=root/rel
            old=p.read_text()
            check(PARENT_REV in old,f"missing parent rev in {rel}")
            p.write_text(old.replace(PARENT_REV,rev))
        profile=root/IDENTITIES[4]
        text=profile.read_text()
        for key,value in {"source_revision":PARENT_REV,"revision":rev,"builder_commit":builder,
                          "base_image_sha256":PARENT_SHA}.items():
            text,n=re.subn(r"(?m)^"+key+r"=.*$",key+"="+value,text)
            check(n==1,f"manifest field {key}")
        fields={"trial_ath12k_sha256":MODULES["ath12k.ko"][1],
                "trial_ath12k_wifi7_sha256":MODULES["ath12k_wifi7.ko"][1],
                "trial_wmi_transport_commit":WMI_COMMIT,
                "trial_primary_umac_commit":PRIMARY_COMMIT,
                "trial_radio_release":family["userpd_release"]}
        if a.donor_squashfs: fields["trial_radio_donor_sha256"]=DONOR_SHA
        for key,value in fields.items():
            check(not re.search(r"(?m)^"+key+"=",text),f"duplicate {key}")
            text+=f"{key}={value}\n"
        profile.write_text(text)
        cmd("sh","-c",'. "$1"; wave7_ap_check_image "$2"',"sh",root/"lib/wave7/overlay-reset.sh",root)
        current=read_manifest(root)
        delta=sorted(k for k in original.keys()|current.keys() if original.get(k)!=current.get(k))
        check(set(delta)<=allow and set(IDENTITIES)<=set(delta),"unexpected root delta: "+str(set(delta)-allow))
        check(original.keys()==current.keys(),"root inventory changed")
        check(all(original[k][0]==current[k][0] and original[k][2]==current[k][2] for k in original),"root types/modes changed")
        cmd(mksq,root,t/"new.sq","-nopad","-noappend","-root-owned","-comp","xz","-Xpreset","9","-Xe","-Xlc","0","-Xlp","2","-Xpb","2","-b","256k","-p","/dev d 755 0 0","-p","/dev/console c 600 0 0 5 1","-no-xattrs","-block-readers","4","-small-readers","4")
        check((t/"new.sq").stat().st_size<=29204480,"rootfs limit")
        verify_special_nodes(unsq,t/"new.sq")
        check(modes(cmd(unsq,"-ll",t/"new.sq"))==old_modes,"archive owner/mode mismatch")
        old_umask=os.umask(0)
        try:
            cmd(unsq,"-no-progress","-d",t/"roundtrip","-exclude-file",t/"exclude",t/"new.sq")
        finally:
            os.umask(old_umask)
        check(read_manifest(t/"roundtrip")==current,"rootfs roundtrip mismatch")
        radio_manifest={p.relative_to(root/RADIO).as_posix():sha(p) for p in sorted((root/RADIO).rglob("*")) if p.is_file()}
        output=t/"image.bin"
        env=os.environ.copy()
        env["TOPDIR"]=str(a.host_tree)
        env["SOURCE_DATE_EPOCH"]=cmd("git","-C",repo,"show","-s","--format=%ct",builder).strip()
        cmd("sh",a.host_tree/"scripts/sysupgrade-tar.sh","--board","acer_wave7","--kernel",t/"kernel","--rootfs",t/"new.sq",output,env=env)
        meta["version"]["revision"]=rev
        meta.update({"wave7_parent_image_sha256":PARENT_SHA,"wave7_trial_radio":fields})
        (t/"new-meta").write_text(json.dumps(meta))
        cmd(fwtool,"-I",t/"new-meta",output)
        cmd(fwtool,"-i",t/"check-meta",output)
        check(json.loads((t/"check-meta").read_text())==meta,"metadata mismatch")
        with tarfile.open(output) as tf:
            check(tf.extractfile("sysupgrade-acer_wave7/CONTROL").read()==b"BOARD=acer_wave7\n","candidate board")
            check(tf.extractfile("sysupgrade-acer_wave7/kernel").read()==(t/"kernel").read_bytes(),"candidate FIT")
            check(tf.extractfile("sysupgrade-acer_wave7/root").read().startswith((t/"new.sq").read_bytes()),"candidate root")
        check(output.stat().st_size<30000000,"image too large")
        report={"status":"OFFLINE_VERIFIED","revision":rev,"builder_commit":builder,
                "parent_sha256":PARENT_SHA,"image_sha256":sha(output),"fit_sha256":FIT_SHA,
                "radio_release":family["userpd_release"],"signing":signing,
                "firmware":radio_manifest,"module_sha256":{k:v[1] for k,v in MODULES.items()},
                "delta":delta,"roundtrip_identical":True}
        a.out.mkdir(mode=0o700)
        filename="wave7-"+"netgear-primary-control-port"+"-dhcp-guard8-sysupgrade.bin"
        shutil.move(output,a.out/filename)
        (a.out/"report.json").write_text(json.dumps(report,indent=2)+"\n")
        (a.out/"radio.sha256").write_text("".join(f"{v}  {k}\n" for k,v in radio_manifest.items()))
        (a.out/"SHA256SUMS").write_text("".join(f"{sha(a.out/f)}  {f}\n" for f in (filename,"report.json","radio.sha256")))
        print(json.dumps({k:v for k,v in report.items() if k not in ("firmware","signing")},indent=2))


if __name__=="__main__":
    main()
