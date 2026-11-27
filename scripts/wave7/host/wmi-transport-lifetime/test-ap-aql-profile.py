#!/usr/bin/env python3
"""Check bounded AQL occupancy evidence, including corrupt and truncated traces."""
import importlib.util
from pathlib import Path

p = Path(__file__).with_name("load-ap-delta.py")
spec = importlib.util.spec_from_file_location("load_delta", p)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
boot = "12345678-1234-1234-1234-123456789abc"
start = 100.0
rows = [f"AQL_PROFILE_READY boot={boot} enabled=1 original=0 seconds=335"]
for i in range(1341):
    t = start + i / 4
    pending = i % 100
    rows.append(f"AQL_PROFILE_SAMPLE {t:.2f} 0 0 {pending} 0 0 {pending}")
rows += ["AQL_PROFILE_DRAINED", "AQL_PROFILE_RESTORE enabled=0", "AQL_PROFILE_END rc=0"]
intervals = {"uplink": (120, 140), "downlink": (160, 180), "bidirectional": (200, 220)}
text = "\n".join(rows)
result = mod.parse_aql_profile(text, boot, intervals)
assert result["enabled"] == 1 and result["original"] == 0 and result["drained"]
assert result["samples"] == 1341
assert all(p["samples"] == 81 and p["max_gap_s"] == .25 for p in result["phases"].values())
assert result["phases"]["uplink"]["pending_us"]["BE"]["max"] == 99
cases = [
    (text.replace(boot, "0" * 36), intervals),
    (text.replace("AQL_PROFILE_DRAINED", "AQL_PROFILE_DRAIN_FAILED"), intervals),
    (text.replace("RESTORE enabled=0", "RESTORE enabled=1"), intervals),
    (text.replace("END rc=0", "END rc=1"), intervals),
    ("\n".join(rows[:500] + rows[520:]), intervals),
    ("\n".join(rows[:500] + [rows[499]] + rows[500:]), intervals),
    ("\n".join(rows[:500] + rows[501:900] + rows[-3:]), intervals),
    (text.replace(" 0 0 99 0 0 99", " 0 0 4294967295 0 0 99"), intervals),
    (text, {"outside": (99, 130)}),
]
for broken, ranges in cases:
    try:
        mod.parse_aql_profile(broken, boot, ranges)
    except ValueError:
        pass
    else:
        raise AssertionError("accepted corrupt AQL profile")
print(f"AQL_PROFILE_PARSER_PASS valid=1 rejected={len(cases)}")
