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
PROFILES = {
    "0491": ("r0+38346-0418bb7af2-ap-dhcp-guard8", "stock-poll-fifo-dhcp-guard8"),
    "0492": ("r0+38346-fe5568a4fb-ap-dhcp-guard8", "conditional-relink-dhcp-guard8"),
    "0493": ("r0+38346-7aa198ca4c-ap-dhcp-guard8", "stock-mac-order-dhcp-guard8"),
    "0494": ("r0+38346-e771c4f65a-ap-dhcp-guard8", "nsscc-parent-order-dhcp-guard8"),
    "0495": ("r0+38346-44d12aa1f7-ap-dhcp-guard8", "instant-fifo-dhcp-guard8"),
    "0496": ("r0+38346-3688c57cd3-ap-dhcp-guard8", "independent-fifo-dhcp-guard8"),
    "0497": ("r0+38346-ef7d41f2b1-ap-dhcp-guard8", "down-mode-dhcp-guard8"),
    "0498": ("r0+38346-f9aa3e1fa3-ap-dhcp-guard8", "serial-speed-dhcp-guard8"),
}
RELINK_REV = PROFILES["0492"][0]
MAC_ORDER_REV = PROFILES["0493"][0]
RELINK_REVISIONS = (RELINK_REV, MAC_ORDER_REV)
CLOCK_REV = PROFILES["0494"][0]
INSTANT_REV = PROFILES["0495"][0]
WORKER_REV = PROFILES["0496"][0]
DOWN_MODE_REV = PROFILES["0497"][0]
SERIAL_SPEED_REV = PROFILES["0498"][0]
WORKER_REVISIONS = (WORKER_REV, DOWN_MODE_REV)
EDGE_REVISIONS = (*RELINK_REVISIONS, CLOCK_REV, INSTANT_REV, *WORKER_REVISIONS, SERIAL_SPEED_REV)
SERIAL_SPEED = re.compile(r"^\[\s*(\d+\.\d+)\].*wave7-diag: serial-speed mode=((?:0x)?[0-9a-f]+) ctrl=((?:0x)?[0-9a-f]+) sts=((?:0x)?[0-9a-f]+) speed=(\d+)$")
FIFO_WORKER = re.compile(r"^\[\s*(\d+\.\d+)\].*QCA8081.*wave7-diag: fifo-worker tick=(\d+) edge=(\d+) ss=(-?\d+) phylib=([01]) result=(-?\d+)$")
INSTANT_FIFO = re.compile(r"^\[\s*(\d+\.\d+)\].*QCA8081.*wave7-diag: fifo-instant ss=([0-9a-f]{4}) phylib=([01]) copper=([01])$")
MAC_ORDER = re.compile(r"^\[\s*(\d+\.\d+)\].*wave7-diag: stock-mac (TX off before prepare|drained RX off TX retained)$")
EDGE = re.compile(r"^\[\s*(\d+\.\d+)\].*QCA8081.*wave7-diag: phy-path edge=(\d+) link=([01]) ")
RELINK = re.compile(r"^\[\s*(\d+\.\d+)\].*wave7-diag: stock-relink (preserve|prepare|committed)(?: speed=(\d+) duplex=(\d+) pause=([01])/([01]))?$")
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
dmesg | grep -E 'QCA8081.*wave7-diag: (phy-path|fifo\[|fifo-instant|fifo-worker)|wave7-diag: stock-(relink|mac) |wave7-diag: down-mode |wave7-diag: serial-speed |NOC ERROR DETECTED' || :
echo "end_boot=$(cat /proc/sys/kernel/random/boot_id)"
"""


def parse(output, expected_boot, revision):
    fields, mac, switch, samples = {}, {}, {}, []
    edges, relinks, mac_order, instant, worker, serial = [], [], [], [], [], []
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
        m = EDGE.match(line)
        if m:
            edges.append({"uptime":float(m[1]), "edge":int(m[2]), "link":int(m[3])})
        m = RELINK.match(line)
        if m:
            relinks.append({"uptime":float(m[1]),"action":m[2],"tuple":list(m.groups()[2:])})
        m = MAC_ORDER.match(line)
        if m:
            mac_order.append({"uptime":float(m[1]),"action":m[2]})
        m = INSTANT_FIFO.match(line)
        if m:
            ss=int(m[2],16)
            phylib,copper=int(m[3]),int(m[4])
            assert ss!=0xffff and copper==int(bool(ss&0x400))
            instant.append(dict(uptime=float(m[1]),status=ss,phylib=phylib,copper=copper))
        m = FIFO_WORKER.match(line)
        if m:
            t=float(m[1])
            tick,edge,ss,phylib,ret=map(int,m.groups()[1:])
            assert -4095<=ss<=65535 and ret<=0
            assert ret<0 or 0<=ss<65535
            assert not worker or (t>worker[-1]["uptime"] and tick>worker[-1]["tick"])
            worker.append(dict(uptime=t,tick=tick,edge=edge,status=ss,phylib=phylib,result=ret,
                               copper=int(bool(ss&0x400)) if 0<=ss<65535 else None))
        m = SERIAL_SPEED.match(line)
        if m:
            serial.append(dict(uptime=float(m[1]),mode=int(m[2],16),ctrl=int(m[3],16),
                               status=int(m[4],16),speed=int(m[5])))
        m = PHY.match(line)
        if m:
            samples.append(dict(zip(
                ("uptime", "sample", "edge", "link", "rx", "drx", "tx", "dtx", "rx_err", "tx_err"),
                (float(m[1]), *map(int, m.groups()[1:])),
            )))
    assert fields["boot"] == fields["end_boot"] == expected_boot
    assert fields["revision"] == revision and fields["management_peer"] == trunk.PATHS["switch"][0]
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
            "phy_edges": edges, "relink_events": relinks, "mac_order_events": mac_order,
            "instant_fifo_events": instant, "fifo_worker_events": worker, "serial_speed_events": serial,
            "noc": "NOC ERROR DETECTED" in output}


def snapshot(expected_boot, routes, revision):
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
            result["state"] = parse(result["stdout"], expected_boot, revision)
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
            try:
                out[name]["speed"] = (root / "speed").read_text().strip()
            except OSError:
                out[name]["speed"] = "absent"
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


def evaluate(window, prior_speed=None):
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
    if b.get("revision") in (CLOCK_REV,INSTANT_REV,*WORKER_REVISIONS):
        edge=b["phy"]["edge"]
        starts=[e for e in b["phy_edges"] if e["edge"]==edge and e["link"]==1]
        if len(starts)!=1 or any(r["host_counters"]["direct"].get("speed")!="1000" for r in window):
            return result
        if any(r["snapshot"]["state"]["phy"]["uptime"]<starts[0]["uptime"] for r in window):
            return result
        if b["revision"]==CLOCK_REV:
            result["clock_trial_edge"]=edge
        else:
            downs=[e for e in b["phy_edges"] if e["edge"]==edge-1 and e["link"]==0]
            if len(downs)!=1 or downs[0]["uptime"]>=starts[0]["uptime"]:
                return result
            down,up=downs[0]["uptime"],starts[0]["uptime"]
            events=b.get("instant_fifo_events",[])
            # Driver logs each change of the sampled pair after successful
            # FIFO write, before phylib's state-change notification.
            def decision(t,link):
                matches=[e for e in events if 0<=t-e["uptime"]<=2]
                latest=max(matches,key=lambda e:e["uptime"],default=None)
                return latest if latest and latest["phylib"]==link and latest["copper"]==int(bool(latest["status"]&0x400)) else None
            down_decision=decision(down,0)
            up_decision=decision(up,1)
            if not down_decision or not up_decision or down_decision["uptime"]>=up_decision["uptime"]:
                return result
            observed=[e for e in events if down-8<=e["uptime"]<=b["uptime"]]
            result["instant_fifo_edge"]=edge
            result["instant_fifo_down"]=down_decision
            result["instant_fifo_up"]=up_decision
            result["instant_fifo_transitions"]=observed
            result["instant_fifo_disagreements"]=[e for e in observed if e["phylib"]!=e["copper"]]
            if b["revision"]in WORKER_REVISIONS:
                worker=[e for e in b.get("fifo_worker_events",[]) if down-2<=e["uptime"]<=b["uptime"]]
                successful=[e for e in worker if e["result"]==0]
                during_down=[e for e in successful if down<=e["uptime"]<up and e["edge"]==edge-1]
                after_up=[e for e in successful if up<=e["uptime"] and e["edge"]==edge]
                result["worker_trial_edge"]=edge
                result["worker_down_ticks"]=during_down
                result["worker_up_ticks"]=len(after_up)
                result["worker_successful_ticks"]=len(successful)
                result["worker_errors"]=[e for e in worker if e["result"]!=0]
                result["worker_disagreements"]=[e for e in successful if e["phylib"]!=e["copper"]]
                result["worker_adjacent_gaps"]=[round(y["uptime"]-x["uptime"],6)
                    for x,y in zip(worker,worker[1:]) if y["tick"]==x["tick"]+1]
                result["worker_exercised"]=bool(during_down and len(after_up)>=3 and after_up[0]["uptime"]-up<=2.5)
                # Preserve the traffic result even if a worker tick was
                # not observed during this particular down window. Its
                # experiment coverage remains explicitly separate.
    if b.get("revision")==SERIAL_SPEED_REV:
        edge=b["phy"]["edge"]
        result["serial_speed_trial_edge"]=edge
        starts=[e for e in b["phy_edges"] if e["edge"]==edge and e["link"]==1]
        decisions=[e for e in b.get("serial_speed_events",[]) if len(starts)==1 and
                   starts[0]["uptime"]<=e["uptime"]<=starts[0]["uptime"]+4]
        result["serial_speed_events"]=decisions
        result["serial_speed_exercised"]=False
        if len(decisions)==1:
            e=decisions[0]
            result["serial_speed_exercised"]=bool(e["mode"]&0x1f71==0x420 and not e["ctrl"]&8
                and e["ctrl"]&0x800 and e["speed"]==1000
                and all(r["host_counters"]["direct"].get("speed")=="1000" for r in window))
            result["serial_speed_status_matches_phy"]=e["status"]&0x30==0x20
            result["serial_speed_pcs_carrier"]=bool(e["status"]&0x80)
    if b.get("revision") in RELINK_REVISIONS:
        # Tie the actual policy decision to this PHY edge, not a prior
        # successful mode transition. Require the host to agree on speed.
        edge=b["phy"]["edge"]
        starts=[e for e in b["phy_edges"] if e["edge"]==edge and e["link"]==1]
        if len(starts)!=1 or any(r["host_counters"]["direct"].get("speed")!="1000" for r in window):
            return result
        start=starts[0]["uptime"]
        decisions=[e for e in b["relink_events"] if start<=e["uptime"]<=start+4]
        result["relink_events"]=decisions
        if (len(decisions)!=2 or decisions[0]["action"] not in ("prepare","preserve")
                or decisions[0]["tuple"][0]!="1000" or decisions[1]["action"]!="committed"):
            return result
        result["relink_policy"]=decisions[0]["action"]
        if b.get("revision")==MAC_ORDER_REV:
            # Exact new up marker before this edge's PCS prepare, not
            # a stale marker from a preceding episode.
            up=[e for e in b.get("mac_order_events",[]) if start<=e["uptime"]<=decisions[0]["uptime"] and e["action"]=="TX off before prepare"]
            if len(up)!=1:
                return result
            result["mac_order_up"]=up[0]
            if prior_speed=="1000":
                # A same-speed trial must also prove the new down
                # sequence ran on the immediately preceding PHY edge.
                down=[e for e in b["phy_edges"] if e["edge"]==edge-1 and e["link"]==0]
                if len(down)!=1:
                    return result
                drains=[e for e in b["mac_order_events"] if down[0]["uptime"]<=e["uptime"]<start and e["action"]=="drained RX off TX retained"]
                if len(drains)!=1:
                    return result
                result["mac_order_down"]=drains[0]
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
    seen_up_edge=None
    def flush():
        nonlocal window
        if episode is not None and window:
            episode["windows"].append(evaluate(window, episode["prior_speed"]))
        window=[]
    for row in rows:
        s=row["snapshot"].get("state")
        if not s:
            flush()
            last_good=None
            continue
        if s.get("revision") in EDGE_REVISIONS:
            # Real kernel edges can occur entirely between snapshots.
            # Use the logged pair without treating pre-capture history
            # as a fresh event or claiming an unobserved healthy baseline.
            events=s.get("phy_edges",[])
            ups=[e for e in events if e["link"]==1]
            newest=max(ups,key=lambda e:e["edge"],default=None)
            if newest is not None:
                n=newest["edge"]
                if seen_up_edge is None:
                    # Already-present history at the first snapshot is
                    # not evidence of a fresh observed transition.
                    seen_up_edge=n
                elif n>seen_up_edge and s["carrier"]=="1" and newest["uptime"]<=s["uptime"]:
                    # Uptime/carrier are sampled before dmesg. A later
                    # log can contain the up edge even if the earlier
                    # sampled carrier is down. Consume it only on a
                    # coherent later snapshot, not on that mixed row.
                    downs=[e for e in events if e["link"]==0 and e["edge"]==n-1 and e["uptime"]<newest["uptime"]]
                    if len(downs)==1 and n==seen_up_edge+2:
                        flush()
                        down=downs[0]["uptime"]
                        if episode is None or episode["up"] is not None:
                            prior=last_good if last_good and 0<=down-last_good["uptime"]<=8 else None
                            episode={"down":down,"up":None,"prior_speed":prior and prior["speed"],"windows":[]}
                            episodes.append(episode)
                        episode.update(down=down,up=newest["uptime"],post_speed=s["speed"],edge_source="kernel_log")
                    seen_up_edge=n
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
        if s.get("revision") in EDGE_REVISIONS:
            # A matched trial requires observed healthy traffic before
            # the edge, with both ends agreeing on the initial speed.
            ready = (row["host_counters"]["direct"].get("speed")==s["speed"]
                     and all(row.get(k,{}).get(n,{}).get("valid",False)
                             for k in ("routes_before","routes_after") for n in trunk.PATHS)
                     and all(probe_count(row,n) is not None and probe_count(row,n)[0]==probe_count(row,n)[1]
                             for n in trunk.PATHS))
            if ready:
                last_good=s
            elif last_good and (s["speed"]!=last_good["speed"] or s["uptime"]-last_good["uptime"]>8):
                last_good=None
        else:
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
        if e["classification"]=="ONE_GIG_RECONNECT_PASS":
            if e["prior_speed"] is None and any(any(k in w for k in ("relink_policy","clock_trial_edge","instant_fifo_edge","serial_speed_trial_edge")) for w in e["windows"]):
                e["classification"]="ONE_GIG_UP_WITHOUT_HEALTHY_BASELINE"
            elif e["prior_speed"]!="1000":
                e["classification"]="ONE_GIG_TRANSITION_PASS"
            elif any(w.get("relink_policy")=="prepare" for w in e["windows"] if w["classification"]=="ONE_GIG_RECONNECT_PASS"):
                e["classification"]="ONE_GIG_RECONNECT_FULL_PREPARE"
    return {"episodes":episodes,"classification":episodes[-1]["classification"] if episodes else "NO_CARRIER_EDGE_OBSERVED"}

def capture(out, boot, duration, profile):
    revision, directory=PROFILES[profile]
    base=trunk.BASE / directory / "observations"
    assert os.getuid() != 0 and trunk.BOOT.fullmatch(boot)
    assert 35 <= duration <= 240 and out.parent.resolve() == base.resolve()
    base.mkdir(mode=0o700,exist_ok=True)
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
                 "probes":probes,"host_counters":host_counters(),"snapshot":snapshot(boot,after,revision)}
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
    rows=[row(1),row(3,"0")]+[row(t) for t in range(12,58,2)]
    for r in rows:
        s=r["snapshot"]["state"]
        s.update(revision=RELINK_REV,phy_edges=[{"edge":3,"link":1,"uptime":11}],
                 relink_events=[{"uptime":11.1,"action":"preserve","tuple":["1000","1","1","1"]},
                                {"uptime":11.2,"action":"committed","tuple":[None]*4}])
        r["host_counters"]["direct"]["speed"]="1000"
    assert report(rows)["classification"]=="ONE_GIG_RECONNECT_PASS"
    rows[0]["host_counters"]["direct"]["speed"]="2500"
    assert report(rows)["classification"]=="ONE_GIG_UP_WITHOUT_HEALTHY_BASELINE"
    rows[0]["host_counters"]["direct"]["speed"]="1000"
    for r in rows:
        r["snapshot"]["state"]["relink_events"][0]["action"]="prepare"
    assert report(rows)["classification"]=="ONE_GIG_RECONNECT_FULL_PREPARE"
    for r in rows:
        r["snapshot"]["state"]["relink_events"][0]["uptime"]=9
    assert report(rows)["classification"]=="INCONCLUSIVE"
    # Stock serial speed is a separate intervention qualification,
    # not a prerequisite to reporting actual delivered/lost traffic.
    for stall in (False,True):
        rows=[row(1),row(3,"0")]+[row(t,stall=stall) for t in range(12,58,2)]
        for r in rows:
            st=r["snapshot"]["state"]
            st.update(revision=SERIAL_SPEED_REV,
                      phy_edges=[{"edge":2,"link":0,"uptime":3},{"edge":3,"link":1,"uptime":11}],
                      serial_speed_events=[{"uptime":11.1,"mode":0x420,"ctrl":0x846,"status":0x60,"speed":1000}])
            r["host_counters"]["direct"]["speed"]="1000"
        w=report(rows)["episodes"][-1]["windows"][-1]
        assert w["serial_speed_exercised"] and w["serial_speed_status_matches_phy"] and not w["serial_speed_pcs_carrier"]
        for field,value in (("ctrl",0x84e),("mode",0x421),("speed",100),("uptime",1)):
            for r in rows:
                events=r["snapshot"]["state"]["serial_speed_events"]
                events[0]={"uptime":11.1,"mode":0x420,"ctrl":0x846,"status":0x60,"speed":1000}
                events[0][field]=value
            w=report(rows)["episodes"][-1]["windows"][-1]
            assert not w["serial_speed_exercised"]
            assert w["classification"]==("COPPER_RX_WITH_GMAC_RX_STALL" if stall else "ONE_GIG_RECONNECT_PASS")
    # A carrier flap between snapshots is still observed when the
    # driver records its complete fresh adjacent edge pair.
    rows=[row(3)]+[row(t) for t in range(12,58,2)]
    for i,r in enumerate(rows):
        st=r["snapshot"]["state"]
        st.update(revision=RELINK_REV,phy_edges=[{"edge":1,"link":1,"uptime":0.5}],relink_events=[])
        r["host_counters"]["direct"]["speed"]="1000"
        if i:
            st["phy_edges"] += [{"edge":2,"link":0,"uptime":9},{"edge":3,"link":1,"uptime":11}]
            st["relink_events"]=[{"uptime":11.1,"action":"preserve","tuple":["1000","1","1","1"]},{"uptime":11.2,"action":"committed","tuple":[None]*4}]
    result=report(rows)
    assert result["classification"]=="ONE_GIG_RECONNECT_PASS",result
    assert result["episodes"][0]["edge_source"]=="kernel_log"
    # A burst can straddle the start of an autoneg transition while
    # the router still reports the previous speed. Retain a recent
    # verified baseline, rather than mistaking that burst for a new one.
    import copy
    prior=copy.deepcopy(rows[0]); prior["snapshot"]["state"]["uptime"]=5
    partial=copy.deepcopy(prior); partial["snapshot"]["state"]["uptime"]=8
    partial["host_counters"]["direct"]["speed"]="-1"
    partial["probes"]["direct"]["received"]=2
    assert report([prior,partial]+rows[1:])["classification"]=="ONE_GIG_RECONNECT_PASS"
    assert report(rows[1:])["classification"]=="NO_CARRIER_EDGE_OBSERVED"
    mixed=copy.deepcopy(rows[1])
    mixed["snapshot"]["state"].update(carrier="0",uptime=10.5)
    mixed["probes"]["direct"]["received"]=0
    mixed["host_counters"]["direct"]["speed"]="-1"
    result=report([rows[0],mixed]+rows[1:])
    assert result["classification"]=="ONE_GIG_RECONNECT_PASS",result
    assert len(result["episodes"])==1
    e=result["episodes"][0]
    assert (e["down"],e["up"],e["edge_source"])==(9,11,"kernel_log"),e
    # 0493 additionally requires a fresh MAC gate marker and, for a
    # matched same-speed reconnect, the previous edge's drain marker.
    ordered=copy.deepcopy(rows)
    for i,r in enumerate(ordered):
        st=r["snapshot"]["state"]
        st["revision"]=MAC_ORDER_REV
        st["mac_order_events"]=[]
        if i:
            st["mac_order_events"]=[
                {"uptime":9.02,"action":"drained RX off TX retained"},
                {"uptime":11.05,"action":"TX off before prepare"}]
    assert report(ordered)["classification"]=="ONE_GIG_RECONNECT_PASS"
    for marker in ("TX off before prepare","drained RX off TX retained"):
        invalid=copy.deepcopy(ordered)
        for r in invalid:
            st=r["snapshot"]["state"]
            st["mac_order_events"]=[e for e in st["mac_order_events"] if e["action"]!=marker]
        assert report(invalid)["classification"]=="INCONCLUSIVE"
    for r in ordered[1:]:
        r["snapshot"]["state"]["mac_order_events"][1]["uptime"]=10.9
    assert report(ordered)["classification"]=="INCONCLUSIVE"
    # 0494 is based on 0491: require real PHY edges but never require
    # 0492/0493-only PCS policy markers.
    clock=copy.deepcopy(rows)
    for r in clock:
        st=r["snapshot"]["state"]
        st["revision"]=CLOCK_REV
        st["relink_events"]=[]
    assert report(clock)["classification"]=="ONE_GIG_RECONNECT_PASS",report(clock)
    assert report(clock[1:])["classification"]=="NO_CARRIER_EDGE_OBSERVED"
    clock[0]["host_counters"]["direct"]["speed"]="2500"
    assert report(clock)["classification"]=="ONE_GIG_UP_WITHOUT_HEALTHY_BASELINE"
    # 0495 uses the same proven edge-pair handling but also demands
    # the actual successful FIFO decisions preceding both notifications.
    instant=copy.deepcopy(rows)
    for i,r in enumerate(instant):
        st=r["snapshot"]["state"]
        st["revision"]=INSTANT_REV
        st["relink_events"]=[]
        st["instant_fifo_events"]=[dict(uptime=0.4,status=0x400,phylib=1,copper=1)]
        if i:
            st["instant_fifo_events"] += [
                dict(uptime=8.99,status=0x400,phylib=0,copper=1),
                dict(uptime=9.6,status=0,phylib=0,copper=0),
                dict(uptime=10.99,status=0x400,phylib=1,copper=1)]
    result=report(instant)
    assert result["classification"]=="ONE_GIG_RECONNECT_PASS",result
    w=result["episodes"][0]["windows"][-1]
    assert len(w["instant_fifo_disagreements"])==1
    assert w["instant_fifo_down"]["copper"]==1
    for event in (1,3):
        invalid=copy.deepcopy(instant)
        for r in invalid[1:]:
            del r["snapshot"]["state"]["instant_fifo_events"][event]
        assert report(invalid)["classification"]=="INCONCLUSIVE"
    for r in instant[1:]:
        r["snapshot"]["state"]["instant_fifo_events"][1]["copper"]=0
    # The actual input bit is verified; malformed events cannot prove policy.
    assert report(instant)["classification"]=="INCONCLUSIVE"
    worker=copy.deepcopy(instant)
    for i,r in enumerate(worker):
        st=r["snapshot"]["state"]
        st["revision"]=WORKER_REV
        st["instant_fifo_events"][1 if i else 0]["copper"]=1
        st["fifo_worker_events"]=[]
        if i:
            st["fifo_worker_events"]=[dict(uptime=float(t)+0.2,tick=t,edge=2 if t<11 else 3,
                status=0 if t<11 else 0x400,phylib=int(t>=11),copper=int(t>=11),result=0)
                for t in range(9,int(st["uptime"]))]
    result=report(worker)
    assert result["classification"]=="ONE_GIG_RECONNECT_PASS",result
    assert result["episodes"][0]["windows"][-1]["worker_exercised"]
    for r in worker:
        st=r["snapshot"]["state"]
        st["fifo_worker_events"]=[e for e in st["fifo_worker_events"] if e["edge"]!=2]
    result=report(worker)
    assert result["classification"]=="ONE_GIG_RECONNECT_PASS" and not result["episodes"][0]["windows"][-1]["worker_exercised"]
    print("PHY_RECONNECT_SELFTEST_PASS")


if __name__ == "__main__":
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest="cmd",required=True)
    sub.add_parser("selftest")
    c=sub.add_parser("capture"); c.add_argument("out",type=Path); c.add_argument("boot"); c.add_argument("--duration",type=int,default=90); c.add_argument("--profile",choices=PROFILES,required=True)
    r=sub.add_parser("report"); r.add_argument("raw",type=Path)
    args=p.parse_args()
    if args.cmd=="selftest":
        selftest()
    elif args.cmd=="capture":
        capture(args.out,args.boot,args.duration,args.profile)
    else:
        print(json.dumps(report([json.loads(l) for l in args.raw.read_text().splitlines()]),indent=2))
