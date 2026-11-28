#!/usr/bin/env python3
"""Verify the exact idle rate probe gate without issuing radio requests."""
from pathlib import Path
import runpy

root=Path(__file__).parent
probe=runpy.run_path(str(root/'verify-htt-rate-probe.py'))
tx=runpy.run_path(str(root/'test-htt-tx-stats.py'))
rate=runpy.run_path(str(root/'test-htt-rate-stats.py'))
boot='d3f12451-51ba-4103-8bcc-5b7ab074ed96'
devs={'ahb-c000000.wifi':0,'ahb-soc@0:wifi':1}

def witness(start, value, **kw):
    return sum((tx['reply'](d,f'{start}.00',f'{start}.01',value,mac_id=m,**kw) for d,m in devs.items()),[])

raw=[boot,'==== HTT_TX_BEFORE',*witness(100,50),'==== HTT_RATE',
     *rate['snapshot'](101,50),'==== HTT_TX_AFTER',*witness(102,51),'==== END',boot]
assert probe['verify'](raw,boot)['qualified']
for bad in (raw[:-1], raw[:1]+raw, [x.replace('101.10','103.10').replace('101.11','103.11') for x in raw],
            [x.replace('HTT_RATE_END','HTT_RATE_BAD') for x in raw],
            [x for x in raw if x != '==== HTT_TX_AFTER']):
    try:
        probe['verify'](bad,boot)
    except ValueError:
        pass
    else:
        raise AssertionError('invalid idle probe accepted')
print('HTT_RATE_PROBE_PASS')
