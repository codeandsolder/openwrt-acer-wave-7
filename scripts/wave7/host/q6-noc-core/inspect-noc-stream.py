#!/usr/bin/env python3
"""Inspect empirically recurring fixed-length records in an extracted trace stream.

This is a structural analyzer, not a NoC path decoder. The current IPQ5332
capture has a recurring 0x1b20 anchor and 16-byte spacing; both are CLI
parameters so new captures and different probes need not share the format.
Only records whose next anchor is exactly one record-width away are grouped.
Gaps are retained as independent evidence rather than treated as packets.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path


def anchors(data: bytes, needle: bytes) -> list[int]:
    if not needle:
        raise ValueError("Anchor cannot be empty")
    found = []
    start = 0
    while (at := data.find(needle, start)) != -1:
        found.append(at)
        start = at + 1
    return found


def summarize(data: bytes, *, anchor: bytes, width: int, field_offset: int) -> dict:
    if width < 1 or len(anchor) > width:
        raise ValueError("Record width must be >= anchor width")
    if field_offset < 0 or field_offset >= width:
        raise ValueError("Family field offset must be within record")
    positions = anchors(data, anchor)
    gaps = Counter(b - a for a, b in zip(positions, positions[1:]))
    families: Counter[int] = Counter()
    variants: defaultdict[int, Counter[bytes]] = defaultdict(Counter)
    samples: dict[int, list[dict]] = defaultdict(list)
    in_range = 0
    for a, b in zip(positions, positions[1:]):
        if b - a != width:
            continue
        rec = data[a:b]
        if len(rec) != width:
            continue
        fid = rec[field_offset]
        families[fid] += 1
        variants[fid][rec[: min(7, width)]] += 1
        if len(samples[fid]) < 3:
            samples[fid].append({"offset": a, "bytes": rec.hex(" ")})
        in_range += 1
    return {
        "input_sha256": hashlib.sha256(data).hexdigest(),
        "input_bytes": len(data),
        "record_anchor_hex": anchor.hex(),
        "record_width_hypothesis": width,
        "empirical_family_field_offset": field_offset,
        "anchor_occurrences": len(positions),
        "anchor_offsets_mod_width": {
            str(r): n for r, n in sorted(Counter(p % width for p in positions).items())
        },
        "gap_sizes": [
            {"bytes": gap, "count": n}
            for gap, n in sorted(gaps.items(), key=lambda x: (-x[1], x[0]))
        ],
        "exact_width_adjacent_records": in_range,
        "unclassified_or_gap_anchor_pairs": sum(gaps.values()) - in_range,
        "family_values": [
            {
                "family_byte": f"0x{fid:02x}",
                "record_count": count,
                "distinct_seven_byte_prefixes": len(variants[fid]),
                "most_common_seven_byte_prefixes": [
                    {"hex": v.hex(" "), "count": n}
                    for v, n in variants[fid].most_common(5)
                ],
                "samples": samples[fid],
            }
            for fid, count in families.most_common()
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stream", type=Path, help="deformatted source stream")
    ap.add_argument("--anchor", default="1b20", help="observed record prefix, hex bytes")
    ap.add_argument("--width", type=int, default=16)
    ap.add_argument("--family-offset", type=int, default=2)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    report = summarize(
        args.stream.read_bytes(),
        anchor=bytes.fromhex(args.anchor),
        width=args.width,
        field_offset=args.family_offset,
    )
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
