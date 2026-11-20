#!/usr/bin/env python3
"""Observe a single direct copper reconnect through independent switch SSH.

Never changes link configuration, reboots or reads clear-on-read PHY registers.
PHY totals come from existing driver link-edge log windows.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
import time

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("trunk_probe", Path(__file__).with_name("probe-trunk-recovery.py"))
trunk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trunk)
REVISION = "r0+38346-0418bb7af2-ap-dhcp-guard8"
BASE = trunk.BASE / "stock-poll-fifo-dhcp-guard8" / "observations"
MAC_KEYS = ("rx_frames", "tx_frames", "rx_crc_err", "rx_frag_err", "rx_drop_frames")
PHY = re.compile(
    r"^\[\s*(\d+\.\d+)\].*QCA8081.*wave7-diag: phy-path sample=(\d+) edge=(\d+) link=([01]) "
    r"rx=(\d+) drx=(\d+) tx=(\d+) dtx=(\d+) rx_err=(\d+) tx_err=(\d+)$"
)
REMOTE = r"""set -e
echo "boot=$(cat /proc/sys/kernel/random/boot_id)"
echo "uptime=$(cut -d' ' -f1 /proc/uptime)"
echo "revision=$(cat /etc/openwrt_version)"
echo "management_peer=${SSH_CONNECTION%% *}"
echo "carrier=$(cat /sys/class/net/lan/carrier 2>/dev/null || echo absent)"
echo "speed=$(cat /sys/class/net/lan/speed 2>/dev/null || echo absent)"
echo "switch_carrier=$(cat /sys/class/net/lan1/carrier 2>/dev/null || echo absent)"
echo "bootfail=$(fw_printenv -n bootfail 2>/dev/null || echo absent)"
ethtool -S lan | grep -E '^[[:space:]]*(rx_frames|tx_frames|rx_crc_err|rx_frag_err|rx_drop_frames):'
ethtool -S switch | grep -E 's00_p06_(dot3StatsFCSErrors|etherStatsFragments|etherStatsDropEvents):'
dmesg | grep -E 'QCA8081.*wave7-diag: (phy-path|fifo\[)|NOC ERROR DETECTED' || :
echo "end_boot=$(cat /proc/sys/kernel/random/boot_id)"
"""


def parse(output, expected_boot):
    fields, mac, switch, samples = {}, {}, {}, []
    for line in output.splitlines():
        m = re.fullmatch(r"(\w+)=(.*)", line)
        if m:
            assert m[1] not in fields, "duplicate field"
            fields[m[1]] = m[2]
        m = re.fullmatch(r"\s*(\w+):\s*(\d+)\s*", line)
        if m:
            if m[1] in MAC_KEYS:
                assert m[1] not in mac, "duplicate GMAC counter"
                mac[m[1]] = int(m[2])
            elif m[1].startswith("s00_p06_"):
                key = m[1].removeprefix("s00_p06_")
                if key in trunk.COUNTERS and trunk.COUNTERS[key] in trunk.ERRORS:
                    assert key not in switch, "duplicate switch counter"
                    switch[key] = int(m[2])
        m = PHY.match(line)
        if m:
            samples.append(dict(zip(
                ("uptime", "sample", "edge", "link", "rx", "drx", "tx", "dtx", "rx_err", "tx_err"),
                (float(m[1]), *map(int, m.groups()[1:])),
            )))
    assert fields["boot"] == fields["end_boot"] == expected_boot
    assert fields["revision"] == REVISION and fields["management_peer"] == trunk.PATHS["switch"][0]
    assert set(mac) == set(MAC_KEYS)
    assert len(switch) == 3
    uptime = float(fields["uptime"])
    assert math.isfinite(uptime) and uptime >= 0
    assert fields["carrier"] in ("0", "1", "absent")
    assert fields["switch_carrier"] in ("0", "1", "absent")
    # dmesg lines sampled after initial uptime can be slightly newer.
    sample = max(samples, key=lambda s: s["uptime"], default=None)
    return {**fields, "uptime": uptime, "mac": mac,
            "switch_errors": switch, "phy": sample,
            "noc": "NOC ERROR DETECTED" in output}


def snapshot(expected_boot, routes):
    if not routes["switch"]["valid"]:
        return {"rc": None, "skipped": "independent management route absent"}
    ip, dev, _ = trunk.PATHS["switch"]
    result = trunk.run(["ssh", "-nT", "-i", "/home/jan/.ssh/wave7-root-rsa",
                        "-o", f"BindInterface={dev}", "-o", f"BindAddress={ip}",
                        "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
                        "-o", "StrictHostKeyChecking=yes",
                        "-o", f"UserKnownHostsFile={trunk.BASE/'known_hosts'}",
                        "-o", "ConnectTimeout=3", "-o", "ConnectionAttempts=1",
                        f"root@{trunk.ROUTER}", REMOTE], 8)
    if result["rc"] == 0:
        try:
            result["state"] = parse(result["stdout"], expected_boot)
        except (AssertionError, KeyError, ValueError) as exc:
            result["parse_error"] = str(exc)
    return result


def host_counters():
    out = {}
    for name, (_, dev, _) in trunk.PATHS.items():
        root = Path("/sys/class/net") / dev
        try:
            out[name] = {k: int((root / "statistics" / k).read_text())
                         for k in ("rx_packets", "tx_packets")}
            out[name]["carrier"] = (root / "carrier").read_text().strip()
        except (OSError, ValueError) as exc:
            out[name] = {"error": str(exc)}
    return out


def state_good(s):
    return s and s["carrier"] == s["switch_carrier"] == "1" and s["bootfail"] == "0" and not s["noc"]


def probe_count(row, name):
    p = row["probes"][name]
    sent, received = p["sent"], p["received"]
    if not isinstance(sent, int) or not isinstance(received, int) or not 0 <= received <= sent or sent <= 0:
        return None
    return sent, received


def evaluate(window):
    if len(window)<2:
        return {"samples":len(window),"classification":"INCONCLUSIVE"}
    a,b = (r["snapshot"]["state"] for r in (window[0],window[-1]))
    elapsed=b["uptime"]-a["uptime"]
    mac={k:b["mac"][k]-a["mac"][k] for k in MAC_KEYS}
    phy={k:b["phy"][k]-a["phy"][k] for k in ("rx","tx","rx_err","tx_err")}
    errors={k:b["switch_errors"][k]-a["switch_errors"][k] for k in a["switch_errors"]}
    totals={n:[sum(probe_count(r,n)[i] for r in window[1:]) for i in (0,1)] for n in trunk.PATHS}
    try:
        peer_tx=window[-1]["host_counters"]["direct"]["tx_packets"]
        peer_tx-=window[0]["host_counters"]["direct"]["tx_packets"]
    except KeyError:
        peer_tx=None
    result=dict(samples=len(window),elapsed=elapsed,mac_delta=mac,phy_delta=phy,
                switch_error_delta=errors,probe_totals=totals,peer_tx_delta=peer_tx,
                phy_edge=b["phy"]["edge"],classification="INCONCLUSIVE")
    if elapsed < 30 or min(*mac.values(),*phy.values(),*errors.values()) < 0 or any(errors.values()) or peer_tx is None or peer_tx<=0:
        return result
    sent, received=totals["direct"]
    if sent and received == 0 and phy["rx"] > 0 and mac["rx_frames"] == 0:
        # PHY RX is copper ingress. PHY TX is *external MAC ingress*,
        # not proof of transmission on the copper wire.
        result["classification"]="COPPER_RX_WITH_GMAC_RX_STALL"
        result["directional_signature"] = (
            "HOST_TX_WITH_PHY_MAC_INGRESS_STALL"
            if mac["tx_frames"] > 0 and phy["tx"] == phy["tx_err"] == 0
            else "PHY_MAC_INGRESS_UNCONFIRMED")
        result["copper_rx_errors"] = phy["rx_err"]
    elif sent and received == sent and phy["rx"] > 0 and phy["tx"] > 0 and mac["rx_frames"] > 0 and mac["tx_frames"] > 0 and not any(mac[k] for k in MAC_KEYS[2:]):
        result["classification"]="ONE_GIG_RECONNECT_PASS"
    return result


def report(rows):
    # Freeze the best complete post-edge window before the driver's
    # bounded 60-sample logging window expires. A subsequent observed
    # link flap gets its own episode; a late loss cannot erase evidence.
    episodes=[]
    last_good=None
    episode=None
    window=[]
    def flush():
        nonlocal window
        if episode is not None and window:
            episode["windows"].append(evaluate(window))
        window=[]
    for row in rows:
        s=row["snapshot"].get("state")
        if not s:
            flush()
            last_good=None
            continue
        if s["carrier"]=="0":
            flush()
            if episode is None or episode["up"] is not None:
                episode={"down":s["uptime"],"up":None,
                         "prior_speed":last_good and last_good["speed"],"windows":[]}
                episodes.append(episode)
            last_good=None
            continue
        if not state_good(s):
            flush()
            last_good=None
            continue
        last_good=s
        if episode is None:
            continue
        if episode["up"] is None:
            episode["up"]=s["uptime"]
            episode["post_speed"]=s["speed"]
        if s["speed"]!="1000" or episode["post_speed"]!="1000":
            flush()
            continue
        phy=s["phy"]
        if s["uptime"]-episode["up"]<3 or not phy or phy["link"]!=1 or phy["uptime"]<episode["up"]-4 or abs(s["uptime"]-phy["uptime"])>5:
            flush()
            continue
        if window:
            prev=window[-1]["snapshot"]["state"]
            if s["uptime"]<=prev["uptime"] or s["uptime"]-prev["uptime"]>8 or phy["edge"]!=prev["phy"]["edge"]:
                flush()
        if not all(row.get(k,{}).get(n,{}).get("valid",False) for k in ("routes_before","routes_after") for n in trunk.PATHS):
            flush()
            continue
        if any(probe_count(row,n) is None for n in trunk.PATHS) or probe_count(row,"switch")[0]!=probe_count(row,"switch")[1]:
            flush()
            continue
        window.append(row)
    flush()
    for e in episodes:
        classes={w["classification"] for w in e["windows"]}-{"INCONCLUSIVE"}
        e["classification"]=next(iter(classes)) if len(classes)==1 else "MIXED" if classes else "INCONCLUSIVE"
        if e["classification"]=="ONE_GIG_RECONNECT_PASS" and e["prior_speed"]!="1000":
            e["classification"]="ONE_GIG_TRANSITION_PASS"
    return {"episodes":episodes,"classification":episodes[-1]["classification"] if episodes else "NO_CARRIER_EDGE_OBSERVED"}

def capture(out, boot, duration):
    assert os.getuid() != 0 and trunk.BOOT.fullmatch(boot)
    assert 35 <= duration <= 240 and out.parent.resolve() == BASE.resolve()
    BASE.mkdir(mode=0o700,exist_ok=True)
    out.mkdir(mode=0o700)
    rows=[]
    with (out/"samples.jsonl").open("x") as stream, ThreadPoolExecutor(2) as pool:
        start=time.monotonic()
        print("OBSERVING",boot,flush=True)
        while time.monotonic()-start < duration:
            t=time.monotonic()
            before=trunk.routes()
            futures={n:pool.submit(trunk.probe,n,4,before[n]) for n in trunk.PATHS}
            probes={n:f.result() for n,f in futures.items()}
            after=trunk.routes()
            row={"wall_epoch":time.time(),"routes_before":before,"routes_after":after,
                 "probes":probes,"host_counters":host_counters(),"snapshot":snapshot(boot,after)}
            rows.append(row)
            stream.write(json.dumps(row)+"\n"); stream.flush()
            state=row["snapshot"].get("state")
            if state:
                print(f'{state["uptime"]:.2f} carrier={state["carrier"]} speed={state["speed"]} direct={probes["direct"]["received"]} switch={probes["switch"]["received"]}',flush=True)
            time.sleep(max(0,2-(time.monotonic()-t)))
    result=report(rows)
    (out/"report.json").write_text(json.dumps(result,indent=2)+"\n")
    (out/"SHA256SUMS").write_text("".join(f"{hashlib.sha256((out/n).read_bytes()).hexdigest()}  {n}\n" for n in ("samples.jsonl","report.json")))
    print(json.dumps(result,indent=2))


def selftest():
    def row(t,carrier="1",speed="1000",stall=False,edge=3):
        g=100 if stall else 100+t
        state={"uptime":t,"carrier":carrier,"switch_carrier":"1","bootfail":"0","noc":False,
               "speed":speed,"mac":dict(zip(MAC_KEYS,[g,g,0,0,0])),
               "switch_errors":{"fcs":0,"fragments":0,"drops":0},
               "phy":{"uptime":t,"link":int(carrier),"edge":edge,"rx":100+t,"tx":g,"rx_err":0,"tx_err":0}}
        return {"snapshot":{"state":state},"probes":{"switch":{"sent":4,"received":4},"direct":{"sent":4,"received":0 if stall else 4}},
                "routes_before":{n:{"valid":True} for n in trunk.PATHS},
                "routes_after":{n:{"valid":True} for n in trunk.PATHS},
                "host_counters":{"direct":{"tx_packets":100+t}}}
    for stall, expected in ((False,"ONE_GIG_RECONNECT_PASS"),(True,"COPPER_RX_WITH_GMAC_RX_STALL")):
        rows=[row(1),row(3,"0")]+[row(t,stall=stall) for t in range(12,58,2)]
        assert report(rows)["classification"] == expected, report(rows)
        if stall:
            # Deliberate host MAC TX activity with no PHY external-MAC
            # ingress/error activity is a distinct second-direction clue.
            for row_ in rows:
                state=row_["snapshot"]["state"]
                state["mac"]["tx_frames"] = 100+state["uptime"]
            result=report(rows)["episodes"][-1]["windows"][-1]
            assert result["directional_signature"] == "HOST_TX_WITH_PHY_MAC_INGRESS_STALL"
            rows[-1]["snapshot"]["state"]["phy"]["tx_err"]=1
            result=report(rows)["episodes"][-1]["windows"][-1]
            assert result["directional_signature"] == "PHY_MAC_INGRESS_UNCONFIRMED"
        assert report(rows[2:])["classification"] == "NO_CARRIER_EDGE_OBSERVED"
        assert report(rows[:-10])["classification"] == "INCONCLUSIVE"
        # A stale log at end must not discard the already measured window.
        assert report(rows+[row(70,edge=4)])["classification"] == expected
        rows[0]["snapshot"]["state"]["speed"]="2500"
        assert report(rows)["classification"] == ("ONE_GIG_TRANSITION_PASS" if not stall else expected)
        rows[12]["snapshot"]={}
        assert report(rows)["classification"] == "INCONCLUSIVE"
    print("PHY_RECONNECT_SELFTEST_PASS")


if __name__ == "__main__":
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest="cmd",required=True)
    sub.add_parser("selftest")
    c=sub.add_parser("capture"); c.add_argument("out",type=Path); c.add_argument("boot"); c.add_argument("--duration",type=int,default=90)
    r=sub.add_parser("report"); r.add_argument("raw",type=Path)
    args=p.parse_args()
    if args.cmd=="selftest":
        selftest()
    elif args.cmd=="capture":
        capture(args.out,args.boot,args.duration)
    else:
        print(json.dumps(report([json.loads(l) for l in args.raw.read_text().splitlines()]),indent=2))
