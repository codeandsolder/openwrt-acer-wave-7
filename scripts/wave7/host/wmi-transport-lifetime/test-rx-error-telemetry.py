#!/usr/bin/env python3
"""Check all histogram dimensions, reserved codes and unknown metadata."""
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location('load', Path(__file__).with_name('load-ap-delta.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

header = 'version=1 sources=2 codes=32 links=7 tids=17'
raw = [header] + [f'{src} {code} {link}' + ' 0' * 17
                  for src in range(2) for code in range(32) for link in range(7)]
before = m.parse_rx_error_stats(raw)
new = raw[:]
i = 1 + (0 * 32 + 7) * 7 + 1
new[i] = '0 7 1 4' + ' 0' * 15 + ' 3'
j = 1 + (1 * 32 + 31) * 7 + 6
new[j] = '1 31 6' + ' 0' * 16 + ' 2'
after = m.parse_rx_error_stats(new)
d = m.rx_error_delta({'qcn': before}, {'qcn': after})['qcn']
assert d['REO/7'] == {'total': 7, 'links': {'1': {'total': 7, 'descriptor_tids': {'0': 4, 'unknown': 3}}}}
assert d['RXDMA/31'] == {'total': 2, 'links': {'unknown': {'total': 2, 'descriptor_tids': {'unknown': 2}}}}
for bad in (raw[:-1], raw + raw[1:2], raw[:1] + ['2' + raw[1][1:]] + raw[2:],
            raw[:1] + ['0 32 0' + ' 0'*17] + raw[2:], raw[:1] + ['0 0 7' + ' 0'*17] + raw[2:],
            raw[:1] + [raw[1] + ' 0'] + raw[2:], raw[:1] + [raw[1][:-1] + str(2**64)] + raw[2:],
            ['version=2 sources=2 codes=32 links=7 tids=17'] + raw[1:]):
    try:
        m.parse_rx_error_stats(bad)
    except ValueError:
        pass
    else:
        raise AssertionError('bad RX error histogram accepted')
for a, b in (({'qcn': after}, {'qcn': before}), ({'qcn': before}, {'ipq': after})):
    try:
        m.rx_error_delta(a, b)
    except ValueError:
        pass
    else:
        raise AssertionError('bad RX error delta accepted')
print('RX_ERROR_TELEMETRY_PASS valid=1 rejected=10')
