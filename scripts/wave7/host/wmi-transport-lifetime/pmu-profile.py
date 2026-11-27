#!/usr/bin/env python3
"""Attribute non-multiplexed, per-CPU PMU deltas to guarded load envelopes."""
from collections import defaultdict
import re

EVENTS = ("cycles", "instructions", "l1d_accesses", "l1d_refills", "branch_misses")
CPUS = 4
SECONDS = 335
NS = 1_000_000_000


def require(ok, message):
    if not ok:
        raise ValueError(message)


def parse(text, boot, intervals):
    lines = text.splitlines()
    require(len(lines) == 2 + (SECONDS + 1) * CPUS, "incomplete PMU profile")
    require(lines[0] == f"PMU_READY boot={boot} cpus={CPUS} seconds={SECONDS}",
            "PMU boot or CPU identity")
    require(lines[-1] == "PMU_END rc=0", "PMU observer failed")
    samples = defaultdict(list)
    for i, line in enumerate(lines[1:-1]):
        m = re.fullmatch(r"PMU_SAMPLE ((?:[0-9]+ ){10}[0-9]+)", line)
        require(m, "invalid PMU sample")
        seq, cpu, lo, hi, enabled, running, *values = map(int, m[1].split())
        require((seq, cpu) == divmod(i, CPUS), "PMU sample sequence or CPU mismatch")
        require(0 < lo <= hi and hi - lo <= NS // 10, "PMU read uncertainty >100ms")
        require(0 < running <= enabled < 2**64 and all(v < 2**64 for v in values),
                "invalid PMU counters")
        row = (lo, hi, enabled, running, *values)
        if samples[cpu]:
            prior = samples[cpu][-1]
            require(prior[1] < lo and NS // 2 <= lo - prior[0] <= 3 * NS // 2,
                    "PMU sample discontinuity")
            require(all(a <= b for a, b in zip(prior[2:], row[2:])),
                    "PMU counter reset")
            de, dr = enabled - prior[2], running - prior[3]
            require(0 < dr <= de and dr * 100 >= 99 * de,
                    "PMU group unscheduled or multiplexed")
            # A pinned system-wide group must cover elapsed time, not just
            # a tiny fraction of it with equal enabled/running timestamps.
            require(de >= (lo - prior[1]) * 9 // 10 and de <= (hi - prior[0]) * 11 // 10,
                    "PMU enabled time discontinuity")
        samples[cpu].append(row)

    for seq in range(SECONDS + 1):
        a, b = samples[0][seq], samples[CPUS - 1][seq]
        require(a[0] <= b[1] and b[1] - a[0] <= NS // 5,
                "cross-core PMU snapshot skew >200ms")
        require(all(samples[c][seq][1] <= samples[c + 1][seq][0] for c in range(CPUS - 1)),
                "cross-core PMU sample order")

    phases = {}
    for mode, (start, end) in intervals.items():
        # /proc/uptime is printed to centiseconds. Discard any intervals
        # crossing either snapshot boundary rather than interpolating counts.
        lower, upper = round(start * NS) + NS // 100, round(end * NS)
        require(0 < lower < upper, "invalid load interval")
        require(samples[CPUS - 1][0][1] <= lower and samples[0][-1][0] >= upper,
                "PMU observer does not enclose load phase")
        cpu_result = {}
        # Use the same complete snapshot indices for all CPUs. No mixing
        # counts from different elapsed intervals when summing cores.
        indexes = [i for i in range(SECONDS)
                   if samples[0][i][0] >= lower and samples[CPUS - 1][i + 1][1] <= upper]
        require(indexes and indexes == list(range(indexes[0], indexes[-1] + 1)),
                "no contiguous PMU intervals in load phase")
        first, last = indexes[0], indexes[-1] + 1
        coverage = (samples[0][last][0] - samples[CPUS - 1][first][1]) / NS
        require(coverage >= (end - start) - 3 and coverage >= 0.8 * (end - start),
                "insufficient PMU load envelope coverage")
        totals = dict.fromkeys(EVENTS, 0)
        for cpu in range(CPUS):
            a, b = samples[cpu][first], samples[cpu][last]
            counters = dict(zip(EVENTS, (y - x for x, y in zip(a[4:], b[4:]))))
            for key, value in counters.items():
                totals[key] += value
            elapsed = ((b[0] + b[1]) - (a[0] + a[1])) / (2 * NS)
            cpu_result[str(cpu)] = {
                "count": counters, "elapsed_s": elapsed,
                "rate_per_s": {k: v / elapsed for k, v in counters.items()},
                "pmu_running_pct": 100 * (b[3] - a[3]) / (b[2] - a[2]),
            }
        phases[mode] = {
            "first_sequence": first, "last_sequence": last,
            "common_coverage_s": coverage,
            "load_envelope_s": end - start,
            "cpus": cpu_result,
            "total": totals,
            "instructions_per_cycle": totals["instructions"] / totals["cycles"] if totals["cycles"] else None,
            "l1d_refills_per_1000_instructions": 1000 * totals["l1d_refills"] / totals["instructions"] if totals["instructions"] else None,
            "branch_misses_per_1000_instructions": 1000 * totals["branch_misses"] / totals["instructions"] if totals["instructions"] else None,
        }
    return {"event_semantics": "ARM PMUv3 generic hardware events; cache references/misses map to L1D access/refill",
            "samples_per_cpu": SECONDS + 1, "phases": phases}
