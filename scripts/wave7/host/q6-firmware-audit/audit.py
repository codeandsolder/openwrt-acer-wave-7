#!/usr/bin/env python3
"""Compare complete Qualcomm split-MDT firmware families without deploying.

Verifies every nonempty .bXX payload against its matching MDT program
header, checks physical PT_LOAD residency/nonoverlap, tracks image
revisions, and examines a QCA-ATH12K-BOARD API2 database while keeping
Acer board calibration distinct from third-party firmware.
"""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

IMAGES = (
    "IPQ5332/hw1.0/q6_fw0",
    "IPQ5332/hw1.0/q6_fw1",
    "IPQ5332/hw1.0/iu_fw",
    "QCN6432/hw1.0/q6_fw2",
    "QCN6432/hw1.0/iu_fw",
)
VERSION_RE = re.compile(rb"QC_IMAGE_VERSION_STRING=(WLAN\.[A-Za-z0-9._-]+)")
MAGIC = b"QCA-ATH12K-BOARD\x00"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inspect_mdt(directory: Path, stem: str):
    mdt = directory / f"{stem}.mdt"
    data = mdt.read_bytes()
    if len(data) < 52 or data[:6] != b"\x7fELF\x01\x01":
        raise ValueError(f"not ELF32 LE: {mdt}")
    e_entry, e_phoff = struct.unpack_from("<II", data, 0x18)
    e_phentsize, e_phnum = struct.unpack_from("<HH", data, 0x2A)
    if not (e_phentsize >= 32 and 1 <= e_phnum <= 256
            and e_phoff + e_phentsize * e_phnum <= len(data)):
        raise ValueError(f"invalid ELF program headers: {mdt}")
    segments = []
    for idx in range(e_phnum):
        at = e_phoff + idx * e_phentsize
        typ, off, vaddr, paddr, filesz, memsz, flags, align = struct.unpack_from(
            "<IIIIIIII", data, at
        )
        file = directory / f"{stem}.b{idx:02d}"
        if filesz:
            if not file.is_file():
                raise ValueError(f"missing split segment: {file}")
            actual = file.stat().st_size
            if actual != filesz:
                raise ValueError(
                    f"split segment size mismatch {file}: {actual} != {filesz}"
                )
        elif file.exists() and file.stat().st_size:
            raise ValueError(f"orphan nonempty split payload: {file}")
        if typ == 1:
            if memsz < filesz or not memsz or not paddr:
                raise ValueError(f"invalid PT_LOAD in {mdt}, segment {idx}")
            segments.append({
                "index": idx,
                "phys_start": paddr,
                "phys_end": paddr + memsz,
                "virt_start": vaddr,
                "filesz": filesz,
                "memsz": memsz,
                "flags": flags,
                "align": align,
            })
        elif typ != 0:
            raise ValueError(f"unexpected program header type {typ} in {mdt}")
    for f in directory.glob(f"{stem}.b[0-9][0-9]"):
        i = int(f.name[-2:])
        if i >= e_phnum:
            raise ValueError(f"unreferenced split payload: {f}")
    if not any(s["phys_start"] <= e_entry < s["phys_end"] for s in segments):
        raise ValueError(f"entrypoint not inside physical PT_LOAD: {mdt}")
    # The only relevant version comes from radio firmware payloads, not
    # arbitrary named strings in the MDT or board database.
    fw_version = None
    for s in segments:
        if s["filesz"]:
            payload = (directory / f"{stem}.b{s['index']:02d}").read_bytes()
            match = VERSION_RE.search(payload)
            if match:
                version = match.group(1).decode("ascii")
                if fw_version and fw_version != version:
                    raise ValueError(f"contradictory firmware versions in {mdt}")
                fw_version = version
    return {
        "entry": e_entry,
        "program_headers": e_phnum,
        "mdt_sha256": digest(data),
        "version": fw_version,
        "segments": segments,
    }


def ie_records(data: bytes):
    pos = 0
    while pos + 8 <= len(data):
        kind, length = struct.unpack_from("<II", data, pos)
        start = pos + 8
        end = start + length
        if end > len(data):
            raise ValueError(f"truncated board IE: kind={kind}, length={length}")
        yield kind, data[start:end]
        pos = start + ((length + 3) & ~3)
    if pos != len(data):
        raise ValueError("trailing unparsed board IE bytes")


def board_database(path: Path):
    data = path.read_bytes()
    if not data.startswith(MAGIC):
        raise ValueError(f"missing ath12k board API2 magic: {path}")
    boards = {}
    pad = (len(MAGIC) + 3) & ~3
    for typ, payload in ie_records(data[pad:]):
        if typ != 0:
            continue  # Top-level regdb is separate from board calibration.
        name = None
        for subtyp, inner in ie_records(payload):
            if subtyp == 0:
                name = inner.decode("ascii")
            elif subtyp == 1:
                if name is None or name in boards:
                    raise ValueError("duplicate or unnamed board data")
                boards[name] = inner
                name = None
            else:
                raise ValueError(f"unsupported board child IE type {subtyp}")
    if not boards:
        raise ValueError("empty board database")
    return boards


def inspect_family(root: Path, paths: tuple[str, ...], reserved: tuple[int, int]):
    data = {}
    intervals = []
    for rel in paths:
        image = inspect_mdt(root / Path(rel).parent, Path(rel).name)
        data[rel] = image
        for s in image["segments"]:
            lo, hi = s["phys_start"], s["phys_end"]
            if not (reserved[0] <= lo < hi <= reserved[1]):
                raise ValueError(f"{rel}: segment {s['index']} outside WCSS reserved memory")
            intervals.append((lo, hi, rel, s["index"]))
    intervals.sort()
    for left, right in zip(intervals, intervals[1:]):
        if right[0] < left[1]:
            raise ValueError(
                f"physical load overlap {left[2]}[{left[3]}] "
                f"vs {right[2]}[{right[3]}]"
            )
    versions = {
        data[path]["version"] for path in paths
        if Path(path).name in ("q6_fw1", "q6_fw2")
    }
    if len(versions) != 1 or None in versions:
        raise ValueError(f"mixed/missing UserPD firmware release: {versions}")
    return {"images": data, "userpd_release": next(iter(versions)),
            "used_physical_intervals": len(intervals)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--accepted", required=True, type=Path)
    ap.add_argument("--candidate", required=True, type=Path)
    ap.add_argument("--wcss-base", type=lambda s: int(s, 0), default=0x4A900000)
    ap.add_argument("--wcss-size", type=lambda s: int(s, 0), default=0x2100000)
    ap.add_argument("--qcn-board-id", type=int, default=83)
    ap.add_argument("--report", required=True, type=Path)
    args = ap.parse_args()
    reserved = (args.wcss_base, args.wcss_base + args.wcss_size)
    stock = inspect_family(args.accepted, IMAGES, reserved)
    candidate = inspect_family(args.candidate, IMAGES, reserved)
    board_name = f"bus=ahb,qmi-chip-id=0,qmi-board-id={args.qcn_board_id}"
    candidate_boards = board_database(
        args.candidate / "QCN6432/hw1.0/board-2.bin"
    )
    if board_name not in candidate_boards:
        raise ValueError(f"candidate does not contain QCN6432 {board_name}")
    actual_board = (args.accepted / "QCN6432/hw1.0/board.bin").read_bytes()
    candidate_board = candidate_boards[board_name]
    if len(actual_board) != len(candidate_board):
        raise ValueError("candidate board data uses a different length")
    if actual_board[:12] != candidate_board[:12]:
        raise ValueError("candidate board data envelope differs")
    current_alias = args.accepted / "IPQ5332/hw1.0/q6_fw2.b02"
    if not current_alias.is_file() or current_alias.read_bytes() != (
        args.accepted / "QCN6432/hw1.0/q6_fw2.b02"
    ).read_bytes():
        raise ValueError("accepted DTS q6_fw2 IPQ5332/QCN6432 aliases disagree")
    # New release must remain distinct; let a caller decide whether to
    # build a separate source/OTA image. Never alter live firmware.
    result = {
        "structural_gates": "PASS",
        "accepted": stock,
        "candidate": candidate,
        "wcss_reserved": {"start": reserved[0], "end": reserved[1]},
        "qcn_board": {
            "lookup": board_name,
            "api2_entries": len(candidate_boards),
            "accepted_sha256": digest(actual_board),
            "gl_candidate_sha256": digest(candidate_board),
            "length": len(actual_board),
            "envelope_first12_equal": True,
            "payload_identical": actual_board == candidate_board,
            "action": "KEEP_ACER_BOARD_AND_CALIBRATION; no automatic substitution",
        },
        "deployment_paths": {
            "ipq_root": "IPQ5332/hw1.0/q6_fw0",
            "ipq_pd1": "IPQ5332/hw1.0/q6_fw1",
            "qcn_pd2_canonical": "QCN6432/hw1.0/q6_fw2",
            "qcn_pd2_dts_alias": "IPQ5332/hw1.0/q6_fw2",
            "ipq_iu": "IPQ5332/hw1.0/iu_fw",
            "qcn_iu": "QCN6432/hw1.0/iu_fw",
        },
        "unverified_runtime_gates": (
            "secureboot/authentication key acceptance", "QMI/WMI/MPD/SSR ABI",
            "BDF compatibility despite same envelope", "MLO/WSI/board behavior",
            "power/thermal/regulatory behavior",
        ),
        "hardware_modified": False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("STRUCTURAL_PASS")
    print("CURRENT", stock["userpd_release"])
    print("CANDIDATE", candidate["userpd_release"])
    print("QCN_BOARD_ID", args.qcn_board_id, "ACER_CAL_DIFFERS",
          actual_board != candidate_board)
    print("LOAD_INTERVALS", candidate["used_physical_intervals"])
    print("RUNTIME_ABI_NOT_VALIDATED; NO_FLASH")


if __name__ == "__main__":
    main()
