#!/usr/bin/env python3
"""Reproduce admission decisions using the actual C policy and sealed trace.

A replay treats successful station binding as the start of active membership,
and historical descriptor submissions as demand in original trace order.
It does not model later packet retransmission or actual queue delay.
"""
import argparse
import importlib.util
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location(
    "binding", Path(__file__).with_name("report-client-link-binding.py"))
binding = importlib.util.module_from_spec(spec)
spec.loader.exec_module(binding)


def replay_input(events):
    # The sealed client experiment uses one associated MLD on one netdev.
    # Reject a second primary peer rather than coalescing distinct owners.
    mapped = {}
    primary = None
    for _, name, _, payload, _ in events:
        if name == "mt7925_lab_binding":
            v = binding.absence.fields(payload)
            bss, link = v["bss"], v["link"]
            if not v["sta"]:
                mapped = {w: x for w, x in mapped.items() if x["bss"] != bss}
                if not mapped:
                    primary = None
                yield f"B {bss} {link} 0"
            elif v["mld"]:
                if primary is not None and primary != v["primary"]:
                    raise ValueError("replay expects a single MLD station")
                primary = v["primary"]
                mapped[v["wcid"]] = v
                yield f"S {bss} {link} 0"
        elif name == "mt7925_lab_absence":
            v = binding.absence.fields(payload)
            if v["tag"] != 0 or v["len"] != 8 or v["absent"] not in (0, 1):
                raise ValueError("invalid absence INFO")
            yield f"A {v['bss']} {v['absent']} {v['quota']}"
        elif name == "mt7925_lab_txdesc":
            v = binding.absence.fields(payload)
            record = mapped.get(v["wcid"])
            if (v["sta"] and v["encap"] == 1 and v["qid"] < 4 and record
                    and (record["bss"], record["link"]) == (v["bss"], v["link"])):
                yield f"T {v['bss']} {v['link']} 0"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("test_binary", type=Path)
    p.add_argument("trace", type=Path)
    a = p.parse_args()
    parsed = binding.absence.trace.parse(a.trace.read_text())
    events = parsed["events"]
    binding.absence.extract(events, True)
    _, _, _, unmatched, presence, quotas = binding.describe(events)
    if unmatched:
        raise ValueError("replay does not guess unmatched station descriptors")
    demand = sum(r["count"] for r in presence)
    denied = sum(v["group_absent_beyond_announced_quota"] for v in quotas)
    charged = sum(v["group_absent_descriptors"] for v in quotas) - denied
    result = subprocess.run([str(a.test_binary.resolve()), "--replay"],
                            input="\n".join(replay_input(events)) + "\n",
                            text=True, capture_output=True, check=True)
    match = re.fullmatch(r"REPLAY allowed=(\d+) charged=(\d+) denied=(\d+)\n",
                         result.stdout)
    if not match or tuple(map(int, match.groups())) != (demand - denied, charged, denied):
        raise ValueError("compiled policy and independent trace analysis disagree")
    print(result.stdout, end="")


if __name__ == "__main__":
    main()
