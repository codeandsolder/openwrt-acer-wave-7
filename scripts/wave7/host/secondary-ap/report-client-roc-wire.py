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
    for t, name, _, payload, cpu in events:
        event = name.removeprefix("mt7925_lab_")
        if event not in {"mlo_roc_req", "mlo_roc_result", "roc_wire", "roc_abort", "roc_geometry", "roc_band", "roc_sync"}:
            continue
        k = rx.fields(payload)
        k["t"] = t
        k["event"] = event
        k["cpu"] = cpu
        token = k["token"]
        if event == "mlo_roc_req" and k["slot"] == 0:
            session = dict(token=token, requests=[], results=[], grants=[], aborts=[],
                           geometry=[], assignments=[], sync=[])
            requests.append(session)
            active[token] = session
        session = active.get(token)
        if session is None or (event == "roc_sync" and not k["mlo"]):
            other.append(k)
            continue
        key = {"mlo_roc_req": "requests", "mlo_roc_result": "results",
               "roc_wire": "grants", "roc_abort": "aborts",
               "roc_geometry": "geometry", "roc_band": "assignments",
               "roc_sync": "sync"}[event]
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

        # roc_band is a trace immediately BEFORE the actual band store.
        # A strictly earlier return proves the waiter left before that store;
        # a later return only establishes order relative to the tracepoint.
        returned = [r for r in s["sync"] if r["phase"] == 1 and r["result"] == 0]
        primary_wake = [r for r in s["sync"] if r["phase"] == 0]
        if len(returned) == 1 and len(primary_wake) == 1 and s.get("bands_applied"):
            last_assignment = max(a["t"] for a in s["assignments"])
            delta = returned[0]["t"] - last_assignment
            s["wait_return_minus_last_band_pretrace_s"] = delta
            s["wait_order"] = (
                "return_before_last_band_pretrace" if delta < -D("0.000001")
                else "return_after_last_band_pretrace" if delta > D("0.000001")
                else "timestamp_ambiguous"
            )

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


def beacon_timing_checks(records):
    """Correlate accepted beacon commands with the last accepted BSS identity.

    A nonzero interval/DTIM and matching link prove consistent command metadata,
    not that firmware uses the values or receives beacons on that link.
    """
    bsses = {}
    latest = {}
    checks = []
    membership = []
    for record in records:
        event = record["event"]
        if event == "bss_result" and record["result"] == 0:
            bss = record["bss"]
            old = bsses.get(bss)
            if not record["enabled"]:
                bsses.pop(bss, None)
                latest.pop(bss, None)
            else:
                if old is None or (old["link"], old["wcid"]) != (record["link"], record["wcid"]):
                    latest.pop(bss, None)
                bsses[bss] = record
        elif event == "bss_bcnft":
            bss = record["bss"]
            binding = bsses.get(bss)
            problems = []
            if record["result"] != 0:
                problems.append("firmware_rejected")
            if not binding:
                problems.append("no_acknowledged_connected_bss")
            elif binding["link"] != record["link"]:
                problems.append("link_mismatch")
            if not record["interval"]:
                problems.append("zero_beacon_interval")
            if not record["dtim"]:
                problems.append("zero_dtim_period")
            check = dict(t=record["t"], bss=bss, command_link=record["link"],
                         connected_link=binding["link"] if binding else None,
                         interval=record["interval"], dtim=record["dtim"],
                         result=record["result"], problems=problems)
            checks.append(check)
            if record["result"] == 0:
                latest[bss] = check
        elif event == "sta_mld_update":
            membership.append(dict(t=record["t"], target_bss=record["bss"],
                                   target_wcid=record["wcid"], result=record["result"],
                                   connected_bsses=[
                                       dict(bss=bss, link=binding["link"],
                                            beacon=latest.get(bss))
                                       for bss, binding in sorted(bsses.items())]))
    return dict(commands=checks, standalone_membership=membership)


def association(trace):
    """Report provisioning even when association/handshake failed before probes."""
    sessions, other = grant_pairs(trace["events"])
    relevant = rx.PROVISION | {"roc_geometry", "roc_band", "roc_sync", "key_result",
                              "decap_config", "sta_mld_slot", "sta_mld_update", "dev_rebind",
                              "bss_ps", "bss_bcnft"}
    transitions = []
    records = []
    for t, name, task, payload, cpu in trace["events"]:
        event = name.removeprefix("mt7925_lab_")
        if name.startswith("mt7925_lab_") and event in relevant:
            records.append(dict(t=t, event=event, cpu=cpu, **rx.fields(payload)))
        if event in {"scan_req", "scan_tlv", "beacon_loss", "absence"}:
            transitions.append(dict(t=t, event=event, cpu=cpu, **rx.fields(payload)))
        elif event == "mcu_rx":
            fields = rx.fields(payload)
            if fields["option"] & 4 and fields["eid"] in {12, 14, 39, 41}:
                transitions.append(dict(t=t, event=event, cpu=cpu, **fields))
        elif name in {"api_connection_loss", "api_beacon_loss",
                      "api_scan_completed", "cfg80211_scan_done",
                      "drv_change_vif_links", "drv_change_sta_links"}:
            transitions.append(dict(t=t, event=name, cpu=cpu, payload=payload))
    if not records:
        raise ValueError("missing association trace")
    return dict(trace_events=trace["trace_count"], sessions=sessions,
                other_roc_events=other, provisioning=records,
                beacon_timing=beacon_timing_checks(records),
                firmware_transitions=transitions,
                clock_offset_lower=trace.get("offset_lo"),
                clock_offset_upper=trace.get("offset_hi"),
                method="Association metadata only; no frame payload or key bytes. "
                       "ROC band trace precedes the actual store; report order relative "
                       "to that trace, not completion of the store.")


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
    report = association({"events": [event("1", "key_result",
        "wcid=2 bss=1 link=0 key_link=-1 key_index=0 cipher=1027076 pairwise=1 add=1 result=0"),
        event("2", "decap_config", "wcid=2 link=0 enabled=1")], "trace_count": 2})
    assert report["provisioning"][0]["key_link"] == -1
    assert report["provisioning"][1]["enabled"] == 1
    assert report["sessions"] == []
    report=association({"events":[event("1","sta_mld_update",
        "wcid=2 bss=0 result=0")],"trace_count":1})
    assert report["provisioning"][0]["event"]=="sta_mld_update"
    assert report["provisioning"][0]["result"]==0
    power = association({"events": [
        event("1", "bss_ps", "bss=1 link=0 state=0 result=0"),
        event("2", "bss_bcnft", "bss=1 link=0 interval=100 dtim=2 result=0"),
    ], "trace_count": 2})
    assert [r["event"] for r in power["provisioning"]] == ["bss_ps", "bss_bcnft"]
    assert power["provisioning"][0]["state"] == 0
    assert power["provisioning"][1]["interval"] == 100
    timing = association({"events": [
        event("1", "bss_result", "bss=0 link=1 wcid=2 enabled=1 result=0"),
        event("2", "bss_bcnft", "bss=0 link=0 interval=0 dtim=0 result=0"),
        event("3", "bss_result", "bss=1 link=0 wcid=3 enabled=1 result=0"),
        event("4", "bss_bcnft", "bss=1 link=0 interval=100 dtim=2 result=0"),
        event("5", "sta_mld_update", "wcid=2 bss=0 result=0"),
        event("6", "bss_bcnft", "bss=0 link=1 interval=100 dtim=2 result=0"),
        event("7", "bss_bcnft", "bss=0 link=0 interval=0 dtim=0 result=1"),
        event("8", "sta_mld_update", "wcid=2 bss=0 result=0"),
        event("9", "bss_result", "bss=1 link=0 wcid=3 enabled=0 result=0"),
        event("10", "sta_mld_update", "wcid=2 bss=0 result=0"),
    ], "trace_count": 10})["beacon_timing"]
    assert timing["commands"][0]["problems"] == [
        "link_mismatch", "zero_beacon_interval", "zero_dtim_period"]
    first, corrected, removed = timing["standalone_membership"]
    assert first["connected_bsses"][0]["beacon"]["interval"] == 0
    assert corrected["connected_bsses"][0]["beacon"]["problems"] == []
    assert len(removed["connected_bsses"]) == 1
    wake = event("1.199990", "roc_sync", "phase=0 bss=0 token=3 mlo=1 granted=0 pending=1 result=0")
    def wait_return(t):
        return event(t, "roc_sync", "phase=1 bss=0 token=3 mlo=1 granted=1 pending=1 result=0")
    for t, expected in (("1.199995", "return_before_last_band_pretrace"),
                        ("1.200000", "timestamp_ambiguous"),
                        ("1.200020", "return_after_last_band_pretrace")):
        ordered = sorted(fixed + [wake, wait_return(t)], key=lambda e: e[0])
        result, _ = grant_pairs(ordered)
        assert result[0]["wait_order"] == expected
    result, _ = grant_pairs(fixed + [wait_return("1.3")])
    assert "wait_order" not in result[0]
    firmware = association({"events": [
        event("1", "key_result", "wcid=2 bss=1 link=0 result=0"),
        event("2", "mcu_rx", "eid=12 seq=0 option=6 ext_eid=0 length=56"),
        event("2.000001", "beacon_loss", "bss=0 tag=0 len=8 reason=1 links=1"),
        event("3", "mcu_rx", "eid=12 seq=1 option=0 ext_eid=0 length=56"),
    ], "trace_count": 4})
    assert [r["event"] for r in firmware["firmware_transitions"]] == ["mcu_rx", "beacon_loss"]
    print("CLIENT_ROC_WIRE_SELFTEST_PASS")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("trace",type=Path,nargs="?")
    p.add_argument("timing",type=Path,nargs="?")
    p.add_argument("--selftest",action="store_true")
    p.add_argument("--association-only",action="store_true")
    a=p.parse_args()
    if a.selftest:
        selftest()
    elif a.association_only:
        if a.trace is None or a.timing is not None:
            p.error("supply only trace for association metadata")
        print(json.dumps(association(rx.absence.trace.parse(a.trace.read_text())),
                         indent=2, default=str))
    else:
        if a.trace is None or a.timing is None:
            p.error("supply trace and timing")
        print(json.dumps(analyze(rx.absence.trace.parse(a.trace.read_text()),
                                 json.loads(a.timing.read_text())),indent=2,default=str))
