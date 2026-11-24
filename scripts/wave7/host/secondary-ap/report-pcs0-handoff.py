#!/usr/bin/env -S uv run --no-project python
"""Compare exact, sealed PCS0 handoff observations across independent boots."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import re
import runpy

cohort = runpy.run_path(str(Path(__file__).with_name("report-ordering-cohort.py")))
MARKER = re.compile(
    r"^\[\s*(\d+\.\d+)\] ipq9574_pcs 7a00000\.ethernet-pcs: "
    r"wave7-handoff: (probe|before-mode) "
    r"mode=(0x[0-9a-f]+|0) misc=(0x[0-9a-f]+|0) cal=(0x[0-9a-f]+|0) "
    r"ctrl=(0x[0-9a-f]+|0) sts=(0x[0-9a-f]+|0)$"
)
FIELDS = ("mode", "misc", "cal", "ctrl", "sts")


def parse(dmesg):
    stages = {}
    for line in dmesg.splitlines():
        if "wave7-handoff:" not in line:
            continue
        match = MARKER.fullmatch(line)
        if not match:
            raise ValueError(f"invalid handoff marker: {line}")
        uptime, stage, *values = match.groups()
        if stage in stages:
            raise ValueError(f"duplicate handoff stage {stage}")
        stages[stage] = {"uptime": uptime, **dict(zip(FIELDS, map(lambda v: int(v, 0), values), strict=True))}
    if set(stages) != {"probe", "before-mode"}:
        raise ValueError("missing handoff stage")
    if Decimal(stages["probe"]["uptime"]) >= Decimal(stages["before-mode"]["uptime"]):
        raise ValueError("non-increasing handoff times")
    for row in stages.values():
        row["decoded"] = {
            "mode_select": (row["mode"] >> 8) & 31,
            "misc_mode": (row["misc"] >> 4) & 7,
            "calibration_done": bool(row["cal"] & 128),
            "adapter_reset_bit": bool(row["ctrl"] & 2048),
            "link": bool(row["sts"] & 128),
        }
    return stages


def load(run):
    record = cohort["load_run"](run)
    if record is None or record["variant"] != "pcs0-handoff":
        raise ValueError("requires exact PCS0 diagnostic boot")
    names = cohort["verify_manifest"](run)
    if record["outcome"] == "clean" or (run / "status").read_text().strip() == "SOAK_PASS":
        if "final-dmesg.txt" not in names:
            raise ValueError("missing sealed final dmesg")
        dmesg = (run / "final-dmesg.txt").read_text()
    else:
        if "pre-rollback.txt" not in names:
            raise ValueError("missing sealed failed-boot dmesg")
        raw = (run / "pre-rollback.txt").read_text()
        prefix = f'====BOOT====\n{record["boot"]}\n====DMESG====\n'
        if not raw.startswith(prefix) or "====ETHERNET====\n" not in raw:
            raise ValueError("failed-boot marker mismatch")
        dmesg = raw[len(prefix):].split("====ETHERNET====\n", 1)[0]
    record["handoff"] = parse(dmesg)
    record["signature"] = {
        stage: [row[key] for key in FIELDS]
        for stage, row in record["handoff"].items()
    }
    return record


def compare(runs):
    records = [load(run) for run in runs]
    if len({record["boot"] for record in records}) != len(records):
        raise ValueError("duplicate diagnostic boot")
    # Separate flash and warm reboot signatures. The predecessor may
    # influence initial register values even when the candidate is identical.
    groups = {}
    for record in records:
        source = cohort["read_state"](Path(record["run"]) / "preflight.txt")
        record["predecessor_revision"] = source["rev"]
        key = (record["method"], source["rev"],
               tuple(record["signature"]["probe"]), tuple(record["signature"]["before-mode"]))
        groups.setdefault(key, []).append(record["outcome"])
    return {"fields": FIELDS, "boots": records, "groups": [
        {"method": method, "predecessor_revision": source,
         "probe": probe, "before_mode": mode, "outcomes": outcomes}
        for (method, source, probe, mode), outcomes in groups.items()
    ]}


def selftest():
    first = "[   11.413314] ipq9574_pcs 7a00000.ethernet-pcs: wave7-handoff: probe mode=0x1021 misc=0x70 cal=0xa00 ctrl=0x844 sts=0x20"
    second = "[   14.966336] ipq9574_pcs 7a00000.ethernet-pcs: wave7-handoff: before-mode mode=0x1021 misc=0x70 cal=0xac1 ctrl=0x844 sts=0x60"
    data = parse(first + "\n" + second)
    assert data["probe"]["decoded"]["mode_select"] == 16
    assert not data["probe"]["decoded"]["calibration_done"]
    assert data["before-mode"]["decoded"]["calibration_done"]
    for bad in (first, first+"\n"+first+"\n"+second, first+"\n"+second.replace("14.966336","10.000000"),
                first+"\n"+second.replace("7a00000","7a10000"), first+"\n"+second.replace("sts=0x60","read failed: -5")):
        try:
            parse(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("malformed trace accepted")
    print("PCS0_HANDOFF_SELFTEST_PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="*", type=Path)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
    else:
        if not args.runs:
            parser.error("requires one or more sealed runs")
        print(json.dumps(compare([run.resolve() for run in args.runs]), indent=2))
