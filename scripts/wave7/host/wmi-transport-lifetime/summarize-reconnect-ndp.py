#!/usr/bin/env python3
"""Locate an NDP provisioning failure using sealed, independent lab boundaries.

Descriptor size is only a candidate classification: the driver trace does not
contain the actual ICMPv6 type. Exact RS/RA types come from IP6 counters and
wired decoding, not from assumptions about TX-token return status.
"""
import argparse
import bisect
import json
from pathlib import Path
import re
import runpy


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('trial', type=Path)
    p.add_argument('--band', required=True, choices=('24', '5'))
    a = p.parse_args()
    helpers = runpy.run_path(str(Path(__file__).with_name('summarize-reconnect-datapath.py')))
    verify = helpers['verify_seal']
    require = helpers['require']
    prefix = f'band-{a.band}.'
    sealed = verify(a.trial)

    def read(name):
        name = prefix + name
        require(name in sealed, f'unsealed {name}')
        return (a.trial / name).read_text()

    client = read('client-control-trace.txt')
    ap = read('ap-control-trace.txt')
    cw = helpers['parse_trace'](client, 'client', 1)
    aw = helpers['parse_trace'](ap, 'ap', 1, True)
    require(len(cw) == len(aw), 'authorization window counts differ')
    tokens = helpers['token_windows'](client, cw)['windows']
    stats = read('wired-ndp-status.txt')
    require('Packets captured:' in stats, 'capture incomplete')
    interfaces = re.findall(r"Packets received/dropped on interface '([^']+)': (\d+)/(\d+) \(pcap:(\d+)/dumpcap:(\d+)/flushed:(\d+)/ps_ifdrop:(\d+)\)", stats)
    require({v[0] for v in interfaces} == {'enp4s0f4u2u4', 'enp4s0f4u2u2u4'} and len(interfaces) == 2 and all(not any(map(int, v[2:])) for v in interfaces), 'capture missing interface or dropped packets')
    require(not read('wired-ndp-decode.txt').strip(), 'wired decode warning')
    wire = [line.split('\t') for line in read('wired-ndp.txt').splitlines() if line.strip()]
    require(all(len(row) >= 8 for row in wire), 'malformed wired packet')
    text = read('client-ip6.txt')
    chunks = re.findall(r'^IP6_SAMPLE index=(\d+) epoch=(\d+\.\d+) monotonic=(\d+\.\d+)\n(.*?)^IP6_SAMPLE_END index=\1$', text, re.M | re.S)
    samples = [(float(mono), float(epoch), {key: int(n) for key, n in re.findall(r'^IP6_COUNTER (\S+) (\d+)$', body, re.M)}) for _, epoch, mono, body in chunks]
    end = re.search(r'^CLIENT_IP6_OBSERVER_END samples=(\d+)$', text, re.M)
    require(end and len(samples) == int(end[1]) and [int(c[0]) for c in chunks] == list(range(len(samples))), 'incomplete counter capture')
    monotonic = [s[0] for s in samples]
    require(monotonic == sorted(set(monotonic)), 'counter sample clock invalid')

    def bound(t):
        i = bisect.bisect_right(monotonic, t) - 1
        require(i >= 0 and i + 1 < len(samples), 'authorization outside counter capture')
        lo, hi = samples[i], samples[i+1]
        require(hi[0] - lo[0] < 2.5, 'counter observation gap')
        # Interpolate clocks; the raw sample clock has centisecond precision.
        epoch = lo[1] + (hi[1] - lo[1]) * (t - lo[0]) / (hi[0] - lo[0])
        return lo, hi, epoch

    result = []
    for i, (c, a_window, t) in enumerate(zip(cw, aw, tokens), 1):
        begin, finish = c['authorized_at'], c['observed_until']
        before, _, epoch0 = bound(begin)
        _, after, epoch1 = bound(finish)
        # Include the two bounding samples so the count is not presented as an
        # exact per-frame association without observing its transition.
        increments = {key: after[2].get(key, 0) - before[2].get(key, 0) for key in ('Icmp6OutType133', 'Icmp6InType134')}
        require(all(v >= 0 for v in increments.values()), 'ICMP counters reset')
        station = a_window['station']
        rows = [r for r in wire if epoch0 <= float(r[0]) <= epoch1 and ((r[5] == '133' and r[1] == station) or (r[5] == '134' and r[2] == station))]
        desc = [{k: d[k] for k in ('submitted_at', 'wcid', 'band', 'link', 'return') if k in d} for d in t['descriptors'] if d['protocol'] == '0x86dd' and d['length'] == '62']
        gro = sum(row['count'] for row in a_window['whole'] if row['fields'] == ['napi_gro_receive_entry', 'ap-mld0', 'IPv6', '48'])
        result.append(dict(association=i, station=station, client_monotonic=[begin, finish], wire_epoch=[epoch0, epoch1], counter_sample_monotonic=[before[0], after[0]], client_icmp6_increments=increments, rs_length_tx_candidates=desc, ap_rs_length_gro_candidates=gro, wired_rs=[r for r in rows if r[5] == '133'], wired_unicast_ra=[r for r in rows if r[5] == '134']))
    print(json.dumps({'band': a.band, 'association_windows': result}, indent=2))


if __name__ == '__main__':
    main()
