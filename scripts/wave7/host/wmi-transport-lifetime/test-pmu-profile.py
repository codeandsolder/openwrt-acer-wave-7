#!/usr/bin/env python3
"""Exercise real PMU parser with malformed, reset and multiplexed traces."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("pmu", Path(__file__).with_name("pmu-profile.py"))
pmu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pmu)
boot = "12345678-1234-1234-1234-123456789abc"
ns = pmu.NS
start = 100 * ns
rows = [f"PMU_READY boot={boot} cpus=4 seconds=335"]
for seq in range(336):
    for cpu in range(4):
        lo = start + seq * ns + cpu * 100_000
        hi = lo + 50_000
        enabled = (seq + 1) * ns
        vals = [(seq + 1) * (cpu + 1) * n for n in (1000, 2000, 500, 50, 25)]
        rows.append("PMU_SAMPLE " + " ".join(map(str, (seq, cpu, lo, hi, enabled, enabled, *vals))))
rows.append("PMU_END rc=0")
text = "\n".join(rows)
phases = {"uplink": (120.1, 138.9), "downlink": (160.1, 178.9), "bidirectional": (200.1, 218.9)}
r = pmu.parse(text, boot, phases)
assert r["samples_per_cpu"] == 336
for phase in r["phases"].values():
    assert phase["instructions_per_cycle"] == 2
    assert phase["l1d_refills_per_1000_instructions"] == 25
    assert phase["total"]["cycles"] == 170_000
    assert phase["last_sequence"] - phase["first_sequence"] == 17
    assert all(cpu["pmu_running_pct"] == 100 for cpu in phase["cpus"].values())

def modify(i, field, value):
    copy = rows[:]
    parts = copy[i].split()
    parts[field] = str(value)
    copy[i] = " ".join(parts)
    return "\n".join(copy)

bad = [
    text.replace(boot, "0" * 36),
    "\n".join(rows[:10] + rows[11:]),
    text.replace("PMU_END rc=0", "PMU_END rc=1"),
    modify(5, 2, 1),
    modify(5, 4, start + 2 * ns),
    modify(5, 5, ns // 2),
    modify(5, 6, ns + ns // 2),
    modify(5, 7, 0),
    modify(5, 3, start + 4 * ns),
    modify(4, 3, start + ns // 2),
]
for case in bad:
    try:
        pmu.parse(case, boot, phases)
    except ValueError:
        pass
    else:
        raise AssertionError("corrupt PMU profile accepted")
try:
    pmu.parse(text, boot, {"outside": (99, 110)})
except ValueError:
    pass
else:
    raise AssertionError("incomplete load envelope accepted")
print(f"PMU_PROFILE_PARSER_PASS valid=1 rejected={len(bad)+1}")
