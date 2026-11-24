#!/usr/bin/env python3
"""Aggregate sealed RTL8367D candidate boots without mixing link speeds."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re

# Exact identities, including the independently changed PCS/PPE modules.
# Never group two experiments merely because the switch module is shared.
PCS_0498 = "6e1293e83985caf4eb352e163036d050de5eb2d3f4272ca8a2a71667833658bf"
PPE_0498 = "1ff7a7d590f7ef45bdaf794a3e5dfeb66ffe9a0f9eed24cf4dd8df5a7c0b5fc0"
RTL_0498 = "ff6b4c93d9ce2cb71b2b8dfd0053df70cc4a3ad4960bd49c099eceea85d7fe91"
RTL_FORCE = "bea25a2aafd1bc236740ad089bc9500b4f064034fd11cec959abd9bb208d322e"
PINS = {
    "0498": ("f9aa3e1fa3", RTL_0498, PCS_0498, PPE_0498, "", ""),
    "mib-diag": ("022d0978e9", "192835d8344c5341b4f5dc7bdb43da000d4568252b78a064c39c82dc7e5c995e", PCS_0498, PPE_0498, "", ""),
    "mib-refresh": ("14a0f757e7", "0675df8af2c490bb5957be5cc2d2124c6500cdcf01d09cef02b744d5e090a485", PCS_0498, PPE_0498, "", ""),
    "stock-order": ("472043f203", "2d0da46a3bb51ebc52d4b70c3e31a4808bcf3a82955bf1b4414375d407aff319", PCS_0498, PPE_0498, "", ""),
    "force-order": ("b9db617b17", RTL_FORCE, PCS_0498, PPE_0498, "", ""),
    "pcs0-handoff": ("6eeae4dd45", RTL_0498, "44e34472f0edab4aae5b8349a7c8b3f42396ecb102ac12803e82ff1c03c8338a", PPE_0498, "6eeae4dd45ab4ebb7c9cb296dc45d53470677c5b", ""),
    "edma-feature-init": ("7ea0722a9a", RTL_FORCE, PCS_0498, "54d77cdbdce44a435afd767c16861fa7ce7fca3a8e754d3b4694f1dfdfd05876", "", "7ea0722a9af6bd078005052ed1c209f07b739aaf"),
    "edma-sg-inheritance": ("5d080c941b", RTL_FORCE, PCS_0498, "d916e3e68e6fa057bce328eba94baba30c695d8087a890bc925f281b6c08554c", "", "5d080c941b8905d8e8f4a22c1292856ef63791fc"),
}
COMMON = {
    "manifest_fit_sha": "c289598628e75f7a603ec127dbb5cbd1fdcf6128ba15cea6c4fe9b0aa0232b8e",
    "manifest_phy_patch": "0418bb7af25d13406bb896696eb78541ccd2aa00",
    "manifest_serial_patch": "f9aa3e1fa3a541bb52e11223c7297cbd4dbc0ecc",
}
BOOT = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
CLEAN = "CLEAN_BOOT_NO_CORRUPTION_OBSERVED"


def verify_manifest(run):
    names = set()
    for line in (run / "evidence.sha256").read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
        if not match:
            raise ValueError(f"{run}: malformed evidence manifest")
        digest, name = match.groups()
        path = run / name
        if name in names or path.is_symlink() or not path.is_file():
            raise ValueError(f"{run}: ambiguous evidence {name}")
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != digest:
            raise ValueError(f"{run}: evidence digest mismatch {name}")
        names.add(name)
    if not {"status", "report.json", "observer.log", "trunk-counters.tsv"} <= names:
        raise ValueError(f"{run}: incomplete evidence manifest")
    return names


def read_state(path):
    state = {}
    for line in path.read_text().splitlines():
        key, value = line.split("=", 1)
        if key in state:
            raise ValueError(f"{path}: repeated state key {key}")
        state[key] = value
    return state


def load_run(run):
    names = verify_manifest(run)
    report = json.loads((run / "report.json").read_text())
    status = (run / "status").read_text().strip()
    if status != report["status"]:
        raise ValueError(f"{run}: report status mismatch")
    if report["classification"] == "PLANNED_APPROVED_RESTORE":
        if status != "RESTORED" or report["samples"] != 0:
            raise ValueError(f"{run}: malformed deliberate restore")
        return None
    if "latest-state.txt" not in names:
        raise ValueError(f"{run}: missing candidate identity")
    state = read_state(run / "latest-state.txt")
    boot = state["boot"]
    if not BOOT.fullmatch(boot) or boot != report["boot"]:
        raise ValueError(f"{run}: boot mismatch")
    variants = [name for name, pin in PINS.items()
                if state["rev"] == f"r0+38346-{pin[0]}-ap-dhcp-guard8"]
    if len(variants) != 1 or any(state.get(k) != v for k, v in COMMON.items()):
        raise ValueError(f"{run}: firmware identity outside matched cohort")
    variant = variants[0]
    _, module, pcs, ppe, handoff, feature = PINS[variant]
    for prefix, digest in (("module", module), ("pcs", pcs), ("ppe", ppe)):
        if any(state.get(k) != digest for k in
               (f"{prefix}_sha", f"{prefix}_rom_sha", f"manifest_{prefix}_sha")):
            raise ValueError(f"{run}: {prefix} identity mismatch")
    # Historic sealed switch-only archives predate these two fields.
    # Absence cannot satisfy a nonempty experiment pin.
    if state.get("manifest_handoff_patch", "") != handoff or state.get("manifest_feature_patch", "") != feature:
        raise ValueError(f"{run}: wrong experiment manifest")
    if any(state.get(f"{prefix}_live") != "live" or state.get(f"{prefix}_taint") != ""
           for prefix in ("pcs", "ppe")):
        raise ValueError(f"{run}: PCS/PPE not verified live")
    if state["module_live"] != "1" or state["module_upper_clear"] != "1":
        raise ValueError(f"{run}: candidate module not verified live")
    direct = int(state["lan_speed"])
    copper = int(state["speed"])
    if direct not in (1000, 2500) or copper != 1000:
        raise ValueError(f"{run}: unsupported peer speed")
    if status not in ("SOAK_PASS", "RESTORED"):
        raise ValueError(f"{run}: not a terminal candidate boot")
    classification = report["classification"]
    if classification == CLEAN:
        outcome = "clean"
        if status != "SOAK_PASS" or report["soak_seconds"] < 300:
            raise ValueError(f"{run}: invalid clean classification")
    elif report["sampled_corrupt_only_at"]:
        outcome = "corrupt_only"
    else:
        outcome = "other"
    # Do not infer boot method merely from a directory prefix.
    method = "reboot" if "reboot.log" in names else "flash" if "sysupgrade.log" in names else "unknown"
    return {"run": str(run), "boot": boot, "variant": variant, "module_sha": module,
            "revision": state["rev"], "direct_mbps": direct, "switch_mbps": copper,
            "method": method, "outcome": outcome, "classification": classification,
            "soak_seconds": report["soak_seconds"], "samples": report["samples"],
            "final_counters": report["final_counters"],
            "paired_xgmac_samples": (report.get("xgmac") or {}).get("samples", 0)}


def aggregate(runs):
    seen = set()
    cohorts = defaultdict(lambda: {"clean": 0, "corrupt_only": 0, "other": 0,
                                   "reboot": 0, "flash": 0, "unknown": 0,
                                   "soak_seconds": 0, "samples": 0,
                                   "paired_xgmac_samples": 0})
    records = []
    for run in runs:
        record = load_run(run)
        if record is None:
            continue
        if record["boot"] in seen:
            raise ValueError(f"duplicate candidate boot {record['boot']}")
        seen.add(record["boot"])
        records.append(record)
        key = (record["variant"], record["direct_mbps"], record["switch_mbps"])
        row = cohorts[key]
        row[record["outcome"]] += 1
        row[record["method"]] += 1
        for k in ("soak_seconds", "samples", "paired_xgmac_samples"):
            row[k] += record[k]
    return {"cohorts": [{"variant": k[0], "direct_mbps": k[1], "switch_mbps": k[2], **v}
                        for k, v in sorted(cohorts.items())], "boots": records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    args = parser.parse_args()
    print(json.dumps(aggregate(args.runs), indent=2))


if __name__ == "__main__":
    main()
