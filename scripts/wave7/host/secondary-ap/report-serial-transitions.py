#!/usr/bin/env python3
"""Qualify genuine 0498 speed changes/reconnects from sealed raw observations."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location(
    "cold", Path(__file__).with_name("report-cold-1g.py"))
cold=importlib.util.module_from_spec(spec)
spec.loader.exec_module(cold)
probe=cold.probe
RATES={"10":0,"100":0x10,"1000":0x20,"2500":None}

def decode_marker(marker,speed):
    return (marker["speed"]==int(speed) and
            marker["mode"]&0x1f71==0x420 and not marker["ctrl"]&8 and
            marker["ctrl"]&0x800 and marker["status"]&0xc0==0xc0 and
            marker["status"]&0x30==RATES[speed])

def physical(row,speed):
    """Both routes, devices, source addresses, carriers and negotiated rates."""
    s=row["snapshot"].get("state")
    try:
        if not probe.state_good(s) or s["speed"]!=speed: return False
        for n,(ip,dev,_) in probe.trunk.PATHS.items():
            if row["host_counters"][n]["speed"]!=(speed if n=="direct" else "1000"): return False
            if row["host_counters"][n]["carrier"]!="1": return False
            for key in ("routes_before","routes_after"):
                r=row[key][n]
                if not r["valid"] or r["route"]["dev"]!=dev or r["route"]["from"]!=ip: return False
            p=row["probes"][n]
            if p["binding"]!=dict(device=dev,source=ip) or p["sent"]!=4 or not 0<=p["received"]<=4: return False
        return row["probes"]["switch"]["received"]==4
    except (KeyError,TypeError):
        return False

def good_window(window, speed, edge, up):
    if len(window)<2: return None
    first, last=(r["snapshot"]["state"] for r in (window[0],window[-1]))
    elapsed=last["uptime"]-first["uptime"]
    if elapsed<30: return None
    totals={n:[sum(r["probes"][n][k] for r in window[1:]) for k in ("sent","received")] for n in probe.trunk.PATHS}
    mac={k:last["mac"][k]-first["mac"][k] for k in probe.MAC_KEYS}
    phy={k:last["phy"][k]-first["phy"][k] for k in ("rx","tx","rx_err","tx_err")}
    errors={k:last["switch_errors"][k]-first["switch_errors"][k] for k in first["switch_errors"]}
    peer_tx=window[-1]["host_counters"]["direct"]["tx_packets"]-window[0]["host_counters"]["direct"]["tx_packets"]
    marker=[m for m in last["serial_speed_events"] if up<=m["uptime"]<=up+4]
    exercised=(not marker) if speed=="2500" else len(marker)==1 and bool(decode_marker(marker[0],speed))
    clean=(min(*mac.values(),*phy.values(),*errors.values())>=0 and not any(errors.values()) and peer_tx>0)
    sent,received=totals["direct"]
    result="INCONCLUSIVE"
    if clean and sent and received==0 and phy["rx"]>0 and mac["rx_frames"]==0:
        result="COPPER_RX_WITH_GMAC_RX_STALL"
    elif clean and sent and received==sent and min(mac["rx_frames"],mac["tx_frames"],phy["rx"],phy["tx"])>0 and not any(mac[k] for k in probe.MAC_KEYS[2:]) and not phy["rx_err"] and not phy["tx_err"]:
        result="TRAFFIC_PASS"
    qualified=exercised and result=="TRAFFIC_PASS"
    return dict(edge=edge,speed=speed,samples=len(window),elapsed=elapsed,probe_totals=totals,
                mac_delta=mac,phy_delta=phy,switch_error_delta=errors,peer_tx_delta=peer_tx,
                serial_marker=marker,policy_exercised=exercised,classification=result,qualified=qualified)

def report(rows):
    valid=[r["snapshot"]["state"] for r in rows if r["snapshot"].get("state")]
    assert valid and all(y["uptime"]>x["uptime"] for x,y in zip(valid,valid[1:]))
    edges=valid[-1]["phy_edges"]
    assert len({e["edge"] for e in edges})==len(edges)
    assert all(y["edge"]==x["edge"]+1 and y["uptime"]>x["uptime"] and y["link"]!=x["link"] for x,y in zip(edges,edges[1:]))
    episodes=[]
    for idx,(down,up) in enumerate(zip(edges,edges[1:])):
        if down["link"] or not up["link"] or down["uptime"]<=valid[0]["uptime"]: continue
        prior=None
        for r in rows:
            s=r["snapshot"].get("state")
            if s and 0<=down["uptime"]-s["uptime"]<=8 and s["speed"] in RATES and physical(r,s["speed"]) and r["probes"]["direct"]["received"]==4: prior=s
        end=edges[idx+2]["uptime"] if idx+2<len(edges) else float("inf")
        post=next((s for s in valid if up["uptime"]<=s["uptime"]<end and s["carrier"]=="1" and s["speed"] in RATES),None)
        if post is None: continue
        speed=post["speed"]; window=[];windows=[]
        def flush():
            nonlocal window
            if w:=good_window(window,speed,up["edge"],up["uptime"]): windows.append(w)
            window=[]
        for r in rows:
            s=r["snapshot"].get("state")
            if not s:
                flush();continue
            if s["uptime"]<up["uptime"]+3 or s["uptime"]>=end:
                flush();continue
            ph=s.get("phy")
            if not physical(r,speed) or not ph or ph["edge"]!=up["edge"] or ph["link"]!=1 or ph["uptime"]<up["uptime"] or abs(s["uptime"]-ph["uptime"])>5:
                flush();continue
            if window and s["uptime"]-window[-1]["snapshot"]["state"]["uptime"]>8: flush()
            window.append(r)
        flush()
        qualified=prior is not None and bool(windows) and all(w["qualified"] for w in windows)
        episodes.append(dict(prior_speed=prior and prior["speed"],post_speed=speed,down=down["uptime"],up=up["uptime"],qualified=qualified,windows=windows))
    return dict(episodes=episodes,qualified=bool(episodes) and all(e["qualified"] for e in episodes))

def selftest():
    # Use the actual PCS status definitions for all three SGMII rates;
    # a marker with a retained forced speed field is legal if force=0.
    for speed,bits in RATES.items():
        if bits is None: continue
        m=dict(speed=int(speed),mode=0x420,ctrl=0x844,status=0xcf|bits)
        assert decode_marker(m,speed)
        for k,v in (("mode",0x421),("ctrl",0x84c),("ctrl",0x44),
                    ("status",bits|0x40),("status",bits|0x80),
                    ("status",0xc0|((bits+0x10)&0x30)),("speed",2500)):
            assert not decode_marker({**m,k:v},speed)
    print("SERIAL_RATE_MARKER_SELFTEST_PASS")

def main():
    assert __debug__
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("capture",type=Path,nargs="?")
    p.add_argument("boot",nargs="?")
    p.add_argument("--selftest",action="store_true")
    a=p.parse_args()
    if a.selftest:
        assert a.capture is None and a.boot is None
        selftest(); return
    assert a.capture is not None and a.boot is not None
    assert probe.trunk.BOOT.fullmatch(a.boot)
    cold.sealed(a.capture,"SHA256SUMS",("samples.jsonl","report.json"))
    rows=[json.loads(l) for l in (a.capture/"samples.jsonl").read_text().splitlines()]
    # Reparse sealed original remote output: never infer from derived report alone.
    for r in rows:
        raw=r["snapshot"]
        if s:=raw.get("state"):
            assert raw["rc"]==0 and probe.parse(raw["stdout"],a.boot,cold.REV)==s
    result=report(rows)
    result.update(boot=a.boot,revision=cold.REV,input_manifest_sha256=cold.sha(a.capture/"SHA256SUMS"))
    print(json.dumps(result,indent=2))
if __name__=="__main__": main()
