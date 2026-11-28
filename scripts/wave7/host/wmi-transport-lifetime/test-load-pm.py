#!/usr/bin/env python3
"""Explicit PM profiles must be selected, retained and restored at all edges."""
import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location('compare',Path(__file__).with_name('compare-load.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
p=m.iperf
def pm(profile,edge=False):
    runtime,deep=p.PM_POLICIES[profile]
    return f'time=2026-11-28T06:00:00+01:00\nruntime-pm={runtime}\ndeep-sleep={deep}\nidle-timeout=83\n' + ('Power save: off\n' if edge else '')
def evidence(profile):
    names=['associated','hold-after','post']+[f'{mode}-{side}' for mode in p.MODES for side in ('before','after')]
    return {'pm-original.txt':pm('normal'),'pm-restored.txt':pm('normal'),
            'pm-selected.txt':pm(profile),'pm-load-profile.txt':profile+'\n',
            **{f'pm-load-{n}.txt':pm(profile,True) for n in names}}
def rejects(fn):
    try: fn()
    except ValueError: return
    raise AssertionError('unqualified PM evidence accepted')
assert p.load_pm_profile({'pm-selected.txt':pm('normal')}) is None
for profile in p.PM_POLICIES:
    data=evidence(profile)
    assert p.load_pm_profile(data)==profile
    for name in data:
        bad=data.copy(); del bad[name]
        rejects(lambda:p.load_pm_profile(bad))
    for name in ('pm-load-associated.txt','pm-load-uplink-before.txt','pm-load-post.txt'):
        bad=data.copy();bad[name]=bad[name].replace('Power save: off','Power save: on')
        rejects(lambda:p.load_pm_profile(bad))
        bad=data.copy();bad[name]+='runtime-pm=0\n'
        rejects(lambda:p.load_pm_profile(bad))
        bad=data.copy();bad[name]=bad[name].replace('idle-timeout=83','idle-timeout=84')
        rejects(lambda:p.load_pm_profile(bad))
    bad=data.copy();bad['pm-restored.txt']=pm('both-off')
    rejects(lambda:p.load_pm_profile(bad))
def run(profile):
    phase=dict(directions={'uplink':{'mbps':100}},latency={k:{'rtt_ms':None} for k in ('v4','v6')})
    return dict(boot='a',image_sha256='b',identity=dict(pm=p.pm_values(pm(profile)),pm_control_profile=profile,geometry=36),
                phases=dict.fromkeys(p.MODES,phase))
a,b=run('normal'),run('deep-sleep-off')
assert m.compare(a,b,compare_pm=True)['matched_except_pm']
assert not m.compare(a,b,compare_pm=True)['matched']
rejects(lambda:m.compare(a,b))
for key in ('boot','image_sha256'):
    bad=b.copy();bad[key]='c';rejects(lambda:m.compare(a,bad,compare_pm=True))
bad=run('both-off');bad['identity']['geometry']=40
rejects(lambda:m.compare(a,bad,compare_pm=True))
print('LOAD_PM_EVIDENCE_PASS')
