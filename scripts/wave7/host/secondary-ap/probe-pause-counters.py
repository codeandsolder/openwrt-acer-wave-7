#!/usr/bin/env -S uv run --no-project python
"""Isolate Realtek copper PAUSE accounting without congestion or flow throttling.

The unprivileged observer retains the lab lock and verifies a sealed clean
boot. Only the bounded AF_PACKET sender requires root. It emits PAUSE
frames with quanta zero, never a nonzero pause or a configuration change.
"""
import argparse
import json
import os
from pathlib import Path
import re
import runpy
import socket
import struct
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
# Root sender is standalone and never loads the unprivileged observer.
IP, DEV, MAC, SPEED = "192.168.76.250", "enp4s0f4u2u2u4", "00:e0:4c:68:01:45", "1000"

def require(ok, message):
    if not ok:
        raise ValueError(message)

def load_observer():
    global probe, bench, FIELDS
    probe = runpy.run_path(str(HERE/"probe-mib-freshness.py"))
    bench = runpy.run_path(str(HERE/"bench-ordering.py"))
    assert (IP,DEV,MAC,SPEED)==tuple(probe["PATHS"]["switch"][i] for i in (0,1,3,4))
    FIELDS = (*probe["FIELDS"], *PAUSE)

COUNTS = (8, 32, 128)
PAUSE = ("dot3InPauseFrames","dot3OutPauseFrames")


def frame():
    data = bytes.fromhex("0180c2000001") + bytes.fromhex(MAC.replace(":",""))
    return (data+struct.pack("!HHH",0x8808,1,0)).ljust(60,b"\0")


def send(count):
    require(os.geteuid()==0 and count in COUNTS,"requires root and a fixed probe count")
    p=Path("/sys/class/net")/DEV
    for key, expected in (("address",MAC),("carrier","1"),("speed",SPEED)):
        require((p/key).read_text().strip()==expected, f"wrong lab interface {key}")
    info=json.loads(subprocess.check_output(["ip","-j","-4","addr","show","dev",DEV],text=True,timeout=5))
    require(len(info)==1 and any(a["local"]==IP for a in info[0]["addr_info"]),
            "wrong lab interface address")
    packet=frame()
    with socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(0x8808)) as sock:
        sock.bind((DEV,0))
        for _ in range(count):
            require(sock.send(packet)==len(packet),"short PAUSE send")
            time.sleep(.02)
    print(json.dumps({"sent":count,"interface":DEV,"quanta":0,"frame":packet.hex()}))


def pause_stats(raw):
    result={}
    for port,prefix in (("cpu","s00_p06_"),("copper","")):
        body=raw.split("=== CPU ===\n" if port=="cpu" else "=== COPPER ===\n",1)[1]
        body=body.split("=== COPPER ===\n" if port=="cpu" else "=== DIRECT ===\n",1)[0]
        vals={}
        for l in body.splitlines():
            m=re.fullmatch(r"\s*"+prefix+r"(\w+):\s+(\d+)",l)
            if m and m[1] in PAUSE:
                require(m[1] not in vals,"duplicate PAUSE counter")
                vals[m[1]]=int(m[2])
        require(set(vals)==set(PAUSE),"missing PAUSE counters")
        result[port]=vals
    return result


def observe(out, name, variant, boot):
    r=bench["sample"](out,name,variant,boot)
    raw=(out/f"{name}.txt").read_text()
    p=pause_stats(raw)
    return {port:{**r["counters"][port],**p[port]} for port in p},r["xgmac"]


def compare(before,after,count):
    a,ma=before
    b,mb=after
    deltas={port:{k:b[port][k]-a[port][k] for k in FIELDS} for port in a}
    mac={k:mb[k]-ma[k] for k in ma}
    require(all(v>=0 for r in (*deltas.values(),mac) for v in r.values()),
            "counter reset/wrap")
    cpu,copper=deltas["cpu"],deltas["copper"]
    require(not any(cpu[k] for k in probe["ERRORS"]) and
            not any(copper[k] for k in probe["ERRORS"][:2]) and
            not any(mac[k] for k in probe["XGMAC_ERRORS"]),"physical errors")
    require(not cpu["dot3InPauseFrames"] and not cpu["dot3OutPauseFrames"] and
            not mac["rx_pause"] and not mac["tx_pause"] and
            not copper["dot3OutPauseFrames"],"unexpected PAUSE traffic")
    return {"sent":count,"delta":deltas,"xgmac_delta":mac,
            "exact_pause_count":copper["dot3InPauseFrames"]==count,
            "exact_drop_count":copper["etherStatsDropEvents"]==count}


def measure(run):
    require(os.getuid()!=0,"run observer as jan; sudo only for the sender")
    record=bench["cohort"]["load_run"](run)
    require(record and record["outcome"]=="clean","requires sealed clean experiment")
    variant,boot=record["variant"],record["boot"]
    out=run/f"pause-counter-probe-{time.strftime('%Y%m%d-%H%M%S')}"
    # Obtain explicit user authorization before taking the exclusive lab lock.
    subprocess.run(["sudo","-v"],check=True)
    report={"variant":variant,"boot":boot,"phases":[]}
    with probe["lab_session"](out):
        try:
            with probe["capture_nics"](out,f"ether proto 0x8808 and ether src {MAC}"):
                for i,count in enumerate((0,COUNTS[0],0,COUNTS[1],0,COUNTS[2],0)):
                    before=observe(out,f"phase{i}-before",variant,boot)
                    if count:
                        result=subprocess.run(["sudo","-n","/usr/bin/python3",str(Path(__file__).resolve()),"--send",str(count)],
                                              check=True,text=True,capture_output=True,timeout=10)
                        (out/f"phase{i}-sent.json").write_text(result.stdout)
                        require(json.loads(result.stdout)["sent"]==count,"sender count mismatch")
                    time.sleep(1)
                    after=observe(out,f"phase{i}-after",variant,boot)
                    report["phases"].append(compare(before,after,count))
            # Packet capture is an independent host-side transmission witness;
            # switch MIB proves that the frames actually crossed the wire.
            for name in probe["PATHS"]:
                data=probe["run"](["tshark","-n","-r",str(out/f"{name}.pcapng"),
                     "-T","fields","-e","eth.src","-e","eth.dst","-e","eth.type",
                     "-e","macc.opcode","-e","macc.pause_time"],20)
                (out/f"{name}-frames.tsv").write_text(data)
                rows=data.splitlines()
                expected=sum(COUNTS) if name=="switch" else 0
                require(len(rows)==expected,f"{name}: capture count mismatch")
                for row in rows:
                    src,dst,proto,op,quanta=row.split("\t")
                    require(src==MAC and dst=="01:80:c2:00:00:01" and
                            int(proto,0)==0x8808 and int(op,0)==1 and int(quanta,0)==0,
                            "unexpected captured frame")
            report["status"]="PASS" if all(p["exact_pause_count"] and p["exact_drop_count"]
                                             for p in report["phases"]) else "INCONCLUSIVE"
        except Exception as exc:
            report.update(status="FAILED",error=str(exc))
        (out/"report.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))
    return report["status"]=="PASS"


def selftest():
    packet=frame()
    assert len(packet)==60 and packet[:6]==bytes.fromhex("0180c2000001")
    assert struct.unpack_from("!HHH",packet,12)==(0x8808,1,0)
    zeros={k:0 for k in FIELDS}
    mac={k:0 for k in probe["XGMAC"]}
    before=({"cpu":dict(zeros),"copper":dict(zeros)},mac)
    for n in (0,*COUNTS):
        after=({"cpu":dict(zeros),"copper":dict(zeros,dot3InPauseFrames=n,etherStatsDropEvents=n)},mac)
        r=compare(before,after,n)
        assert r["exact_pause_count"] and r["exact_drop_count"]
        after[0]["copper"]["etherStatsDropEvents"]+=1
        assert not compare(before,after,n)["exact_drop_count"]
        after[0]["copper"]["dot3StatsFCSErrors"]=1
        try:compare(before,after,n)
        except ValueError:pass
        else:raise AssertionError("physical error accepted")
    print("PAUSE_COUNTER_PROBE_SELFTEST_PASS")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--send",type=int,choices=COUNTS)
    action.add_argument("--run",type=Path)
    action.add_argument("--selftest",action="store_true")
    args=parser.parse_args()
    if args.send:
        send(args.send)
    else:
        load_observer()
        if args.selftest:selftest()
        else:sys.exit(0 if measure(args.run.resolve()) else 1)
