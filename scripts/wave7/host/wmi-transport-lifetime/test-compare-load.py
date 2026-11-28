#!/usr/bin/env python3
"""Check that the comparator rejects any change in matched conditions."""
import copy
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location('compare', Path(__file__).with_name('compare-load.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

phase = dict(directions={'uplink': {'mbps': 100}}, latency={k: {'rtt_ms': {'mean': 5}} for k in ('v4', 'v6')})
a = dict(identity={'kernel': '7.4', 'firmware': 'A', 'stack': {'mt76': 'x'},
                   'geometry': ['20MHz', '80MHz'], 'affinity_uplink': {1: '0'},
                   'diagnostic_profiles': [], 'link_stats': False},
         phases=dict.fromkeys(m.load.MODES, phase))
b = copy.deepcopy(a)
b['phases']['uplink']['directions']['uplink']['mbps'] = 125
r = m.compare(a, b)
assert r['changes']['uplink']['goodput_pct']['uplink'] == 25
for key in a['identity']:
    bad = copy.deepcopy(b)
    del bad['identity'][key]
    try:
        m.compare(a, bad)
    except ValueError as e:
        assert key in str(e)
    else:
        raise AssertionError(f'missing {key} accepted')
print('COMPARE_LOAD_SELFTEST_PASS')
