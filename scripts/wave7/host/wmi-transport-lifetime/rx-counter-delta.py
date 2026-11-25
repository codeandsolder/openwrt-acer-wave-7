#!/usr/bin/env python3
"""Compare the radio RX error counters on a single continuously healthy boot."""

import argparse
import json
from pathlib import Path
import re

SECTIONS = {"RXDMA errors", "REO errors", "HAL REO errors"}
DEVICE = re.compile(r"^===/sys/kernel/debug/ath12k/([^/]+)/device_dp_stats$")
COUNTER = re.compile(r"^([^:]+): ([0-9]+)$")
BOOT = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")


def parse(raw):
    lines = raw.splitlines()
    if len(lines) < 3 or not BOOT.fullmatch(lines[0]):
        raise ValueError("missing boot identity")
    uptime = float(lines[1].split()[0])
    if uptime < 0:
        raise ValueError("invalid uptime")
    devices = {}
    device = section = None
    for line in lines[2:]:
        match = DEVICE.fullmatch(line)
        if match:
            device = match[1]
            if device in devices:
                raise ValueError("duplicate device")
            devices[device] = {}
            section = None
            continue
        if device is None:
            continue
        if line.endswith(":"):
            section = line[:-1]
        elif section in SECTIONS and (match := COUNTER.fullmatch(line)):
            key = f"{section}/{match[1]}"
            value = int(match[2])
            if key in devices[device] or not 0 <= value < 2**32:
                raise ValueError("invalid or duplicate counter")
            devices[device][key] = value
    if not devices:
        raise ValueError("no radio devices")
    for device, counters in devices.items():
        present = {key.split("/")[0] for key in counters}
        if present != SECTIONS:
            raise ValueError(f"incomplete device {device}")
    return lines[0], uptime, devices


def compare(before, after):
    boot, start, a = parse(before)
    end_boot, end, b = parse(after)
    if boot != end_boot or not start < end or a.keys() != b.keys():
        raise ValueError("incomparable snapshots")
    changes = {}
    for device, counters in a.items():
        if counters.keys() != b[device].keys():
            raise ValueError(f"counter set changed: {device}")
        delta = {}
        for key, value in counters.items():
            latest = b[device][key]
            if latest < value:
                # A reset/restart cannot be distinguished from a wrap.
                raise ValueError(f"counter decreased: {device}/{key}")
            if latest != value:
                delta[key] = latest - value
        changes[device] = delta
    return {"boot": boot, "start_s": start, "end_s": end, "increments": changes}


def selftest():
    a = """96f67cfc-e011-49e1-aff7-1832e25fcf3e
1.00 2.00
===/sys/kernel/debug/ath12k/radio0/device_dp_stats
RXDMA errors:
FCS: 2
REO errors:
Frame OOR: 0
HAL REO errors:
ring0: 0
DEVICE TX STATS:
ring0: 5
"""
    b = a.replace("1.00 2.00", "4.00 8.00").replace("Frame OOR: 0", "Frame OOR: 4")
    assert compare(a, b)["increments"] == {"radio0": {"REO errors/Frame OOR": 4}}
    for wrong in (b.replace("FCS: 2", "FCS: 1"),
                  b.replace("FCS: 2", ""),
                  b.replace("96f67cfc", "86f67cfc"),
                  b.replace("4.00 8.00", "1.00 2.00")):
        try:
            compare(a, wrong)
        except ValueError:
            pass
        else:
            raise AssertionError("accepted invalid snapshot")
    print("RX_COUNTER_DELTA_SELFTEST_PASS")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("before", nargs="?", type=Path)
    p.add_argument("after", nargs="?", type=Path)
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()
    if args.selftest:
        selftest()
    elif args.before and args.after:
        print(json.dumps(compare(args.before.read_text(), args.after.read_text()), indent=2))
    else:
        p.error("provide two snapshots or --selftest")
