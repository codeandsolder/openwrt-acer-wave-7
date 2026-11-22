#!/usr/bin/env python3
"""Require a matching driver marker before attributing a scan to the no-split trial."""
import argparse
from decimal import Decimal as D
import json
from pathlib import Path
import re

MARKER=re.compile(
    r"^(\d+\.\d+) .*wave7-diag: no-split scan seq=(\d+) bss=(\d+) "
    r"valid=(0x[0-9a-fA-F]+) active=(0x[0-9a-fA-F]+) freq=(\d+) passive=([01])$"
)


def parse_markers(lines):
    result=[]
    for line in lines:
        m=MARKER.fullmatch(line)
        if m is None:
            raise ValueError(f"unparseable driver marker: {line}")
        epoch,seq,bss,valid,active,freq,passive=m.groups()
        row={"time":D(epoch),"seq":int(seq),"bss":int(bss),
             "valid":int(valid,16),"active":int(active,16),
             "freq":int(freq),"passive":bool(int(passive))}
        if row["valid"].bit_count()<2 or not 0<=row["seq"]<=255 or (
                result and row["time"]<result[-1]["time"]):
            raise ValueError("invalid no-split marker")
        result.append(row)
    return result


def qualify(scope,timing,markers):
    observed={w["label"]:w for w in timing["windows"]}
    used=set()
    requests=[]
    for req in scope["scope_report"]["requests"]:
        if req["status"]!="return=0" or req["matched_scan"] is None:
            continue
        freqs=req["requested_frequencies_mhz"]
        if len(freqs)!=1:
            continue
        label=req["label"]
        passive=label.startswith("passive")
        if not (passive or label.startswith("active")):
            continue
        # Same client clock. Allow bounded journald timestamp delivery skew,
        # require unique matching frequency/request mode and a completed scan.
        lower=D(req["requested_epoch"])-D(".05")
        upper=D(req["return_epoch"])+D(".25")
        candidates=[(i,m) for i,m in enumerate(markers) if lower<=m["time"]<=upper
                    and m["freq"]==freqs[0] and m["passive"]==passive]
        r={"label":label,"marker_candidates":len(candidates),
           "marker":None,"isolated":req["isolated_postscan_window"],
           "timing":observed.get(label)}
        if len(candidates)==1 and candidates[0][0] not in used:
            i,m=candidates[0]
            r["marker"]=m
            r["marker_after_request_s"]=m["time"]-D(req["requested_epoch"])
            used.add(i)
        requests.append(r)
    qualified=[r for r in requests if r["marker"] is not None and r["isolated"]
               and r["timing"] is not None]
    return {"requests":requests,"marker_count":len(markers),
            "matched_marker_count":len(used),"qualified_isolated_count":len(qualified),
            "qualified_isolated_with_loss":sum(
                any(p["missing_sequences"] for p in r["timing"]["paths"]) for r in qualified),
            "qualified_isolated_all_paths_loss":sum(
                all(p["missing_sequences"] for p in r["timing"]["paths"]) for r in qualified),
            "unmatched_markers":[m for i,m in enumerate(markers) if i not in used],
            "method":"Driver diagnostic proves branch selection before the MCU request, not firmware compliance. Exact frequency/mode, bounded same-host request timestamp, unique accepted completed scan and isolated covered timing required."}


def selftest():
    line="100.010000 wifi7-lab kernel: mt7925e 0000:02:00.0: wave7-diag: no-split scan seq=129 bss=0 valid=0x3 active=0x3 freq=2412 passive=1"
    m=parse_markers([line])
    r={"scope_report":{"requests":[{"status":"return=0","matched_scan":{},
        "label":"passive24-1","requested_frequencies_mhz":[2412],
        "requested_epoch":"100","return_epoch":"100.03","isolated_postscan_window":True}]}}
    t={"windows":[{"label":"passive24-1","paths":[{"target":"a","missing_sequences":[1]},
                                                 {"target":"b","missing_sequences":[]}]}]}
    q=qualify(r,t,m)
    assert q["qualified_isolated_count"]==1 and q["qualified_isolated_with_loss"]==1
    assert q["qualified_isolated_all_paths_loss"]==0
    assert qualify(r,t,m+m)["matched_marker_count"]==0
    assert qualify(r,t,parse_markers([line.replace("passive=1","passive=0")]))["matched_marker_count"]==0
    print("NOSPLIT_REPORT_SELFTEST_PASS")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("scope",type=Path,nargs="?")
    p.add_argument("timing",type=Path,nargs="?")
    p.add_argument("markers",type=Path,nargs="?")
    p.add_argument("--selftest",action="store_true")
    a=p.parse_args()
    if a.selftest:
        selftest()
    else:
        if a.scope is None or a.timing is None or a.markers is None:
            p.error("provide combined scope report, timing and driver markers")
        print(json.dumps(qualify(json.loads(a.scope.read_text()),json.loads(a.timing.read_text()),
            parse_markers(a.markers.read_text().splitlines())),indent=2,default=str))
