#!/usr/bin/env python3
"""Qualify a sealed 0498 cold/late first-link trial, not just boot acceptance."""
import argparse
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
    assert status and status[0]["seq"] == 1, "first PHY status not captured"
    assert all(y["seq"] > x["seq"] and y["t"] > x["t"] for x,y in zip(status,status[1:])), "ambiguous PHY status history"
    up = next((s for s in status if s["link"]), None)
    assert up and up["speed"] == 1000 and up["interface"] == "sgmii", "first copper-up not 1G SGMII"
    ups = [e for e in edges if e["link"]]
    assert len(ups) == 1 and len(edges) == (2 if status[0]["link"] == 0 else 1), "later flap or missing first edge"
    edge = ups[0]
    assert 0 <= edge["t"]-up["t"] <= 2, "driver edge not matched to first status"
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
    return dict(first_status=status[0],first_up=up,edge=edge,marker=m,
                phy_samples=len(points),phy_delta=delta)

def peer_window(log, expected):
    events = []
    for line in log.splitlines():
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2}T\S+) (PEER_\S+)(?: mode=(fast|delayed))?", line)
        if m:
            events.append((dt.datetime.fromisoformat(m[1]), m[2], m[3]))
    ready = [e for e in events if e[1] == "PEER_READY"]
    assert len(ready) == 1 and ready[0][2] == expected, "wrong peer window"
    names = [e[1] for e in events]
    if expected == "delayed":
        assert names == ["PEER_READY","PEER_CARRIER_FELL","PEER_ADMIN_DOWN","PEER_RELEASED_1G"], "missing/failed delay hold proof"
        seconds = (events[-1][0]-events[-2][0]).total_seconds()
        assert 64 <= seconds <= 90, "unexpected hold duration"
    else:
        assert names == ["PEER_READY"], "unexpected peer event"
        seconds = 0
    return dict(mode=expected,admin_down_seconds=seconds,events=[(t.isoformat(),n) for t,n,_ in events])

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
    return dict(status="COLD_1G_PASS",boot=boot,revision=REV,
                expected=expected,soak_seconds=soak["soak_seconds"],
                first_link=first_link((run/"final-dmesg.txt").read_text(),expected),
                peer=peer_window(peer_log.read_text(),expected),
                traffic=traffic(capture,boot,float(final[1].split()[0])),
                inputs=dict(run_manifest_sha256=sha(run/"evidence.sha256"),capture_manifest_sha256=sha(capture/"SHA256SUMS"),peer_log_sha256=sha(peer_log)))

def selftest():
    def log(up):
        return f"""[   15.100000] Qualcomm QCA8081 90000.mdio-1:18: wave7-diag: status[1] state=4 link=0 speed=-1 interface=sgmii master_slave=1
[   15.110000] Qualcomm QCA8081 90000.mdio-1:18: wave7-diag: phy-path edge=1 link=0 fifo_action=stock_status_poll
[   {up:.6f}] Qualcomm QCA8081 90000.mdio-1:18: wave7-diag: status[2] state=6 link=1 speed=1000 interface=sgmii master_slave=3
[   {up+.02:.6f}] Qualcomm QCA8081 90000.mdio-1:18: wave7-diag: phy-path edge=2 link=1 fifo_action=stock_status_poll
[   {up+.08:.6f}] ipq9574_pcs 7a10000.ethernet-pcs: wave7-diag: serial-speed mode=0x420 ctrl=0x844 sts=0xef speed=1000
[   {up+1:.6f}] Qualcomm QCA8081 90000.mdio-1:18: wave7-diag: phy-path sample=1 edge=2 link=1 rx=46 drx=27 tx=7 dtx=7 rx_err=0 tx_err=0
[   {up+40:.6f}] Qualcomm QCA8081 90000.mdio-1:18: wave7-diag: phy-path sample=40 edge=2 link=1 rx=146 drx=27 tx=107 dtx=7 rx_err=0 tx_err=0"""
    assert first_link(log(16),"fast")["phy_delta"]["tx"]==100
    assert first_link(log(62),"delayed")["first_up"]["t"]==62
    def rejects(fn,*args):
        try: fn(*args)
        except AssertionError: return
        raise AssertionError("invalid fixture accepted")
    rejects(first_link,log(16),"delayed")
    rejects(first_link,log(62),"fast")
    for a,b in (("ctrl=0x844","ctrl=0x84c"),("mode=0x420","mode=0x421"),
                ("sts=0xef","sts=0x60"),("tx=107","tx=7"),("status[1]","status[3]"),
                ("speed=1000 interface=sgmii","speed=2500 interface=2500base-x")):
        rejects(first_link,log(62).replace(a,b),"delayed")
    peer="""2026-11-22T05:00:00+01:00 PEER_READY mode=delayed
2026-11-22T05:00:10+01:00 PEER_CARRIER_FELL
2026-11-22T05:00:11+01:00 PEER_ADMIN_DOWN
2026-11-22T05:01:16+01:00 PEER_RELEASED_1G"""
    assert peer_window(peer,"delayed")["admin_down_seconds"]==65
    rejects(peer_window,peer.replace("05:01:16","05:00:16"),"delayed")
    rejects(peer_window,peer.replace("PEER_RELEASED_1G","PEER_UNEXPECTED_ADMIN_UP"),"delayed")
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
