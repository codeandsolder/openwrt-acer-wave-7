#!/usr/bin/env python3
"""Test accounting, epoch identity, high-water marks and malformed snapshots."""
import runpy
from pathlib import Path

h = runpy.run_path(str(Path(__file__).with_name("reo-command-stats.py")))
FIELDS, KINDS = h["FIELDS"], h["KINDS"]


def fixture(**updates):
    values = dict.fromkeys(FIELDS, 0)
    values.update(updates)
    return ["version=1 generation=1 unmatched_status=0", "kind " + " ".join(FIELDS),
            *[kind + " " + " ".join(str(values[f] if kind == "ba" else 0) for f in FIELDS)
              for kind in sorted(KINDS)]]


def rejected(fn, *args):
    try:
        fn(*args)
    except ValueError:
        return
    raise AssertionError("invalid input accepted")


parse, compare = h["parse_radio"], h["compare"]
a = parse(fixture(submitted=3, success=1, blocked=1, pending=1,
                  oldest_pending_ns=20, max_latency_ns=500, unhandled_failure=1))
b = parse(fixture(submitted=6, success=3, blocked=1, failed=2,
                  max_latency_ns=800, unhandled_failure=3))
r = compare({"qcn": a}, {"qcn": b})["qcn"]["kinds"]["ba"]
assert r["delta"]["submitted"] == 3 and r["delta"]["failed"] == 2
assert r["pending"] == [1, 0] and r["max_latency_ns"] == [500, 800]
rejected(compare, {"qcn": b}, {"qcn": a})
rejected(compare, {"qcn": a}, {"qcn": dict(b, generation=2)})
rejected(compare, {"qcn": a}, {"ipq": b})
rejected(parse, fixture(submitted=1))
rejected(parse, fixture(submitted=1, success=1, unhandled_failure=1))
rejected(parse, fixture(submitted=257, pending=257))
rejected(parse, fixture(oldest_pending_ns=10))
rejected(parse, fixture(max_latency_ns=10))
rejected(parse, fixture(statusless=2**64))
rejected(parse, fixture(statusless=-1))
rejected(parse, fixture()[:-1])
rejected(parse, fixture()[:-1] + [fixture()[2]])
rejected(h["parse_sections"], {"REO_CMD ipq": fixture()}, {"ipq", "qcn"})
print("REO_COMMAND_STATS_PASS")
