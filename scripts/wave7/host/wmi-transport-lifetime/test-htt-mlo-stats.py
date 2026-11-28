#!/usr/bin/env python3
"""Exact MLO schema, radio coverage and reset witness tests."""
import runpy
from pathlib import Path
h=runpy.run_path(str(Path(__file__).with_name('htt-mlo-stats.py')))
devices={'a/mac0','b/mac0'}

def reply(dev, kind, start, end, value):
    if kind == '63':
        body=['HTT_STATS_MLO_SCHED_STATS:',*(f'{k} = {value}' for k in sorted(h['SCHED']))]
    else:
        body=['HTT_STATS_MLO_IPC_STATS:']
        for link in range(6):
            body += [f'src_link: {link}', *(f'mlo_ipc_ring_full_cnt[{ring}]: {value}' for ring in range(7))]
    return [f'HTT_MLO_BEGIN {dev} {kind} {start}',*body,f'HTT_MLO_END {dev} {kind} {end} rc=0']

def snapshot(t,v):
    return sum((reply(r,k,f'{t}.0{i*2}',f'{t}.0{i*2+1}',v)
                for i,(r,k) in enumerate((r,k) for r in sorted(devices) for k in ('63','64'))),[])
parse=lambda s:h['describe_snapshot'](s,devices)
a,b=parse(snapshot(100,50)),parse(snapshot(118,100))
tx=dict(qualified=True,radios=dict.fromkeys(devices,{}))
tb=dict(radios=dict.fromkeys(devices,dict(end_ms=99990)))
ta=dict(radios=dict.fromkeys(devices,dict(start_ms=118100)))
compare=lambda a,b,t:h['compare'](a,b,tb,ta,t)
assert a['qualified'] and b['qualified']
r=compare(a,b,tx)
assert r['qualified'] and r['radios']['a/mac0']['64']['delta']['link5/ring6']==50
assert r['radios']['b/mac0']['63']['delta']['num_pref_link_timeout']==50
assert not compare(a,b,dict(qualified=False))['qualified']
assert not compare(b,a,tx)['qualified']
assert not compare(a,parse(snapshot(118,49)),tx)['qualified']
assert not h['compare'](a,b,tb,dict(radios=dict.fromkeys(devices,dict(start_ms=118010))),tx)['qualified']
raw=snapshot(100,50)
for bad in (raw[:-1], raw+raw, raw[1:],
            [x.replace('src_link: 5','src_link: 4') for x in raw],
            [x.replace('ring_full_cnt[6]','ring_full_cnt[7]') for x in raw],
            [x.replace('rc=0','rc=1') for x in raw],
            [x.replace(' = 50',' = 4294967296') for x in raw],
            [x for x in raw if not x.startswith('num_pref_link_timeout =')]):
    assert not parse(bad)['qualified']
assert not h['describe_snapshot']([],[])['qualified']
print('HTT_MLO_STATS_PASS')
