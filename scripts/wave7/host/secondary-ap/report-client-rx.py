#!/usr/bin/env python3
"""Correlate raw RX descriptor channel and resolved host WCID with absence.

No payload or MAC address is captured. Successful fill_rx indicates driver
acceptance, not delivery through mac80211/reorder/security or to the socket.
"""
import argparse
from collections import Counter
from decimal import Decimal as D
import importlib.util
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location(
    "absence", Path(__file__).with_name("report-bss-absence.py"))
absence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(absence)

RX = "mt7925_lab_rxdesc"
PROVISION = {
    "bss_basic", "bss_mld", "bss_rlm", "sta_mld", "sta_eht_mld",
    "sta_result", "bss_result", "mlo_roc_req", "mlo_roc_result", "binding", "roc",
}


def fields(payload):
    # Firmware command and RX parser return codes are signed.
    return {k: int(v) for k, v in re.findall(r"(\w+)=(-?\d+)", payload)}


def decode(k):
    ch = (k["word3"] >> 8) & 255
    if ch > 180:
        freq = 5950 + (ch - 181) * 20 + 5
    elif ch > 14:
        freq = 5000 + ch * 5
    elif ch == 14:
        freq = 2484
    elif ch:
        freq = 2407 + ch * 5
    else:
        freq = 0
    addr_type = (k["word3"] >> 16) & 3
    return dict(raw_wcid=k["word1"] & 4095, raw_band=(k["word1"] >> 27) & 3,
                raw_bss=k["word2"] & 63, channel_code=ch, raw_freq=freq,
                u2m=addr_type == 1, data=not bool(k["word2"] & (1 << 29)),
                raw_encap=bool(k["word2"] & (1 << 7)),
                fcs_error=bool(k["word3"] & (1 << 24)),
                icv_error=bool(k["word1"] & (1 << 25)),
                mic_error=bool(k["word1"] & (1 << 26)),
                cipher_mismatch=bool(k["word1"] & (1 << 23)))


def summarize(records):
    c = Counter()
    for r in records:
        key = (r["raw_freq"], r["raw_wcid"], r["resolved_wcid"], r["link"],
               r["data"], r["u2m"], r["sta"], r["result"], r["encap"],
               r["binding_match"], r["absence"], r["fcs_error"], r["icv_error"],
               r["mic_error"], r["cipher_mismatch"])
        c[key] += 1
    names = ("freq", "raw_wcid", "resolved_wcid", "link", "data", "u2m",
             "sta", "result", "encap", "binding_match", "absence", "fcs_error",
             "icv_error", "mic_error", "cipher_mismatch")
    return [dict(zip(names, key), count=count) for key, count in sorted(c.items())]


def analyze(trace, timing):
    absence.extract(trace["events"], True)
    bindings = {}
    bss_state = {}
    records, provision = [], []
    for t, name, task, payload, cpu in trace["events"]:
        if not name.startswith("mt7925_lab_"):
            continue
        event = name.removeprefix("mt7925_lab_")
        if event == "binding":
            k = fields(payload)
            if not k["sta"]:
                bindings = {w: v for w, v in bindings.items() if v["bss"] != k["bss"]}
                bss_state.pop(k["bss"], None)
            else:
                bindings[k["wcid"]] = k
        elif event == "absence":
            k = fields(payload)
            bss_state[k["bss"]] = "absent" if k["absent"] else "present"
        elif name == RX:
            k = fields(payload)
            r = dict(t=t, **k, **decode(k))
            if not k["result"] and r["raw_freq"] != k["freq"]:
                raise ValueError("raw channel decode disagrees with driver freq")
            b = bindings.get(k["resolved_wcid"]) if k["sta"] else None
            r["binding_match"] = ("unknown" if b is None else
                                  "match" if (b["link"], b["freq"]) == (k["link"], k["freq"])
                                  else "mismatch")
            r["absence"] = bss_state.get(b["bss"], "unknown") if b else "unknown"
            records.append(r)
        if event in PROVISION:
            provision.append(dict(t=t, event=event, **fields(payload)))
    if not records or not any(r["sta"] and r["data"] and not r["result"] for r in records):
        raise ValueError("missing peer RX evidence")
    lo, hi = trace["offset_lo"], trace["offset_hi"]
    windows = []
    for w in timing["windows"] + timing.get("isolated_unattributed_multichannel", []):
        span = w["common_arrival_silence"]
        start, end = D(span["last_reply"]), D(span["next_reply"])
        if end-start < D(".25") or not any(p["missing_sequences"] for p in w["paths"]):
            continue
        if start < trace["first_anchor"]+hi or end > trace["last_anchor"]+lo:
            continue
        width = end-start
        phases = {}
        for label, a, b in (("before", start-width, start), ("inside", start, end),
                            ("after", end, end+width)):
            rows = [r for r in records if a <= r["t"]+lo and r["t"]+hi <= b]
            phases[label] = dict(count=len(rows), by_descriptor=summarize(rows),
                                 peer_data_accepted=sum(r["sta"] and r["data"] and not r["result"] for r in rows),
                                 rejected=sum(bool(r["result"]) for r in rows))
        windows.append(dict(label=w.get("label", "unattributed-multichannel"),
                            duration_s=width, phases=phases))
    return dict(trace_events=trace["trace_count"], clock_uncertainty_s=hi-lo,
                raw_rx=len(records), all_rx=summarize(records),
                errors=dict(Counter(str(r["result"]) for r in records if r["result"])),
                provisioning=provision, windows=windows,
                method="RX raw channel code and resolved WCID are independent. Presence is last firmware declaration, not RF availability. Window counts include only records wholly within bracketed clock bounds.")


def selftest():
    base=dict(word1=1, word2=128, word3=(36 << 8) | (1 << 16))
    row=decode(base)
    assert row["raw_freq"] == 5180 and row["data"] and row["u2m"] and row["raw_encap"]
    assert decode(dict(base, word3=14 << 8))["raw_freq"] == 2484
    assert decode(dict(base, word3=181 << 8))["raw_freq"] == 5955
    assert decode(dict(base, word3=182 << 8))["raw_freq"] == 5975
    assert not decode(dict(base, word2=1 << 29))["data"]
    assert decode(dict(base, word1=1 << 25))["icv_error"]
    assert fields("event: result=-22 enabled=1") == {"result": -22, "enabled": 1}
    print("CLIENT_RX_SELFTEST_PASS")


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("trace", type=Path, nargs="?")
    p.add_argument("timing", type=Path, nargs="?")
    p.add_argument("--selftest", action="store_true")
    a=p.parse_args()
    if a.selftest:
        selftest()
    else:
        if a.trace is None or a.timing is None:
            p.error("supply trace and timing")
        print(json.dumps(analyze(absence.trace.parse(a.trace.read_text()),
                                 json.loads(a.timing.read_text())), indent=2, default=str))
