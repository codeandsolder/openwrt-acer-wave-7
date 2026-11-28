#!/usr/bin/env python3
"""Prove a single idle rate request is supported and bracketed by pdev reset witnesses."""
import json
from pathlib import Path
import runpy
import sys

h = Path(__file__).parent
tx = runpy.run_path(str(h / "htt-tx-stats.py"))
rate = runpy.run_path(str(h / "htt-rate-stats.py"))


def verify(lines, boot):
    require = rate["require"]
    require(lines and lines[0] == lines[-1] == boot, "idle probe boot mismatch")
    markers = ["==== HTT_TX_BEFORE", "==== HTT_RATE", "==== HTT_TX_AFTER", "==== END"]
    require(all(lines.count(x) == 1 for x in markers), "incomplete idle probe")
    i = [lines.index(x) for x in markers]
    require(i == sorted(i) and i[0] == 1 and i[-1] == len(lines)-2, "invalid idle probe order")
    devices = {"ahb-c000000.wifi", "ahb-soc@0:wifi"}
    a = tx["describe_snapshot"](lines[i[0]+1:i[1]], devices)
    b = tx["describe_snapshot"](lines[i[2]+1:i[3]], devices)
    d = tx["compare"](a,b)
    require(d["qualified"], "idle probe reset witness: " + json.dumps(d))
    r = rate["describe_snapshot"](lines[i[1]+1:i[2]], a)
    require(r["qualified"], "idle rate reply: " + json.dumps(r))
    require(r["radios"].keys() == b["radios"].keys(), "idle probe radio coverage")
    for radio, v in r["radios"].items():
        require(a["radios"][radio]["end_ms"] <= v["start_ms"] <= v["end_ms"] <=
                b["radios"][radio]["start_ms"], "idle rate probe not bracketed")
        require(v["mac_id"] == b["radios"][radio]["mac_id"], "idle rate identity")
    return r


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify-htt-rate-probe.py RAW BOOT")
    print(json.dumps(verify(Path(sys.argv[1]).read_text().splitlines(), sys.argv[2]),
                     indent=2, sort_keys=True))
