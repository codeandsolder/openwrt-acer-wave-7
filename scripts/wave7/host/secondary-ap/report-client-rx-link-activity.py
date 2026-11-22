#!/usr/bin/env python3
"""Count descriptor-backed per-link RX during common sustained probe coverage.

A successful driver RX parse is not a successful socket delivery. Require
matching raw/resolved station, connected BSS, associated STA, channel and
no descriptor errors for the strongest category. Retain mismatches.
"""
import argparse
from collections import Counter
from bisect import bisect_right
from decimal import Decimal as D
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location(
    "roc", Path(__file__).with_name("report-client-roc-wire.py"))
roc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(roc)
rx = roc.rx


def frequency(band, channel):
    if band == 1:
        return 2484 if channel == 14 else 2407 + 5 * channel
    if band == 2:
        return 5000 + 5 * channel
    if band == 3:
        return 5935 if channel == 2 else 5950 + 5 * channel
    raise ValueError("unknown ROC RF band")


def analyze(trace, scan):
    paths = scan["tests"]
    if len(paths) < 2 or any(not p["replies"] for p in paths):
        raise ValueError("missing sustained paths")
    start = max(min(D(r["received"]) for r in p["replies"]) for p in paths)
    end = min(max(D(r["received"]) for r in p["replies"]) for p in paths)
    lo, hi = trace["offset_lo"], trace["offset_hi"]
    if not (trace["first_anchor"] + hi <= start < end <= trace["last_anchor"] + lo):
        raise ValueError("sustained coverage outside anchored trace")
    sessions, _ = roc.grant_pairs(trace["events"])
    assignments = []
    for session in sessions:
        if session["complete"] and session.get("bands_applied"):
            t = max(r["t"] for r in session["assignments"])
            assignments.append((t, {r["bss"]: frequency(r["band"], r["channel"])
                                    for r in session["requests"]},
                                {r["bss"]: r["granted_hw_bands"][0]
                                 for r in session["requests"]}))
    assignments.sort()
    active_freq, active_band, bss, sta = {}, {}, {}, {}
    next_assignment = 0
    counts, frame_counts, tx_counts = Counter(), Counter(), Counter()
    mismatches=[]
    scan_starts=sorted(t for t,name,*_ in trace["events"] if name=="drv_hw_scan")
    scan_completions=sorted(t for t,name,*_ in trace["events"] if name=="api_scan_completed")
    def previous_delta(values,t):
        i=bisect_right(values,t)
        return t-values[i-1] if i else None
    def next_delta(values,t):
        i=bisect_right(values,t)
        return values[i]-t if i<len(values) else None
    for t, name, _, payload, _ in trace["events"]:
        while next_assignment < len(assignments) and assignments[next_assignment][0] < t:
            _, active_freq, active_band = assignments[next_assignment]
            next_assignment += 1
        event = name.removeprefix("mt7925_lab_")
        if event not in {"bss_result", "sta_result", "rxdesc", "rx_frame", "txs_peer_data"}:
            continue
        k = rx.fields(payload)
        if event == "bss_result":
            if k["result"] == 0:
                bss[k["bss"]] = k
        elif event == "sta_result":
            if k["result"] == 0:
                sta[k["wcid"]] = k
        elif start <= t + lo and t + hi <= end:
            if event == "txs_peer_data":
                peer=sta.get(k["wcid"])
                link=bss.get(peer["bss"]) if peer else None
                expected=active_band.get(peer["bss"]) if peer else None
                if not (peer and peer["enabled"] and peer["state"]==2 and
                        link and link["enabled"] and link["wcid"]==peer["wcid"]):
                    kind="no_verified_connected_peer"
                elif not (k["valid"] and k["link"]==peer["link"]==link["link"]
                          and k["band"]==expected):
                    kind="binding_or_band_mismatch"
                else:
                    kind="matching_associated_peer"
                tx_counts[(kind,k["band"],k["wcid"],k["link"],k["format"],
                           k["ack_error"],k["encap"])]+=1
                continue
            if event == "rx_frame":
                frame = roc.decode_frame(k)
                frame_counts[(frame["freq"], frame["wcid"], frame["bss"],
                              frame["kind"], frame["u2m"], frame["data"])] += 1
                continue
            r = rx.decode(k)
            if k["result"] or not (r["data"] and r["u2m"] and k["sta"]):
                continue
            if r["raw_freq"] != k["freq"]:
                raise ValueError("raw channel and driver frequency disagree")
            peer = sta.get(k["resolved_wcid"])
            link = bss.get(peer["bss"]) if peer else None
            expected = active_freq.get(peer["bss"]) if peer else None
            if any(r[f] for f in ("fcs_error", "icv_error", "mic_error", "cipher_mismatch")):
                kind = "descriptor_error"
            elif not (peer and peer["enabled"] and peer["state"] == 2 and
                      link and link["enabled"] and link["wcid"] == peer["wcid"]):
                kind = "no_verified_connected_peer"
            elif not (k["valid"] and k["link"] == peer["link"] == link["link"]
                      and r["raw_wcid"] == k["resolved_wcid"]
                      and r["raw_bss"] == peer["bss"] and expected == r["raw_freq"]):
                kind = "binding_or_frequency_mismatch"
            else:
                kind = "matching_associated_peer"
            if kind=="binding_or_frequency_mismatch":
                mismatches.append(dict(t=t,raw_freq=r["raw_freq"],raw_band=r["raw_band"],
                    raw_wcid=r["raw_wcid"],resolved_wcid=k["resolved_wcid"],
                    raw_bss=r["raw_bss"],resolved_link=k["link"],expected_freq=expected,
                    expected_bss=peer["bss"],length=k.get("length"),
                    after_scan_completed_s=previous_delta(scan_completions,t),
                    after_scan_start_s=previous_delta(scan_starts,t),
                    before_next_scan_start_s=next_delta(scan_starts,t)))
            counts[(kind, r["raw_freq"], r["raw_wcid"], k["resolved_wcid"],
                    k["link"], r["raw_bss"], k["encap"])] += 1
    if not counts:
        raise ValueError("no peer data descriptors in sustained window")
    fields = ("classification", "freq", "raw_wcid", "resolved_wcid",
              "link", "raw_bss", "encap")
    frame_fields = ("freq", "wcid", "bss", "kind", "u2m", "data")
    return dict(start=start, end=end, clock_uncertainty_s=hi-lo,
                descriptor_counts=[dict(zip(fields, key), count=n)
                                   for key, n in sorted(counts.items())],
                binding_mismatches=mismatches,
                matched_host_data_tx_status_counts=[
                    dict(zip(("classification","hw_band","wcid","link","format",
                              "ack_error","encap"),key),count=n)
                    for key,n in sorted(tx_counts.items())],
                accepted_frame_counts=[dict(zip(frame_fields, key), count=n)
                                       for key, n in sorted(frame_counts.items())],
                method="RX descriptor evidence, not socket or TX success. "
                       "Connected BSS and STA state come from acknowledged commands; "
                       "frequency from matched granted ROC requests.")


def selftest():
    assert frequency(1, 1) == 2412 and frequency(1, 14) == 2484
    assert frequency(2, 36) == 5180 and frequency(3, 1) == 5955
    assert frequency(3, 2) == 5935
    # Synthetic two-link grant and acknowledged peer lifecycle. Exercise
    # both links, deactivation, raw/host mismatch and descriptor corruption.
    events = []
    def emit(t, event, **fields):
        events.append((D(t), "mt7925_lab_" + event, "test-1",
                       " ".join(f"{k}={v}" for k,v in fields.items()), 0))
    for slot, band, channel in ((0, 2, 36), (1, 1, 1)):
        emit(1, "mlo_roc_req", slot=slot, token=3, tag=slot*3,
             bss=slot, type=10, band=band, channel=channel)
    emit(2, "mlo_roc_result", token=3, result=0)
    for slot, band, channel in ((0, 2, 36), (1, 1, 1)):
        emit(3, "roc_wire", token=3, expected=3, status=0, tag=slot*4,
             bss=slot, type=10, band=band, channel=channel, dbdc=slot)
        emit(4, "roc_band", token=3, tag=slot*4, bss=slot, new=slot)
        emit(5, "bss_result", bss=slot, link=1-slot, wcid=slot+2,
             enabled=1, result=0)
        emit(6, "sta_result", bss=slot, link=1-slot, wcid=slot+2,
             enabled=1, state=2, result=0)
    def descriptor(t, slot, raw_bss=None, corrupt=False):
        channel = (36, 1)[slot]
        emit(t, "rxdesc", word1=slot+2+(int(corrupt)<<25),
             word2=(slot if raw_bss is None else raw_bss) | 128,
             word3=(channel<<8) | (1<<16), resolved_wcid=slot+2,
             result=0, sta=1, valid=1, link=1-slot, encap=1,
             freq=(5180, 2412)[slot])
    descriptor(11, 0)
    descriptor(12, 1)
    events.append((D("12.025"),"api_scan_completed","test-1","",0))
    descriptor(13, 1, raw_bss=0)
    events.append((D("13.5"),"drv_hw_scan","test-1","",0))
    descriptor(14, 0, corrupt=True)
    emit("12.1","txs_peer_data",wcid=2,link=1,valid=1,band=0,
         pid=3,format=0,ack_error=0,encap=1,length=100)
    emit("12.2","txs_peer_data",wcid=3,link=0,valid=1,band=1,
         pid=4,format=0,ack_error=0,encap=1,length=100)
    emit("12.3","txs_peer_data",wcid=3,link=0,valid=1,band=0,
         pid=5,format=0,ack_error=1,encap=1,length=100)
    emit(15, "sta_result", bss=1, link=0, wcid=3,
         enabled=0, state=0, result=0)
    descriptor(16, 1)
    descriptor(21, 0)  # outside common coverage
    parsed = dict(events=sorted(events,key=lambda e:e[0]), offset_lo=D(0),
                  offset_hi=D(0), first_anchor=D(0), last_anchor=D(30))
    scan = {"tests": [{"replies": [{"received": "10"}, {"received": "20"}]}]*2}
    result = analyze(parsed, scan)
    assert Counter({r["classification"]: sum(x["count"] for x in result["descriptor_counts"]
                    if x["classification"] == r["classification"])
                    for r in result["descriptor_counts"]}) == Counter({
        "matching_associated_peer": 2, "binding_or_frequency_mismatch": 1,
        "descriptor_error": 1, "no_verified_connected_peer": 1})
    assert {r["freq"] for r in result["descriptor_counts"]
            if r["classification"] == "matching_associated_peer"} == {2412,5180}
    mismatch,=result["binding_mismatches"]
    assert mismatch["after_scan_completed_s"]==D(".975")
    assert mismatch["before_next_scan_start_s"]==D(".5")
    assert mismatch["expected_bss"]==1 and mismatch["raw_bss"]==0
    tx=result["matched_host_data_tx_status_counts"]
    assert sum(r["count"] for r in tx)==3
    assert {r["hw_band"] for r in tx if r["classification"]=="matching_associated_peer"
            and r["ack_error"]==0}=={0,1}
    assert sum(r["count"] for r in tx if r["classification"]=="binding_or_band_mismatch")==1
    print("RX_LINK_ACTIVITY_SELFTEST_PASS")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("trace", nargs="?", type=Path)
    p.add_argument("scan", nargs="?", type=Path)
    p.add_argument("--selftest", action="store_true")
    a = p.parse_args()
    if a.selftest:
        selftest()
    elif a.trace and a.scan:
        print(json.dumps(analyze(rx.absence.trace.parse(a.trace.read_text()),
                                 json.loads(a.scan.read_text())), default=str, indent=2))
    else:
        p.error("supply trace and scan report")
