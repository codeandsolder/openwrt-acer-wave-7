#!/usr/bin/env python3
"""Join bounded manual scan attempts to synchronous cfg80211/driver traces.

An iw -EBUSY with no rdev_scan trace is only a pre-rdev rejection at the
observed boundary, not proof of a particular check within nl80211.
"""
import argparse
from collections import Counter
import csv
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

INTEREST = {"rdev_scan", "rdev_return_int", "drv_hw_scan", "drv_return_int",
            "mt7925_mcu_hw_scan"}
RETURN = re.compile(r"(?:returned: | - )(-?\d+)$")
IW = re.compile(r"^iw-\d+$")


def report(parsed, attempts):
    lo, hi = parsed["offset_lo"], parsed["offset_hi"]
    rows = []
    counts = Counter()
    previous = None
    for start, end, label, number, status, freqs in csv.reader(attempts.splitlines()):
        a, b = D(start), D(end)
        num, rc = int(number), int(status)
        if not a.is_finite() or not b.is_finite() or b < a or num < 1:
            raise ValueError("invalid scan attempt")
        if previous is not None and a <= previous:
            raise ValueError("overlapping or unsorted scan attempts")
        previous = b
        covered = (parsed["first_anchor"] + hi <= a and
                   b <= parsed["last_anchor"] + lo)
        candidates = [e for e in parsed["events"] if e[1] in INTEREST
                      and IW.fullmatch(e[2]) and e[0] + hi >= a and e[0] + lo <= b]
        tasks = {e[2] for e in candidates}
        scans = [e for e in candidates if e[1] == "rdev_scan"]
        drvs = [e for e in candidates if e[1] == "drv_hw_scan"]
        rdev_ret = [int(m[1]) for e in candidates
                    if e[1] == "rdev_return_int" and (m := RETURN.search(e[3]))]
        drv_ret = [int(m[1]) for e in candidates
                   if e[1] == "drv_return_int" and (m := RETURN.search(e[3]))]
        if not covered:
            kind = "outside_anchored_trace"
        elif rc == 0:
            kind = "accepted"
        elif rc != 240:
            kind = "other_error"
        elif len(tasks) > 1 or len(scans) > 1 or len(drvs) > 1:
            kind = "ambiguous"
        elif not scans and not drvs:
            kind = "before_rdev_scan"
        elif len(scans) == 1 and not drvs and rdev_ret == [-16]:
            kind = "rdev_rejected_before_driver"
        elif len(scans) == 1 and len(drvs) == 1 and -16 in drv_ret and -16 in rdev_ret:
            kind = "driver_returned_busy"
        else:
            kind = "ambiguous"
        counts[kind] += 1
        rows.append(dict(start=a, end=b, label=label, attempt=num, rc=rc,
                         frequencies_mhz=list(map(int, freqs.split())),
                         covered=covered, classification=kind, tasks=sorted(tasks),
                         rdev_returns=rdev_ret, driver_returns=drv_ret,
                         events=[dict(t=e[0], name=e[1], task=e[2], payload=e[3])
                                 for e in candidates]))
    return dict(counts=dict(counts), attempts=rows,
                clock_offset_lower=lo, clock_offset_upper=hi,
                trace_count=parsed["trace_count"])


def selftest():
    def e(t, name, payload):
        return D(t), name, "iw-42", payload, 0
    events = [
        e("2.01", "rdev_scan", "rdev_scan: phy1"),
        e("2.02", "rdev_return_int", "rdev_return_int: phy1, returned: -16"),
        e("3.01", "rdev_scan", "rdev_scan: phy1"),
        e("3.02", "drv_hw_scan", "drv_hw_scan: phy1"),
        e("3.03", "drv_return_int", "drv_return_int: phy1 - -16"),
        e("3.04", "rdev_return_int", "rdev_return_int: phy1, returned: -16"),
    ]
    parsed = dict(events=events, offset_lo=D("99.999"), offset_hi=D("100.001"),
                  first_anchor=D(0), last_anchor=D(10), trace_count=len(events))
    attempts = ("101,101.1,active24-1,1,240,2412\n"
                "102,102.1,active24-1,2,240,2412\n"
                "103,103.1,active24-1,3,240,2412\n"
                "104,104.1,active24-1,4,0,2412\n"
                "111,111.1,active5-1,1,240,5180\n")
    assert report(parsed, attempts)["counts"] == {
        "before_rdev_scan": 1, "rdev_rejected_before_driver": 1,
        "driver_returned_busy": 1, "accepted": 1, "outside_anchored_trace": 1}
    print("SCAN_ADMISSION_REPORT_SELFTEST_PASS")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("trace", nargs="?", type=Path)
    p.add_argument("attempts", nargs="?", type=Path)
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()
    if args.selftest:
        selftest()
    elif args.trace and args.attempts:
        result = report(trace.parse(args.trace.read_text()), args.attempts.read_text())
        print(json.dumps(result, default=str, indent=2))
    else:
        p.error("trace and attempts required")


if __name__ == "__main__":
    main()
