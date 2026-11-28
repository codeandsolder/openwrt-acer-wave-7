#!/usr/bin/env python3
"""Check all histogram rows, epoch, counter bounds and release-list accounting."""
import runpy
from pathlib import Path
h=runpy.run_path(str(Path(__file__).with_name('tx-attempt-stats.py')))

def snapshot(generation, updates=None):
    updates=updates or {}
    return [f'version=1 generation={generation} reasons=16 classes=5 counts=128',
            *(f'{reason} {position} ' + ' '.join(str(updates.get((reason,position,n),0))
                 for n in range(128)) for reason in range(16) for position in range(5))]
parse=h['parse_radio']
delta=h['compare']
a=parse(snapshot(1))
b=parse(snapshot(1,{(0,0,1):10,(0,2,2):7,(0,3,2):3,(0,4,0):2,(15,1,127):1}))
r=delta({'a':a},{'a':b})['a']
assert r['records']==23
assert r['records_by_position']=={'direct':10,'list_middle':1,'list_first':7,'list_last':3,'list_single':2}
assert r['reasons']['0']['list_first']['transmit_count']=={'2':7}
assert r['reasons']['15']['list_middle']['transmit_count']=={'127':1}
assert r['reasons']['0']['list_single']['transmit_count']=={'0':2}
assert not delta({'a':a},{'a':a})['a']['reasons']
def rejects(f):
    try:
        f()
    except ValueError:
        return
    raise AssertionError('invalid histogram accepted')
raw=snapshot(1)
for bad in (raw[:-1], [*raw[:-1],raw[1]], snapshot(0), snapshot(2**64),
            snapshot(1,{(0,0,0):2**64}), [*raw[:-1],raw[-1]+' 0'],
            [*raw[:-1],raw[-1].replace('15 4 ','16 4 ',1)],
            [*raw[:-1],raw[-1].replace('15 4 ','15 5 ',1)]):
    rejects(lambda:parse(bad))
rejects(lambda:delta({'a':b},{'a':a}))
rejects(lambda:delta({'a':a},{'a':parse(snapshot(2))}))
rejects(lambda:delta({'a':a},{'b':a}))
rejects(lambda:h['parse_sections']({'TX_ATTEMPT a':raw},{'a','b'}))
assert h['parse_sections']({'TX_ATTEMPT a':raw},{'a'})=={'a':a}
print('TX_ATTEMPT_STATS_PASS')
