#!/usr/bin/env python3
"""Exercise rate distributions with malformed replies and reset-witness gates."""
import copy
from pathlib import Path
import runpy

h = runpy.run_path(str(Path(__file__).with_name('htt-rate-stats.py')))
devices = {'ahb-c000000.wifi/mac0':0, 'ahb-soc@0:wifi/mac0':1}


def hist(name, shape, value):
    first, count = shape
    return name + ' = ' + ', '.join(f'{i}:{value+i}' for i in range(first, first+count))


def reply(dev, mac, t, value, optional):
    body = [h['HEADER'], f'mac_id = {mac}', 'ack_rssi = 52',
            *(f'{k} = {value}' for k in sorted(h['SCALARS'])),
            *(hist(k, s, value) for k,s in h['ARRAYS'].items()), '']
    if optional:
        body += [*(f'{k} = {value}' for k in sorted(h['PER_SCALARS'])), '',
                 h['PER_HEADER'], *(hist(k,s,value) for k,s in h['PER_ARRAYS'].items()), '']
    # Unrelated vendor TLV with its own mac_id is not part of tag 34.
    body += ['HTT_TX_PDEV_RATE_STATS_BE_OFDMA_TLV:', f'mac_id = {mac}', '']
    return [f'HTT_RATE_BEGIN {dev} 9 {t}.10', *body,
            f'HTT_RATE_END {dev} 9 {t}.11 rc=0']


def snapshot(t, value, optional=True):
    return sum((reply(dev, mac, t, value, optional) for dev, mac in devices.items()), [])


witness = dict(qualified=True, radios={r:dict(mac_id=m) for r,m in devices.items()})
tb = dict(radios={r:dict(end_ms=100090) for r in devices})
ta = dict(radios={r:dict(start_ms=118120) for r in devices})
parse = lambda s: h['describe_snapshot'](s, witness)
compare = lambda a,b: h['compare'](a,b,tb,ta,witness)
for optional in (False, True):
    a,b = parse(snapshot(100,50,optional)), parse(snapshot(118,100,optional))
    assert a['qualified'] and b['qualified']
    r=compare(a,b)
    assert r['qualified']
    for v in r['radios'].values():
        assert v['histogram_delta']['tx_nss'] == [50]*8
        assert v['fraction_pct']['tx_bw'] == [20]*5
        assert v['wall_ms_range']==[17990,18010]
        assert ('per_histogram_count' in v['histogram_delta']) == optional
    assert not compare(b,a)['qualified']
    assert not compare(a,parse(snapshot(118,49,optional)))['qualified']
    assert compare(a,parse(snapshot(118,50,optional)))['radios'][next(iter(devices))]['fraction_pct']['tx_bw'] is None
    changed=copy.deepcopy(b)
    changed['radios'][next(iter(devices))]['histograms']['tx_bw'][1]=0
    assert not compare(a,changed)['qualified']
    assert not h['compare'](a,b,tb,ta,dict(qualified=False))['qualified']
    assert not h['compare'](a,b,dict(radios={r:dict(end_ms=100111) for r in devices}),ta,witness)['qualified']
    assert not h['compare'](a,b,tb,dict(radios={r:dict(start_ms=118109) for r in devices}),witness)['qualified']
    # ACK RSSI may decrease; it is not differenced as a counter.
    gauge = parse([line.replace('ack_rssi = 52','ack_rssi = 3') for line in snapshot(118,100,optional)])
    assert compare(a,gauge)['qualified']
raw=snapshot(100,50)
for bad in (raw[:-1], raw+raw, raw[1:],
            [x.replace('mac_id = 1','mac_id = 0') for x in raw],
            [x.replace('rc=0','rc=1') for x in raw],
            [x.replace('100.11','103.00') for x in raw],
            [x.replace('100.11','100.09') for x in raw],
            [x.replace('1:51','0:51') for x in raw],
            [x.replace('1:51','1:4294967296') for x in raw],
            [x for x in raw if not x.startswith('tx_bw =')],
            [x for x in raw if not x.startswith('per_histogram_count =')],
            [x.replace('PER_HISTOGRAM_STATS','MISSING_HEADER') for x in raw]):
    assert not parse(bad)['qualified'], bad[:4]
assert not h['describe_snapshot']([],dict(qualified=True,radios={}))['qualified']
assert not h['describe_snapshot'](raw,dict(qualified=False))['qualified']
assert not compare(parse(snapshot(100,50,False)),parse(snapshot(118,100,True)))['qualified']
print('HTT_RATE_STATS_PASS')
