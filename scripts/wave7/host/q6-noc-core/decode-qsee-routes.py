#!/usr/bin/env python3
"""Decode four system NoCs in the *exact* Acer Wave7 QSEE 067 ELF.

This is NOT an IPQ5332 UserPD1 UMACNOC route decoder. The four QSEE
system NoCs have different RouteId bit allocations and none share
UserPD1 UMACNOC's logger MMIO base.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import struct

# Rooted in the actual Ghidra AArch64 function at 0x4a65c5e4 and its
# reference tables. Tied to a byte-identical QSEE ELF to prevent silently
# decoding arbitrary firmware with the wrong SoC or array layout.
ACER_067_QSEE_SHA256 = "2d67ed3873ad692b6f0c51aefbc5bca2cca6c4bed0bd34b4e8351874e14968f8"
# Fabric, bit counts, initiator array VA, target array VA, logger descriptor VA.
FABRICS = (
    ("PCNOC", 3, 4, 0x4A6B6860, 0x4A6B6EA0, 0x4A6C9AA8),
    ("SNOC", 4, 5, 0x4A6B69F0, 0x4A6B7030, 0x4A6C9B40),
    ("MEMNOC", 3, 3, 0x4A6B6B80, 0x4A6B71C0, 0x4A6C9BD8),
    ("NSSNOC", 3, 3, 0x4A6B6D10, 0x4A6B7350, 0x4A6C9C70),
)


class Qsee:
    def __init__(self, image: bytes):
        self.data = image
        if sha256(image).hexdigest() != ACER_067_QSEE_SHA256:
            raise ValueError("Unsupported QSEE image SHA256; no route table verified for this firmware")
        if image[:6] != b"\x7fELF\x02\x01":
            raise ValueError("Expected ELF64 little-endian firmware")
        phoff = struct.unpack_from("<Q", image, 32)[0]
        entsize, count = struct.unpack_from("<HH", image, 54)
        self.segments = []
        for i in range(count):
            typ, _, off, va, _, size, _, _ = struct.unpack_from("<IIQQQQQQ", image, phoff + i * entsize)
            if typ == 1 and size:
                self.segments.append((off, va, size))

    def read(self, va: int, n: int) -> bytes:
        for off, begin, length in self.segments:
            if begin <= va and va + n <= begin + length:
                return self.data[off + va - begin:off + va - begin + n]
        raise ValueError(f"Unmapped QSEE VA {va:#x}")

    def u64(self, va: int) -> int:
        return struct.unpack("<Q", self.read(va, 8))[0]

    def string(self, va: int) -> str:
        if va == 0:
            return ""
        return self.read(va, 96).split(b"\0", 1)[0].decode("ascii")

    def route(self, route_id: int) -> dict:
        if route_id < 0 or route_id > 0xFFFFFFFF:
            raise ValueError("route ID must fit a uint32")
        decoded = {}
        for fabric, init_bits, target_bits, initiators, targets, descriptor in FABRICS:
            # These shifts and masks are taken directly from the real
            # QSEE AArch64 decompilation, not inferred from a generic NoC.
            init_id = (route_id >> target_bits) & ((1 << init_bits) - 1)
            target_id = route_id & ((1 << target_bits) - 1)
            if self.string(self.u64(descriptor)) != fabric:
                raise ValueError(f"QSEE descriptor does not match {fabric}")
            decoded[fabric] = {
                "logger_mmio": f"0x{self.u64(descriptor + 16):08x}",
                "initiator_id": init_id,
                "initiator_name": self.string(self.u64(initiators + 8 * init_id)),
                "target_id": target_id,
                "target_name": self.string(self.u64(targets + 8 * target_id)),
            }
        return {
            "route_id": f"0x{route_id:08x}",
            "qsee_sha256": ACER_067_QSEE_SHA256,
            "scope": "qsee_system_nocs_ONLY_not_ipq5332_wifi_umacnoc",
            "fabrics": decoded,
        }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--qsee-elf", type=Path, required=True)
    ap.add_argument("--route-id", type=lambda v: int(v, 0), required=True)
    args = ap.parse_args()
    qsee = Qsee(args.qsee_elf.read_bytes())
    print(json.dumps(qsee.route(args.route_id), indent=2))


if __name__ == "__main__":
    main()
