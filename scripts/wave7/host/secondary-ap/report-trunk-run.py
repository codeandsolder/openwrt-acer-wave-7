#!/usr/bin/env python3
"""Summarize one guarded boot from its immutable evidence, not link flags."""
import csv
import json
import re
import sys
from pathlib import Path

HEADER = ("wall_epoch", "boot", "uptime", "fcs", "fragments",
          "ucast", "mcast", "bcast", "drops", "switch", "keep")
COUNTERS = ("fcs", "fragments", "ucast", "mcast", "bcast", "drops")
ERRORS = ("fcs", "fragments", "drops")
BOOT_RE = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")

def report(run):
    with (run / "trunk-counters.tsv").open(newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        if tuple(reader.fieldnames or ()) != HEADER:
            raise ValueError("unexpected counter columns")
        rows = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("malformed counter row")
            rows.append({k: v if k == "boot" else int(v) for k, v in row.items()})
    if not rows:
        raise ValueError("no counter samples")
    boot = rows[0]["boot"]
    if not BOOT_RE.fullmatch(boot) or any(r["boot"] != boot for r in rows):
        raise ValueError("mixed or invalid boot IDs")
    if any(r[k] < 0 for r in rows for k in HEADER if k != "boot"):
        raise ValueError("negative sample")
    if any(r[k] not in (0, 1) for r in rows for k in ("keep", "switch")):
        raise ValueError("invalid binary sample")
    resets = []
    corrupt_only = []
    errors = []
    for prev, cur in zip(rows, rows[1:]):
        if cur["wall_epoch"] <= prev["wall_epoch"] or cur["uptime"] <= prev["uptime"]:
            raise ValueError("non-increasing sample clocks")
        delta = {k: cur[k] - prev[k] for k in COUNTERS}
        if any(v < 0 for v in delta.values()):
            resets.append(cur["uptime"])
            continue
        if any(delta[k] for k in ERRORS):
            errors.append({"uptime": cur["uptime"], **delta})
        if delta["fcs"] + delta["fragments"] and not any(
            delta[k] for k in ("ucast", "mcast", "bcast")
        ):
            corrupt_only.append(cur["uptime"])
    accepted = [r for r in rows if r["keep"]]
    # Samples before commitment can legitimately lack the switch path.
    # No post-commit unreachability is compatible with a clean boot.
    state = dict(line.split("=", 1) for line in
                 (run / "latest-state.txt").read_text().splitlines() if "=" in line)
    if state.get("boot") != boot:
        raise ValueError("latest state does not match counter boot")
    status = (run / "status").read_text().strip()
    log = (run / "observer.log").read_text()
    match = re.search(r"\b(?:AUTONOMOUS_)?SOAK_PASS seconds=(\d+)\b", log)
    soak_seconds = int(match[1]) if match else 0
    restored_boot = None
    if status == "RESTORED":
        raw = (run / "pre-rollback.txt").read_text()
        marker = f"====BOOT====\n{boot}\n====DMESG====\n"
        if not raw.startswith(marker) or "====ETHERNET====\n" not in raw:
            raise ValueError("pre-rollback evidence does not match trial boot")
        dmesg, tail = raw[len(marker):].split("====ETHERNET====\n", 1)
        if "====END_BOOT====\n" in tail and not tail.endswith(f"====END_BOOT====\n{boot}\n"):
            raise ValueError("pre-rollback boot changed")
        restored = dict(line.split("=", 1) for line in
                        (run / "restored-state.txt").read_text().splitlines() if "=" in line)
        restored_boot = restored.get("boot")
        if (not restored_boot or not BOOT_RE.fullmatch(restored_boot) or restored_boot == boot or
            not all(restored.get(k) == v for k, v in {
                "rev": "r0+38346-0418bb7af2-ap-dhcp-guard8",
                "bootfail": "0", "keep": "1", "noc": "0", "approval": "1",
                "token": "0", "local_ready": "1", "switch_verified": "1",
                "direct_verified": "1",
            }.items())):
            raise ValueError("missing verified restored 0491 identity")
    elif status == "SOAK_PASS":
        dmesg = (run / "final-dmesg.txt").read_text()
    else:
        raise ValueError("trial not terminal or missing supported evidence")

    trigger = [line for line in dmesg.splitlines() if
               "SerDes CPU port" in line and "corrupt-only ingress" in line]
    link_loss = [line for line in dmesg.splitlines() if
                 "SerDes link lost outside a reconfiguration" in line]
    pulse_attempts = [line for line in dmesg.splitlines() if
                      "trying stock-derived recovery pulse" in line]
    pulse_completed = [line for line in dmesg.splitlines() if
                       "SerDes recovery pulse completed" in line]
    pulse_failed = [line for line in dmesg.splitlines() if
                    "SerDes recovery pulse failed" in line or
                    "SerDes recovery controls still pending" in line]
    recovery_seen = bool(trigger or link_loss or pulse_attempts or pulse_completed or pulse_failed)
    state_good = all(state.get(k) == v for k, v in {
        "keep": "1", "bootfail": "0", "q6": "3", "ap": "2", "noc": "0",
        "module_live": "1", "switch_verified": "1", "local_ready": "1",
    }.items())
    autonomous = state.get("approval") == "1" and state.get("token") == "0"
    complete = status == "SOAK_PASS" and soak_seconds >= 300 and state_good
    no_error = not resets and not any(r[k] for r in rows for k in ERRORS)
    clean = complete and no_error and all(r["switch"] for r in accepted)
    return {
        "boot": boot, "status": status, "soak_seconds": soak_seconds,
        "restored_boot": restored_boot,
        "autonomous": autonomous, "samples": len(rows), "first_uptime": rows[0]["uptime"],
        "last_uptime": rows[-1]["uptime"],
        "first_accepted_uptime": accepted[0]["uptime"] if accepted else None,
        "first_switch_uptime": next((r["uptime"] for r in rows if r["switch"]), None),
        "max_sample_gap_seconds": max((b["uptime"] - a["uptime"]
                                       for a, b in zip(rows, rows[1:])), default=0),
        "precommit_switch_misses": sum(not r["switch"] and not r["keep"] for r in rows),
        "postcommit_switch_misses": sum(not r["switch"] and r["keep"] for r in rows),
        "initial_counters": {k: rows[0][k] for k in COUNTERS},
        "final_counters": {k: rows[-1][k] for k in COUNTERS},
        "resets_or_wraps_at": resets, "error_deltas": errors,
        "sampled_corrupt_only_at": corrupt_only, "driver_corruption_triggers": trigger,
        "driver_link_loss_events": link_loss,
        "native_pulse_attempts": pulse_attempts,
        "native_pulse_completed": pulse_completed,
        "native_pulse_failed_or_pending": pulse_failed,
        "classification": (
            "CLEAN_BOOT_NO_CORRUPTION_OBSERVED" if clean and not recovery_seen else
            "CORRUPTION_TRIGGER_OBSERVED_REVIEW_RECOVERY" if trigger else
            "LINK_RECOVERY_OBSERVED_REVIEW_RECOVERY" if recovery_seen else
            "REVIEW_REQUIRED"),
    }

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: report-trunk-run.py RUN_DIR")
    print(json.dumps(report(Path(sys.argv[1])), indent=2))
