#!/usr/bin/env python3
"""Correlate AP peer-counter deltas to observed client reply gaps.

The observer records command round-trip brackets on the synchronized Asus.
The Wyse ping/event clock is a separate host clock; no hard bound on residual
NTP offset is claimed. Counter changes include all traffic for this peer.
"""
import argparse
from decimal import Decimal as D
import json
from pathlib import Path
import re

FIELDS=("rx packets","tx packets","tx failed","tx retries","rx drop misc")
DEBUG_COUNTERS=("tx_filtered","link-0/rx_duplicates","link-1/rx_duplicates",
                "link-0/rx_fragments","link-1/rx_fragments")
NANO=D(10)**9

def read_samples(lines):
    samples=[]
    for line in lines:
        s=json.loads(line)
        start,end=D(s["before_ns"])/NANO,D(s["after_ns"])/NANO
        if end<start or s["seq"]!=len(samples) or (samples and start<samples[-1]["end"]):
            raise ValueError("unqualified AP sample sequence")
        uptime=D(s["router_uptime_s"])
        if samples and uptime<samples[-1]["uptime"]:
            raise ValueError("router uptime reset")
        data=s["data"]
        counters={}
        if data["present"]:
            sta,debug=data["station"],data["debug"]
            for field in FIELDS:
                value=sta.get(field)
                if value is not None and re.fullmatch(r"\d+",value):
                    counters[field]=int(value)
            for field in DEBUG_COUNTERS:
                values=debug.get(field,[])
                if len(values)==1 and re.fullmatch(r"\d+",values[0]):
                    counters[field]=int(values[0])
        samples.append({"start":start,"end":end,"uptime":uptime,"data":data,"counters":counters})
    if not samples:
        raise ValueError("empty AP observation")
    return samples

def summarize(samples):
    if not samples:
        return {"sample_count":0,"qualified":False}
    present=all(s["data"]["present"] for s in samples)
    durations=[s["end"]-s["start"] for s in samples]
    gaps=[b["start"]-a["end"] for a,b in zip(samples,samples[1:])]
    result={"sample_count":len(samples),"start":samples[0]["start"],"end":samples[-1]["end"],
            "all_present":present,"max_roundtrip_s":max(durations),
            "max_inter_sample_gap_s":max(gaps,default=D(0))}
    if not present:
        return {**result,"qualified":False}
    common=set.intersection(*(set(s["counters"]) for s in samples))
    monotonic=all(b["counters"][key]>=a["counters"][key]
                  for a,b in zip(samples,samples[1:]) for key in common)
    result["qualified"]=len(samples)>=2 and monotonic and set(FIELDS)<=common and max(gaps,default=D(0))<=D(".55") and max(durations)<=D(".12")
    result["counter_deltas"]={key:samples[-1]["counters"][key]-samples[0]["counters"][key]
                             for key in sorted(common)}
    result["flags_seen"]=sorted({flag for s in samples for flag in s["data"]["debug"].get("flags",[])})
    ps_counts=[]
    tids=[]
    for s in samples:
        dbg=s["data"]["debug"]
        ps=dbg.get("num_ps_buf_frames",[])
        if len(ps)==4 and all(re.fullmatch(r"AC[0-3]: \d+",v) for v in ps):
            ps_counts.append(sum(int(v.split(": ")[1]) for v in ps))
        values=dbg.get("driver_buffered_tids",[])
        if len(values)==1 and re.fullmatch(r"0x[0-9a-fA-F]+",values[0]):
            tids.append(int(values[0],16))
    result["host_ps_buffer_samples"]=len(ps_counts)
    result["host_ps_buffer_max"]=max(ps_counts,default=None)
    result["driver_buffered_tids_samples"]=len(tids)
    result["driver_buffered_tids_nonzero_samples"]=sum(v!=0 for v in tids)
    return result

def correlate(samples,report):
    windows=[]
    for scope in report["scope_report"]["requests"]:
        if not scope.get("isolated_postscan_window") or not all(t["covered"] and t["missing_clusters"] for t in scope["tests"]):
            continue
        clusters=[]
        for test in scope["tests"]:
            bounded=[c for c in test["missing_clusters"]
                     if c["prior_reply_epoch"] is not None and c["following_reply_epoch"] is not None]
            if len(bounded)!=1:
                break
            clusters.append(bounded[0])
        if len(clusters)!=len(scope["tests"]):
            continue
        overlap_start=max(D(c["prior_reply_epoch"]) for c in clusters)
        overlap_end=min(D(c["following_reply_epoch"]) for c in clusters)
        if overlap_end<=overlap_start:
            continue
        previous=[i for i,s in enumerate(samples) if s["end"]<=overlap_start]
        following=[i for i,s in enumerate(samples) if s["start"]>=overlap_end]
        bracket=[]
        if previous and following:
            lo,hi=previous[-1],following[0]
            if overlap_start-samples[lo]["end"]<=D(".65") and samples[hi]["start"]-overlap_end<=D(".65"):
                bracket=samples[lo:hi+1]
        interior=[s for s in samples if s["start"]>=overlap_start and s["end"]<=overlap_end]
        scan_start=D(scope["matched_scan"]["start"])
        reference=[s for s in samples if s["start"]>=scan_start-D(2) and s["end"]<=scan_start]
        windows.append({"label":scope["label"],"common_reply_gap_start":overlap_start,
                        "common_reply_gap_end":overlap_end,"common_reply_gap_s":overlap_end-overlap_start,
                        "missing_counts":[len(c["sequences"]) for c in clusters],
                        "before_scan_reference":summarize(reference),
                        "inside_observed_gap":summarize(interior),
                        "bracketing_samples":summarize(bracket)})
    return {"windows":windows,
            "method":"Associated station cumulative counters; sample command brackets on Asus nominal NTP-aligned to Wyse. Common gap bounded by last successful and next successful replies, not exact missing TX instants; counters include all peer data and may be firmware-polled. Host PS buffers do not describe all firmware buffering."}

def selftest():
    def row(i,received,failed):
        return json.dumps({"seq":i,"before_ns":(i+1)*250_000_000,
            "after_ns":(i+1)*250_000_000+20_000_000,"router_uptime_s":str(i),
            "data":{"present":True,"station":{"rx packets":str(received),"tx packets":"10",
                "tx failed":str(failed),"tx retries":"1","rx drop misc":"0"},
                "debug":{"flags":["AUTH","ASSOC"],"num_ps_buf_frames":["AC0: 0","AC1: 0","AC2: 0","AC3: 0"],
                         "driver_buffered_tids":["0x0"],"tx_filtered":["0"]}}})
    samples=read_samples([row(0,10,0),row(1,11,1),row(2,11,2),row(3,14,3)])
    assert summarize(samples)["qualified"]
    assert summarize(samples)["counter_deltas"]["tx failed"]==3
    assert summarize(samples)["host_ps_buffer_max"]==0
    r={"scope_report":{"requests":[{"label":"a","isolated_postscan_window":True,
         "matched_scan":{"start":"0.1"},"tests":[{"covered":True,"missing_clusters":[
            {"prior_reply_epoch":"0.3","following_reply_epoch":"0.9","sequences":[2,3]}]}]}]}}
    window=correlate(samples,r)["windows"][0]
    assert window["inside_observed_gap"]["counter_deltas"]["tx failed"]==1
    assert window["bracketing_samples"]["counter_deltas"]["tx failed"]==3
    print("AP_CLIENT_REPORT_SELFTEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("samples",type=Path,nargs="?")
    p.add_argument("client_report",type=Path,nargs="?")
    p.add_argument("--selftest",action="store_true")
    a=p.parse_args()
    if a.selftest:
        selftest()
    else:
        if a.samples is None or a.client_report is None:
            p.error("provide samples and combined client report")
        print(json.dumps(correlate(read_samples(a.samples.read_text().splitlines()),
            json.loads(a.client_report.read_text())),indent=2,default=str))
