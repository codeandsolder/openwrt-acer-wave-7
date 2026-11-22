#!/usr/bin/env python3
"""Inspect host MLO binding and descriptor evidence, not inferred RF link."""
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


def describe(events):
    bindings = {}
    counts = Counter()
    unmatched = Counter()
    descriptors = []
    history = []
    for t, name, task, payload, cpu in events:
        if name == "mt7925_lab_binding":
            k = absence.fields(payload)
            history.append(dict(t=t, **k))
            if k["sta"]:
                # A subsequent successful binding replaces this index.
                # This is a host map, not an RF or firmware execution map.
                bindings[k["wcid"]] = k
        elif name == "mt7925_lab_txdesc":
            k = absence.fields(payload)
            # mt76_connac3_mac.h: WLAN_IDX 11:0, TGID 13:12,
            # OWN_MAC 30:25 and DIS_MAT in TXD6 bit 3.
            decoded = dict(wcid=k["word1"] & 0xfff,
                           tgid=(k["word1"] >> 12) & 3,
                           own_mac=(k["word1"] >> 25) & 63,
                           mat_enabled=not bool(k["word6"] & 8))
            if decoded["wcid"] != k["wcid"]:
                raise ValueError("descriptor WLAN index disagrees with WCID")
            if not k["sta"]:
                continue
            binding = bindings.get(k["wcid"])
            if binding is None or (binding["bss"], binding["link"]) != (k["bss"], k["link"]):
                unmatched[(k["wcid"], k["bss"], k["link"])] += 1
                continue
            if not binding["mld"]:
                continue
            key = (k["bss"], k["link"], k["wcid"], decoded["tgid"],
                   decoded["own_mac"], decoded["mat_enabled"], k["encap"], k["qid"])
            counts[key] += 1
            descriptors.append((t, key))
    if not history or not counts:
        raise ValueError("missing binding or mapped MLO descriptor evidence")
    def rows(counter):
        return [dict(bss=b, link=l, wcid=w, tgid=g, own_mac=o,
                     mat_enabled=m, encap=e, qid=q, count=n)
                for (b,l,w,g,o,m,e,q),n in sorted(counter.items())]
    return history, descriptors, rows(counts), [
        dict(wcid=w,bss=b,link=l,count=n) for (w,b,l),n in sorted(unmatched.items())]


def analyze(parsed, timing):
    history, desc, counts, unmatched = describe(parsed["events"])
    lo, hi = parsed["offset_lo"], parsed["offset_hi"]
    windows = []
    for window in timing["windows"] + timing.get("isolated_unattributed_multichannel", []):
        gap = window["common_arrival_silence"]
        start, end = D(gap["last_reply"]), D(gap["next_reply"])
        if end-start < D(".25") or not any(p["missing_sequences"] for p in window["paths"]):
            continue
        if start < parsed["first_anchor"]+hi or end > parsed["last_anchor"]+lo:
            continue
        selected = Counter(key for t,key in desc if start <= t+lo and t+hi <= end)
        windows.append(dict(label=window.get("label","unattributed-multichannel"),
                            start=start, end=end, mapped_descriptors=sum(selected.values()),
                            destinations=[dict(bss=b,link=l,wcid=w,tgid=g,own_mac=o,
                                               mat_enabled=m,encap=e,qid=q,count=n)
                                          for (b,l,w,g,o,m,e,q),n in sorted(selected.items())]))
    return dict(method="Host provisioning and final TX descriptor fields; a mapped descriptor, including MAT, does not establish the RF transmit link. Unmatched station descriptors are reported, never guessed.",
                bindings=history, descriptors=counts, unmatched=unmatched, windows=windows)


def selftest():
    def e(t, name, payload):
        return D(t), "mt7925_lab_"+name, "task", payload, 0
    binding = e("10","binding","bss=0 link=1 wcid=3 primary=3 freq=5180 sta=1 mld=1")
    desc = e("10.2","txdesc","bss=0 link=1 wcid=3 pid=0 qid=0 word1=4099 word6=0 encap=1 sta=1")
    mismatched = e("10.3","txdesc","bss=1 link=0 wcid=3 pid=0 qid=0 word1=4099 word6=8 encap=1 sta=1")
    history, entries, rows, unmatched = describe([binding,desc,mismatched])
    assert len(history)==len(entries)==len(rows)==len(unmatched)==1
    assert rows[0]["mat_enabled"] and rows[0]["tgid"]==1 and rows[0]["wcid"]==3
    assert unmatched[0]["bss"]==1
    try:
        describe([binding, e("10.2","txdesc",desc[3].replace("word1=4099","word1=4100"))])
    except ValueError:
        pass
    else:
        raise AssertionError("inconsistent WLAN index accepted")
    print("CLIENT_LINK_BINDING_SELFTEST_PASS")


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("trace",type=Path,nargs="?")
    p.add_argument("timing",type=Path,nargs="?")
    p.add_argument("--selftest",action="store_true")
    a=p.parse_args()
    if a.selftest:
        selftest()
    else:
        if a.trace is None or a.timing is None:
            p.error("supply trace and arrival timing")
        print(json.dumps(analyze(absence.trace.parse(a.trace.read_text()),
                                 json.loads(a.timing.read_text())),indent=2,default=str))
