#!/usr/bin/env python3
"""Read-only, boot-bound register/clock comparison in the isolated Wave7 lab.

Only the previously validated, explicit PHY register allowlist is read.
No MMD7 packet-counter accesses, generic MMIO dumps or device changes.
Capture raw outputs and full route/probe evidence before comparison.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import time

sys.dont_write_bytecode=True
spec=importlib.util.spec_from_file_location("probe",Path(__file__).with_name("probe-phy-reconnect.py"))
probe=importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
trunk=probe.trunk
REMOTE=r"""set -eu
echo "boot=$(cat /proc/sys/kernel/random/boot_id)"
echo "revision=$(cat /etc/openwrt_version)"
echo "peer=${SSH_CONNECTION%% *}"
echo "start_uptime=$(cut -d' ' -f1 /proc/uptime)"
echo "start_speed=$(cat /sys/class/net/lan/speed)"
echo "start_carrier=$(cat /sys/class/net/lan/carrier)"
echo "switch_carrier=$(cat /sys/class/net/lan1/carrier)"
echo "bootfail=$(fw_printenv -n bootfail)"
echo PCS_BEGIN
cat /sys/kernel/debug/ipq-pcs-7a10000.ethernet-pcs/link_state
echo PCS_END
echo MAC_BEGIN
cat /sys/kernel/debug/ppe/port2_mac_regs
echo MAC_END
echo CLOCK_BEGIN
awk '$1 ~ /^7a10000[.]ethernet-pcs::(phy_ref_clk|rx_clk|tx_clk)$/ || $1 ~ /^nss_cc_(uniphy_)?port2_(rx|tx)(_div)?_clk(_src)?$/ || $1=="nss_cc_port2_mac_clk" {print $1,$2,$3,$5,$9}' /sys/kernel/debug/clk/clk_summary
echo CLOCK_END
echo PARENT_BEGIN
for clk in nss_cc_port2_rx_clk_src nss_cc_port2_tx_clk_src; do
  printf '%s=' "$clk"
  cat "/sys/kernel/debug/clk/$clk/clk_parent"
done
echo PARENT_END
echo PHY_BEGIN
for reg in 17 31; do
  echo "c22.$reg=$(phytool read lan/0x18/$reg)"
done
for reg in 0x0009 0x001e 0x001f 0x006e 0x006f 0x0070 0x007d 0x9072; do
  echo "mmd1.$reg=$(phytool read lan/0x19:1/$reg)"
done
echo "mmd3.0x805a=$(phytool read lan/0x18:3/0x805a)"
echo "mmd7.0x8029=$(phytool read lan/0x18:7/0x8029)"
echo PHY_END
echo COUNTERS_BEGIN
ethtool -S lan | grep -E '^[[:space:]]*(rx_frames|tx_frames|rx_crc_err|rx_frag_err|rx_drop_frames):'
echo COUNTERS_END
echo "end_carrier=$(cat /sys/class/net/lan/carrier)"
echo "end_speed=$(cat /sys/class/net/lan/speed)"
echo "end_boot=$(cat /proc/sys/kernel/random/boot_id)"
echo "end_uptime=$(cut -d' ' -f1 /proc/uptime)"
"""
CLOCKS={"7a10000.ethernet-pcs::"+n for n in ("phy_ref_clk","rx_clk","tx_clk")}
CLOCKS|={"nss_cc_port2_"+d+s for d in ("rx","tx") for s in ("_clk_src","_div_clk_src","_clk")}
CLOCKS|={"nss_cc_uniphy_port2_"+d+"_clk" for d in ("rx","tx")}
CLOCKS.add("nss_cc_port2_mac_clk")
PARENT_KEYS={"nss_cc_port2_rx_clk_src","nss_cc_port2_tx_clk_src"}
PHY_KEYS={"c22.17","c22.31","mmd3.0x805a","mmd7.0x8029"}|{"mmd1."+r for r in ("0x0009","0x001e","0x001f","0x006e","0x006f","0x0070","0x007d","0x9072")}
PCS_KEYS={"interface","calibration","mode_ctrl","misc2","vco_cal_ctrl","pll_reset","clkout_50m_ctrl","link_detect","mii0_control","mii0_status"}
MAC_KEYS={"port_mux_ctrl","port2_gmac_enable","port2_gmac_speed","port2_gmac_ctrl0","port2_bridge_ctrl"}
def parse(raw,boot,rev,speed):
    sections={"CORE":[]}
    active="CORE"
    for line in raw.splitlines():
        if line.endswith("_BEGIN"):
            assert active=="CORE"
            active=line[:-6]
            assert active not in sections
            sections[active]=[]
        elif line.endswith("_END"):
            assert active==line[:-4]
            active="CORE"
        else:
            sections[active].append(line)
    required={"CORE","PCS","MAC","CLOCK","PHY","COUNTERS"}
    assert active=="CORE" and required<=set(sections)<=required|{"PARENT"}
    if rev==probe.CLOCK_REV:
        assert "PARENT" in sections, "clock trial requires logical parent evidence"
    def fields(lines):
        out={}
        for line in lines:
            k,v=line.split("=",1)
            assert k not in out,k
            out[k]=v
        return out
    core=fields(sections["CORE"])
    assert core["boot"]==core["end_boot"]==boot
    assert core["revision"]==rev and core["peer"]==trunk.PATHS["switch"][0]
    assert core["bootfail"]=="0" and core["start_carrier"]==core["end_carrier"]==core["switch_carrier"]=="1"
    assert core["start_speed"]==core["end_speed"]==speed
    assert 0<=float(core["end_uptime"])-float(core["start_uptime"])<=5
    pcs=fields(sections["PCS"]);mac=fields(sections["MAC"]);phy=fields(sections["PHY"])
    assert set(pcs)==PCS_KEYS and set(mac)==MAC_KEYS and set(phy)==PHY_KEYS
    # phytool prints zero as 0000, and nonzero values with 0x.
    assert all(re.fullmatch(r"(?:0x[0-9a-fA-F]{4}|0000)",v) and v.lower()!="0xffff" for v in phy.values())
    phy={k:f"0x{int(v,16):04x}" for k,v in phy.items()}
    clocks={}
    for line in sections["CLOCK"]:
        n,*values=line.split()
        assert n not in clocks and len(values)==4
        clocks[n]=values
    assert set(clocks)==CLOCKS,(CLOCKS-set(clocks),set(clocks)-CLOCKS)
    counters={}
    for line in sections["COUNTERS"]:
        n,v=line.strip().split(":")
        assert n not in counters
        counters[n]=int(v)
    assert set(counters)==set(probe.MAC_KEYS)
    result=dict(core=core,pcs=pcs,mac=mac,phy=phy,clocks=clocks,counters=counters)
    if "PARENT" in sections:
        parents=fields(sections["PARENT"])
        assert set(parents)==PARENT_KEYS
        assert all(re.fullmatch(r"[a-zA-Z0-9_.:-]+",v) for v in parents.values())
        result["parents"]=parents
    return result

def capture(out,boot,profile,speed,expected):
    rev,directory=probe.PROFILES[profile]
    base=trunk.BASE/directory/"observations"
    assert out.parent.resolve()==base.resolve() and trunk.BOOT.fullmatch(boot)
    out.mkdir(mode=0o700)
    ip,dev,_=trunk.PATHS["switch"]
    ssh=["ssh","-nT","-i","/home/jan/.ssh/wave7-root-rsa","-o",f"BindInterface={dev}","-o",f"BindAddress={ip}","-o","BatchMode=yes","-o","IdentitiesOnly=yes","-o","StrictHostKeyChecking=yes","-o",f"UserKnownHostsFile={trunk.BASE/'known_hosts'}","-o","ConnectTimeout=3","-o","ConnectionAttempts=1",f"root@{trunk.ROUTER}",REMOTE]
    rows=[]
    with (out/"samples.jsonl").open("x") as f,ThreadPoolExecutor(2) as pool:
        for i in range(3):
            before=trunk.routes()
            futures={n:pool.submit(trunk.probe,n,4,before[n]) for n in trunk.PATHS}
            p={n:v.result() for n,v in futures.items()}
            r=trunk.run(ssh,8)
            after=trunk.routes()
            row=dict(wall_epoch=time.time(),routes_before=before,routes_after=after,probes=p,remote=r,host=probe.host_counters())
            f.write(json.dumps(row)+"\n");f.flush()
            assert all(routes[n]["valid"] for routes in (before,after) for n in trunk.PATHS)
            assert r["rc"]==0,r
            assert row["host"]["direct"]["speed"]==speed
            assert p["switch"]["sent"]==p["switch"]["received"]==4
            assert p["direct"]["sent"]==4 and p["direct"]["received"]==(4 if expected=="healthy" else 0)
            rows.append(parse(r["stdout"],boot,rev,speed))
            if i<2:time.sleep(1)
    (out/"parsed.json").write_text(json.dumps(rows,indent=2)+"\n")
    (out/"SHA256SUMS").write_text("".join(f"{hashlib.sha256((out/n).read_bytes()).hexdigest()}  {n}\n" for n in ("samples.jsonl","parsed.json")))
    print("PHY_STATE_CAPTURE_PASS",expected,speed,boot)

def load_capture(p):
    manifest={}
    for line in (p/"SHA256SUMS").read_text().splitlines():
        digest,name=line.split("  ")
        assert name not in manifest
        manifest[name]=digest
    assert set(manifest)=={"samples.jsonl","parsed.json"}
    for name,digest in manifest.items():
        assert hashlib.sha256((p/name).read_bytes()).hexdigest()==digest
    parsed=json.loads((p/"parsed.json").read_text())
    raw=[json.loads(line) for line in (p/"samples.jsonl").read_text().splitlines()]
    assert len(parsed)==len(raw)==3
    core=parsed[0]["core"]
    boot,rev,speed=core["boot"],core["revision"],core["start_speed"]
    states=set()
    for row,expected in zip(raw,parsed):
        assert all(row[k][n]["valid"] for k in ("routes_before","routes_after") for n in trunk.PATHS)
        assert row["remote"]["rc"]==0 and row["host"]["direct"]["speed"]==speed
        assert parse(row["remote"]["stdout"],boot,rev,speed)==expected
        probes=row["probes"]
        assert probes["switch"]["sent"]==probes["switch"]["received"]==4
        assert probes["direct"]["sent"]==4 and probes["direct"]["received"] in (0,4)
        states.add("healthy" if probes["direct"]["received"]==4 else "fault")
    assert len(states)==1,"mixed traffic state"
    return parsed,states.pop()

def compare(a,b):
    x,xstate=load_capture(a)
    y,ystate=load_capture(b)
    allrows=x+y
    assert len({(r["core"]["boot"],r["core"]["revision"],r["core"]["start_speed"]) for r in allrows})==1
    out={}
    categories=("pcs","mac","phy","clocks")
    has_parents={"parents" in row for row in allrows}
    assert len(has_parents)==1,"cannot compare mixed clock-parent coverage"
    if True in has_parents:
        categories+=("parents",)
    for category in categories:
        for k in x[0][category]:
            av={json.dumps(r[category][k]) for r in x}
            bv={json.dumps(r[category][k]) for r in y}
            if av!=bv:
                out[category+"."+k]={"first":[json.loads(v) for v in sorted(av)],"second":[json.loads(v) for v in sorted(bv)],"stable_difference":len(av)==len(bv)==1}
    print(json.dumps({"first":{"path":str(a),"state":xstate},"second":{"path":str(b),"state":ystate},"matched_healthy_fault":xstate!=ystate,"differences":out,"fields_compared":sum(len(x[0][n]) for n in categories)},indent=2))
def selftest():
    boot="12345678-1234-1234-1234-123456789abc"
    rev=probe.CLOCK_REV
    core=dict(boot=boot,end_boot=boot,revision=rev,peer=trunk.PATHS["switch"][0],
              start_uptime="100",end_uptime="101",start_speed="1000",end_speed="1000",
              start_carrier="1",end_carrier="1",switch_carrier="1",bootfail="0")
    def section(name,lines):
        return [name+"_BEGIN",*lines,name+"_END"]
    def fields(values):
        return [f"{k}={v}" for k,v in values.items()]
    raw=fields(core)
    raw+=section("PCS",fields(dict.fromkeys(PCS_KEYS,"0x0001")))
    raw+=section("MAC",fields(dict.fromkeys(MAC_KEYS,"0x0001")))
    raw+=section("CLOCK",[f"{name} 1 1 125000000 Y" for name in CLOCKS])
    raw+=section("PHY",fields(dict.fromkeys(PHY_KEYS,"0x0001")))
    raw+=section("COUNTERS",[f"{name}: 1" for name in probe.MAC_KEYS])
    parent_section=section("PARENT",[
        "nss_cc_port2_rx_clk_src=7a10000.ethernet-pcs::rx_clk",
        "nss_cc_port2_tx_clk_src=7a10000.ethernet-pcs::tx_clk"])
    def check(lines,revision=rev):
        return parse("\n".join(lines),boot,revision,"1000")
    assert set(check(raw+parent_section)["parents"])==PARENT_KEYS
    def rejects(lines):
        try:
            check(lines)
        except AssertionError:
            return
        raise AssertionError("invalid parent fixture accepted")
    rejects(raw)
    rejects(raw+parent_section[:-2]+parent_section[-1:])
    rejects(raw+parent_section[:2]+parent_section[1:])
    rejects(raw+[line.replace("::rx_clk","") if "::rx_clk" in line else line for line in
                 [line.replace("7a10000.ethernet-pcs","") if "::rx_clk" in line else line for line in parent_section]])
    # Historical sealed captures retain their original schema.
    old_rev=probe.PROFILES["0493"][0]
    old=[line.replace(rev,old_rev) for line in raw]
    assert "parents" not in check(old,old_rev)
    print("PHY_STATE_SELFTEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest="cmd",required=True)
    sub.add_parser("selftest")
    c=sub.add_parser("capture");c.add_argument("out",type=Path);c.add_argument("boot");c.add_argument("--profile",choices=probe.PROFILES,required=True);c.add_argument("--speed",choices=("1000","2500"),required=True);c.add_argument("--expected",choices=("healthy","fault"),required=True)
    c=sub.add_parser("compare");c.add_argument("first",type=Path);c.add_argument("second",type=Path)
    a=p.parse_args()
    if a.cmd=="capture":capture(a.out,a.boot,a.profile,a.speed,a.expected)
    elif a.cmd=="compare":compare(a.first,a.second)
    else:selftest()
