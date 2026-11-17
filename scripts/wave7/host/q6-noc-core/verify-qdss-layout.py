#!/usr/bin/env python3
"""Verify IPQ5332 QDSS ETR isolation against the original Acer memory map.

Checks the entire direct-child reserved-memory map (not merely one intended
region), and the physical p_memsz extents of all three stock Q6 ELF images.
Runtime allocations still need a separate controlled validation.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import struct
import subprocess

ETR_START = 0x4CD00000
ETR_SIZE = 0x100000
SOURCE = "target/linux/qualcommbe/dts/ipq5332-acer-wave7.dts"


@dataclass(frozen=True)
class Region:
    name: str
    start: int
    end: int

    def overlaps(self, other: "Region") -> bool:
        return self.start < other.end and other.start < self.end


def match_brace(text: str, begin: int) -> int:
    """Return matching closing-brace location for a brace at begin."""
    if text[begin] != "{":
        raise ValueError("Expected opening brace")
    level = 1
    for index in range(begin + 1, len(text)):
        if text[index] == "{":
            level += 1
        elif text[index] == "}":
            level -= 1
            if not level:
                return index
    raise ValueError("Unclosed DTS node")


def direct_reserved_regions(dts: str) -> dict[str, Region]:
    dts = re.sub(r"/\*.*?\*/", "", dts, flags=re.S)
    dts = re.sub(r"//[^\n]*", "", dts)
    match = re.search(r"\breserved-memory\s*\{", dts)
    if match is None:
        raise ValueError("No reserved-memory node in the target board DTS")
    block = dts[match.end():match_brace(dts, match.end() - 1)]
    pattern = re.compile(r"(?:(?:\b[\w-]+)\s*:\s*)?([\w,@.-]+)\s*\{")
    found: dict[str, Region] = {}
    pos = 0
    while (item := pattern.search(block, pos)) is not None:
        end = match_brace(block, item.end() - 1)
        name = item.group(1)
        body = block[item.end():end]
        spans = re.findall(r"\breg\s*=\s*<([^>]+)>\s*;", body)
        if len(spans) != 1:
            raise ValueError(f"Expected exactly one reg property in {name}")
        cells = [int(cell, 0) for cell in spans[0].split()]
        if len(cells) != 4 or any(not (0 <= v <= 0xFFFFFFFF) for v in cells):
            raise ValueError(f"Expected four address/size cells in {name}: {cells}")
        start = cells[0] << 32 | cells[1]
        size = cells[2] << 32 | cells[3]
        if size == 0:
            raise ValueError(f"Zero-size reserved node: {name}")
        if name in found:
            raise ValueError(f"Duplicate reserved node: {name}")
        found[name] = Region(name, start, start + size)
        pos = end + 1

    if not found:
        raise ValueError("No directly defined reserved-memory children")
    sorted_regions = sorted(found.values(), key=lambda x: x.start)
    for a, b in zip(sorted_regions, sorted_regions[1:]):
        if a.overlaps(b):
            raise ValueError(f"Overlapping reservations: {a} and {b}")
    return found


def coverage(regions: dict[str, Region]) -> list[tuple[int, int]]:
    spans = sorted(((r.start, r.end) for r in regions.values()))
    merged = []
    for start, end in spans:
        if merged and start == merged[-1][1]:
            merged[-1] = merged[-1][0], end
        else:
            merged.append((start, end))
    return merged


def elf_load_regions(path: Path) -> list[Region]:
    blob = path.read_bytes()
    if blob[:6] not in (b"\x7fELF\x01\x01", b"\x7fELF\x02\x01"):
        raise ValueError(f"Expected little-endian ELF: {path}")
    if blob[4] == 1:
        phoff = struct.unpack_from("<I", blob, 28)[0]
        entsize, count = struct.unpack_from("<HH", blob, 42)
        fmt = "<IIIIIIII"
    else:
        phoff = struct.unpack_from("<Q", blob, 32)[0]
        entsize, count = struct.unpack_from("<HH", blob, 54)
        fmt = "<IIQQQQQQ"
    if entsize < struct.calcsize(fmt) or phoff + count * entsize > len(blob):
        raise ValueError(f"Invalid ELF program headers in {path}")
    result = []
    for i in range(count):
        values = struct.unpack_from(fmt, blob, phoff + i * entsize)
        if blob[4] == 1:
            typ, _, _, paddr, _, msize, _, _ = values
        else:
            typ, _, _, _, paddr, _, msize, _ = values
        if typ == 1 and msize:
            result.append(Region(f"{path.name}:LOAD[{i}]", paddr, paddr + msize))
    if not result:
        raise ValueError(f"No PT_LOAD segments in {path}")
    return result


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--repo", type=Path, required=True)
    cli.add_argument("--baseline-rev", required=True)
    cli.add_argument("--stock-fw-dir", type=Path, required=True)
    opts = cli.parse_args()

    base = subprocess.run(
        ["git", "-C", str(opts.repo), "show", f"{opts.baseline_rev}:{SOURCE}"],
        check=True, capture_output=True, text=True).stdout
    edited = (opts.repo / SOURCE).read_text()
    old, new = direct_reserved_regions(base), direct_reserved_regions(edited)
    if coverage(old) != coverage(new):
        raise ValueError("QDSS variant changes the reserved-memory coverage")
    etr = new.get("wifi-etr@4cd00000")
    if etr != Region("wifi-etr@4cd00000", ETR_START, ETR_START + ETR_SIZE):
        raise ValueError("Missing or moved 1 MiB ETR reservation")
    if "wifi-etr@4cd00000" in old:
        raise ValueError("Original DTS already assigned the ETR range")
    if not re.search(r"q6_etr:\s+wifi-etr@4cd00000\s*\{[^{}]*\bno-map\s*;",
                     edited, flags=re.S):
        raise ValueError("ETR region must be no-map")
    if edited.count('"q6-etr-dump"') != 1 or "<&q6_etr>" not in edited:
        raise ValueError("ETR region must be referenced exactly once by Wi-Fi")

    candidates = sorted(opts.stock_fw_dir.glob("q6_fw?.mdt"))
    if len(candidates) != 3:
        raise ValueError(f"Expected exactly three stock Q6 ELF images: {candidates}")
    for image in candidates:
        segments = elf_load_regions(image)
        for segment in segments:
            if segment.overlaps(etr):
                raise ValueError(f"QDSS ETR overlaps firmware: {segment}")
        print(f"{image.name}: {len(segments)} PT_LOAD segments, "
              f"no overlap, SHA256 {hashlib.sha256(image.read_bytes()).hexdigest()}")

    print(f"PASS: {len(new)} disjoint direct reserved-memory regions, "
          f"original coverage preserved, ETR {etr.start:#x}–{etr.end:#x}")
    print("Scope: statically declared DTS regions and ELF PT_LOAD only; "
          "runtime firmware allocations require separate verification")


if __name__ == "__main__":
    main()
