#!/usr/bin/env python3
"""Create NoC-only QDSS profile from the exact Acer WBE1.3 stock profile."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

EXPECTED_SHA256 = "9b562386f2f1b48f946c405fbd22193dbac2f7cf9160c63221352471ed3502db"
STOCK_FILENAME = "qdss_trace_config.bin"
DIAG_FILENAME = "qdss_trace_umacnoc.bin"


def generate(stock: bytes) -> bytes:
    if hashlib.sha256(stock).hexdigest() != EXPECTED_SHA256:
        raise ValueError("Stock QDSS profile changed; revalidate all offsets before enabling")
    # Only uncomment the noc_trace block. Keep its stock, unfiltered match
    # configuration until field mask semantics have been measured in hardware.
    # The on-device QDSS parser also accepts LF (the QCN6432 vendor
    # profile uses LF). Normalize CRLF so the generated diagnostic profile
    # has portable text line endings and Git can review it normally.
    lines = [line.replace(b"\r\n", b"\n") for line in
             stock.splitlines(keepends=True)]
    start = [
        i for i, line in enumerate(lines)
        if line.rstrip(b"\r\n") == b"//seq_type:noc_trace;"
    ]
    if len(start) != 1:
        raise ValueError(f"Expected one NoC block; found {len(start)}")
    first = start[0] - 1
    if lines[first].rstrip(b"\r\n") != b"//seq_start;":
        raise ValueError("Unexpected NoC sequence start")
    last = first + 1
    while last < len(lines) and lines[last].rstrip(b"\r\n") != b"//seq_end;":
        if not lines[last].startswith(b"//"):
            raise ValueError("Unexpected live line in NoC trace block")
        last += 1
    if last == len(lines):
        raise ValueError("Missing NoC sequence end")
    if lines[first + 2].rstrip(b"\r\n") != b"//noc_id:umacnoc;":
        raise ValueError("Unexpected trace target")
    for index in range(first, last + 1):
        if not lines[index].startswith(b"//"):
            raise ValueError("Uncommenting would modify a live setting")
        lines[index] = lines[index][2:]
    # Explicitly disable the pre-existing high-volume MAC and PHY event
    # tracers in this dedicated diagnostic profile. Otherwise their
    # ETR traffic can overwrite the rare NoC transaction we're trying
    # to capture. The normal stock profile is unchanged.
    disabled = set()
    in_block = None
    for idx, line in enumerate(lines):
        plain = line.rstrip(b"\r\n")
        if plain == b"seq_start;":
            if in_block is not None:
                raise ValueError("Nested QDSS sequence")
            in_block = idx
        elif plain == b"seq_end;":
            if in_block is None:
                raise ValueError("Unpaired QDSS sequence end")
            content = [x.strip(b"\r\n") for x in lines[in_block:idx+1]]
            types = [x.removeprefix(b"seq_type:").removesuffix(b";")
                     for x in content if x.startswith(b"seq_type:")]
            if len(types) != 1:
                raise ValueError("Missing or ambiguous active QDSS sequence type")
            trace_type = types[0]
            if trace_type in (b"mac_event_trace", b"phy_event_trace"):
                disabled.add(trace_type)
                for j in range(in_block, idx + 1):
                    if not lines[j].startswith(b"//"):
                        lines[j] = b"//" + lines[j]
            elif trace_type not in (b"mem_req", b"noc_trace"):
                raise ValueError(f"Unexpected active trace {trace_type!r}")
            in_block = None
    if in_block is not None or disabled != {b"mac_event_trace", b"phy_event_trace"}:
        raise ValueError("Failed to isolate UMACNOC trace")
    result = b"".join(lines)
    for wanted in (b"seq_type:mem_req;", b"seq_type:noc_trace;"):
        if result.count(b"\n" + wanted) != 1:
            raise ValueError(f"Expected one active {wanted!r}")
    return result


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("stock", type=Path)
    cli.add_argument("destination", type=Path)
    opts = cli.parse_args()
    output = generate(opts.stock.read_bytes())
    opts.destination.parent.mkdir(parents=True, exist_ok=True)
    opts.destination.write_bytes(output)
    print(f"{opts.destination} {len(output)} bytes SHA256 {hashlib.sha256(output).hexdigest()}")


if __name__ == "__main__":
    main()
