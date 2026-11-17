#!/usr/bin/env python3
"""Summarize an offline CoreSight ETR raw snapshot without assuming a packet format.

This is deliberately format-agnostic: an all-zero buffer, sparse register writes,
a circular trace with wrap, and dense framed traffic must be distinguishable
before any attempt at route/probe field decoding.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path


def describe(data: bytes, chunk_size: int) -> dict:
    if not data:
        raise ValueError("ETR snapshot is empty")
    if chunk_size <= 0:
        raise ValueError("chunk size must be positive")
    counts = Counter(data)
    nonzero = [idx for idx, val in enumerate(data) if val != 0]
    non_filler = [idx for idx, val in enumerate(data) if val not in (0, 0xff)]
    entropy = -sum((n / len(data)) * math.log2(n / len(data)) for n in counts.values())
    windows = []
    for offset in range(0, len(data), chunk_size):
        part = data[offset:offset + chunk_size]
        windows.append(
            {
                "offset": offset,
                "bytes": len(part),
                "nonzero": sum(x != 0 for x in part),
                "non_00_ff": sum(x not in (0, 0xff) for x in part),
                "sha256": hashlib.sha256(part).hexdigest(),
            }
        )

    def span(indices: list[int]) -> dict:
        return {
            "count": len(indices),
            "first_offset": indices[0] if indices else None,
            "last_offset": indices[-1] if indices else None,
        }

    # Keep samples bounded. A first/last view is useful for checking whether
    # a supposed trace is only stale memory or has a recognizable sink header.
    interesting = non_filler or nonzero
    first_middle_last = (
        (interesting[0], interesting[len(interesting) // 2], interesting[-1])
        if interesting else ()
    )
    sample_offsets = sorted(
        {
            0,
            max(0, len(data) - min(len(data), 64)),
            *(max(0, i - 16) for i in first_middle_last),
        }
    )
    return {
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "entropy_bits_per_byte": round(entropy, 6),
        "zero_bytes": counts[0],
        "ff_bytes": counts[255],
        "unique_byte_values": len(counts),
        "value_counts": [{"value": f"{value:02x}", "count": count} for value, count in counts.most_common(16)],
        "nonzero": span(nonzero),
        "non_00_ff": span(non_filler),
        "window_size": chunk_size,
        "windows_with_non_00_ff": sum(w["non_00_ff"] != 0 for w in windows),
        "windows": windows,
        "samples": [{"offset": i, "hex": data[i:i + 64].hex(" ")} for i in sample_offsets],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("snapshot", type=Path)
    ap.add_argument("--chunk-size", type=int, default=4096)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    analysis = describe(args.snapshot.read_bytes(), args.chunk_size)
    result = json.dumps(analysis, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(result)
    else:
        print(result, end="")


if __name__ == "__main__":
    main()
