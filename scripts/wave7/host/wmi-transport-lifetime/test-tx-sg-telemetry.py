#!/usr/bin/env python3
"""Validate complete SG ring accounting and legacy non-SG captures."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('load_delta', Path(__file__).with_name('load-ap-delta.py'))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
base = [f'{name}: 0:10 1:20 2:30 3:40' for name in sorted(mod.TX_MATRIX)]
sg = [f'{name}: 0:1 1:2 2:3 3:4' for name in sorted(mod.SG_MATRIX)]
keys = ['/sys/kernel/debug/ath12k/ipq5332/device_dp_stats', '/sys/kernel/debug/ath12k/qcn6432/device_dp_stats']
for lines in (base, base + sg):
    parsed = mod.parse_tx_matrices(dict.fromkeys(keys, lines))
    assert parsed.keys() == {'ipq5332', 'qcn6432'}
    assert all(len(v) == len(lines) * 4 for v in parsed.values())
    for counters in parsed.values():
        assert counters['tx_enqueued/2'] == 30
        if lines == base + sg:
            assert counters['tx_sg_enqueued/2'] == 3
cases = [
    [base, base + sg],
    [base + sg[:-1], base + sg[:-1]],
    [base + sg + sg[:1], base + sg],
    [base + [sg[0].replace(' 3:4', '')] + sg[1:], base + sg],
    [base + [sg[0].replace(' 3:4', ' 4:4')] + sg[1:], base + sg],
    [base + [sg[0] + ' 0:9'] + sg[1:], base + sg],
]
for a, b in cases:
    try:
        mod.parse_tx_matrices(dict(zip(keys, (a, b))))
    except ValueError:
        pass
    else:
        raise AssertionError('accepted incomplete/ambiguous SG telemetry')
print(f'TX_SG_TELEMETRY_PASS valid=2 rejected={len(cases)}')
