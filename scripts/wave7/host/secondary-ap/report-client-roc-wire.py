#!/usr/bin/env python3
"""Observe actual ROC grant pair, aborts, TX status hardware band and RX class.

The hardware band selector is not an RF-frequency label in single-radio MLO.
No RX frame payload or address is captured.
"""
import argparse
from collections import Counter
from decimal import Decimal as D
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location(
    "rx", Path(__file__).with_name("report-client-rx.py"))
rx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rx)


def decode_txs(k):
    return dict(wcid=(k["word2"] >> 16) & 4095,
                hw_band=(k["word2"] >> 28) & 3,
                pid=(k["word3"] >> 24) & 255,
                fmt=(k["word0"] >> 23) & 3,
                ack_error=(k["word0"] >> 16) & 7,
                ba_error=bool(k["word0"] & (1 << 22)),
                ps_flag=bool(k["word0"] & (1 << 21)),
                txop_timeout=bool(k["word0"] & (1 << 20)),
                host_status=bool(k["word0"] & (1 << 15)))


def decode_frame(k):
    fc = k["fc"]
    if k["encap"]:
        if fc != 65535:
            raise ValueError("unexpected 802.11 frame control for encapsulated RX")
        kind = "8023"
    elif fc == 65535:
        kind = "unknown"
    else:
        frame_type, subtype = (fc >> 2) & 3, (fc >> 4) & 15
        kind = f"type{frame_type}/subtype{subtype}"
        if frame_type == 0:
            kind = {8: "beacon", 5: "probe-response", 13: "action",
                    11: "auth", 1: "assoc-response", 3: "reassoc-response"}.get(subtype, kind)
        elif frame_type == 2:
            kind = {0: "data", 4: "null", 8: "qos-data", 12: "qos-null"}.get(subtype, kind)
    return dict(kind=kind, freq=k["freq"], wcid=k["wcid"], bss=k["raw_bss"],
                u2m=k["u2m"], data=k["data"])


def summarize(records, keys):
    return [dict(zip(keys, key), count=n)
            for key, n in sorted(Counter(tuple(r[k] for k in keys) for r in records).items())]


def grant_pairs(events):
    requests = []
    active = {}
    other = []
    for t, name, _, payload, _ in events:
        event = name.removeprefix("mt7925_lab_")
        if event not in {"mlo_roc_req", "mlo_roc_result", "roc_wire", "roc_abort", "roc_geometry", "roc_band"}:
            continue
        k = rx.fields(payload)
        k["t"] = t
        k["event"] = event
        token = k["token"]
        if event == "mlo_roc_req" and k["slot"] == 0:
            session = dict(token=token, requests=[], results=[], grants=[], aborts=[],
                           geometry=[], assignments=[])
            requests.append(session)
            active[token] = session
        session = active.get(token)
        if session is None:
            other.append(k)
            continue
        key = {"mlo_roc_req": "requests", "mlo_roc_result": "results",
               "roc_wire": "grants", "roc_abort": "aborts",
               "roc_geometry": "geometry", "roc_band": "assignments"}[event]
        session[key].append(k)
    for s in requests:
        rows = s["requests"]
        grants = s["grants"]
        # Require corresponding token, BSS, tag, RF channel and successful status.
        for req in rows:
            want_tag = {0: 0, 3: 4}.get(req["tag"])
            same = [g for g in grants if g["tag"] == want_tag and
                    g["bss"] == req["bss"] and g["token"] == g["expected"] and
                    g["status"] == 0 and g["band"] == req["band"] and
                    g["channel"] == req["channel"] and g["type"] == req["type"]]
            req["matched_grants"] = len(same)
            req["granted_hw_bands"] = sorted({g["dbdc"] for g in same})
        s["complete"] = (len(rows) >= 2 and
                         {r["tag"] for r in rows} == {0, 3} and
                         all(r["matched_grants"] == 1 for r in rows) and
                         len(s["results"]) == 1 and s["results"][0]["result"] == 0)
        if s["geometry"]:
            # Each selected BSS must have the exact geometry record,
            # including marker and matching channel/AP width.
            s["geometry_complete"] = (
                len(s["geometry"]) == len(rows)
                and all(sum(g["slot"] == r["slot"] and
                            g["bss"] == r["bss"] and
                            g["channel"] == r["channel"] and
                            g["bw"] == g["bw_ap"] and g["extra"] & 1
                            for g in s["geometry"]) == 1 for r in rows))
        if s["assignments"]:
            s["bands_applied"] = all(
                len(r["granted_hw_bands"]) == 1 and
                sum(a["bss"] == r["bss"] and
                    a["tag"] == {0:0,3:4}[r["tag"]] and
                    a["new"] == r["granted_hw_bands"][0]
                    for a in s["assignments"]) == 1 for r in rows)

    return requests, other


def analyze(trace, timing):
    events = trace["events"]
    sessions, other = grant_pairs(events)
    frames, txs = [], []
    for t, n, _, p, _ in events:
        if n == "mt7925_lab_rx_frame":
            frames.append(dict(t=t, **decode_frame(rx.fields(p))))
        elif n == "mt7925_lab_txs_wire":
            txs.append(dict(t=t, **decode_txs(rx.fields(p))))
    if not sessions or not frames or not txs:
        raise ValueError("missing ROC, RX or TX wire trace evidence")
    fkeys = ("freq", "wcid", "bss", "kind", "u2m", "data")
    tkeys = ("wcid", "hw_band", "fmt", "ack_error", "ba_error", "ps_flag",
             "txop_timeout", "host_status")
    lo, hi = trace["offset_lo"], trace["offset_hi"]
    windows = []
    for w in timing["windows"] + timing.get("isolated_unattributed_multichannel", []):
        span = w["common_arrival_silence"]
        a, b = D(span["last_reply"]), D(span["next_reply"])
        if b-a < D(".25") or not any(p["missing_sequences"] for p in w["paths"]):
            continue
        if a < trace["first_anchor"]+hi or b > trace["last_anchor"]+lo:
            continue
        f = [r for r in frames if a <= r["t"]+lo and r["t"]+hi <= b]
        tx = [r for r in txs if a <= r["t"]+lo and r["t"]+hi <= b]
        windows.append(dict(label=w.get("label","unattributed-multichannel"),
                            duration_s=b-a, frames=summarize(f,fkeys),
                            txs=summarize(tx,tkeys)))
    return dict(trace_events=trace["trace_count"], clock_uncertainty_s=hi-lo,
                sessions=sessions, other_roc_events=other, raw_txs=len(txs),
                raw_frames=len(frames), txs=summarize(txs,tkeys),
                frames=summarize(frames,fkeys), windows=windows,
                method="Hardware-band selector, not RF frequency. TX status records may be unmatched and are not necessarily unique delivered packets. Receive subtype is only decoded for raw 802.11 frames.")


def selftest():
    assert decode_frame(dict(fc=128, encap=0, freq=2412, wcid=18,
                             raw_bss=1,u2m=0,data=0))["kind"] == "beacon"
    assert decode_frame(dict(fc=65535,encap=1,freq=5180,wcid=1,
                             raw_bss=0,u2m=1,data=1))["kind"] == "8023"
    assert decode_txs(dict(word0=1<<16,word1=0,word2=(2<<28)|(4<<16),
                           word3=12<<24,word4=0))["ack_error"] == 1
    def event(t, n, p):
        return D(t), "mt7925_lab_"+n, "task", p, 0
    events=[
        event("1", "mlo_roc_req","slot=0 tag=0 bss=0 token=3 type=10 band=2 channel=36 dbdc=255 duration=5"),
        event("1", "mlo_roc_req","slot=1 tag=3 bss=1 token=3 type=10 band=1 channel=1 dbdc=255 duration=5"),
        event("1.1","mlo_roc_result","token=3 result=0"),
        event("1.2","roc_wire","tag=0 len=20 bss=0 token=3 expected=3 status=0 type=10 band=2 channel=36 dbdc=0 duration=5"),
        event("1.2","roc_wire","tag=4 len=20 bss=1 token=3 expected=3 status=0 type=10 band=1 channel=1 dbdc=1 duration=5"),
        event("1.3","roc_abort","bss=0 token=3 expected=3 band=255 result=0"),
    ]
    result, other=grant_pairs(events)
    assert not other and result[0]["complete"]
    assert result[0]["requests"][1]["granted_hw_bands"]==[1]
    result,_=grant_pairs(events[:-2])
    assert not result[0]["complete"]
    result,_=grant_pairs(events[:4]+[event("1.2","roc_wire",events[4][3].replace("expected=3","expected=4"))])
    assert not result[0]["complete"]
    fixed=events[:2]+[
        event("1.01","roc_geometry","slot=0 token=3 bss=0 bw=1 bw_ap=1 channel=36 center=42 center2=0 sco=1 extra=1"),
        event("1.01","roc_geometry","slot=1 token=3 bss=1 bw=0 bw_ap=0 channel=1 center=1 center2=0 sco=0 extra=1"),
    ]+events[2:5]+[
        event("1.2","roc_band","bss=0 link=1 old=255 new=0 token=3 tag=0"),
        event("1.2","roc_band","bss=1 link=0 old=255 new=1 token=3 tag=4"),
    ]+events[5:]
    result,_=grant_pairs(fixed)
    assert result[0]["geometry_complete"] and result[0]["bands_applied"]
    result,_=grant_pairs(fixed[:-2]+fixed[-1:])
    assert not result[0]["bands_applied"]
    print("CLIENT_ROC_WIRE_SELFTEST_PASS")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("trace",type=Path,nargs="?")
    p.add_argument("timing",type=Path,nargs="?")
    p.add_argument("--selftest",action="store_true")
    a=p.parse_args()
    if a.selftest:
        selftest()
    else:
        if a.trace is None or a.timing is None:
            p.error("supply trace and timing")
        print(json.dumps(analyze(rx.absence.trace.parse(a.trace.read_text()),
                                 json.loads(a.timing.read_text())),indent=2,default=str))
