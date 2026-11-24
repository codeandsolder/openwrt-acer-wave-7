#!/usr/bin/env -S uv run --no-project python
"""Read-only IPQ5332 PCS0/NSSCC port1 state for CPU-trunk fault comparison.

The board DTS maps Realtek CPU6 to PPE port1 and PCS0 channel0 (2500base-x).
The PCS debugfs handler is a source-backed fixed register allowlist.
NSSCC offsets below are port1 RCG/divider/CBCR controls from nsscc-ipq5332.c.
Never dump arbitrary register ranges or alter PHY/clock/register state.
"""
import argparse
import json
from pathlib import Path
import re
import runpy
import subprocess
import time

probe = runpy.run_path(str(Path(__file__).with_name("probe-mib-freshness.py")))
BASE = probe["BASE"]
PINS = probe["PINS"]
require = probe["require"]
remote = probe["remote"]
NSSCC = {
    "mac_cbcr": "428", "rx_cmd": "450", "rx_cfg": "454", "rx_div": "458",
    "tx_cmd": "45c", "tx_cfg": "460", "tx_div": "464", "rx_cbcr": "480",
    "tx_cbcr": "488", "pcs_rx_cbcr": "4b4", "pcs_tx_cbcr": "4b8",
}
PCS = ("calibration", "mode_ctrl", "misc2", "vco_cal_ctrl", "pll_reset",
       "clkout_50m_ctrl", "link_detect", "mii0_control", "mii0_status")
CLOCKS = {"7a00000.ethernet-pcs::"+n for n in ("phy_ref_clk","rx_clk","tx_clk")}
CLOCKS |= {"nss_cc_port1_"+d+s for d in ("rx","tx")
           for s in ("_clk_src","_div_clk_src","_clk")}
CLOCKS |= {"nss_cc_uniphy_port1_"+d+"_clk" for d in ("rx","tx")}
CLOCKS.add("nss_cc_port1_mac_clk")
PARENTS = ("nss_cc_port1_rx_clk_src","nss_cc_port1_tx_clk_src")
XGMAC = probe["XGMAC"]
COMMAND = r"""set -eu
echo "boot=$(cat /proc/sys/kernel/random/boot_id)"
echo "rev=$(cat /rom/etc/openwrt_version)"
echo "peer=${SSH_CONNECTION%% *}"
echo "uptime=$(cut -d' ' -f1 /proc/uptime)"
echo "bootfail=$(fw_printenv -n bootfail)"
echo "lan1=$(cat /sys/class/net/lan1/carrier)"
echo "switch=$(cat /sys/class/net/switch/carrier)"
echo '=== PCS ==='
cat /sys/kernel/debug/ipq-pcs-7a00000.ethernet-pcs/link_state
echo '=== CLOCK ==='
awk '$1 ~ /^7a00000[.]ethernet-pcs::(phy_ref_clk|rx_clk|tx_clk)$/ || $1 ~ /^nss_cc_(uniphy_)?port1_(rx|tx)(_div)?_clk(_src)?$/ || $1=="nss_cc_port1_mac_clk" {print $1,$2,$3,$5,$9}' /sys/kernel/debug/clk/clk_summary
echo '=== PARENT ==='
for clk in nss_cc_port1_rx_clk_src nss_cc_port1_tx_clk_src; do
  printf '%s=' "$clk"
  cat "/sys/kernel/debug/clk/$clk/clk_parent"
done
echo '=== NSSCC ==='
regmap=/sys/kernel/debug/regmap/39b00000.clock-controller
test "$(cat "$regmap/name")" = qcom,ipq5332-nsscc
test "$(cat "$regmap/range")" = 0-800
for reg in OFFSETS; do
    line=$(dd if="$regmap/registers" bs=14 skip=$((0x$reg / 4)) count=1 2>/dev/null)
    case "$line" in "$reg: "????????) printf '%s\n' "$line";; *) exit 1;; esac
done
echo '=== XGMAC ==='
ethtool -S switch
echo '=== END ==='
echo "end_boot=$(cat /proc/sys/kernel/random/boot_id)"
echo "end_uptime=$(cut -d' ' -f1 /proc/uptime)"
""".replace("OFFSETS"," ".join(NSSCC.values()))


def fields(lines):
    data = {}
    for line in lines:
        key,val = line.split("=",1)
        require(key not in data, f"duplicate {key}")
        data[key] = val
    return data


def decode(values):
    def branch(value):
        return {"enable":bool(value&1),"halt":bool(value&(1<<31))}
    def rcg(direction):
        cmd,cfg,div = (values[direction+"_"+k] for k in ("cmd","cfg","div"))
        return {"update":bool(cmd&1),"root_off":bool(cmd&(1<<31)),
                "selector":(cfg>>8)&7,"hid":cfg&31,"post_div":(div&15)+1,
                "branch":branch(values[direction+"_cbcr"]),
                "pcs_branch":branch(values["pcs_"+direction+"_cbcr"])}
    return {"rx":rcg("rx"),"tx":rcg("tx"),"mac":branch(values["mac_cbcr"])}


def parse(raw, boot, rev):
    sections = {"CORE":[]}
    active = "CORE"
    for line in raw.splitlines():
        match = re.fullmatch(r"=== (\w+) ===",line)
        if match:
            active = match[1]
            require(active not in sections,"duplicate section")
            sections[active] = []
        else:
            sections[active].append(line)
    require(list(sections)==["CORE","PCS","CLOCK","PARENT","NSSCC","XGMAC","END"],"incomplete sections")
    core = {**fields(sections["CORE"]),**fields(sections["END"])}
    require(core["boot"]==core["end_boot"]==boot and core["rev"]==rev,"wrong boot or revision")
    require(core["peer"]=="192.168.76.2" and core["bootfail"]=="0","wrong management path or uncommitted boot")
    require(all(core[k] in ("0","1") for k in ("lan1","switch")),"invalid carrier")
    require(0<=float(core["end_uptime"])-float(core["uptime"])<=10,"snapshot not bounded")
    pcs = fields(sections["PCS"])
    require(set(pcs)=={"interface",*PCS},"missing PCS fields")
    require(re.fullmatch(r"2500base-x mppe=[01]",pcs["interface"]),"unexpected PCS mode")
    for key in PCS:
        require(re.fullmatch(r"0x[0-9a-f]{8}(?: force=[01] adapter_reset=[01]| link=[01])?",pcs[key]),
                f"malformed PCS {key}")
    clocks = {}
    for line in sections["CLOCK"]:
        name,*vals = line.split()
        require(name not in clocks and len(vals)==4,"invalid clock sample")
        clocks[name] = vals
    require(set(clocks)==CLOCKS,f"clock set mismatch: {CLOCKS-set(clocks)} / {set(clocks)-CLOCKS}")
    parents = fields(sections["PARENT"])
    require(set(parents)==set(PARENTS),"missing parents")
    regs = {}
    for line in sections["NSSCC"]:
        match = re.fullmatch(r"([0-9a-f]{3}): ([0-9a-f]{8})",line)
        require(match is not None and match[1] not in regs,"invalid NSSCC sample")
        regs[match[1]] = int(match[2],16)
    require(set(regs)==set(NSSCC.values()),"NSSCC allowlist mismatch")
    nsscc = {name:regs[reg] for name,reg in NSSCC.items()}
    xgmac = probe["parse_xgmac"]("\n".join(sections["XGMAC"]))
    return {"core":core,"pcs":pcs,"clocks":clocks,"parents":parents,
            "nsscc":nsscc,"nsscc_decoded":decode(nsscc),"xgmac":xgmac}


def capture(variant,out):
    with probe["lab_session"](out):
        first = probe["snapshot"](out,"initial",variant)
        boot = first["fields"]["boot"]
        rev = first["fields"]["rev"]
        samples=[]
        for index in range(3):
            probe["routes"]()
            pings={}
            for name,(ip,dev,*_) in probe["PATHS"].items():
                result=subprocess.run(["ping","-n","-I",dev,"-I",ip,"-c","4","-i","0.2","-W","1","192.168.76.1"],
                    text=True,capture_output=True,timeout=5)
                (out/f"{index}-{name}-ping.txt").write_text(result.stdout+result.stderr)
                match=re.search(r"(\d+) packets transmitted, (\d+)(?: packets)? received",result.stdout)
                require(match is not None and int(match[1])==4,"unobserved path")
                pings[name]=int(match[2])
            raw=remote(COMMAND)
            (out/f"{index}-registers.txt").write_text(raw)
            sample=parse(raw,boot,rev)
            samples.append({"pings":pings,"state":sample})
            if index<2:
                time.sleep(1)
        final=probe["snapshot"](out,"final",variant)
        changes=probe["delta"](first,final)
        report={"variant":variant,"boot":boot,"samples":samples,"mib_deltas":changes}
        (out/"report.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))


def selftest():
    boot="12345678-1234-1234-1234-123456789abc"
    rev="test"
    raw=f"boot={boot}\nrev={rev}\npeer=192.168.76.2\nuptime=1.00\nbootfail=0\nlan1=1\nswitch=1\n=== PCS ===\ninterface=2500base-x mppe=1\n"
    raw+="".join(f"{k}=0x00000001\n" for k in PCS)
    raw+="=== CLOCK ===\n"+"".join(f"{n} 1 1 312500000 Y\n" for n in sorted(CLOCKS))
    raw+="=== PARENT ===\n"+"".join(f"{n}=parent\n" for n in PARENTS)
    raw+="=== NSSCC ===\n"+"".join(f"{r}: 00000001\n" for r in NSSCC.values())
    raw+="=== XGMAC ===\n"+"".join(f" {n}: 10\n" for n in XGMAC)
    raw+=f"=== END ===\nend_boot={boot}\nend_uptime=1.20\n"
    result=parse(raw,boot,rev)
    require(result["nsscc_decoded"]["rx"]["branch"]=={"enable":True,"halt":False},"decode")
    require(result["xgmac"]["rx_frames"]==10,"xgmac")
    for bad in (raw.replace("end_boot="+boot,"end_boot=bad"),
                raw.replace("428: 00000001","429: 00000001"),
                raw.replace("mii0_status=0x00000001\n","")):
        try:
            parse(bad,boot,rev)
        except ValueError:
            pass
        else:
            raise ValueError("invalid fixture accepted")
    print("TRUNK_PCS_STATE_SELFTEST_PASS")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="cmd",required=True)
    sub.add_parser("selftest")
    c=sub.add_parser("capture")
    c.add_argument("variant",choices=PINS)
    c.add_argument("out",type=Path)
    args=parser.parse_args()
    if args.cmd=="selftest":
        selftest()
    else:
        require(args.out.parent.resolve()==(BASE/"mib-refresh-dhcp-guard8"/"observations").resolve(),
                "output must be in wired observations")
        capture(args.variant,args.out)
