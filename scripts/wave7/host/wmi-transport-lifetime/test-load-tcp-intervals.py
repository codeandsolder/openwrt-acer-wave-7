#!/usr/bin/env python3
"""Exercise interval direction, identity, coverage, and zero progress."""
import copy
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location('tcp', Path(__file__).with_name('load-tcp-intervals.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def fixture(endpoint, direction, bidir):
    sender = (endpoint == 'asus') == (direction == 'downlink')
    result = {'start': {'connected': [
        {'socket': n, 'local_port': n+40000, 'remote_port': n+40000}
        for n in range(4*(1+bidir))], 'test_start': {'bidir': bidir}}, 'intervals': []}
    for sec in range(-2, 15):
        interval = {'streams': []}
        for reverse in range(1+bidir):
            own_sender = sender if reverse == (direction == 'uplink' and bidir) else not sender
            streams = []
            for n in range(4):
                size = 0 if sec == 4 else 10000
                s = dict(socket=4*reverse+n, start=sec if sec >=0 else sec+2,
                         end=(sec if sec>=0 else sec+2)+1, seconds=1,
                         bytes=size, bits_per_second=size*8, omitted=sec<0, sender=own_sender)
                if own_sender:
                    s.update(retransmits=1,rtt=3000,snd_cwnd=10000,snd_wnd=20000)
                streams.append(s)
            interval['streams'] += streams
            total = {k:v for k,v in streams[0].items() if k not in ('socket','rtt','snd_cwnd','snd_wnd')}
            total['bytes'] *= 4
            total['bits_per_second'] *= 4
            if own_sender:
                total['retransmits'] *= 4
            interval['sum' + ('_bidir_reverse' if reverse else '')] = total
        result['intervals'].append(interval)
    return result

for endpoint in ('asus','wyse'):
    for direction in ('uplink','downlink'):
        for bidir in (False,True):
            f=fixture(endpoint,direction,bidir)
            r=m.intervals(f,endpoint,direction)
            assert r['zero_progress_s']==1 and r['duration_s']==15 and len(r['intervals'])==15
            assert abs(r['mean_mbps'] - .32*14/15)<1e-10
f=fixture('asus','downlink',False)
for mutate in (
    lambda x:x['intervals'][4]['streams'].pop(),
    lambda x:x['intervals'][4]['streams'][0].update(socket=1),
    lambda x:x['intervals'][4]['sum'].update(bytes=999),
    lambda x:x['intervals'][4]['sum'].update(bits_per_second=999),
    lambda x:x['intervals'][4]['sum'].update(start=9),
    lambda x:x['intervals'][4]['sum'].update(omitted=True),
    lambda x:x['intervals'][4]['streams'][0].update(rtt=-1),
    lambda x:x['intervals'][4]['sum'].update(retransmits=999),
    lambda x:x['intervals'].__delitem__(slice(3,None)),
):
    bad=copy.deepcopy(f); mutate(bad)
    try: m.intervals(bad,'asus','downlink')
    except ValueError: pass
    else: raise AssertionError('malformed interval accepted')
print('TCP_INTERVAL_SELFTEST_PASS 8 valid 9 invalid')
