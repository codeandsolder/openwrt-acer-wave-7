#!/usr/bin/env python3
"""Qualify a sealed 0498 cold/late first-link trial, not just boot acceptance."""
import argparse
import csv
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location(
    "reconnect", Path(__file__).with_name("probe-phy-reconnect.py"))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

REV = probe.SERIAL_SPEED_REV
PCS = "6e1293e83985caf4eb352e163036d050de5eb2d3f4272ca8a2a71667833658bf"
BUILDER = "bcaae0c7eac821a46fdfdecd1dad4f6ad13adbf9"
PHY_PREFIX = r"^\[\s*(\d+\.\d+)\] Qualcomm QCA8081 90000\.mdio-1:18: wave7-diag: "
STATUS = re.compile(PHY_PREFIX + r"status\[(\d+)\] state=(\d+) link=([01]) speed=(-?\d+) interface=(\S+) master_slave=(\d+)$")
PHY_EDGE = re.compile(PHY_PREFIX + r"phy-path edge=(\d+) link=([01]) ")
PHY_SAMPLE = re.compile(PHY_PREFIX + r"phy-path sample=(\d+) edge=(\d+) link=([01]) rx=(\d+) drx=(\d+) tx=(\d+) dtx=(\d+) rx_err=(\d+) tx_err=(\d+)$")
SERIAL = re.compile(r"^\[\s*(\d+\.\d+)\] ipq9574_pcs 7a10000\.ethernet-pcs: wave7-diag: serial-speed mode=(0x[0-9a-f]+) ctrl=(0x[0-9a-f]+) sts=(0x[0-9a-f]+|0) speed=(\d+)$")

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def sealed(directory, name, required):
    entries = {}
    for line in (directory/name).read_text().splitlines():
        digest, file = line.split("  ", 1)
        assert re.fullmatch(r"[0-9a-f]{64}", digest) and Path(file).name == file and file not in entries
        assert sha(directory/file) == digest, f"bad digest: {file}"
        entries[file] = digest
    assert set(required) <= entries.keys(), "missing evidence"
    return entries

def fields(path):
    d = {}
    for line in path.read_text().splitlines():
        key, val = line.split("=", 1)
        assert key not in d
        d[key] = val
    return d

def first_link(log, expected):
    assert "NOC ERROR DETECTED" not in log
    status, edges, samples, markers = [], [], [], []
    for line in log.splitlines():
        if m := STATUS.match(line):
            t, seq, state, link, speed, interface, ms = m.groups()
            status.append(dict(t=float(t), seq=int(seq), state=int(state),
                               link=int(link), speed=int(speed), interface=interface,
                               master_slave=int(ms)))
        if m := PHY_EDGE.match(line):
            t, edge, link = m.groups()
            edges.append(dict(t=float(t), edge=int(edge), link=int(link)))
        if m := PHY_SAMPLE.match(line):
            t, sample, edge, link, rx, drx, tx, dtx, rxerr, txerr = m.groups()
            samples.append(dict(t=float(t), sample=int(sample), edge=int(edge), link=int(link),
                                rx=int(rx), tx=int(tx), rxerr=int(rxerr), txerr=int(txerr)))
        if m := SERIAL.match(line):
            t, mode, ctrl, sts, speed = m.groups()
            markers.append(dict(t=float(t), mode=int(mode,16), ctrl=int(ctrl,16),
                                status=int(sts,16), speed=int(speed)))
    # Diagnostic patch 0473 logs exactly the first three status polls.
    # A genuinely late carrier cannot have an up status in that window.
    # Patch 0481's uncapped link notifier and the matched PCS marker are
    # independent, source-backed first-up evidence after those polls.
    assert [v["seq"] for v in status] == [1, 2, 3], "incomplete initial PHY polls"
    assert all(y["t"] > x["t"] for x,y in zip(status,status[1:])), "ambiguous PHY poll history"
    ups = [e for e in edges if e["link"]]
    assert len(ups) == 1 and len(edges) == (2 if status[0]["link"] == 0 else 1), "later flap or missing first edge"
    assert [e["edge"] for e in edges] == list(range(1, len(edges)+1)), "missing initial link history"
    assert edges[0]["link"] == status[0]["link"] and 0 <= edges[0]["t"]-status[0]["t"] <= 2
    edge = ups[0]
    up_status = next((v for v in status if v["link"]), None)
    for v in status:
        if v["link"]:
            assert v["speed"] == 1000 and v["interface"] == "sgmii", "initial PHY poll not 1G SGMII"
        else:
            assert v["t"] < edge["t"], "down poll after first up edge"
    if up_status is not None:
        assert 0 <= edge["t"]-up_status["t"] <= 2, "driver edge not matched to first up poll"
    else:
        assert status[-1]["t"] < edge["t"], "first up edge not after initial down polls"
    up = {"t":edge["t"],"evidence":"phy-link-notifier"}
    assert len(markers) == 1, "missing/ambiguous first-link PCS marker"
    m = markers[0]
    assert 0 <= m["t"]-edge["t"] <= 4 and m["speed"] == 1000
    assert m["mode"] & 0x1f71 == 0x420 and not m["ctrl"] & 8 and m["ctrl"] & 0x800
    assert m["status"] & 0x30 == 0x20 and m["status"] & 0x80, "PCS speed/carrier disagrees"
    if expected == "delayed":
        assert not status[0]["link"] and up["t"] >= 35 and up["t"]-status[0]["t"] >= 20, "delay not exercised"
    else:
        assert up["t"] < 35, "first link unexpectedly late"
    points = [s for s in samples if s["edge"] == edge["edge"] and s["link"] and s["t"] >= edge["t"]]
    assert len(points) >= 2 and points[-1]["t"]-points[0]["t"] >= 20, "insufficient first-edge PHY counter coverage"
    for x,y in zip(points,points[1:]):
        assert y["t"] > x["t"] and y["sample"] > x["sample"]
        assert all(y[k] >= x[k] for k in ("rx","tx","rxerr","txerr"))
    delta = {k: points[-1][k]-points[0][k] for k in ("rx","tx","rxerr","txerr")}
    assert delta["rx"] > 0 and delta["tx"] > 0 and not delta["rxerr"] and not delta["txerr"], "first-edge bidirectional PHY traffic not clean"
    return dict(initial_status=status,first_up=up,first_up_status=up_status,edge=edge,marker=m,
                phy_samples=len(points),phy_delta=delta)

def peer_window(log, expected):
    events = []
    for line in log.splitlines():
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2}T\S+) (PEER_\S+)(?: mode=(fast|delayed))?", line)
        if m:
            events.append((dt.datetime.fromisoformat(m[1]), m[2], m[3]))
    assert all(t.tzinfo is not None for t,_,_ in events), "peer timestamps lack offsets"
    assert all(x[0] <= y[0] for x,y in zip(events,events[1:])), "peer timestamps out of order"
    ready = [e for e in events if e[1] == "PEER_READY"]
    assert len(ready) == 1 and ready[0][2] == expected, "wrong peer window"
    names = [e[1] for e in events]
    if expected == "delayed":
        assert names == ["PEER_READY","PEER_CARRIER_FELL","PEER_PHY_DOWN","PEER_PHY_HOLD_VERIFIED","PEER_PHY_RELEASED_1G"], "missing/failed delay hold proof"
        seconds = (events[-1][0]-events[2][0]).total_seconds()
        verified = (events[-2][0]-events[2][0]).total_seconds()
        assert 64 <= verified <= seconds, "PHY hold not continuously verified"
        assert 64 <= seconds <= 90, "unexpected hold duration"
    else:
        assert names == ["PEER_READY"], "unexpected peer event"
        seconds = 0
    return dict(mode=expected,phy_down_seconds=seconds,events=[(t.isoformat(),n) for t,n,_ in events])

def correlate_peer_boot(counter_log, boot, peer, link):
    # Both wall_epoch and peer timestamps come from the Asus observer.
    # Router uptime is integer-truncated, and the SSH observation has
    # sampling latency; allow a bounded clock envelope, not arbitrary
    # independent wall/uptime evidence.
    rows = list(csv.DictReader(counter_log.splitlines(), delimiter="\t"))
    assert len(rows) >= 2 and all(r["boot"] == boot for r in rows), "wrong boot in counter history"
    times = [(int(r["wall_epoch"]), int(r["uptime"])) for r in rows]
    assert all(a < c and b < d for (a,b),(c,d) in zip(times,times[1:])), "counter clock not monotonic"
    offsets = [wall-uptime for wall,uptime in times]
    assert max(offsets)-min(offsets) <= 5, "counter clock alignment unstable"
    lo, hi = min(offsets)-3, max(offsets)+3
    events = {name: dt.datetime.fromisoformat(t).timestamp() for t,name in peer["events"]}
    ready = events["PEER_READY"]
    assert hi-300 <= ready <= lo, "peer ready is not from the observed reboot"
    if peer["mode"] == "delayed":
        down = events["PEER_PHY_DOWN"]
        release = events["PEER_PHY_RELEASED_1G"]
        first = link["initial_status"][0]["t"]
        up = link["first_up"]["t"]
        assert hi-60 <= events["PEER_CARRIER_FELL"] <= lo+first, "carrier loss not tied to reboot"
        assert down <= lo+first and release >= hi+first, "first PHY-down observation not inside peer hold"
        assert release <= hi+up, "first PHY-up preceded peer release"
    return dict(boot_epoch_bounds=[lo,hi], clock_offset_spread=max(offsets)-min(offsets),
                peer_ready_before_boot_bounds=[lo-ready,hi-ready])

def traffic(directory, boot, min_uptime):
    sealed(directory, "SHA256SUMS", ("samples.jsonl","report.json"))
    rows = [json.loads(line) for line in (directory/"samples.jsonl").read_text().splitlines()]
    assert len(rows) >= 2
    states = []
    totals = dict.fromkeys(probe.trunk.PATHS,0)
    for row in rows:
        raw = row["snapshot"]
        assert raw["rc"] == 0
        s = probe.parse(raw["stdout"],boot,REV)
        assert s == raw["state"] and probe.state_good(s) and s["speed"] == "1000"
        assert s["uptime"] >= min_uptime
        assert row["host_counters"]["direct"]["speed"] == "1000"
        assert row["host_counters"]["switch"]["speed"] == "1000"
        assert len([e for e in s["phy_edges"] if e["link"] == 1]) == 1
        for n,(ip,dev,_) in probe.trunk.PATHS.items():
            for key in ("routes_before","routes_after"):
                route=row[key][n]
                assert route["valid"] and route["route"]["dev"] == dev and route["route"]["from"] == ip
            p=row["probes"][n]
            assert p["binding"] == dict(device=dev,source=ip) and p["sent"] == p["received"] == 4 and p["rc"] == 0
            totals[n]+=p["received"]
        states.append(s)
    assert states[-1]["uptime"]-states[0]["uptime"] >= 30
    assert all(0 < y["uptime"]-x["uptime"] <= 8 for x,y in zip(states,states[1:]))
    mac = {k: states[-1]["mac"][k]-states[0]["mac"][k] for k in probe.MAC_KEYS}
    errors={k:states[-1]["switch_errors"][k]-states[0]["switch_errors"][k] for k in states[0]["switch_errors"]}
    assert mac["rx_frames"] > 0 and mac["tx_frames"] > 0 and not any(mac[k] for k in probe.MAC_KEYS[2:]) and not any(errors.values())
    return dict(samples=len(states),elapsed=states[-1]["uptime"]-states[0]["uptime"],
                probe_totals=totals,mac_delta=mac,switch_error_delta=errors)

def qualify(run, capture, peer_log, expected):
    sealed(run, "evidence.sha256", ("status","report.json","latest-state.txt","preflight.txt","final-dmesg.txt","final-hardware.txt","reboot.log","trunk-counters.tsv","attestation-success.log"))
    assert (run/"status").read_text().strip() == "SOAK_PASS"
    s = fields(run/"latest-state.txt")
    old = fields(run/"preflight.txt")
    boot = s["boot"]
    assert old["boot"] != boot and old["rev"] == s["rev"] == REV
    for key,val in {"rev":REV,"builder_commit":BUILDER,"pcs_sha":PCS,"pcs_rom_sha":PCS,
                    "manifest_pcs_sha":PCS,"lan_speed":"1000","direct_peer_speed":"1000",
                    "approval":"0","token":"1","bootfail":"0","keep":"1",
                    "ap":"2","q6":"3","direct_verified":"1","switch_verified":"1"}.items():
        assert s[key]==val, f"wrong final state: {key}"
    final=(run/"final-hardware.txt").read_text().splitlines()
    assert final[0]==boot and final[2]==REV and final[3]=="0"
    assert "LOCAL_READY" in final
    soak=json.loads((run/"report.json").read_text())
    assert soak["boot"]==boot and soak["status"]=="SOAK_PASS" and soak["soak_seconds"]>=300
    assert not soak["postcommit_switch_misses"] and not soak["error_deltas"]
    assert soak["classification"]=="CLEAN_BOOT_NO_CORRUPTION_OBSERVED"
    link=first_link((run/"final-dmesg.txt").read_text(),expected)
    peer=peer_window(peer_log.read_text(),expected)
    alignment=correlate_peer_boot((run/"trunk-counters.tsv").read_text(),boot,peer,link)
    return dict(status="COLD_1G_PASS",boot=boot,revision=REV,
                expected=expected,soak_seconds=soak["soak_seconds"],
                first_link=link, peer=peer, peer_boot_alignment=alignment,
                traffic=traffic(capture,boot,float(final[1].split()[0])),
                inputs=dict(run_manifest_sha256=sha(run/"evidence.sha256"),capture_manifest_sha256=sha(capture/"SHA256SUMS"),peer_log_sha256=sha(peer_log)))

def selftest():
    def log(up):
        prefix = "Qualcomm QCA8081 90000.mdio-1:18: wave7-diag: "
        def poll(t, seq, link):
            return f"[{t:.6f}] {prefix}status[{seq}] state=6 link={link} speed={1000 if link else -1} interface=sgmii master_slave={3 if link else 1}"
        # Initial three polls can be exhausted long before the up edge.
        rows = [
            poll(15.1,1,0),
            f"[15.110000] {prefix}phy-path edge=1 link=0 fifo_action=stock_status_poll",
            poll(16,2,int(up <= 16)),
            poll(17,3,int(up <= 17)),
            f"[{up+.02:.6f}] {prefix}phy-path edge=2 link=1 fifo_action=stock_status_poll",
            f"[{up+.08:.6f}] ipq9574_pcs 7a10000.ethernet-pcs: wave7-diag: serial-speed mode=0x420 ctrl=0x844 sts=0xef speed=1000",
            f"[{up+1:.6f}] {prefix}phy-path sample=1 edge=2 link=1 rx=46 drx=27 tx=7 dtx=7 rx_err=0 tx_err=0",
            f"[{up+40:.6f}] {prefix}phy-path sample=40 edge=2 link=1 rx=146 drx=27 tx=107 dtx=7 rx_err=0 tx_err=0",
        ]
        return "\n".join(sorted(rows,key=lambda x:float(x.split("]")[0][1:])))
    assert first_link(log(16),"fast")["phy_delta"]["tx"]==100
    assert first_link(log(16),"fast")["first_up_status"]["seq"]==2
    assert first_link(log(62),"delayed")["first_up"]["t"]==62.02
    assert first_link(log(62),"delayed")["first_up_status"] is None
    def rejects(fn,*args):
        try: fn(*args)
        except AssertionError: return
        raise AssertionError("invalid fixture accepted")
    rejects(first_link,log(16),"delayed")
    rejects(first_link,log(62),"fast")
    for a,b in (("ctrl=0x844","ctrl=0x84c"),("mode=0x420","mode=0x421"),
                ("sts=0xef","sts=0x60"),("tx=107","tx=7"),("status[1]","status[3]"),
                ("phy-path edge=2","phy-path edge=3")):
        rejects(first_link,log(62).replace(a,b),"delayed")
    rejects(first_link,log(16).replace("speed=1000 interface=sgmii","speed=2500 interface=2500base-x"),"fast")
    rejects(first_link,log(62).replace("status[3] state=6 link=0","status[3] state=6 link=1"),"delayed")
    peer="""2026-11-22T05:00:00+01:00 PEER_READY mode=delayed
2026-11-22T05:00:10+01:00 PEER_CARRIER_FELL
2026-11-22T05:00:11+01:00 PEER_PHY_DOWN
2026-11-22T05:01:16+01:00 PEER_PHY_HOLD_VERIFIED
2026-11-22T05:01:16+01:00 PEER_PHY_RELEASED_1G"""
    assert peer_window(peer,"delayed")["phy_down_seconds"]==65
    rejects(peer_window,peer.replace("05:01:16","05:00:16"),"delayed")
    rejects(peer_window,peer.replace("PEER_PHY_RELEASED_1G","PEER_PHY_HOLD_LOST"),"delayed")
    epoch=int(dt.datetime.fromisoformat("2026-11-22T05:00:15+01:00").timestamp())
    counters=f"wall_epoch\tboot\tuptime\n{epoch+22}\tb\t22\n{epoch+27}\tb\t27"
    delayed=peer_window(peer,"delayed")
    # Release at boot+61; first up at boot+62, with coarse clock uncertainty.
    assert correlate_peer_boot(counters,"b",delayed,first_link(log(62),"delayed"))["clock_offset_spread"]==0
    rejects(correlate_peer_boot,counters,"b",delayed,first_link(log(42),"delayed"))
    rejects(correlate_peer_boot,counters,"b",peer_window(peer.replace("05:00:", "04:00:").replace("05:01:", "04:01:"),"delayed"),first_link(log(62),"delayed"))
    rejects(correlate_peer_boot,counters.replace(str(epoch+27),str(epoch+37)),"b",delayed,first_link(log(62),"delayed"))
    rejects(correlate_peer_boot,counters.replace("\tb\t27","\tc\t27"),"b",delayed,first_link(log(62),"delayed"))
    print("COLD_1G_QUALIFIER_SELFTEST_PASS")

if __name__ == "__main__":
    assert __debug__
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="command",required=True)
    sub.add_parser("selftest")
    q=sub.add_parser("qualify")
    q.add_argument("run",type=Path)
    q.add_argument("capture",type=Path)
    q.add_argument("peer_log",type=Path)
    q.add_argument("--expect",choices=("fast","delayed"),required=True)
    a=p.parse_args()
    if a.command=="selftest": selftest()
    else: print(json.dumps(qualify(a.run,a.capture,a.peer_log,a.expect),indent=2))
