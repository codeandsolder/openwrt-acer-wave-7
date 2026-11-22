#!/usr/bin/env python3
"""Inspect host MLO binding and descriptor evidence, not inferred RF link."""
import argparse
from collections import Counter
from decimal import Decimal as D
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location(
    "absence", Path(__file__).with_name("report-bss-absence.py"))
absence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(absence)


def describe(events):
    bindings = {}
    availability = {}
    presence_counts = Counter()
    quota_windows = {}
    counts = Counter()
    unmatched = Counter()
    descriptors = []
    history = []
    for t, name, task, payload, cpu in events:
        if name == "mt7925_lab_binding":
            k = absence.fields(payload)
            history.append(dict(t=t, **k))
            if not k["sta"]:
                # Provisioning can reuse a firmware BSS index.
                availability.pop(k["bss"], None)
                for wcid, binding in list(bindings.items()):
                    if binding["bss"] == k["bss"]:
                        del bindings[wcid]
            if k["sta"]:
                # A subsequent successful binding replaces this index.
                # This is a host map, not an RF or firmware execution map.
                bindings[k["wcid"]] = k
        elif name == "mt7925_lab_absence":
            k = absence.fields(payload)
            if k["tag"] != 0 or k["len"] != 8 or k["absent"] not in (0, 1):
                raise ValueError("unrecognized BSS absence format")
            interval = dict(start=t, bss=k["bss"], absent=k["absent"],
                            quota=k["quota"], ordinary_descriptors=0)
            availability[k["bss"]] = interval
            if k["absent"]:
                quota_windows[(k["bss"], t)] = interval
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
            state = availability.get(k["bss"])
            own_state = "unknown" if state is None else ("absent" if state["absent"] else "present")
            alternatives = {v["bss"] for v in bindings.values()
                            if v["mld"] and v["primary"] == binding["primary"]
                            and v["bss"] != k["bss"]}
            alt_states = [availability.get(b) for b in alternatives]
            alt_state = ("present" if any(v is not None and not v["absent"] for v in alt_states)
                         else "unknown" if not alt_states or any(v is None for v in alt_states)
                         else "absent")
            # AC queues, individually addressed station, hardware 802.3
            # encapsulation; deliberately not management/PS/offchannel TX.
            ordinary = k["qid"] < 4 and k["encap"] == 1
            if ordinary:
                presence_counts[(k["bss"], own_state, alt_state, decoded["mat_enabled"])] += 1
                if state is not None and state["absent"]:
                    state["ordinary_descriptors"] += 1
            descriptors.append((t, key, own_state, alt_state, ordinary))
    if not history or not counts:
        raise ValueError("missing binding or mapped MLO descriptor evidence")
    def rows(counter):
        return [dict(bss=b, link=l, wcid=w, tgid=g, own_mac=o,
                     mat_enabled=m, encap=e, qid=q, count=n)
                for (b,l,w,g,o,m,e,q),n in sorted(counter.items())]
    presence_rows = [dict(bss=b, target=own, alternate=alt, mat_enabled=mat, count=n)
                     for (b,own,alt,mat),n in sorted(presence_counts.items())]
    quota_rows = [dict(**v, descriptors_beyond_announced_quota=max(
        0, v["ordinary_descriptors"]-v["quota"])) for _,v in sorted(quota_windows.items())]
    return history, descriptors, rows(counts), [
        dict(wcid=w,bss=b,link=l,count=n) for (w,b,l),n in sorted(unmatched.items())], presence_rows, quota_rows


def analyze(parsed, timing):
    history, desc, counts, unmatched, presence_rows, quota_rows = describe(parsed["events"])
    lo, hi = parsed["offset_lo"], parsed["offset_hi"]
    windows = []
    for window in timing["windows"] + timing.get("isolated_unattributed_multichannel", []):
        gap = window["common_arrival_silence"]
        start, end = D(gap["last_reply"]), D(gap["next_reply"])
        if end-start < D(".25") or not any(p["missing_sequences"] for p in window["paths"]):
            continue
        if start < parsed["first_anchor"]+hi or end > parsed["last_anchor"]+lo:
            continue
        interior = [(key, own, alt, ordinary) for t,key,own,alt,ordinary in desc
                    if start <= t+lo and t+hi <= end]
        selected = Counter(key for key,_,_,_ in interior)
        states = Counter((key[0], own, alt, key[5]) for key,own,alt,ordinary in interior if ordinary)
        windows.append(dict(label=window.get("label","unattributed-multichannel"),
                            start=start, end=end, mapped_descriptors=sum(selected.values()),
                            ordinary_presence=[dict(bss=b,target=own,alternate=alt,mat_enabled=mat,count=n)
                                               for (b,own,alt,mat),n in sorted(states.items())],
                            destinations=[dict(bss=b,link=l,wcid=w,tgid=g,own_mac=o,
                                               mat_enabled=m,encap=e,qid=q,count=n)
                                          for (b,l,w,g,o,m,e,q),n in sorted(selected.items())]))
    return dict(method="Host provisioning and final TX descriptor fields; a mapped descriptor, including MAT, does not establish the RF transmit link. Unmatched station descriptors are reported, never guessed. Counts beyond an announced quota are host descriptor submissions, not proof of firmware quota consumption or over-air loss.",
                bindings=history, descriptors=counts, unmatched=unmatched,
                ordinary_presence=presence_rows, announced_quota_windows=quota_rows, windows=windows)


def selftest():
    def e(t, name, payload):
        return D(t), "mt7925_lab_"+name, "task", payload, 0
    binding = e("10","binding","bss=0 link=1 wcid=3 primary=3 freq=5180 sta=1 mld=1")
    desc = e("10.2","txdesc","bss=0 link=1 wcid=3 pid=0 qid=0 word1=4099 word6=0 encap=1 sta=1")
    mismatched = e("10.3","txdesc","bss=1 link=0 wcid=3 pid=0 qid=0 word1=4099 word6=8 encap=1 sta=1")
    history, entries, rows, unmatched, states, quotas = describe([binding,desc,mismatched])
    assert len(history)==len(entries)==len(rows)==len(unmatched)==1
    assert rows[0]["mat_enabled"] and rows[0]["tgid"]==1 and rows[0]["wcid"]==3
    assert unmatched[0]["bss"]==1
    assert states==[dict(bss=0,target="unknown",alternate="unknown",mat_enabled=True,count=1)]
    alt=e("10.01","binding","bss=1 link=0 wcid=4 primary=3 freq=2412 sta=1 mld=1")
    absent=e("10.02","absence","bss=0 tag=0 len=8 absent=1 quota=2")
    present=e("10.03","absence","bss=1 tag=0 len=8 absent=0 quota=0")
    _,_,_,_,states,quotas=describe([binding,alt,absent,present,desc,desc,desc])
    assert states==[dict(bss=0,target="absent",alternate="present",mat_enabled=True,count=3)]
    assert quotas[0]["ordinary_descriptors"]==3 and quotas[0]["descriptors_beyond_announced_quota"]==1
    # A quota announcement is a fresh budget, not the sum of all earlier quotas.
    _,_,_,_,_,quotas=describe([binding,alt,absent,present,desc,
        e("10.3","absence","bss=0 tag=0 len=8 absent=1 quota=1"),
        e("10.4","txdesc",desc[3])])
    assert [v["ordinary_descriptors"] for v in quotas]==[1,1]
    # A new non-station provisioning invalidates stale index bindings/state.
    rebinding=e("10.1","binding","bss=0 link=1 wcid=63 primary=63 freq=5180 sta=0 mld=1")
    try:
        describe([binding,absent,rebinding,desc])
    except ValueError:
        pass
    else:
        raise AssertionError("stale binding accepted")
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
