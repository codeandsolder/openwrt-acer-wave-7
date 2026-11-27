#!/usr/bin/env python3
"""Bounded, read-only trace of copper PHY C22.31 wrapper mode during a flap.

Bracket each mode read by non-latching vendor-status reads (C22.17).
Use the independent switch route and exact boot/revision; no register
writes or clear-on-read counter reads. An observation is not an atomic
hardware snapshot; report timing/invalid-read coverage explicitly.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.dont_write_bytecode = True
# Existing observers own exact profile identities, paths and route checks.
import importlib.util
spec = importlib.util.spec_from_file_location("probe", Path(__file__).with_name("probe-phy-reconnect.py"))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
trunk = probe.trunk
HELPER_SHA = 'bd8436acbc628b8e6fd4dc965d3916f007cfe40755d570d67a75fe23d0270262'
REMOTE = r'''set -eu
echo "boot=$(cat /proc/sys/kernel/random/boot_id)"
echo "revision=$(cat /etc/openwrt_version)"
echo "peer=${SSH_CONNECTION%% *}"
echo "bootfail=$(fw_printenv -n bootfail)"
echo "switch_carrier=$(cat /sys/class/net/lan1/carrier)"
test "$(cat /sys/class/net/lan1/carrier)" = 1
test "$(cat /proc/sys/kernel/random/boot_id)" = '@BOOT@'
test "$(cat /etc/openwrt_version)" = '@REV@'
test "$(fw_printenv -n bootfail)" = 0
umask 077
tmp=$(mktemp -d /tmp/wave7-mode.XXXXXX)
trap 'rm -f "$tmp/sampler"; rmdir "$tmp"' EXIT
trap 'exit 1' HUP INT TERM
cat >"$tmp/sampler"
test "$(sha256sum "$tmp/sampler" | cut -d " " -f 1)" = '@SHA@'
chmod 700 "$tmp/sampler"
"$tmp/sampler" @COUNT@
echo "end_boot=$(cat /proc/sys/kernel/random/boot_id)"
echo "end_revision=$(cat /etc/openwrt_version)"
echo "end_switch_carrier=$(cat /sys/class/net/lan1/carrier)"
echo "end_bootfail=$(fw_printenv -n bootfail)"
'''

def regval(raw):
    if not re.fullmatch(r"(?:0x)?[0-9a-fA-F]{4}", raw):
        return None
    value = int(raw, 16)
    return value if value != 0xffff else None

def parse(raw, boot, rev, count):
    fields, samples = {}, []
    for line in raw.splitlines():
        if line.startswith("sample "):
            _, a, ss0, mode, ss1, b = line.split()
            t0,t1=map(float,(a,b))
            assert math.isfinite(t0) and math.isfinite(t1) and 0<=t0<=t1
            assert not samples or samples[-1]["end"]<=t0
            s0,m,s1=map(regval,(ss0,mode,ss1))
            # The raw status word can change even with link unchanged.
            # Preserve the full words and mark non-identical brackets.
            coherent=s0 is not None and s1==s0 and m is not None and t1-t0<=.15
            samples.append(dict(start=t0,end=t1,status_before=s0,status_after=s1,
                                mode_raw=m,mode=(m>>13)&3 if m is not None else None,
                                copper=int(bool(s0&0x400)) if coherent else None,
                                coherent=coherent))
        else:
            k,v=line.split("=",1)
            assert k not in fields
            fields[k]=v
    assert fields == dict(boot=boot,revision=rev,peer=trunk.PATHS["switch"][0],
                          bootfail="0",switch_carrier="1",end_boot=boot,end_revision=rev,
                          end_switch_carrier="1",end_bootfail="0")
    assert len(samples)==count
    valid=[s for s in samples if s["coherent"]]
    assert valid
    return dict(boot=boot,revision=rev,samples=samples,valid=len(valid),
                max_gap=max(y["start"]-x["end"] for x,y in zip(samples,samples[1:])) if len(samples)>1 else None,
                transitions=transitions(valid))

def transitions(rows):
    out=[]
    for r in rows:
        key=(r["copper"],r["mode"])
        if not out or key!=(out[-1]["copper"],out[-1]["mode"]):
            out.append(r)
    return out

def correlate(result, down, up):
    """Do not make absence claims when the sampler missed an edge."""
    assert 0<=down<up
    rows=result["samples"]
    # Sample a half second either side of the real phylib edges.
    # Include the entire down interval, not only rows where carrier=0.
    lo,hi=down-.5,up+.5
    interval=[r for r in rows if r["end"]>=lo and r["start"]<=hi]
    before=[r for r in rows if r["end"]<=down and r["coherent"]]
    after=[r for r in rows if r["start"]>=up and r["coherent"]]
    valid=[r for r in interval if r["coherent"]]
    gaps=[y["start"]-x["end"] for x,y in zip(valid,valid[1:])]
    covered=bool(valid and valid[0]["start"]<=lo+.15 and valid[-1]["end"]>=hi-.15
                 and before and after and max(gaps,default=0)<=.2)
    return dict(down=down,up=up,samples=len(interval),valid=len(valid),
                covered=covered,max_valid_gap=max(gaps,default=None),
                modes=sorted({r["mode"] for r in valid}),
                down_modes=sorted({r["mode"] for r in valid if r["copper"]==0}),
                up_modes=sorted({r["mode"] for r in valid if r["copper"]==1}),
                transitions=transitions(valid))

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def capture(out,boot,profile,count):
    rev,directory=probe.PROFILES[profile]
    assert os.getuid()!=0 and trunk.BOOT.fullmatch(boot) and 100<=count<=600
    assert out.parent.resolve()==(trunk.BASE/directory/"observations").resolve()
    before=trunk.routes()
    assert all(v["valid"] for v in before.values())
    out.mkdir(mode=0o700)
    ip,dev,_=trunk.PATHS["switch"]
    helper=Path(__file__).with_name("sample-phy-mode")
    assert digest(helper)==HELPER_SHA
    argv=["ssh","-T","-i","/home/jan/.ssh/wave7-root-rsa","-o",f"BindInterface={dev}",
          "-o",f"BindAddress={ip}","-o","BatchMode=yes","-o","IdentitiesOnly=yes",
          "-o","StrictHostKeyChecking=yes","-o",f"UserKnownHostsFile={trunk.BASE/'known_hosts'}",
          "-o","ConnectTimeout=3","-o","ConnectionAttempts=1",f"root@{trunk.ROUTER}",
          REMOTE.replace("@COUNT@",str(count)).replace("@BOOT@",boot).replace("@REV@",rev).replace("@SHA@",HELPER_SHA)]
    start=time.time()
    with helper.open("rb") as stdin,(out/"raw.txt").open("x") as stdout,(out/"stderr.txt").open("x") as stderr:
        proc=subprocess.run(argv,stdin=stdin,stdout=stdout,stderr=stderr,timeout=90)
    after=trunk.routes()
    metadata=dict(start=start,end=time.time(),before=before,after=after,rc=proc.returncode,helper_sha256=HELPER_SHA,count=count)
    (out/"capture.json").write_text(json.dumps(metadata,indent=2)+"\n")
    assert proc.returncode==0 and all(v["valid"] for v in after.values())
    result=parse((out/"raw.txt").read_text(),boot,rev,count)
    (out/"parsed.json").write_text(json.dumps(result,indent=2)+"\n")
    files=("raw.txt","stderr.txt","capture.json","parsed.json")
    (out/"SHA256SUMS").write_text("".join(f"{digest(out/n)}  {n}\n" for n in files))
    print(json.dumps({k:v for k,v in result.items() if k!="samples"},indent=2))

DOWN_MODE_MARKER = re.compile(
    r"^\[\s*(\d+\.\d+)\].*wave7-diag: down-mode "
    r"(PHY C22\.31=[0-9a-f]{4} 2500base-x -> sgmii|host prepare sgmii|"
    r"PCS prepared sgmii|host result=-?\d+|PCS reuse sgmii)$"
)

def qualify_preparation(mode, edge, output):
    # Require whole observed edge window, an actual down bracket after
    # successful major config, and a matching reuse after raw copper up.
    # A marker before the first observed up is not sufficient proof.
    covered=correlate(mode,edge["down"],edge["up"])["covered"]
    events=sorted({(float(m[1]),m[2]) for raw in output
                   for line in raw.splitlines() if (m:=DOWN_MODE_MARKER.match(line))})
    events=[(t,msg) for t,msg in events if edge["down"]-1<=t<=edge["up"]+1]
    result=dict(qualified=False,events=events,reason="missing or ambiguous early preparation")
    if not covered:
        return {**result,"reason":"mode trace does not cover edge"}
    if (edge["prior_speed"],edge["post_speed"])!=("2500","1000"):
        return {**result,"reason":"not a 2500-to-1000 transition"}
    raw=[r for r in mode["samples"] if r["coherent"]]
    down=[r for r in raw if edge["down"]-1<=r["start"]<=edge["up"] and
          r["mode"]==0 and r["copper"]==0]
    if not down:
        return {**result,"reason":"no coherent SGMII copper-down bracket"}
    last_down=down[-1]["start"]
    ups=[r for r in raw if r["start"]>last_down and r["copper"]==1 and r["mode"]==0]
    if not ups:
        return {**result,"reason":"no coherent SGMII copper-up bracket"}
    # The exact log sequence is unique within this single edge.
    if len(events)!=5:
        return result
    phy,prepare,pcs,host,reuse=events
    if not (phy[1].startswith("PHY C22.31=") and
            int(phy[1].split("=")[1].split()[0],16)&0x6000==0 and
            prepare[1]=="host prepare sgmii" and pcs[1]=="PCS prepared sgmii" and
            host[1]=="host result=0" and reuse[1]=="PCS reuse sgmii"):
        return result
    if not (phy[0]<prepare[0]<pcs[0]<host[0]<last_down and
            ups[0]["end"]<=reuse[0]):
        return {**result,"reason":"completion not proven before copper-up, or reuse not proven after"}
    return dict(qualified=True,events=events,reason="early preparation and matching reuse observed",
                last_confirmed_down=last_down,first_confirmed_up=ups[0]["end"])

def compare(mode_path, traffic_path):
    for p in (mode_path,traffic_path):
        for line in (p/"SHA256SUMS").read_text().splitlines():
            sha,name=line.split()
            assert Path(name).name==name and digest(p/name)==sha
    mode=json.loads((mode_path/"parsed.json").read_text())
    report=json.loads((traffic_path/"report.json").read_text())
    rows=[json.loads(line) for line in (traffic_path/"samples.jsonl").read_text().splitlines()]
    states=[r["snapshot"]["state"] for r in rows if "state" in r["snapshot"]]
    assert states and all(s["boot"]==mode["boot"] and s["revision"]==mode["revision"] for s in states)
    assert len(report["episodes"])==1 and report["episodes"][0]["edge_source"]=="kernel_log"
    e=report["episodes"][0]
    result=correlate(mode,e["down"],e["up"])
    result.update(boot=mode["boot"],revision=mode["revision"],classification=report["classification"],
                  prior_speed=e["prior_speed"],post_speed=e["post_speed"])
    if mode["revision"]==probe.DOWN_MODE_REV:
        result["down_mode_preparation"]=qualify_preparation(
            mode,e,[r["snapshot"].get("stdout","") for r in rows])
    print(json.dumps(result,indent=2))

def selftest():
    boot="12345678-1234-1234-1234-123456789abc";rev=probe.WORKER_REV
    head=f"boot={boot}\nrevision={rev}\npeer=192.168.76.250\nbootfail=0\nswitch_carrier=1\n"
    foot=f"end_boot={boot}\nend_revision={rev}\nend_switch_carrier=1\nend_bootfail=0\n"
    raw=head
    for i in range(100):
        t=i*.05
        ss="0xbd1c" if t<1 or t>=3 else "0000"
        mode="0x8544" if t<2 else "0xa544"
        raw+=f"sample {t:.2f} {ss} {mode} {ss} {t+.01:.2f}\n"
    result=parse(raw+foot,boot,rev,100)
    assert result["valid"]==100 and len(result["transitions"])==4
    r=correlate(result,1,3)
    assert r["covered"] and r["down_modes"]==[0,1] and r["up_modes"]==[0,1]
    bad=raw.replace("sample 1.00 0000","sample 1.00 0xffff")
    assert parse(bad+foot,boot,rev,100)["valid"]==99
    assert not correlate(result,.1,3)["covered"]
    assert not correlate({**result,"samples":result["samples"][:20]+result["samples"][30:]},1,3)["covered"]
    try: parse(raw+foot.replace("end_boot="+boot,"end_boot=wrong"),boot,rev,100)
    except AssertionError: pass
    else: raise AssertionError("mixed boot accepted")
    # All markers must be fresh, ordered and uniquely aligned to the
    # raw down/up brackets; duplicate samples of dmesg are de-duplicated.
    edge=dict(down=1,up=3.2,prior_speed="2500",post_speed="1000")
    trace={**result,"samples":[{**r,"mode":0} for r in result["samples"]]}
    lines=["[ 1.000001] QCA8081 wave7-diag: down-mode PHY C22.31=8544 2500base-x -> sgmii",
           "[ 1.100001] lan wave7-diag: down-mode host prepare sgmii",
           "[ 1.200001] PCS wave7-diag: down-mode PCS prepared sgmii",
           "[ 1.300001] lan wave7-diag: down-mode host result=0",
           "[ 3.210001] PCS wave7-diag: down-mode PCS reuse sgmii"]
    log="\n".join(lines)
    assert qualify_preparation(trace,edge,[log,log])["qualified"]
    for i in range(5):
        assert not qualify_preparation(trace,edge,["\n".join(lines[:i]+lines[i+1:])])["qualified"]
    assert not qualify_preparation(trace,edge,[log.replace("1.300001","3.010001")])["qualified"]
    assert not qualify_preparation(trace,edge,[log.replace("host result=0","host result=-5")])["qualified"]
    assert not qualify_preparation(trace,{**edge,"prior_speed":"1000"},[log])["qualified"]
    print("PHY_MODE_SAMPLER_SELFTEST_PASS")

def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="cmd",required=True)
    c=sub.add_parser("capture");c.add_argument("out",type=Path);c.add_argument("boot");c.add_argument("--profile",required=True,choices=probe.PROFILES);c.add_argument("--count",type=int,default=400)
    c=sub.add_parser("compare");c.add_argument("mode",type=Path);c.add_argument("traffic",type=Path)
    sub.add_parser("selftest")
    a=p.parse_args()
    if a.cmd=="capture":capture(a.out,a.boot,a.profile,a.count)
    elif a.cmd=="compare":compare(a.mode,a.traffic)
    else:selftest()
if __name__=="__main__":
    main()
