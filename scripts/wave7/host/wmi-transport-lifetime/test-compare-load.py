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
assert r['matched'] and not r['mismatches']
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
    descriptive = m.compare(a, bad, describe_unmatched=True)
    assert not descriptive['matched'] and descriptive['mismatches'] == [key]
print('COMPARE_LOAD_SELFTEST_PASS')

info = """Interface ap-mld0
	MLD with links:
	 - link ID  0 link addr 70:5a:6f:5a:bb:16
	   channel 1 (2412 MHz), width: 20 MHz, center1: 2412 MHz
	   txpower 18.00 dBm
	 - link ID  1 link addr 4e:5a:6f:5a:bb:16
	   channel 36 (5180 MHz), width: 80 MHz, center1: 5210 MHz
	   txpower 18.00 dBm
	Radios: 0 1"""
g = m.geometry(info)
assert len(g) == 7
changed = info.replace('36 (5180', '40 (5200')
assert m.geometry(changed) != g
def survey(a,b):
    return ['GEOMETRY_BEFORE', *a.splitlines(), 'GEOMETRY_BEFORE_END rc=0',
            'SURVEY_BEGIN 1.00', 'malformed firmware data', 'SURVEY_END 1.01 rc=1',
            'GEOMETRY_AFTER', *b.splitlines(), 'GEOMETRY_AFTER_END rc=0']
assert m.survey_geometry(survey(info, info)) == g
for bad in (survey(info, changed), survey(info,info)[:-1],
            survey(info.replace('link ID  1','link ID  0'),info)):
    try:
        m.survey_geometry(bad)
    except ValueError:
        pass
    else:
        raise AssertionError('invalid edge geometry accepted')
print('COMPARE_GEOMETRY_SELFTEST_PASS')
