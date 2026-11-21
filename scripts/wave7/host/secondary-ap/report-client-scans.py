#!/usr/bin/env python3
"""Analyze archived ping -D and iw event -t logs from an isolated MLO client.

This is an offline report, not a change to the strict client acceptance gate.
Per-reply transmit times are estimates (receipt epoch minus reported RTT).
Missing packets have no measured timestamp; nominal cadence is illustrative.
"""
import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import statistics

D = Decimal
EVENT = re.compile(r"^(\d+\.\d+): (\S+)(?: \(phy #\d+\))?: (.*)$")
REPLY = re.compile(r"^\[(\d+\.\d+)\].*icmp_seq=(\d+).*?time([=<])([0-9.]+) ms")
SUMMARY = re.compile(r"^(\d+) packets transmitted, (\d+) (?:packets )?received, (?:\+\d+ duplicates, )?.*packet loss")
PING = re.compile(r"^PING (\S+)")


def parse_events(lines, iface):
    scans, associations, warnings = [], [], []
    pending = None
    linked = None
    last_cqm = None
    previous = None
    for line in lines:
        m = EVENT.fullmatch(line)
        if not m or m[2] != iface:
            continue
        t, event = D(m[1]), m[3]
        if previous is not None and t < previous:
            raise ValueError("non-monotonic iw event clock")
        previous = t
        if event.startswith("connected to "):
            if linked is not None:
                warnings.append("association began without preceding disconnect")
                associations.append({"start":linked, "end":t, "complete":False})
            linked=t
        elif event.startswith("disconnected"):
            if linked is not None:
                associations.append({"start":linked,"end":t,"complete":True})
            linked=None
        elif event.startswith("CQM event:"):
            last_cqm=t
        elif event=="scan started":
            if pending is not None:
                warnings.append("scan start without preceding completion")
                scans.append({**pending,"end":t,"complete":False})
            pending={"start":t,"associated_at_start":linked is not None,
                     "seconds_since_cqm":t-last_cqm if last_cqm is not None else None}
        elif event.startswith(("scan finished", "scan aborted")):
            if pending is None:
                warnings.append("scan completion without preceding start")
                continue
            scans.append({**pending,"end":t,"complete":True,
                          "aborted":event.startswith("scan aborted")})
            pending=None
    if pending is not None:
        scans.append({**pending,"end":previous,"complete":False})
    if linked is not None:
        associations.append({"start":linked,"end":previous,"complete":False})
    return scans,associations,warnings


def parse_ping(lines):
    tests=[]
    current=None
    for line in lines:
        m=PING.match(line)
        if m:
            if current is not None:
                raise ValueError("ping test missing summary")
            current={"target":m[1],"replies":{}}
        elif current is not None:
            m=REPLY.match(line)
            if m:
                epoch,seq,rtt=D(m[1]),int(m[2]),D(m[4])
                if seq<=0 or not rtt.is_finite() or rtt<0:
                    raise ValueError("invalid ping reply")
                if seq in current["replies"]:
                    raise ValueError("duplicate reply; cannot infer unique timing")
                # Reported RTT precision depends on display magnitude.
                # Use one full display unit plus 1 us for endpoint ambiguity.
                estimate=epoch-rtt/D(1000)
                uncertainty=(D(10)**rtt.as_tuple().exponent)/D(1000)+D("0.000001")
                if m[3]=="<":
                    uncertainty=max(uncertainty,rtt/D(1000))
                current["replies"][seq]={"seq":seq,"received":epoch,"rtt_ms":rtt,"rtt_is_upper_bound":m[3]=="<",
                                        "send_estimate":estimate,"send_uncertainty_s":uncertainty}
            elif (m:=SUMMARY.match(line)):
                sent,received=map(int,m.groups())
                if not 0<=received<=sent or received!=len(current["replies"]) or any(i>sent for i in current["replies"]):
                    raise ValueError("reply/summary count mismatch")
                current.update(sent=sent,received=received)
                tests.append(current)
                current=None
    if current is not None or not tests:
        raise ValueError("incomplete or missing ping summary")
    return tests


def scan_union(scans, start, end):
    intervals=sorted((max(s["start"],start),min(s["end"],end)) for s in scans
                     if s["complete"] and s["start"]<end and s["end"]>start)
    total=D(0)
    stop=start
    for a,b in intervals:
        total+=max(D(0),b-max(a,stop))
        stop=max(stop,b)
    return total


def describe(tests, scans, associations, interval):
    result=[]
    for t in tests:
        replies=list(t["replies"].values())
        # A packet interval may overlap a completed scan; this does not
        # establish causality, or guarantee the interface was on/off-channel.
        for p in replies:
            low=p["send_estimate"]-p["send_uncertainty_s"]
            high=p["send_estimate"]+p["send_uncertainty_s"]
            r=p["received"]
            definite=any(s["complete"] and s["start"]<=r and s["end"]>=high for s in scans)
            possible=any(s["start"]<=r and s["end"]>=low for s in scans)
            p["scan_overlap"]="overlap" if definite else "possible" if possible else "none_observed"
        nominal_origins=[p["send_estimate"]-(p["seq"]-1)*interval for p in replies]
        nominal_origin=statistics.median(nominal_origins) if nominal_origins else None
        missing=[{"seq":i,"nominal_send_estimate":nominal_origin+(i-1)*interval if nominal_origin is not None else None,
                  "actual_send_time":None} for i in range(1,t["sent"]+1) if i not in t["replies"]]
        stats={}
        for category in ("overlap","possible","none_observed"):
            matching=[p for p in replies if p["scan_overlap"]==category]
            vals=[p["rtt_ms"] for p in matching if not p["rtt_is_upper_bound"]]
            stats[category]={"replies":len(matching),"rtt_samples":len(vals),"mean_rtt_ms":statistics.mean(vals) if vals else None,
                             "max_rtt_ms":max(vals) if vals else None}
        result.append({"target":t["target"],"sent":t["sent"],"received":t["received"],
                       "missing":missing,"reply_stats":stats,
                       "nominal_cadence_residual_range_s":max(nominal_origins)-min(nominal_origins) if nominal_origins else None,
                       "replies":replies})
    assoc_time=sum((a["end"]-a["start"] for a in associations if a["complete"]),D(0))
    scan_time=sum((scan_union(scans,a["start"],a["end"]) for a in associations if a["complete"]),D(0))
    return {"scans":[{**s,"duration_s":s["end"]-s["start"]} for s in scans],
            "associations":associations,"complete_association_seconds":assoc_time,
            "completed_scan_seconds_during_complete_associations":scan_time,
            "scan_fraction":scan_time/assoc_time if assoc_time else None,
            "tests":result}


def report(ping_log,event_log,iface,interval):
    scans,associations,warnings=parse_events(event_log.splitlines(),iface)
    if not scans:
        warnings.append("no scan events parsed; absence of observed overlap is not proof of no scans")
    return {**describe(parse_ping(ping_log.splitlines()),scans,associations,interval),
            "event_warnings":warnings,
            "method":"receipt epoch minus displayed RTT (estimate); missing packets have no measured send time; overlap is not causation"}


def selftest():
    events="""100.000000: wlp2s0 (phy #0): connected to abc
101.000000: wlp2s0 (phy #0): CQM event: RSSI (-60 dBm) went below threshold
101.010000: wlp2s0 (phy #0): scan started
102.000000: other (phy #1): scan started
103.000000: wlp2s0 (phy #0): scan finished: 2412
105.000000: wlp2s0 (phy #0): disconnected (local request)
"""
    ping="""PING 192.168.76.2 (192.168.76.2) from 192.168.76.145
[102.100000] 64 bytes from 192.168.76.2: icmp_seq=1 ttl=64 time=40.0 ms
[104.000000] 64 bytes from 192.168.76.2: icmp_seq=3 ttl=64 time=100 ms
3 packets transmitted, 2 received, 33.333% packet loss
"""
    r=report(ping,events,"wlp2s0",D(".25"))
    assert r["scan_fraction"]==D("1.99")/5
    t=r["tests"][0]
    assert t["reply_stats"]["overlap"]["replies"]==1
    assert t["reply_stats"]["none_observed"]["replies"]==1
    assert report(ping.replace("time=40.0","time<40.0"),events,"wlp2s0",D(".25"))["tests"][0]["replies"][0]["rtt_is_upper_bound"]
    assert t["missing"][0]["seq"]==2 and t["missing"][0]["actual_send_time"] is None
    for broken in (ping.replace("2 received","3 received"),ping.replace("icmp_seq=3","icmp_seq=1")):
        try:
            report(broken,events,"wlp2s0",D(".25"))
        except ValueError:
            pass
        else:
            raise AssertionError("malformed ping accepted")
    print("CLIENT_SCAN_REPORT_SELFTEST_PASS")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("ping",type=Path,nargs="?")
    p.add_argument("events",type=Path,nargs="?")
    p.add_argument("--iface",default="wlp2s0")
    p.add_argument("--interval",type=D,default=D(".25"))
    p.add_argument("--selftest",action="store_true")
    args=p.parse_args()
    if args.selftest:
        selftest()
    else:
        if args.ping is None or args.events is None or not args.interval.is_finite() or args.interval<=0:
            p.error("provide ping/event logs and a positive probe interval")
        result=report(args.ping.read_text(),args.events.read_text(),args.iface,args.interval)
        print(json.dumps(result,indent=2,default=str))
