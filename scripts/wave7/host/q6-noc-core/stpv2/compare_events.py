#!/usr/bin/env python3
"""Compare two exported MIPI STPv2 packet CSVs from paired NoC ETR captures.

Reports per-source opcode and payload distributions after normalizing to
decoded data packets. This is evidence of differential occupancy, NOT
absolute packet rates or proof of a particular NoC RouteId.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path


DATA_TYPES = frozenset({1, 2, 4, 8, 16})


def load(path: Path) -> dict:
    packet_counts: Counter[tuple[int, int, int, int, int]] = Counter()
    opcodes: Counter[int] = Counter()
    channels: Counter[tuple[int, int]] = Counter()
    rows = 0
    packets = 0
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        expected = {"type", "major", "channel", "marked", "data"}
        if not expected.issubset(reader.fieldnames or ()):
            raise ValueError(f"Missing expected columns in {path}")
        for r in reader:
            rows += 1
            op = int(r["type"])
            opcodes[op] += 1
            if op not in DATA_TYPES:
                continue
            packets += 1
            major = int(r["major"])
            channel = int(r["channel"])
            marked = int(r["marked"])
            value = int(r["data"], 0)
            packet_counts[(op, major, channel, marked, value)] += 1
            channels[(major, channel)] += 1
    if not packets:
        raise ValueError(f"No decoded STPv2 data packets in {path}")
    return {
        "name": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "rows": rows,
        "data_packets": packets,
        "payloads": packet_counts,
        "opcodes": opcodes,
        "channels": channels,
    }


def compare(idle: dict, load_data: dict, limit: int) -> dict:
    a, b = idle, load_data
    total_a = a["data_packets"]
    total_b = b["data_packets"]
    changes = []
    for key in a["payloads"].keys() | b["payloads"].keys():
        n_a = a["payloads"][key]
        n_b = b["payloads"][key]
        fraction_a = n_a / total_a
        fraction_b = n_b / total_b
        changes.append(
            {
                "opcode": key[0],
                "master": key[1],
                "channel": key[2],
                "marked": bool(key[3]),
                "data": f"0x{key[4]:016x}",
                "idle_count": n_a,
                "load_count": n_b,
                "idle_per_10000_data_packets": round(fraction_a * 10000, 4),
                "load_per_10000_data_packets": round(fraction_b * 10000, 4),
                "delta_per_10000": round((fraction_b - fraction_a) * 10000, 4),
            }
        )

    def compact_counts(counter: Counter, label: str) -> list[dict]:
        return [
            {"key": label.format(*key) if isinstance(key, tuple) else str(key),
             "count": n}
            for key, n in counter.most_common()
        ]

    return {
        "method": "Frequency per 10k decoded STPv2 data packets, not time-normalized",
        "warnings": [
            "Circular ETR capture window durations and alignment may differ",
            "Zephyr decoder has unsupported opcodes and some MERROR/discontinuous timestamps",
            "Master/channel context may be invalid across trace integrity errors",
            "Observed packet deltas alone do not decode Qualcomm NoC RouteIds",
        ],
        "idle": {
            "source": a["name"], "sha256": a["sha256"],
            "rows": a["rows"], "data_packets": total_a,
            "opcodes": compact_counts(a["opcodes"], "{}"),
            "channels": compact_counts(a["channels"], "master={} channel={}"),
        },
        "wlan_load": {
            "source": b["name"], "sha256": b["sha256"],
            "rows": b["rows"], "data_packets": total_b,
            "opcodes": compact_counts(b["opcodes"], "{}"),
            "channels": compact_counts(b["channels"], "master={} channel={}"),
        },
        "changed_payload_signatures": sum(
            1 for x in changes if x["idle_count"] != x["load_count"]
        ),
        "new_signatures_in_load": sum(
            1 for x in changes if x["idle_count"] == 0 and x["load_count"]
        ),
        "largest_normalized_increases": sorted(
            changes, key=lambda x: x["delta_per_10000"], reverse=True
        )[:limit],
        "largest_normalized_decreases": sorted(
            changes, key=lambda x: x["delta_per_10000"]
        )[:limit],
        "new_in_load": sorted(
            (x for x in changes if x["idle_count"] == 0),
            key=lambda x: -x["load_count"]
        )[:limit],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("idle_csv", type=Path)
    ap.add_argument("load_csv", type=Path)
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    if args.limit < 1:
        ap.error("--limit must be positive")
    report = compare(load(args.idle_csv), load(args.load_csv), args.limit)
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output is None:
        print(encoded, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)


if __name__ == "__main__":
    main()
