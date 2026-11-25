#!/usr/bin/env python3
"""Compare firmware CNM BSS/OMAC snapshots with host and LWTBL bands."""
import argparse
import json
import re
from pathlib import Path

STAGES = {2: "pre_refresh", 3: "post_refresh", 4: "post_add",
          10: "pre_assoc", 5: "post_assoc", 6: "post_mld", 7: "post_keys"}
EVENT = re.compile(r"(\d+\.\d+): mt7925_lab_(cnm_bss|cnm_result|wtbl_peer): (.*)")
FIELD = re.compile(r"(\w+)=(0x[0-9a-f]+|-?\d+)")

def summarize(text):
    snapshots = []
    pending = []
    for match in EVENT.finditer(text):
        time, event, fields = match.groups()
        values = {key: int(value, 0) for key, value in FIELD.findall(fields)}
        stage = values.get("stage")
        if stage == 1:
            continue
        if stage not in STAGES:
            raise ValueError(f"unknown stage {stage}")
        if event == "wtbl_peer":
            pending.append({
                "time": float(time), "stage": stage, "bss": values["bss"],
                "link": values["link"], "wcid": values["wcid"],
                "wtbl_band": (values["dw0"] >> 26) & 3,
                "cipher": values["cipher"],
            })
        elif event == "cnm_result":
            # Each result begins a new query, even when a station retries.
            same_stage = [row for row in pending if row["stage"] == stage]
            snapshots.append({"time": float(time), "stage": STAGES[stage],
                              "stage_id": stage, "ret": values["ret"],
                              "firmware_bss_count": values["count"],
                              "bss": [], "wtbl": same_stage})
            pending.clear()
        else:
            if not snapshots or snapshots[-1]["stage_id"] != stage:
                raise ValueError("CNM BSS row without matching query result")
            row = dict(values)
            del row["stage"]
            row["conn_state"] = row.pop("connected")
            snapshot = snapshots[-1]
            if snapshot["ret"] or any(b["bss"] == row["bss"] for b in snapshot["bss"]):
                raise ValueError("duplicate or unexpected BSS result")
            if row["bss"] >= snapshot["firmware_bss_count"]:
                raise ValueError("BSS index outside response")
            peer = next((w for w in snapshot["wtbl"] if w["bss"] == row["bss"]), None)
            if peer:
                row.update({k: peer[k] for k in ("wcid", "link", "wtbl_band", "cipher")})
            snapshot["bss"].append(row)
    if not snapshots:
        raise ValueError("no CNM query result")
    if pending:
        raise ValueError("truncated WTBL/CNM pairing")
    return snapshots

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.trace.read_text()), indent=2))

if __name__ == "__main__":
    main()
