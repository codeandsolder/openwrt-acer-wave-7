#!/usr/bin/env python3
"""Join sealed wired DHCP metadata with the client authorization clock.

Absence on the observed wired interfaces is not evidence that a client never
transmitted a frame over the air. Preserve retransmissions and copies on each
interface; do not collapse them into synthetic over-the-air events.
"""
import argparse
import bisect
import ipaddress
import json
from pathlib import Path
import re
import runpy

INTERFACES = {'enp4s0f4u2u4', 'enp4s0f4u2u2u4'}
TYPES = {1: 'discover', 2: 'offer', 3: 'request', 4: 'decline', 5: 'ack',
         6: 'nak', 7: 'release', 8: 'inform'}
MAC = re.compile(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def parse_packets(text):
    packets = []
    for line in text.splitlines():
        fields = line.split('\t')
        require(len(fields) == 13, 'invalid DHCP field count')
        time, src, dst, iface, ips, ipd, udp_src, udp_dst, op, xid, chaddr, yiaddr, typ = fields
        require(iface in INTERFACES and re.fullmatch(r'\d+\.\d+', time), 'invalid packet boundary')
        require(MAC.fullmatch(src) and MAC.fullmatch(dst), 'invalid link address')
        require((udp_src, udp_dst) in {('67', '68'), ('68', '67'), ('67', '67')}, 'invalid DHCP ports')
        for ip in (ips, ipd, yiaddr):
            if ip:
                ipaddress.IPv4Address(ip)
        require(not xid or re.fullmatch(r'0x[0-9a-f]{8}', xid), 'invalid xid')
        # Wireshark uses dhcp.hw.mac_addr for the fixed BOOTP chaddr and
        # subsequently decoded Ethernet client identifiers. The first
        # occurrence is the header address; retain all occurrences for audit.
        addresses = chaddr.split(',') if chaddr else []
        require(all(MAC.fullmatch(address) for address in addresses), 'invalid client address')
        require(not op or op in {'1', '2'}, 'invalid BOOTP operation')
        require(not typ or typ.isdecimal() and 0 <= int(typ) <= 255, 'invalid DHCP type')
        packets.append(dict(epoch=float(time), interface=iface, eth_src=src, eth_dst=dst,
                            ipv4_src=ips, ipv4_dst=ipd, udp_src=int(udp_src), udp_dst=int(udp_dst),
                            op=int(op) if op else None, xid=xid or None, client=addresses[0] if addresses else None,
                            client_address_fields=addresses,
                            offered_ipv4=yiaddr or None, message=TYPES.get(int(typ), f'type_{typ}') if typ else 'undecoded'))
    return sorted(packets, key=lambda packet: packet['epoch'])


def group(packets, begin, end, station):
    by_xid = {}
    for row in packets:
        if begin <= row['epoch'] < end and row['client'] == station:
            by_xid.setdefault(row['xid'], []).append(row)
    return [dict(xid=xid, packets=rows, messages={kind: {iface: sum(r['message'] == kind and r['interface'] == iface for r in rows) for iface in sorted(INTERFACES)} for kind in sorted({r['message'] for r in rows})}) for xid, rows in by_xid.items()]


def parse_boundary_observer(text, iface):
    """Validate metadata and independent realtime/mono clock anchors."""
    lines = text.splitlines()
    require(len(lines) >= 4, 'incomplete boundary observer')
    ready = re.fullmatch(r'DHCP_OBSERVER_READY iface=(\S+) ifindex=(\d+) duration=(\d+)', lines[0])
    end = re.fullmatch(r'DHCP_OBSERVER_END iface=(\S+) seen=(\d+) decoded=(\d+) malformed=(\d+) packets=(\d+) drops=(\d+)', lines[-1])
    require(ready and end and ready[1] == end[1] == iface and int(ready[2]) > 0,
            'boundary observer identity or markers')
    rows, clocks, link_downs = [], [], []
    for line in lines[1:-1]:
        fields = line.split()
        require(fields, 'empty boundary observer record')
        if fields[0] == 'DHCP_LINK_DOWN':
            require(len(fields) == 3 and re.fullmatch(r'\d+\.\d+', fields[1]) and
                    fields[2] == f'ifindex={ready[2]}', 'invalid link-down witness')
            link_downs.append(float(fields[1]))
            continue
        if fields[0] == 'DHCP_CLOCK':
            require(len(fields) == 4 and all(re.fullmatch(r'\d+\.\d+', f) for f in fields[1:]),
                    'invalid boundary clock')
            before, epoch, after = map(float, fields[1:])
            require(0 <= after - before < 0.05, 'uncertain boundary clock anchor')
            clocks.append(((before + after) / 2, epoch))
            continue
        require(len(fields) == 13 and fields[0] == 'DHCP_PACKET',
                'invalid boundary packet record')
        _, epoch, name, direction, ips, ipd, src, dst, op, xid, client, offered, kind = fields
        require(name == iface and direction in {'tx', 'rx'} and re.fullmatch(r'\d+\.\d+', epoch),
                'invalid boundary packet interface or direction')
        require((src, dst) in {('67', '68'), ('68', '67'), ('67', '67')} and op in {'1', '2'},
                'invalid boundary packet protocol')
        require(re.fullmatch(r'0x[0-9a-f]{8}', xid) and MAC.fullmatch(client),
                'invalid boundary packet identity')
        require(kind.isdecimal() and 0 <= int(kind) <= 255, 'invalid boundary DHCP type')
        for addr in (ips, ipd, offered):
            ipaddress.IPv4Address(addr)
        rows.append(dict(epoch=float(epoch), interface=iface, direction=direction,
                         ipv4_src=ips, ipv4_dst=ipd, udp_src=int(src), udp_dst=int(dst),
                         op=int(op), xid=xid, client=client, offered_ipv4=offered,
                         message=TYPES.get(int(kind), f'type_{kind}') if int(kind) else 'undecoded'))
    seen, decoded, malformed, packets, drops = map(int, end.groups()[1:])
    require(seen == decoded == packets == len(rows) and malformed == drops == 0,
            'boundary observer packet loss or undecodable packet')
    require(len(clocks) >= 2 and clocks[-1][0] - clocks[0][0] >= int(ready[3]) - 0.1,
            'short boundary clock capture')
    for (m0, e0), (m1, e1) in zip(clocks, clocks[1:]):
        require(0 < m1 - m0 < 2.5 and abs((e1 - e0) - (m1 - m0)) < 0.1,
                'boundary clock gap or realtime step')
    require(link_downs == sorted(link_downs) and all(clocks[0][0] <= t <= clocks[-1][0] for t in link_downs),
            'link-down witness outside capture')
    return sorted(rows, key=lambda row: row['epoch']), clocks, link_downs


def clock_epoch(clocks, timestamp):
    mono = [m for m, _ in clocks]
    i = bisect.bisect_right(mono, timestamp) - 1
    require(i >= 0 and i + 1 < len(clocks), 'authorization outside clock capture')
    lo, hi = clocks[i:i + 2]
    require(0 < hi[0] - lo[0] < 2.5, 'clock sample gap')
    return lo[1] + (hi[1] - lo[1]) * (timestamp - lo[0]) / (hi[0] - lo[0])



def clock_probe(text):
    """Bound remote-local realtime offset using three SSH round trips."""
    rows = []
    for line in text.splitlines():
        fields = line.split()
        require(len(fields) == 3 and all(re.fullmatch(r'\d+\.\d+', f) for f in fields),
                'invalid client/wire clock probe')
        before, client, after = map(float, fields)
        require(0 <= after - before < 1 and (not rows or before >= rows[-1][2]),
                'invalid client/wire clock round trip')
        rows.append((before, client, after))
    require(len(rows) == 3, 'incomplete client/wire clock probe')
    low = max(client - after for before, client, after in rows)
    high = min(client - before for before, client, after in rows)
    require(low <= high and high - low < 0.25, 'inconsistent client/wire clock bound')
    return ((rows[0][1] + rows[-1][1]) / 2, (low + high) / 2, (high - low) / 2)


def wire_clock(before, after, client_epoch):
    t0, offset0, error0 = before
    t1, offset1, error1 = after
    require(t0 <= client_epoch <= t1 and t1 > t0 and abs(offset1 - offset0) < 0.25,
            'client/wire clock outside measured interval or stepped')
    ratio = (client_epoch - t0) / (t1 - t0)
    offset = offset0 + ratio * (offset1 - offset0)
    # Endpoint bounds plus the observed offset change, conservatively
    # accounting for an unknown nonlinear slew during the bounded trial.
    return client_epoch - offset, max(error0, error1) + abs(offset1 - offset0)


def wire_group_with_uncertainty(packets, start, stop, station):
    begin, begin_error = start
    end, end_error = stop
    require(begin + begin_error < end - end_error, 'uncertain wire authorization window')
    ambiguous = [p for p in packets if p['client'] == station and
                 (begin - begin_error <= p['epoch'] < begin + begin_error or
                  end - end_error <= p['epoch'] < end + end_error)]
    return group(packets, begin + begin_error, end - end_error, station), ambiguous

def boundary_window(packets, clocks, window, station):
    begin = clock_epoch(clocks, window['authorized_at'])
    end = clock_epoch(clocks, window['observed_until'])
    require(begin < end, 'inverted local authorization clock')
    return [begin, end], [p for p in packets
                         if begin <= p['epoch'] < end and p['client'] == station]


def join_boundaries(wired, client, ap):
    """Keep local witnesses separate; cross-host epoch is not a causal clock."""
    by_xid = {t['xid']: dict(t, client_packets=[], ap_packets=[]) for t in wired}
    for side, rows in (('client', client), ('ap', ap)):
        for row in rows:
            tx = by_xid.setdefault(row['xid'], dict(xid=row['xid'], packets=[],
                                                   messages={}, client_packets=[], ap_packets=[]))
            tx[f'{side}_packets'].append(row)
    for tx in by_xid.values():
        kinds = set(tx['messages']) | {p['message'] for side in ('client', 'ap')
                                      for p in tx[f'{side}_packets']}
        tx['boundary_counts'] = {
            kind: {f'{side}_{direction}': sum(p['message'] == kind and p['direction'] == direction
                                           for p in tx[f'{side}_packets'])
                   for side in ('client', 'ap') for direction in ('tx', 'rx')}
            for kind in sorted(kinds)}
    return list(by_xid.values())


def selftest():
    station = '02:01:02:03:04:05'
    row = lambda t, i, xid, typ, c=station: '\t'.join([str(t), station, 'ff:ff:ff:ff:ff:ff', i, '0.0.0.0', '255.255.255.255', '68', '67', '1', xid, c, '0.0.0.0', str(typ)])
    a,b = sorted(INTERFACES)
    packets = parse_packets('\n'.join([row(1.0,a,'0x12345678',1), row(1.1,b,'0x12345678',1), row(1.2,a,'0x12345678',2), row(1.3,a,'0x12345678',3), row(1.4,a,'0x12345678',5), row(1.5,a,'0x11111111',1,'02:01:02:03:04:06'), row(4.0,a,'0x12345678',1)]))
    grouped = group(packets, 1, 2, station)
    assert len(grouped) == 1 and len(grouped[0]['packets']) == 5
    assert grouped[0]['messages']['discover'] == {a:1,b:1}
    assert grouped[0]['messages']['ack'] == {a:1,b:0}
    assert not group(packets, 2, 3, station)
    other = '02:01:02:03:04:06'
    repeated = parse_packets(row(1.0, a, '0x12345678', 1, station + ',' + station))[0]
    assert repeated['client'] == station and repeated['client_address_fields'] == [station, station]
    distinct = parse_packets(row(1.0, a, '0x12345678', 1, station + ',' + other))[0]
    assert distinct['client'] == station and distinct['client_address_fields'] == [station, other]
    assert not group([distinct], 0, 2, other)
    assert [r['epoch'] for r in parse_packets('\n'.join([row(2.0, a, '0x12345678', 1), row(1.0, b, '0x12345678', 1)]))] == [1, 2]
    try:
        parse_packets(row(1.0, a, '0x12345678', 1, station + ',invalid'))
    except ValueError:
        pass
    else:
        raise AssertionError('malformed repeated address accepted')
    boundary = '\n'.join([
        'DHCP_OBSERVER_READY iface=wlp2s0 ifindex=4 duration=2',
        'DHCP_CLOCK 10.000 100.000 10.000',
        f'DHCP_PACKET 100.500 wlp2s0 tx 0.0.0.0 255.255.255.255 68 67 1 0x12345678 {station} 0.0.0.0 1',
        'DHCP_LINK_DOWN 10.950 ifindex=4',
        'DHCP_CLOCK 11.000 101.000 11.000',
        f'DHCP_PACKET 101.500 wlp2s0 rx 192.168.76.2 192.168.76.145 67 68 2 0x12345678 {station} 192.168.76.145 2',
        'DHCP_CLOCK 12.000 102.000 12.000',
        'DHCP_OBSERVER_END iface=wlp2s0 seen=2 decoded=2 malformed=0 packets=2 drops=0'])
    local, clocks, link_downs = parse_boundary_observer(boundary, 'wlp2s0')
    assert link_downs == [10.95]
    first, one = boundary_window(local, clocks, {'authorized_at': 10.1, 'observed_until': 11.0}, station)
    second, two = boundary_window(local, clocks, {'authorized_at': 11.0, 'observed_until': 11.9}, station)
    assert first == [100.1, 101.0] and second == [101.0, 101.9]
    assert len(one) == len(two) == 1
    joined = join_boundaries([], one, [])
    assert joined[0]['boundary_counts']['discover'] == {'client_tx': 1, 'client_rx': 0, 'ap_tx': 0, 'ap_rx': 0}
    assert join_boundaries([], two, [dict(two[0], direction='tx')])[0]['boundary_counts']['offer']['ap_tx'] == 1
    for invalid in (boundary.replace('drops=0', 'drops=1'),
                    boundary.replace('seen=2', 'seen=3'),
                    boundary.replace('DHCP_LINK_DOWN 10.950 ifindex=4', 'DHCP_LINK_DOWN 10.950 ifindex=5'),
                    boundary.replace('101.000 11.000', '103.000 11.000'),
                    boundary.rsplit('\n', 1)[0]):
        try:
            parse_boundary_observer(invalid, 'wlp2s0')
        except ValueError:
            pass
        else:
            raise AssertionError('invalid boundary evidence accepted')
    probe0 = clock_probe('10.000 110.010 10.020\n10.030 110.040 10.050\n10.060 110.070 10.080')
    probe1 = clock_probe('20.000 120.010 20.020\n20.030 120.040 20.050\n20.060 120.070 20.080')
    mapped, error = wire_clock(probe0, probe1, 115.0)
    assert abs(mapped - 15.0) < 1e-8 and 0.009 < error < 0.011
    certain, ambiguous = wire_group_with_uncertainty(packets, (1.0, 0.05), (2.0, 0.05), station)
    assert len(ambiguous) == 1 and len(certain[0]['packets']) == 4
    print('WIRED_DHCP_SUMMARY_SELFTEST_PASS')


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
    helpers = runpy.run_path(str(Path(__file__).with_name('summarize-reconnect-datapath.py')))
    sealed = helpers['verify_seal'](a.trial)
    prefix = f'band-{a.band}.'
    def read(name):
        name = prefix + name
        require(name in sealed, f'unsealed {name}')
        return (a.trial / name).read_text()
    require(not read('wired-ndp-decode.txt').strip() and not read('wired-provisioning-split.txt').strip(), 'capture decode warnings')
    dhcp = read('wired-dhcp.txt')
    capture = runpy.run_path(str(Path(__file__).with_name('split-wired-provisioning.py')))
    capture['verify_capture'](read('wired-ndp-status.txt'), read('wired-ndp.txt'), dhcp)
    packets = parse_packets(dhcp)
    cw = helpers['parse_trace'](read('client-control-trace.txt'), 'client', 1)
    aw = helpers['parse_trace'](read('ap-control-trace.txt'), 'ap', 1, True)
    require(len(cw) == len(aw), 'authorization windows differ')
    text = read('client-ip6.txt')
    chunks = re.findall(r'^IP6_SAMPLE index=(\d+) epoch=(\d+\.\d+) monotonic=(\d+\.\d+)\n(.*?)^IP6_SAMPLE_END index=\1$', text, re.M | re.S)
    end = re.search(r'^CLIENT_IP6_OBSERVER_END samples=(\d+)$',text,re.M)
    require(end and len(chunks) == int(end[1]) and [int(c[0]) for c in chunks] == list(range(len(chunks))), 'clock sample sequence incomplete')
    clocks = [(float(m),float(e)) for _,e,m,_ in chunks]
    mono = [m for m, _ in clocks]
    require(mono == sorted(set(mono)), 'nonmonotonic clock')
    boundary_names = [prefix + f'{side}-dhcp-boundary.txt' for side in ('client', 'ap')]
    boundaries = any(name in sealed for name in boundary_names)
    local = {}
    if boundaries:
        probe_before = clock_probe(read('client-wire-clock-before.txt'))
        probe_after = clock_probe(read('client-wire-clock-after.txt'))
        for side, iface in (('client', 'wlp2s0'), ('ap', 'ap-mld0')):
            require(not read(f'{side}-dhcp-boundary-error.txt').strip(), 'boundary observer error')
            local[side] = parse_boundary_observer(read(f'{side}-dhcp-boundary.txt'), iface)
    windows = []
    assigned = {'client': 0, 'ap': 0}
    for i, (c, w) in enumerate(zip(cw, aw), 1):
        begin = clock_epoch(clocks, c['authorized_at'])
        finish = clock_epoch(clocks, c['observed_until'])
        station = w['station']
        transactions = group(packets, begin, finish, station)
        window = dict(association=i, station=station, wire_epoch=[begin, finish])
        if boundaries:
            client_epoch, client_rows = boundary_window(*local['client'][:2], c, station)
            ap_epoch, ap_rows = boundary_window(*local['ap'][:2], w, station)
            start = wire_clock(probe_before, probe_after, client_epoch[0])
            stop = wire_clock(probe_before, probe_after, client_epoch[1])
            transactions, ambiguous = wire_group_with_uncertainty(packets, start, stop, station)
            window.update(client_epoch=client_epoch, ap_epoch=ap_epoch,
                          wire_epoch=[start[0], stop[0]],
                          wire_epoch_uncertainty_s=[start[1], stop[1]],
                          wire_boundary_ambiguous=ambiguous,
                          link_down_notifications={side: [t for t in local[side][2]
                              if w['authorized_at'] <= t < w['observed_until']]
                              for side, w in (('client', c), ('ap', w))})
            assigned['client'] += len(client_rows)
            assigned['ap'] += len(ap_rows)
            transactions = join_boundaries(transactions, client_rows, ap_rows)
        window['transactions'] = transactions
        windows.append(window)
    result = dict(band=a.band, wire_packets=len(packets),
                  undecoded=sum(r['message'] == 'undecoded' for r in packets),
                  association_windows=windows)
    if boundaries:
        station = aw[0]['station']
        result['client_wire_clock_probes'] = [probe_before, probe_after]
        result['boundary_observers'] = {
            side: dict(packets=len(rows),
                       station_packets=sum(p['client'] == station for p in rows),
                       assigned_packets=assigned[side],
                       clock_anchors=len(anchors), link_down_notifications=downs)
            for side, (rows, anchors, downs) in local.items()}
    print(json.dumps(result, indent=2))



if __name__ == '__main__':
    main()
