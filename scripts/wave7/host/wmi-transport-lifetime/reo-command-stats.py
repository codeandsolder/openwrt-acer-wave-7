#!/usr/bin/env python3
"""Qualify software-only REO command accounting across a sealed interval."""
import argparse
import json
from pathlib import Path
import re

KINDS = {"stats", "flush", "ba", "pn", "valid", "other"}
FIELDS = ("submitted statusless ring_full slot_busy submit_failed success blocked failed "
          "resource_blocked other_status unhandled_failure max_latency_ns pending oldest_pending_ns").split()
COUNTERS = FIELDS[:11]
TERMINAL = ("success", "blocked", "failed", "resource_blocked", "other_status")
HEADER = re.compile(r"version=1 generation=(\d+) unmatched_status=(\d+)")
BOOT = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
RADIOS = {"ahb-c000000.wifi", "ahb-soc@0:wifi"}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def parse_radio(lines):
    require(len(lines) == len(KINDS) + 2, "wrong command counter row count")
    m = HEADER.fullmatch(lines[0])
    require(m and 0 < int(m[1]) < 2**64 and int(m[2]) < 2**64, "invalid REO epoch")
    require(lines[1].split() == ["kind", *FIELDS], "unexpected REO counter schema")
    kinds = {}
    for line in lines[2:]:
        kind, *raw = line.split()
        require(kind in KINDS and kind not in kinds, "invalid or duplicate command kind")
        require(len(raw) == len(FIELDS) and all(re.fullmatch(r"\d+", v) for v in raw),
                "invalid REO counter row")
        values = dict(zip(FIELDS, map(int, raw)))
        require(all(v < 2**64 for v in values.values()), "REO counter outside u64")
        terminal = sum(values[k] for k in TERMINAL)
        require(values["submitted"] == terminal + values["pending"], "lost command accounting")
        require(values["unhandled_failure"] <= terminal - values["success"], "invalid failure count")
        require(values["pending"] or values["oldest_pending_ns"] == 0, "age of empty queue")
        require(terminal or values["max_latency_ns"] == 0, "latency without completion")
        kinds[kind] = values
    require(kinds.keys() == KINDS and sum(v["pending"] for v in kinds.values()) <= 256,
            "incomplete command kinds or impossible ring occupancy")
    return dict(generation=int(m[1]), unmatched_status=int(m[2]), kinds=kinds)


def parse_sections(sections, expected_devices):
    radios = {key.removeprefix("REO_CMD "): parse_radio(value)
              for key, value in sections.items() if key.startswith("REO_CMD ")}
    require(radios.keys() == set(expected_devices), "incomplete REO radio coverage")
    return radios


def compare(before, after):
    require(before.keys() == after.keys(), "REO radio set changed")
    result = {}
    for radio, pre in before.items():
        post = after[radio]
        require(pre["generation"] == post["generation"], "REO command epoch changed")
        require(pre["unmatched_status"] <= post["unmatched_status"], "REO unmatched counter regressed")
        kinds = {}
        for kind, a in pre["kinds"].items():
            b = post["kinds"][kind]
            require(all(a[k] <= b[k] for k in (*COUNTERS, "max_latency_ns")),
                    "REO command counter regressed")
            delta = {k: b[k] - a[k] for k in COUNTERS}
            require(delta["submitted"] - sum(delta[k] for k in TERMINAL) ==
                    b["pending"] - a["pending"], "inconsistent command interval")
            kinds[kind] = dict(delta=delta,
                               pending=[a["pending"], b["pending"]],
                               oldest_pending_ns=[a["oldest_pending_ns"], b["oldest_pending_ns"]],
                               max_latency_ns=[a["max_latency_ns"], b["max_latency_ns"]])
        result[radio] = dict(generation=pre["generation"],
                             unmatched_status=post["unmatched_status"] - pre["unmatched_status"],
                             kinds=kinds)
    return result


def parse_file(path):
    lines = path.read_text().splitlines()
    require(len(lines) >= 4 and BOOT.fullmatch(lines[0]) and lines[-2:] == ["==== END", lines[0]],
            "bad REO snapshot boot seal")
    uptime = lines[1].split()
    require(len(uptime) == 2 and all(re.fullmatch(r"\d+\.\d+", v) for v in uptime),
            "bad REO snapshot uptime")
    sections = {}
    key = None
    for line in lines[2:-2]:
        if line.startswith("==== REO_CMD "):
            key = line[5:]
            require(key not in sections, "duplicate REO radio section")
            sections[key] = []
        else:
            require(key is not None, "REO section marker missing")
            sections[key].append(line)
    return lines[0], float(uptime[0]), parse_sections(sections, RADIOS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    a = parser.parse_args()
    boot, start, before = parse_file(a.before)
    boot2, end, after = parse_file(a.after)
    require(boot == boot2 and start < end, "unmatched REO snapshot interval")
    print(json.dumps(dict(boot=boot, start_s=start, end_s=end,
                          radios=compare(before, after)), indent=2))


if __name__ == "__main__":
    main()
