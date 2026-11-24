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

XGMAC_ERRORS = ("rx_crc_err","rx_frag_err","rx_jabber_err","rx_len_err",
                "rx_fifo_overflow","rx_drop_frames","tx_underflow_err")
XGMAC = ("rx_frames","tx_frames","rx_unicast_g","tx_unicast","rx_pause","tx_pause",*XGMAC_ERRORS)
XGMAC_HEADER = ("wall_epoch","boot","uptime",*XGMAC)

def xgmac_report(run, mib_rows):
    path = run / "trunk-xgmac.tsv"
    if not path.exists():
        return None
    def identity(row):
        return (row["wall_epoch"],row["boot"],row["uptime"])
    expected = {identity(r):r for r in mib_rows}
    rows = []
    seen = set()
    with path.open(newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        if tuple(reader.fieldnames or ()) != XGMAC_HEADER:
            raise ValueError("unexpected XGMAC columns")
        for raw in reader:
            if None in raw or any(v is None for v in raw.values()):
                raise ValueError("malformed XGMAC row")
            row = {k:v if k=="boot" else int(v) for k,v in raw.items()}
            key = identity(row)
            if key not in expected or key in seen or any(row[k]<0 for k in XGMAC):
                raise ValueError("unmatched, duplicate or invalid XGMAC sample")
            if rows and row["uptime"]<=rows[-1]["uptime"]:
                raise ValueError("non-increasing XGMAC sample clocks")
            seen.add(key)
            rows.append(row)
    intervals=[]
    for a,b in zip(rows,rows[1:]):
        md0,md1=expected[identity(a)],expected[identity(b)]
        mac={k:b[k]-a[k] for k in XGMAC}
        mib={k:md1[k]-md0[k] for k in COUNTERS}
        reset=any(v<0 for v in (*mac.values(),*mib.values()))
        corrupt=not reset and mib["fcs"]+mib["fragments"]>0 and not any(mib[k] for k in ("ucast","mcast","bcast"))
        rx_silent = (not reset and md0["keep"] and md1["keep"] and
                     not md0["switch"] and not md1["switch"] and
                     not any(mib[k] for k in ERRORS) and
                     not any(mac[k] for k in XGMAC_ERRORS) and
                     sum(mib[k] for k in ("ucast","mcast","bcast")) > 0 and
                     mac["tx_frames"] > 0 and mac["rx_frames"] == 0)
        intervals.append({"rx_silent":bool(rx_silent),"start_uptime":a["uptime"],"end_uptime":b["uptime"],
                          "reset":reset,"corrupt_only":corrupt,"mib":mib,"xgmac":mac})
    corrupt=[r for r in intervals if r["corrupt_only"]]
    complete = len(rows)==len(expected)
    no_errors = not any(row[k] for row in rows for k in XGMAC_ERRORS)
    resets = [r["end_uptime"] for r in intervals if r["reset"]]
    return {"samples":len(rows),"missing_samples":len(expected)-len(rows),
            "complete":complete,"clean":complete and no_errors and not resets,
            "tx_unicast_minus_rtl_ingress_range":(
                [min(diffs),max(diffs)] if (diffs := [
                    row["tx_unicast"]-expected[identity(row)]["ucast"] for row in rows
                ]) else None),
            "initial":{k:rows[0][k] for k in XGMAC} if rows else None,
            "final":{k:rows[-1][k] for k in XGMAC} if rows else None,
            "resets":resets,
            "corrupt_only_with_mac_tx_unicast":[r["end_uptime"] for r in corrupt if r["xgmac"]["tx_unicast"]>0],
            "corrupt_only_with_mac_tx_frames":[r["end_uptime"] for r in corrupt if r["xgmac"]["tx_frames"]>0],
            "rx_silent_during_switch_miss":[r["end_uptime"] for r in intervals if r["rx_silent"]],
            "hardware_error_intervals":[r["end_uptime"] for r in intervals if not r["reset"] and any(r["xgmac"][k] for k in XGMAC_ERRORS)],
            "intervals":intervals}

def planned_restore_report(run):
    """A deliberate return to 0491 is not a candidate soak or fault."""
    def state(name):
        return dict(line.split("=", 1) for line in
                    (run / name).read_text().splitlines() if "=" in line)
    source = state("preflight.txt")
    restored = state("restored-state.txt")
    boot = source.get("boot", "")
    target = restored.get("boot", "")
    if (not BOOT_RE.fullmatch(boot) or not BOOT_RE.fullmatch(target)
            or boot == target or not all(restored.get(k) == v for k, v in {
                "rev": "r0+38346-0418bb7af2-ap-dhcp-guard8",
                "bootfail": "0", "keep": "1", "noc": "0", "approval": "1",
                "token": "0", "local_ready": "1", "switch_verified": "1",
                "direct_verified": "1",
            }.items())):
        raise ValueError("missing verified restored 0491 identity")
    log = (run / "observer.log").read_text()
    if f"ARMED predecessor={boot}" not in log or f"ACCEPTED_IMAGE_BOOT_HEALTHY boot={target}" not in log:
        raise ValueError("restoration observer identity mismatch")
    with (run / "trunk-counters.tsv").open() as f:
        if list(csv.reader(f, delimiter="\t")) != [list(HEADER)]:
            raise ValueError("planned restoration contains candidate samples")
    return {"boot": boot, "source_revision": source.get("rev"),
            "restored_boot": target, "restored_revision": restored["rev"],
            "status": "RESTORED", "classification": "PLANNED_APPROVED_RESTORE",
            "samples": 0, "soak_seconds": 0}


def report(run, *, candidate_only=False):
    if ((run / "status").read_text().strip() == "RESTORED"
            and not (run / "latest-state.txt").exists()
            and (run / "preflight.txt").exists()):
        return planned_restore_report(run)
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
    if candidate_only and (status not in ("RESTORE_ISSUED","RESTORED","TIMEOUT") or
                           "RESTORE_NATIVE_SYSUPGRADE" not in log):
        raise ValueError("candidate-only report requires an issued native restore")
    if status == "RESTORED" or candidate_only:
        raw = (run / "pre-rollback.txt").read_text()
        marker = f"====BOOT====\n{boot}\n====DMESG====\n"
        if not raw.startswith(marker) or "====ETHERNET====\n" not in raw:
            raise ValueError("pre-rollback evidence does not match trial boot")
        dmesg, tail = raw[len(marker):].split("====ETHERNET====\n", 1)
        if "====END_BOOT====\n" in tail and not tail.endswith(f"====END_BOOT====\n{boot}\n"):
            raise ValueError("pre-rollback boot changed")
        if status == "RESTORED":
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
    xgmac = xgmac_report(run, rows)
    clean = (complete and no_error and all(r["switch"] for r in accepted)
             and (xgmac is None or xgmac["clean"]))
    return {
        "boot": boot, "status": status, "soak_seconds": soak_seconds,
        "restored_boot": restored_boot,
        "xgmac": xgmac,
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
            "RX_SILENT_DURING_SWITCH_FAILURE" if xgmac and xgmac["rx_silent_during_switch_miss"] else
            "LINK_RECOVERY_OBSERVED_REVIEW_RECOVERY" if recovery_seen else
            "REVIEW_REQUIRED"),
    }

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run",type=Path)
    parser.add_argument("--candidate-only",action="store_true",
                        help="summarize a failed candidate after restore issuance, without claiming healthy rollback")
    args=parser.parse_args()
    print(json.dumps(report(args.run,candidate_only=args.candidate_only), indent=2))
