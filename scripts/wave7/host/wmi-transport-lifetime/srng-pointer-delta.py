#!/usr/bin/env python3
"""Compare physical SRNG pointers and logical TX counters on one AP boot."""
import argparse
import json
from pathlib import Path
import re

from importlib.util import module_from_spec, spec_from_file_location

spec = spec_from_file_location('tx_ring_delta', Path(__file__).with_name('tx-ring-delta.py'))
if spec is None or spec.loader is None:
    raise RuntimeError('missing TX counter analyzer')
tx = module_from_spec(spec)
spec.loader.exec_module(tx)
BOOT = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')
MAP = re.compile(r'map tcl=(\d+) wbm=(\d+) rbm=(\d+)')
HEADER = re.compile(r'rx_release=(\d+) rx_rbm=(\d+) rx_buffer_rbm=(\d+)')
RING = re.compile(r'(TCL|WBM|WBM_RX)(\d+) id=(\d+) hp=(\d+) tp=(\d+) sw=(\d+) shadow=(\d+) cached=(\d+) entry=(\d+) size=(\d+)')


def parse(text):
    lines = text.splitlines()
    if len(lines) < 3 or not BOOT.fullmatch(lines[0]):
        raise ValueError('missing boot identity')
    uptime = float(lines[1].split()[0])
    if not (header := HEADER.fullmatch(lines[2])):
        raise ValueError('missing RX release map')
    rx, rx_rbm, rx_buf = map(int, header.groups())
    mapping, rings = {}, {}
    for line in lines[3:]:
        if m := MAP.fullmatch(line):
            logical, physical, rbm = map(int, m.groups())
            if logical in mapping or physical == rx or physical in [v[0] for v in mapping.values()]:
                raise ValueError('overlapping release map')
            mapping[logical] = physical, rbm
        elif m := RING.fullmatch(line):
            name = m[1] + m[2]
            row = dict(zip(('id','hp','tp','sw','shadow','cached','entry','size'), map(int, m.groups()[2:])))
            if name in rings or any(r['id'] == row['id'] for r in rings.values()):
                raise ValueError('duplicate physical ring')
            entry, size = row['entry'], row['size']
            if not entry or not size or size % entry or any(row[k] >= size or row[k] % entry for k in ('hp','tp','sw','shadow','cached')):
                raise ValueError('invalid ring geometry or pointer')
            rings[name] = row
        else:
            raise ValueError(f'unknown SRNG line: {line}')
    if not mapping or set(mapping) != set(range(len(mapping))):
        raise ValueError('incomplete logical map')
    expected = {f'TCL{i}' for i in mapping} | {f'WBM{physical}' for physical, _ in mapping.values()} | {f'WBM_RX{rx}'}
    if set(rings) != expected or any(rings[f'WBM{physical}']['id'] != rings[f'WBM_RX{rx}']['id'] + physical - rx for physical, _ in mapping.values()):
        raise ValueError('incomplete or inconsistent physical map')
    return lines[0], uptime, (rx, rx_rbm, rx_buf), mapping, rings


def compare(before, after, counter_before, counter_after, device=tx.IPQ):
    boot, start, rx, mapping, a = parse(before)
    boot_end, end, rx_end, mapping_end, b = parse(after)
    counter = tx.compare(counter_before, counter_after, device)
    if boot != boot_end or boot != counter['boot'] or not start < end or rx != rx_end or mapping != mapping_end or set(a) != set(b):
        raise ValueError('incomparable SRNG snapshots')
    # The counter and ring snapshots are adjacent SSH calls; permit movement
    # between them, but never silently accept a different time interval.
    if abs(start - counter['start_s']) > 5 or abs(end - counter['end_s']) > 5:
        raise ValueError('counter and physical snapshots not contemporaneous')
    result = {}
    for name, old in a.items():
        new = b[name]
        if any(old[k] != new[k] for k in ('id','entry','size')):
            raise ValueError('ring geometry changed')
        entry, size = old['entry'], old['size']
        advance = {k: (new[k]-old[k]) % size // entry for k in ('hp','tp','sw','shadow','cached')}
        drained = new['hp'] == new['tp'] == new['sw'] == new['shadow']
        result[name] = dict(id=old['id'], entries=size//entry, advance=advance, drained=drained, before=old, after=new)
    correlation = {}
    for row in counter['rings']:
        logical = row['tcl']
        if logical not in mapping:
            raise ValueError('missing logical ring')
        physical, rbm = mapping[logical]
        tcl, wbm = result[f'TCL{logical}'], result[f'WBM{physical}']
        correlation[logical] = dict(physical=physical, rbm=rbm,
            queued=row['queued'], completed=row['completed'],
            tcl_produced_matches=tcl['advance']['hp'] == row['queued'] % tcl['entries'],
            wbm_consumed_matches=wbm['advance']['tp'] == row['completed'] % wbm['entries'],
            drained=tcl['drained'] and wbm['drained'])
    return dict(boot=boot, start_s=start, end_s=end, rx_release=rx[0], rx_rbm=rx[1], rx_buffer_rbm=rx[2], rings=result, correlation=correlation)


def selftest():
    boot = '96f67cfc-e011-49e1-aff7-1832e25fcf3e'
    def snapshot(time, tcl3, wbm3, wbm3_tp=None):
        rows = [boot, f'{time} 0', 'rx_release=5 rx_rbm=10 rx_buffer_rbm=10']
        for i in range(4):
            rows.append(f'map tcl={i} wbm={i} rbm={i+5}')
            for name, rid, size, ptr in ((f'TCL{i}',24+i,4096,tcl3 if i==3 else 0), (f'WBM{i}',128+i,131072,wbm3 if i==3 else 0)):
                tp = wbm3_tp if name=='WBM3' and wbm3_tp is not None else ptr
                sw = tp if name.startswith('WBM') else ptr
                shadow = ptr
                rows.append(f'{name} id={rid} hp={ptr} tp={tp} sw={sw} shadow={shadow} cached={shadow} entry=8 size={size}')
        rows.append('WBM_RX5 id=133 hp=0 tp=0 sw=0 shadow=0 cached=0 entry=8 size=8192')
        return '\n'.join(rows)+'\n'
    def counters(time, queued, completed, pending):
        return f'{boot}\n{time} 0\n{tx.DEVICE}\ntx_enqueued: 0:0 1:0 2:0 3:{queued}\ntx_completed: 0:0 1:0 2:0 3:{completed}\nradio0 tx_pending: {pending}\n'
    # Both physical ring pointers wrap during a six-descriptor interval.
    a,b = snapshot(1,4080,131056),snapshot(8,32,32)
    x,y = counters(1,100,100,0),counters(8,106,106,0)
    good = compare(a,b,x,y)['correlation'][3]
    assert good['drained'] and good['tcl_produced_matches'] and good['wbm_consumed_matches']
    bad = compare(a,snapshot(8,32,32,131056),x,counters(8,106,100,6))['correlation'][3]
    assert not bad['drained'] and bad['wbm_consumed_matches']
    for invalid in (b.replace(boot,'86f67cfc-e011-49e1-aff7-1832e25fcf3e'), b.replace('WBM3 id=131','WBM3 id=130'), b.replace('map tcl=3 wbm=3','map tcl=3 wbm=5'), b.replace('entry=8 size=4096','entry=0 size=4096')):
        try:
            compare(a,invalid,x,y)
        except ValueError:
            pass
        else:
            raise AssertionError('accepted invalid physical evidence')
    print('SRNG_POINTER_DELTA_SELFTEST_PASS')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--selftest', action='store_true')
    p.add_argument('--device', choices=(tx.IPQ,tx.QCN), default=tx.IPQ)
    p.add_argument('before', type=Path, nargs='?')
    p.add_argument('after', type=Path, nargs='?')
    p.add_argument('counter_before', type=Path, nargs='?')
    p.add_argument('counter_after', type=Path, nargs='?')
    a = p.parse_args()
    if a.selftest:
        selftest()
    elif all((a.before,a.after,a.counter_before,a.counter_after)):
        print(json.dumps(compare(*(v.read_text() for v in (a.before,a.after,a.counter_before,a.counter_after)), device=a.device), indent=2))
    else:
        p.error('provide ring and counter snapshot pairs or --selftest')

if __name__ == '__main__':
    main()
