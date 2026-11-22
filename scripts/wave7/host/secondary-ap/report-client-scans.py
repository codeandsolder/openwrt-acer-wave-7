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
OUTSTANDING = re.compile(r"^\[(\d+\.\d+)\] no answer yet for icmp_seq=(\d+)$")
SUMMARY = re.compile(r"^(\d+) packets transmitted, (\d+) (?:packets )?received, (?:\+\d+ duplicates, )?.*packet loss")
PING = re.compile(r"^PING (\S+)")
SCAN_FREQS = re.compile(r"^scan finished: ([0-9]+(?: [0-9]+)*)(?:,|$)")
SCOPE_LABEL = re.compile(r"(home|off24|off5|off6|full)-[12]")


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
            freqs=SCAN_FREQS.match(event)
            scans.append({**pending,"end":t,"complete":True,
                          "aborted":event.startswith("scan aborted"),
                          "frequencies_mhz":[int(x) for x in freqs[1].split()] if freqs else None})
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
            current={"target":m[1],"replies":{},"outstanding":{}}
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
            elif (m:=OUTSTANDING.match(line)):
                epoch,seq=D(m[1]),int(m[2])
                if seq<=0 or seq in current["outstanding"]:
                    raise ValueError("invalid duplicate outstanding notice")
                current["outstanding"][seq]=epoch
            elif (m:=SUMMARY.match(line)):
                sent,received=map(int,m.groups())
                if not 0<=received<=sent or received!=len(current["replies"]) or any(i>sent for i in (*current["replies"],*current["outstanding"])):
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


def missing_clusters(test, scans):
    """Observed -O notices bound reply gaps; never claim actual missing send times."""
    missing=[i for i in range(1,test["sent"]+1) if i not in test["replies"]]
    groups=[]
    for seq in missing:
        if groups and seq==groups[-1][-1]+1:
            groups[-1].append(seq)
        else:
            groups.append([seq])
    result=[]
    for seqs in groups:
        prior=test["replies"].get(seqs[0]-1)
        following=test["replies"].get(seqs[-1]+1)
        notices=[{"seq":i,"epoch":test["outstanding"].get(i)} for i in seqs]
        first=notices[0]["epoch"]
        last=notices[-1]["epoch"]
        # A completed scan and at least one observed successful packet
        # after completion distinguish this from ordinary scan dwell.
        scan=max((s for s in scans if s["complete"] and not s["aborted"] and
                   first is not None and s["end"]<=first),
                  key=lambda s:s["end"],default=None)
        end=scan["end"] if scan else None
        after=lambda t: t-end if t is not None and end is not None else None
        result.append({
            "sequences":seqs,"observed_unanswered_notices":notices,
            "prior_reply_epoch":prior["received"] if prior else None,
            "following_reply_epoch":following["received"] if following else None,
            "following_reply_rtt_ms":following["rtt_ms"] if following else None,
            "reply_gap_seconds":following["received"]-prior["received"] if prior and following else None,
            "scan_end_epoch":end,
            "prior_reply_after_scan_s":after(prior["received"] if prior else None),
            "first_notice_after_scan_s":after(first),
            "last_notice_after_scan_s":after(last),
            "following_reply_after_scan_s":after(following["received"] if following else None),
            "successful_reply_after_scan_before_gap":bool(prior and end is not None and prior["received"]>end),
            "actual_missing_send_times_known":False,
        })
    return result


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
                  "actual_send_time":None,"observed_unanswered_notice_epoch":t["outstanding"].get(i)}
                 for i in range(1,t["sent"]+1) if i not in t["replies"]]
        stats={}
        for category in ("overlap","possible","none_observed"):
            matching=[p for p in replies if p["scan_overlap"]==category]
            vals=[p["rtt_ms"] for p in matching if not p["rtt_is_upper_bound"]]
            stats[category]={"replies":len(matching),"rtt_samples":len(vals),"mean_rtt_ms":statistics.mean(vals) if vals else None,
                             "max_rtt_ms":max(vals) if vals else None}
        result.append({"target":t["target"],"sent":t["sent"],"received":t["received"],
                       "missing":missing,"missing_clusters":missing_clusters(t,scans),"reply_stats":stats,
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
            "method":"receipt epoch minus displayed RTT (estimate); -O notices are observed unanswered-reply notifications, not send timestamps; missing packets have no measured send time; overlap is not causation"}


def scan_scope_report(result, request_log):
    """Correlate accepted requests to actual iw scan events, not intended scopes."""
    requests={}
    for line in request_log.splitlines():
        epoch,label,status,freqs=line.split(",",3)
        now=D(epoch)
        frequencies=[int(f) for f in freqs.split()]
        if (not SCOPE_LABEL.fullmatch(label) or not frequencies or
                len(frequencies)!=len(set(frequencies)) or not now.is_finite()):
            raise ValueError("invalid scope request log")
        if status in ("request","busy-timeout"):
            if label in requests:
                raise ValueError("duplicate scope request")
            requests[label]={"label":label,"requested_epoch":now,
                             "requested_frequencies_mhz":frequencies,
                             "status":status,"return_epoch":None}
        elif status.startswith("return="):
            req=requests[label]
            if (req["status"]!="request" or now<req["requested_epoch"] or
                    req["requested_frequencies_mhz"]!=frequencies):
                raise ValueError("inconsistent scope return")
            req["status"]=status
            req["return_epoch"]=now
        else:
            raise ValueError("unknown scope status")

    used=set()
    for req in requests.values():
        req["matched_scan"]=None
        req["candidate_scan_count"]=0
        if req["status"]!="return=0":
            continue
        candidates=[(i,scan) for i,scan in enumerate(result["scans"])
                    if scan["start"]>=req["requested_epoch"] and
                    scan["start"]<=req["return_epoch"]+D(2)]
        req["candidate_scan_count"]=len(candidates)
        if len(candidates)!=1:
            continue
        i,scan=candidates[0]
        if (i in used or not scan["complete"] or scan["aborted"] or
                not scan["associated_at_start"] or
                sorted(scan.get("frequencies_mhz") or [])!=
                sorted(req["requested_frequencies_mhz"])):
            continue
        used.add(i)
        req["matched_scan"]=scan
        # A nearby natural scan can itself cause a delayed gap; retain
        # such samples, but separate them from isolated causal contrasts.
        prior=[s["end"] for j,s in enumerate(result["scans"])
               if j!=i and s["complete"] and s["end"]<=scan["start"]]
        later=[s["start"] for j,s in enumerate(result["scans"])
               if j!=i and s["start"]>=scan["end"]]
        req["previous_scan_end_distance_s"]=scan["start"]-max(prior) if prior else None
        req["next_scan_start_distance_s"]=min(later)-scan["end"] if later else None
        req["isolated_postscan_window"]=(
            (not prior or scan["start"]-max(prior)>=D(3)) and
            (not later or min(later)-scan["end"]>=D(3)))
        req["tests"]=[]
        for test in result["tests"]:
            replies=sorted(test["replies"],key=lambda p:p["received"])
            end=scan["end"]
            covered=bool(replies and replies[0]["received"]<=end and
                         replies[-1]["received"]>=end+D(3))
            clusters=[c for c in test["missing_clusters"]
                      if c["scan_end_epoch"]==end and c["first_notice_after_scan_s"] is not None
                      and D(0)<=c["first_notice_after_scan_s"]<=D(3)]
            # Only classify 'no recorded missing notices' inside the
            # observation window; a missing send timestamp is unavailable.
            post=[p for p in replies if end<=p["received"]<=end+D(3)]
            req["tests"].append({"target":test["target"],"covered":covered,
                                 "missing_clusters":clusters,
                                 "missing_packets_with_notices":sum(len(c["sequences"]) for c in clusters),
                                 "postscan_replies":len(post),
                                 "max_postscan_rtt_ms":max((p["rtt_ms"] for p in post),default=None)})
    return {"requests":list(requests.values()),
            "matched_count":len(used),
            "unmatched_completed_associated_scans":[s for i,s in enumerate(result["scans"])
               if i not in used and s["complete"] and not s["aborted"] and s["associated_at_start"]],
            "method":"Accepted iw trigger plus unique scan-start event and exact completed frequency list; natural background scans retained. Missing-probe notices are not TX timestamps."}


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
[103.500000] no answer yet for icmp_seq=2
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
    assert t["missing"][0]["observed_unanswered_notice_epoch"]==D("103.5")
    cl=t["missing_clusters"][0]
    assert cl["first_notice_after_scan_s"]==D(".5")
    assert not cl["successful_reply_after_scan_before_gap"]
    assert cl["actual_missing_send_times_known"] is False
    # If a reply was already received after scan end, the next gap is
    # delayed relative to the observable firmware scan completion.
    moved=report(ping.replace("102.100000","103.100000"),events,"wlp2s0",D(".25"))
    assert moved["tests"][0]["missing_clusters"][0]["successful_reply_after_scan_before_gap"]
    for broken in (ping.replace("2 received","3 received"),ping.replace("icmp_seq=3","icmp_seq=1")):
        try:
            report(broken,events,"wlp2s0",D(".25"))
        except ValueError:
            pass
        else:
            raise AssertionError("malformed ping accepted")
    assert r["scans"][0]["frequencies_mhz"]==[2412]
    req="101.005000,home-1,request,2412\n101.020000,home-1,return=0,2412\n"
    scoped=scan_scope_report(r,req)
    assert scoped["matched_count"]==1
    assert scoped["requests"][0]["tests"][0]["missing_packets_with_notices"]==1
    assert not scoped["requests"][0]["tests"][0]["covered"]
    assert scan_scope_report(r,req.replace("2412","5180"))["matched_count"]==0
    assert scan_scope_report(r,req.replace("return=0","return=1"))["matched_count"]==0
    print("CLIENT_SCAN_REPORT_SELFTEST_PASS")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("ping",type=Path,nargs="?")
    p.add_argument("events",type=Path,nargs="?")
    p.add_argument("--iface",default="wlp2s0")
    p.add_argument("--interval",type=D,default=D(".25"))
    p.add_argument("--requests",type=Path)
    p.add_argument("--selftest",action="store_true")
    args=p.parse_args()
    if args.selftest:
        selftest()
    else:
        if args.ping is None or args.events is None or not args.interval.is_finite() or args.interval<=0:
            p.error("provide ping/event logs and a positive probe interval")
        result=report(args.ping.read_text(),args.events.read_text(),args.iface,args.interval)
        if args.requests is not None:
            result["scope_report"]=scan_scope_report(result,args.requests.read_text())
        print(json.dumps(result,indent=2,default=str))
