#!/usr/bin/env python3
"""Compare operator-captured iw multipart station dumps without merging links."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re

STAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$")
MAC = r"[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}"
STATION = re.compile(rf"^Station ({MAC}) \(on ([^)]+)\)$")
LINK = re.compile(r"^\s+Link (\d+):$")
FIELD = re.compile(r"^\s+([^:]+):\s*(.*)$")
COUNTERS = ("rx packets", "tx packets", "rx bytes", "tx bytes",
            "tx retries", "tx failed", "rx drop misc")


def parse(lines):
    samples = []
    peer = None
    target = None
    for raw in lines:
        line = raw.rstrip()
        if STAMP.fullmatch(line):
            stamp = datetime.fromisoformat(line)
            if samples and stamp <= samples[-1]["time"]:
                raise ValueError("non-increasing sample time")
            samples.append({"time": stamp, "stations": {}})
            peer = target = None
            continue
        if not line:
            continue
        if match := STATION.fullmatch(line):
            if not samples:
                raise ValueError("missing capture timestamp")
            key = f"{match[1].lower()}@{match[2]}"
            peer = samples[-1]["stations"].setdefault(key, {"aggregate": {}, "links": {}})
            target = peer["aggregate"]
            continue
        if match := LINK.fullmatch(line):
            if peer is None:
                raise ValueError("link fragment without station")
            target = peer["links"].setdefault(int(match[1]), {})
            continue
        if match := FIELD.fullmatch(line):
            if target is None:
                raise ValueError("field without station")
            name, value = (x.strip() for x in match.groups())
            if name in target and target[name] != value:
                raise ValueError(f"conflicting field {name}")
            target[name] = value
            continue
        raise ValueError(f"unrecognized capture line: {line}")
    if len(samples) < 2:
        raise ValueError("need at least two timestamped samples")
    return samples


def deltas(first, last):
    result = {}
    for key in COUNTERS:
        if key not in first or key not in last:
            continue
        if not re.fullmatch(r"\d+", first[key]) or not re.fullmatch(r"\d+", last[key]):
            raise ValueError(f"nonnumeric counter {key}")
        change = int(last[key]) - int(first[key])
        if change < 0:
            raise ValueError(f"counter reset: {key}")
        result[key] = change
    return result


def compare(samples):
    intervals = []
    for first, last in zip(samples, samples[1:]):
        peers = {}
        for key in sorted(first["stations"].keys() | last["stations"].keys()):
            a, b = first["stations"].get(key), last["stations"].get(key)
            if a is None or b is None:
                peers[key] = {"qualified": False, "reason": "station not present in both samples"}
                continue
            x, y = a["aggregate"], b["aggregate"]
            identity = "associated at [boottime]"
            if not x.get(identity) or x.get(identity) != y.get(identity):
                peers[key] = {"qualified": False, "reason": "association identity not established"}
                continue
            if any(d.get(f) != "yes" for d in (x, y)
                   for f in ("associated", "authorized", "authenticated")):
                peers[key] = {"qualified": False, "reason": "station not fully associated"}
                continue
            links = {}
            for link in sorted(a["links"].keys() | b["links"].keys()):
                u, v = a["links"].get(link), b["links"].get(link)
                if not u or not v or not u.get("address") or u.get("address") != v.get("address"):
                    links[link] = {"qualified": False, "reason": "link identity not established"}
                    continue
                changes = deltas(u, v)
                links[link] = {"qualified": {"rx packets", "tx packets"} <= changes.keys(),
                               "first": u, "last": v, "deltas": changes}
            changes = deltas(x, y)
            peers[key] = {"qualified": {"rx packets", "tx packets"} <= changes.keys(),
                          "aggregate_deltas": changes, "links": links,
                          "association": x[identity]}
        intervals.append({"start": first["time"].isoformat(), "end": last["time"].isoformat(),
                          "seconds": (last["time"] - first["time"]).total_seconds(),
                          "stations": peers})
    return {"intervals": intervals, "sample_count": len(samples),
            "method": "Host capture timestamps, stable AP association identity and link addresses; "
                      "counters are cumulative, sampled, not exhaustive traffic attribution. "
                      "AP epoch is not assumed synchronized with the host."}


def selftest():
    sta = "Station 00:11:22:33:44:55 (on ap-mld0)"
    def sample(second, rx, assoc="1.000s", secondary_tx=0):
        return [f"2026-11-22T18:00:{second:02d}+01:00", sta,
                "\tauthorized: yes", "\tauthenticated: yes", "\tassociated: yes",
                f"\tassociated at [boottime]: {assoc}", f"\trx packets: {rx}",
                f"\ttx packets: {rx}", sta, "\tLink 0:",
                "\t\taddress: 00:11:22:33:44:56", "\t\trx packets: 0",
                f"\t\ttx packets: {secondary_tx}", sta, "\tLink 1:",
                "\t\taddress: 00:11:22:33:44:57", f"\t\trx packets: {rx}",
                f"\t\ttx packets: {rx}"]
    peer = "00:11:22:33:44:55@ap-mld0"
    result = compare(parse(sample(0, 12) + sample(5, 68)))
    links = result["intervals"][0]["stations"][peer]["links"]
    assert links[0]["qualified"] and links[0]["deltas"] == {"rx packets": 0, "tx packets": 0}
    assert links[1]["qualified"] and links[1]["deltas"]["rx packets"] == 56
    assert not compare(parse(sample(0, 12) + sample(5, 68, "2.000s")))["intervals"][0]["stations"][peer]["qualified"]
    for bad in [sample(5, 11), sample(5, 68) + ["\t\trx packets: 99"], sample(0, 68)]:
        try:
            compare(parse(sample(0, 12) + bad))
        except ValueError:
            pass
        else:
            raise AssertionError("invalid capture accepted")
    print("AP_LINK_CAPTURES_SELFTEST_PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", nargs="?", type=Path)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
    elif args.capture:
        print(json.dumps(compare(parse(args.capture.read_text().splitlines())), indent=2))
    else:
        parser.error("provide capture")
