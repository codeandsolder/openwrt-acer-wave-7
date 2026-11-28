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

# Affinity-only comparison requires the exact attested spread, no other
# differences, and all four original IRQs restored on the same AP boot.
boot = '95840492-8857-4c4b-9a3f-a7cef0bff900'
groups = [(81, 3, '1'), (82, 4, '2'), (83, 5, '3'), (86, 8, '2')]
trace = ([f'IRQ_PROFILE_ORIGINAL irq={irq} group={group} configured=0-3 effective=0'
          for irq, group, _ in groups] +
         [f'IRQ_PROFILE_APPLIED irq={irq} cpu={cpu}' for irq, _, cpu in groups] +
         [f'IRQ_PROFILE_READY boot={boot} seconds=335'] +
         [f'IRQ_PROFILE_RESTORE irq={irq} configured=0-3 effective=0' for irq, _, _ in reversed(groups)] +
         ['IRQ_PROFILE_END rc=0'])
plan = m.irq_profile('\n'.join(trace), boot)
assert plan == {irq: cpu for irq, _, cpu in groups}
for bad in (trace[:-1], trace[:4] + [trace[4].replace('cpu=1','cpu=2')] + trace[5:],
            trace[:9] + [trace[9].replace('effective=0','effective=2')] + trace[10:],
            trace[:8] + [trace[8].replace(boot, 'other')] + trace[9:]):
    try:
        m.irq_profile('\n'.join(bad), boot)
    except ValueError:
        pass
    else:
        raise AssertionError('invalid IRQ trace accepted')
a = dict(boot=boot, image_sha256='image', irq_profile=None,
         identity={'diagnostic_profiles': ['load-series.txt'], 'firmware': 'A',
                   **{f'affinity_{mode}': {irq:'0' for irq in range(78,90)} for mode in m.load.MODES}},
         phases=dict.fromkeys(m.load.MODES, phase))
b = copy.deepcopy(a)
b['irq_profile'] = plan
b['identity']['diagnostic_profiles'].insert(0, 'irq-profile.txt')
for mode in m.load.MODES:
    b['identity'][f'affinity_{mode}'].update(plan)
assert m.compare(a,b,compare_irq=True)['matched_except_irq']
for key, value in [('boot','other'), ('image_sha256','other'), ('irq_profile',None)]:
    bad = copy.deepcopy(b)
    bad[key] = value
    try:
        m.compare(a,bad,compare_irq=True)
    except ValueError:
        pass
    else:
        raise AssertionError(f'IRQ contrast accepted {key} mismatch')
for key, value in [('firmware','B'), ('affinity_uplink', b['identity']['affinity_uplink'] | {78:'3'}),
                   ('diagnostic_profiles', ['irq-profile.txt','load-series.txt','other-profile.txt'])]:
    bad = copy.deepcopy(b)
    bad['identity'][key] = value
    try:
        m.compare(a,bad,compare_irq=True)
    except ValueError:
        pass
    else:
        raise AssertionError(f'IRQ contrast accepted {key} mismatch')
print('COMPARE_IRQ_SELFTEST_PASS')
