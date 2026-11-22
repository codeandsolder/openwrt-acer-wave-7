#!/usr/bin/env python3
"""Correlate vendor BSS absence notifications with measured reply silence.

BSS indices are firmware identities, not mac80211 link IDs. Report them
separately until a live index/link mapping is established. A presence
event is a firmware declaration, not proof of RF reception.
"""
import argparse
from collections import Counter, defaultdict
from decimal import Decimal as D
import importlib.util
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location(
    "trace", Path(__file__).with_name("report-client-kernel-trace.py"))
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)

HEADER = "mt7925_lab_mcu_rx"
ABSENCE = "mt7925_lab_absence"


def fields(payload):
    return {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", payload)}


def extract(events, require_fields):
    pending = {}
    headers, records = [], []
    for when, name, task, payload, cpu in events:
        if name == HEADER:
            key = (cpu, task)
            pending.pop(key, None)
            kv = fields(payload)
            if kv["eid"] == 0x29 and kv["option"] & 4:
                headers.append((when, kv))
                if kv["length"] == 56:
                    pending[key] = when
        elif name == ABSENCE:
            kv = fields(payload)
            # The diagnostic is called directly after the MCU header
            # tracepoint on the same NAPI execution path. Do not join
            # different contexts or two records to one header.
            key = (cpu, task)
            if key not in pending:
                raise ValueError("absence field record without matching MCU header")
            before = pending.pop(key)
            if when < before or when-before > D(".010"):
                raise ValueError("absence/header pairing outside 10ms")
            if kv["tag"] != 0 or kv["len"] != 8 or kv["absent"] not in (0, 1):
                raise ValueError(f"unrecognized absence ABI: {kv}")
            records.append(dict(t=when, **kv))
    expected = sum(kv["length"] == 56 for _, kv in headers)
    if require_fields and (not headers or expected != len(headers) or len(records) != expected):
        raise ValueError(f"incomplete field coverage: {len(headers)} headers, {expected} fixed-size, {len(records)} field records")
    if records and len(records) != expected:
        raise ValueError("partial absence field capture")
    return headers, records


def intervals(records):
    """Return completed intervals; repeated absent events update quota only."""
    opened = {}
    complete = defaultdict(list)
    unpaired_presence = Counter()
    for event in records:
        bss, absent = event["bss"], event["absent"]
        if absent:
            opened.setdefault(bss, []).append(event)
        elif bss not in opened:
            unpaired_presence[bss] += 1
        else:
            start = opened.pop(bss)
            complete[bss].append(dict(start=start[0]["t"], end=event["t"],
                                      quota_updates=[(e["t"], e["quota"]) for e in start],
                                      presence_quota=event["quota"]))
    return complete, opened, unpaired_presence


def overlap(span, lo, hi, start, end):
    # Same-client monotonic timestamps share a single clock offset.
    # Extremal overlap is at one of the offset bounds or a boundary
    # alignment; evaluate the piecewise-linear function exactly.
    a, b = span["start"], span["end"]
    offsets = [lo, hi]
    offsets.extend(x for x in (start-a, start-b, end-a, end-b) if lo <= x <= hi)
    lengths = [max(D(0), min(b+x, end)-max(a+x, start)) for x in offsets]
    return min(lengths), max(lengths)


def classify(parsed, timing, require_fields):
    lo, hi = parsed["offset_lo"], parsed["offset_hi"]
    headers, records = extract(parsed["events"], require_fields)
    spans, open_spans, unpaired = intervals(records)
    windows = []
    gap_header_indices = set()
    for window in timing["windows"] + timing.get("isolated_unattributed_multichannel", []):
        silence = window["common_arrival_silence"]
        start, end = D(silence["last_reply"]), D(silence["next_reply"])
        if end-start < D(".25") or not any(p["missing_sequences"] for p in window["paths"]):
            continue
        if start < parsed["first_anchor"]+hi or end > parsed["last_anchor"]+lo:
            continue
        # Only count header records guaranteed inside the measured window.
        inside = [i for i, (t, _) in enumerate(headers) if start <= t+lo and t+hi <= end]
        gap_header_indices.update(inside)
        nearby_events = [(t, kv) for t, kv in headers
                         if start-D(".15") <= t+lo and t+hi <= end+D(".15")]
        nearby = [dict(offset_from_last_reply_bounds=[t+lo-start, t+hi-start],
                       length=kv["length"], option=kv["option"]) for t, kv in nearby_events]
        # Monotonic event-to-event intervals do not incur wall-clock offset uncertainty.
        nearby_intervals = [b[0]-a[0] for a,b in zip(nearby_events,nearby_events[1:])]
        by_bss = {}
        for bss, candidates in sorted(spans.items()):
            matches = []
            for span in candidates:
                lower, upper = overlap(span, lo, hi, start, end)
                if not upper:
                    continue
                matches.append(dict(
                    absent_start_bounds=[span["start"]+lo-start, span["start"]+hi-start],
                    present_relative_recovery_bounds=[span["end"]+lo-end, span["end"]+hi-end],
                    duration=span["end"]-span["start"],
                    overlap_bounds=[lower,upper],
                    quota_updates=[dict(offset_bounds=[t+lo-start,t+hi-start], quota=q)
                                   for t,q in span["quota_updates"]],
                    presence_quota=span["presence_quota"]))
            if matches:
                by_bss[bss] = matches
        windows.append(dict(label=window.get("label", "unattributed-multichannel"),
                            gap_start=start, gap_end=end, gap_duration=end-start,
                            headers_inside=len(inside), nearby_headers=nearby,
                            nearby_header_intervals_s=nearby_intervals,
                            completed_absence_by_bss=by_bss))
    return dict(
        method="Validated monotonic trace; clock offset bounds propagated to each event and exact interval overlap. Only paired absent-to-present intervals are classified; BSS identities are not inferred as MLO link IDs.",
        field_capture=bool(records),
        headers_total=len(headers),
        headers_within_qualified_gaps=len(gap_header_indices),
        headers_not_definitely_in_qualified_gaps=len(headers)-len(gap_header_indices),
        header_signatures=[dict(option=o, length=l, count=n)
                           for (o,l),n in sorted(Counter((k["option"],k["length"]) for _,k in headers).items())],
        field_signatures=[dict(bss=b, absent=a, quota=q, count=n)
                          for (b,a,q),n in sorted(Counter((e["bss"],e["absent"],e["quota"]) for e in records).items())],
        completed_intervals_by_bss={b:len(v) for b,v in spans.items()},
        unpaired_presence_by_bss=dict(unpaired),
        open_absence_by_bss={b:[dict(t=e["t"],quota=e["quota"]) for e in v] for b,v in open_spans.items()},
        windows=windows)


def selftest():
    def h(t, cpu=0):
        return D(t), HEADER, "napi-1", f"{HEADER}: eid=41 seq=0 option=6 ext_eid=0 length=56", cpu
    def f(t, bss, absent, quota, cpu=0):
        return D(t), ABSENCE, "napi-1", f"{ABSENCE}: bss={bss} tag=0 len=8 absent={absent} quota={quota}", cpu
    events = [h("10"),f("10.000001",3,1,4),h("10.2"),f("10.200001",3,1,0),
              h("10.6"),f("10.600001",3,0,0),h("11"),f("11.000001",4,1,2)]
    headers, records = extract(events, True)
    assert len(headers)==len(records)==4
    spans, opened, unpaired = intervals(records)
    assert spans[3][0]["quota_updates"] == [(D("10.000001"),4),(D("10.200001"),0)]
    assert list(opened)==[4] and not unpaired
    assert overlap(dict(start=D(0),end=D(2)),D(-1),D(1),D(0),D(2)) == (D(1),D(2))
    parsed = dict(events=events, offset_lo=D(99),offset_hi=D("99.002"),
                  first_anchor=D(8),last_anchor=D(15))
    timing = dict(windows=[dict(label="fixture",common_arrival_silence=dict(
        last_reply="109",next_reply="109.7"),paths=[dict(missing_sequences=[1])])])
    result = classify(parsed,timing,True)
    assert result["headers_within_qualified_gaps"]==3
    assert result["headers_not_definitely_in_qualified_gaps"]==1
    assert result["windows"][0]["nearby_header_intervals_s"]==[D(".2"),D(".4")]
    span = result["windows"][0]["completed_absence_by_bss"][3][0]
    assert span["duration"]==D(".6") and span["overlap_bounds"]==[D(".6"),D(".6")]
    for bad in (events[:-1], [h("10"),f("10.000001",3,1,4,cpu=1)],
                [h("10"),f("10.1",3,1,4)],
                [h("10"),f("10.000001",3,2,4)]):
        try:
            extract(bad,True)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid trace accepted")
    assert classify(dict(parsed,events=[e for e in events if e[1]==HEADER]),timing,False)["field_capture"] is False
    print("BSS_ABSENCE_SELFTEST_PASS")


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("trace_file",type=Path,nargs="?")
    p.add_argument("arrival_report",type=Path,nargs="?")
    p.add_argument("--require-fields",action="store_true")
    p.add_argument("--selftest",action="store_true")
    a=p.parse_args()
    if a.selftest:
        selftest()
    else:
        if a.trace_file is None or a.arrival_report is None:
            p.error("supply trace and arrival report")
        print(json.dumps(classify(trace.parse(a.trace_file.read_text()),
                                  json.loads(a.arrival_report.read_text()),
                                  a.require_fields),default=str,indent=2))
