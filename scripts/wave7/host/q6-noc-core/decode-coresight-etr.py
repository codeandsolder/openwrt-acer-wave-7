#!/usr/bin/env python3
"""Deframe Arm CoreSight trace formatter bytes into per-ATID streams.

Implements IHI 0029F D4.2, including delayed ID transitions, the
auxiliary least-significant bits, null/flush source IDs, and 16/32-bit
frame synchronization packets. Does not guess device-specific trace
packet meanings, which must be decoded separately.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path


FRAME_BYTES = 16
FULL_SYNC = b"\xff\xff\xff\x7f"
HALF_SYNC = b"\xff\x7f"


def remove_sync(raw: bytes) -> tuple[bytes, Counter[str]]:
    if len(raw) & 1:
        raise ValueError("CoreSight capture must end at least on a 16-bit boundary")
    output = bytearray()
    removed: Counter[str] = Counter()
    i = 0
    while i < len(raw):
        if raw.startswith(FULL_SYNC, i):
            removed["full_32bit"] += 1
            i += len(FULL_SYNC)
        elif raw.startswith(HALF_SYNC, i):
            removed["half_16bit"] += 1
            i += len(HALF_SYNC)
        else:
            output.extend(raw[i:i + 2])
            i += 2
    return bytes(output), removed


def deframe(data: bytes) -> tuple[dict[int, bytes], dict]:
    if len(data) % FRAME_BYTES:
        raise ValueError("Trace formatter frames must be exactly 16 bytes")
    streams: defaultdict[int, bytearray] = defaultdict(bytearray)
    marker_count: Counter[int] = Counter()
    orphan = 0
    current: int | None = None

    def emit(value: int) -> None:
        nonlocal orphan
        if current is None:
            orphan += 1
        else:
            streams[current].append(value)

    for base in range(0, len(data), FRAME_BYTES):
        frame = data[base:base + FRAME_BYTES]
        aux = frame[15]
        for slot in range(8):
            pos = 2 * slot
            mixed = frame[pos]
            aux_bit = (aux >> slot) & 1
            if mixed & 1:
                new_id = mixed >> 1
                marker_count[new_id] += 1
                if slot == 7:
                    if aux_bit != 0:
                        raise ValueError(
                            f"Reserved ID transition auxiliary bit set at offset {base + pos}"
                        )
                    current = new_id
                elif aux_bit:
                    emit(frame[pos + 1])  # belongs to previous source
                    current = new_id
                else:
                    current = new_id
                    emit(frame[pos + 1])
            else:
                # Bit 0 is carried in the corresponding bit of byte 15.
                emit((mixed & 0xFE) | aux_bit)
                if slot < 7:
                    emit(frame[pos + 1])
    return {sid: bytes(content) for sid, content in streams.items()}, {
        "frames": len(data) // FRAME_BYTES,
        "source_id_markers": {
            f"0x{sid:02x}": n for sid, n in sorted(marker_count.items())
        },
        "orphan_bytes_before_first_id": orphan,
    }


def decode(raw: bytes) -> tuple[dict[int, bytes], dict]:
    clean, sync = remove_sync(raw)
    streams, metadata = deframe(clean)
    metadata.update({
        "input_size": len(raw),
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "formatted_without_sync_bytes": len(clean),
        "frame_sync_packets": dict(sync),
        "streams": {
            f"0x{sid:02x}": {
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "null_stream": sid == 0,
            }
            for sid, content in sorted(streams.items())
        },
    })
    accounting = (
        sum(len(stream) for stream in streams.values())
        + metadata["orphan_bytes_before_first_id"]
        + sum(metadata["source_id_markers"].values())
        + metadata["frames"]
    )
    if accounting != len(clean):
        raise ValueError(f"Formatter byte accounting mismatch {accounting} != {len(clean)}")
    return streams, metadata


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("capture", type=Path)
    ap.add_argument("--out-dir", type=Path)
    args = ap.parse_args()
    streams, manifest = decode(args.capture.read_bytes())
    if args.out_dir is not None:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        for sid, content in streams.items():
            (args.out_dir / f"trace-id{sid:02x}.bin").write_bytes(content)
        (args.out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
