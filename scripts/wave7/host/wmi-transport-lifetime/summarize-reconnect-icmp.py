#!/usr/bin/env python3
"""Localize IPv4 echo losses at independently sealed client/AP boundaries.

Match an echo flow to the actual ping receiver output before examining each
sequence. No cross-host realtime ordering or RF delivery is inferred. A
missing boundary is a missing witness, not proof of an over-air drop.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import runpy

from packet_boundary import clock_epoch, parse_observer, require

TARGETS = ('192.168.76.1', '192.168.76.2')
STAGES = (('client', 'tx', 8), ('ap', 'rx', 8),
          ('ap', 'tx', 0), ('client', 'rx', 0))
HOLDS = (('short-hold-1.txt', 'short-hold-2.txt'),
         ('reconnect-hold-ap.txt', 'reconnect-hold-asus.txt'),
         ('reconnect-hold-2-ap.txt', 'reconnect-hold-2-asus.txt'))


def decode_echo4(fields):
    require(len(fields) == 5 and all(v.isdecimal() for v in fields), 'invalid ICMP4 fields')
    kind, identifier, seq, length, ip_id = map(int, fields)
    require(kind in (0, 8) and all(0 <= v <= 65535 for v in (identifier, seq, ip_id))
            and 28 <= length <= 65535, 'invalid ICMP4 header')
    return dict(kind=kind, identifier=identifier, seq=seq, length=length, ip_id=ip_id)


def local_window(local, window):
    rows, clocks, downs = local
    start, stop = window['authorized_at'], window['observed_until']
    clipped = stop > clocks[-1][0]
    require(not clipped or window['right_censored'], 'closed association outside observer coverage')
    stop = min(stop, clocks[-1][0])
    require(start < stop, 'empty observer window')
    lo, hi = clock_epoch(clocks, start), clock_epoch(clocks, stop)
    return ([r for r in rows if lo <= r['epoch'] < hi], [lo, hi],
            [t for t in downs if start <= t < stop], clipped or window['right_censored'])


def ping_log(text, target, expected):
    footer = re.findall(r'^(\d+) packets transmitted, (\d+) received', text, re.M)
    require(len(footer) == 1, 'missing/duplicate ping summary')
    sent, received = map(int, footer[0])
    require(sent == expected and 0 <= received <= sent, 'incomplete ping hold')
    replies = defaultdict(list)
    for epoch, seq in re.findall(rf'^\[([0-9.]+)\] \d+ bytes from {re.escape(target)}: icmp_seq=(\d+)\b', text, re.M):
        seq = int(seq)
        require(1 <= seq <= sent, 'out-of-range ping sequence')
        replies[seq].append(float(epoch))
    require(len(replies) == received, 'ping sequence/footer disagreement')
    return replies


def flow(row, target):
    src, dst = row['ipv4_src'], row['ipv4_dst']
    if row['kind'] == 8 and dst == target:
        return src, row['identifier']
    if row['kind'] == 0 and src == target:
        return dst, row['identifier']
    return None


def select_flow(client, replies, target, count):
    groups = defaultdict(list)
    for row in client:
        key = flow(row, target)
        if key is not None:
            groups[key].append(row)
    candidates = []
    for key, rows in groups.items():
        if any(not 1 <= r['seq'] <= count for r in rows):
            continue
        rx = defaultdict(list)
        tx = set()
        for r in rows:
            if r['direction'] == 'rx' and r['kind'] == 0:
                rx[r['seq']].append(r['epoch'])
            elif r['direction'] == 'tx' and r['kind'] == 8:
                tx.add(r['seq'])
        if replies:
            # Same-host packet timestamp precedes ping output. Allow a small
            # clock/format margin and refuse uncertain process identity.
            if all(any(-0.005 <= logged - captured <= 1.0
                       for captured in rx[seq] for logged in times)
                   for seq, times in replies.items()):
                candidates.append(key)
        elif tx == set(range(1, count + 1)):
            # A fully unanswered hold can only be identified if every
            # request was witnessed and the flow is unique.
            candidates.append(key)
    return candidates


def classify(stages, received, coverage):
    sizes = [len(stage) for stage in stages]
    if any(n > 1 for n in sizes):
        return 'ambiguous_repeated_boundary'
    for left, right in ((0, 1), (2, 3)):
        if stages[left] and stages[right]:
            a, b = stages[left][0], stages[right][0]
            if (a['length'], a['ip_id']) != (b['length'], b['ip_id']):
                return 'packet_identity_disagreement'
    if received and not sizes[3]:
        return 'ping_reply_without_boundary'
    if all(sizes):
        return 'received' if received else 'client_boundary_to_ping_gap'
    if not coverage:
        return 'capture_window_inconclusive'
    if any(not a and b for a, b in zip(sizes, sizes[1:])):
        return 'inconsistent_boundary_order'
    return ('client_request_not_witnessed', 'client_tx_to_ap_rx_gap',
            'ap_rx_to_ap_tx_gap', 'ap_tx_to_client_rx_gap')[sizes.index(0)]


def summarize_hold(client, ap, target, count, text, coverage):
    replies = ping_log(text, target, count)
    candidates = select_flow(client, replies, target, count)
    report = dict(target=target, sent=count, received=len(replies),
                  missing_sequences=sorted(set(range(1, count+1)) - replies.keys()),
                  duplicate_replies=sum(len(times)-1 for times in replies.values()),
                  coverage=coverage, flow_candidates=[dict(source=s, identifier=i) for s,i in candidates])
    if len(candidates) != 1:
        return dict(report, status='unresolved_flow_identity')
    key, = candidates
    by_stage = defaultdict(list)
    for side, rows in (('client', client), ('ap', ap)):
        for row in rows:
            if flow(row, target) == key:
                by_stage[(row['seq'], side, row['direction'], row['kind'])].append(row)
    results = []
    for seq in range(1, count + 1):
        stages = [by_stage[(seq, *stage)] for stage in STAGES]
        state = classify(stages, seq in replies, coverage)
        row = dict(seq=seq, ping_received=seq in replies, status=state,
                   stage_counts=[len(stage) for stage in stages])
        if state != 'received':
            row['boundaries'] = [stage for stage in stages]
        results.append(row)
    return dict(report, status='identified', counts=dict(Counter(r['status'] for r in results)),
                stage_order=[f'{side}_{direction}_{"request" if kind == 8 else "reply"}'
                             for side,direction,kind in STAGES], sequences=results)


def selftest():
    def packet(kind, seq, direction, time, identifier=55, ip_id=None):
        a, b = '192.168.76.140', TARGETS[0]
        return dict(kind=kind, seq=seq, direction=direction, epoch=time,
                    identifier=identifier, ipv4_src=a if kind==8 else b,
                    ipv4_dst=b if kind==8 else a, length=84,
                    ip_id=seq if ip_id is None else ip_id)
    client, ap = [], []
    for seq in range(1, 7):
        t = 100 + seq/10
        client.append(packet(8, seq, 'tx', t))
        if seq == 2:
            continue
        ap.append(packet(8, seq, 'rx', t+50))
        if seq == 3:
            continue
        ap.append(packet(0, seq, 'tx', t+50.01))
        if seq == 4:
            continue
        client.append(packet(0, seq, 'rx', t+0.02))
        if seq == 6:
            ap.append(packet(0, seq, 'tx', t+50.02))
    text = f'[100.121] 64 bytes from {TARGETS[0]}: icmp_seq=1 ttl=64 time=21 ms\n6 packets transmitted, 1 received, 83% packet loss'
    report = summarize_hold(client, ap, TARGETS[0], 6, text, True)
    assert report['counts'] == {'received':1, 'client_tx_to_ap_rx_gap':1,
                                'ap_rx_to_ap_tx_gap':1, 'ap_tx_to_client_rx_gap':1,
                                'client_boundary_to_ping_gap':1, 'ambiguous_repeated_boundary':1}, report
    assert summarize_hold(client, ap, TARGETS[0], 6, text, False)['counts']['capture_window_inconclusive'] == 3
    assert summarize_hold(client+[packet(0, 1, 'rx', 100.12, 56)], ap, TARGETS[0], 6, text, True)['status'] == 'unresolved_flow_identity'
    all_lost = '6 packets transmitted, 0 received, 100% packet loss'
    assert summarize_hold(client, ap, TARGETS[0], 6, all_lost, True)['status'] == 'identified'
    assert classify([[packet(8,1,'tx',1)], [packet(8,1,'rx',2,ip_id=999)], [], []], False, True) == 'packet_identity_disagreement'
    observer = '\n'.join(['ICMP4_OBSERVER_READY iface=wlp2s0 ifindex=4 duration=1',
        'ICMP4_CLOCK 10.000 100.000 10.000', 'ICMP4_PACKET 100.1 wlp2s0 tx 192.168.76.140 192.168.76.1 8 55 1 84 1',
        'ICMP4_CLOCK 11.000 101.000 11.000', 'ICMP4_OBSERVER_END iface=wlp2s0 seen=1 decoded=1 malformed=0 packets=1 drops=0'])
    local = parse_observer(observer,'wlp2s0','ICMP4',decode_echo4)
    assert local_window(local,dict(authorized_at=10.05, observed_until=10.9,right_censored=False))[0][0]['seq'] == 1
    for bad in (observer.replace('drops=0','drops=1'), observer.replace('8 55 1 84 1','3 55 1 84 1'),
                observer.replace('seen=1','seen=2'), observer.rsplit('\n',1)[0]):
        try:
            parse_observer(bad,'wlp2s0','ICMP4',decode_echo4)
        except ValueError:
            pass
        else:
            raise AssertionError('bad witness accepted')
    print('ICMP4_RECONNECT_SUMMARY_SELFTEST_PASS')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('trial', type=Path, nargs='?')
    p.add_argument('--band', choices=('24','5'))
    p.add_argument('--selftest', action='store_true')
    a = p.parse_args()
    if a.selftest:
        selftest()
        return
    if not a.trial or not a.band:
        p.error('trial and band required')
    here = Path(__file__).parent
    verifier = runpy.run_path(str(here/'verify-wbm-parent.py'))
    sealed = verifier['seal'](a.trial)
    trace = runpy.run_path(str(here/'summarize-reconnect-datapath.py'))
    load = runpy.run_path(str(here/'load-result.py'))
    prefix = f'band-{a.band}.'
    def read(name):
        name = prefix+name
        require(name in sealed, f'unsealed {name}')
        return (a.trial/name).read_text()
    tag = read('tag').strip()
    require(re.fullmatch(r'0498-\d{8}-\d{6}',tag) and prefix+'client.tar' in sealed,'unsealed client archive')
    archive = load['load_archive'](a.trial/(prefix+'client.tar'),tag)
    cw = trace['parse_trace'](read('client-control-trace.txt'),'client',1)
    aw = trace['parse_trace'](read('ap-control-trace.txt'),'ap',1,True)
    require(len(cw)==len(aw) and 1 <= len(cw) <= len(HOLDS),'unmatched association windows')
    local = {}
    for side,iface in (('client','wlp2s0'),('ap','ap-mld0')):
        require(not read(f'{side}-icmp4-boundary-error.txt').strip(),'observer error')
        local[side]=parse_observer(read(f'{side}-icmp4-boundary.txt'),iface,'ICMP4',decode_echo4)
    windows=[]
    for i,(c,w) in enumerate(zip(cw,aw)):
        cr,ce,cd,cc=local_window(local['client'],c)
        ar,ae,ad,ac=local_window(local['ap'],w)
        coverage=not(cd or ad or cc or ac)
        holds=[]
        for target,filename in zip(TARGETS,HOLDS[i]):
            if filename not in archive:
                holds.append(dict(target=target,status='hold_not_executed'))
            else:
                holds.append(summarize_hold(cr,ar,target,440,archive[filename],coverage))
        windows.append(dict(association=i+1,client_epoch=ce,ap_epoch=ae,
                            link_downs={'client':cd,'ap':ad},censored={'client':cc,'ap':ac},holds=holds))
    print(json.dumps(dict(band=a.band,observer_counts={s:len(v[0]) for s,v in local.items()},windows=windows),indent=2))


if __name__ == '__main__':
    main()
