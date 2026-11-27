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

from packet_boundary import clock_epoch, parse_observer

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


def exchange_timing(rows):
    """Measure same-interface request/reply intervals, never cross-host clocks.

    A retransmission makes exact request/reply attribution ambiguous. Report
    the elapsed time since both first and latest matching request instead.
    Only correctly directed BOOTP messages are eligible.
    """
    result = []
    for iface in sorted({p['interface'] for p in rows}):
        pending = {'discover': [], 'request': [], 'inform': []}
        for p in sorted((p for p in rows if p['interface'] == iface), key=lambda p: p['epoch']):
            kind = p['message']
            if p['op'] == 1 and p['udp_src'] == 68 and p['udp_dst'] == 67 and kind in pending:
                pending[kind].append(p['epoch'])
                continue
            if p['op'] != 2 or (p['udp_src'], p['udp_dst']) != (67, 68):
                continue
            if kind == 'offer':
                candidates = ('discover',)
            elif kind in ('ack', 'nak'):
                candidates = ('request', 'inform') if kind == 'ack' else ('request',)
            else:
                continue
            eligible = [k for k in candidates if pending[k]]
            times = sorted(t for k in eligible for t in pending[k])
            result.append(dict(interface=iface, response=kind, response_epoch=p['epoch'],
                               request_types=eligible, requests_seen=len(times),
                               since_first_ms=round((p['epoch']-times[0])*1000, 3) if times else None,
                               since_latest_ms=round((p['epoch']-times[-1])*1000, 3) if times else None))
            for k in eligible:
                pending[k].clear()
    return result


def group(packets, begin, end, station):
    by_xid = {}
    for row in packets:
        if begin <= row['epoch'] < end and row['client'] == station:
            by_xid.setdefault(row['xid'], []).append(row)
    return [dict(xid=xid, packets=rows, wire_exchanges=exchange_timing(rows), messages={kind: {iface: sum(r['message'] == kind and r['interface'] == iface for r in rows) for iface in sorted(INTERFACES)} for kind in sorted({r['message'] for r in rows})}) for xid, rows in by_xid.items()]


def decode_dhcp_boundary(fields):
    require(len(fields) == 7, 'invalid boundary DHCP fields')
    src, dst, op, xid, client, offered, kind = fields
    require((src, dst) in {('67', '68'), ('68', '67'), ('67', '67')} and op in {'1', '2'},
            'invalid boundary packet protocol')
    require(re.fullmatch(r'0x[0-9a-f]{8}', xid) and MAC.fullmatch(client),
            'invalid boundary packet identity')
    require(kind.isdecimal() and 0 <= int(kind) <= 255, 'invalid boundary DHCP type')
    ipaddress.IPv4Address(offered)
    return dict(udp_src=int(src), udp_dst=int(dst), op=int(op), xid=xid, client=client,
                offered_ipv4=offered, message=TYPES.get(int(kind), f'type_{kind}') if int(kind) else 'undecoded')


def parse_boundary_observer(text, iface):
    return parse_observer(text, iface, 'DHCP', decode_dhcp_boundary)


def clock_probe(text):
    """Intersect remote-local offset bounds from independent round trips."""
    rows = []
    for line in text.splitlines():
        fields = line.split()
        require(len(fields) == 3 and all(re.fullmatch(r'\d+\.\d+', f) for f in fields),
                'invalid client/wire clock probe')
        before, client, after = map(float, fields)
        require(0 <= after - before < 1 and (not rows or before >= rows[-1][2]),
                'invalid client/wire clock round trip')
        rows.append((before, client, after))
    require(3 <= len(rows) <= 16, 'incomplete client/wire clock probe')
    low = max(client - after for before, client, after in rows)
    high = min(client - before for before, client, after in rows)
    require(low <= high, 'inconsistent client/wire clock bound')
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
    stop = window['observed_until']
    clipped = stop > clocks[-1][0]
    require(not clipped or window.get('right_censored'), 'closed lifetime outside clock capture')
    end = clock_epoch(clocks, min(stop, clocks[-1][0]))
    require(begin < end, 'inverted local authorization clock')
    return [begin, end], [p for p in packets
                         if begin <= p['epoch'] < end and p['client'] == station], clipped


# The direct NIC hosts the lab DHCP server. The switched NIC is an
# independent observation of a flooded copy, not a hop to that server.
SERVER_INTERFACE = 'enp4s0f4u2u4'
REQUEST_TYPES = {'discover', 'request', 'decline', 'release', 'inform'}
RESPONSE_TYPES = {'offer', 'ack', 'nak'}


def message_path(tx, kind, station, all_rows):
    """Report transaction-level witnesses; no attempt to pair retransmissions.

    AP TX copies of flooded client requests are not the server-directed
    boundary. Direction and BOOTP ports/op must agree with the message type.
    Any matching evidence outside the selected authorization window makes
    an otherwise absent witness ambiguous rather than proving a loss.
    """
    if kind in REQUEST_TYPES:
        op, ports = 1, (68, 67)
        path = [('client', 'tx'), ('ap', 'rx'), ('wire', SERVER_INTERFACE)]
    elif kind in RESPONSE_TYPES:
        op, ports = 2, (67, 68)
        path = [('wire', SERVER_INTERFACE), ('ap', 'tx'), ('client', 'rx')]
    else:
        return None
    local_rows = {'client': tx['client_packets'], 'ap': tx['ap_packets'],
                  'wire': tx['packets']}
    stages = []
    for side, boundary in path:
        def matches(row):
            return (row['xid'] == tx['xid'] and row['client'] == station and
                    row['message'] == kind and row['op'] == op and
                    (row['udp_src'], row['udp_dst']) == ports and
                    row.get('direction' if side != 'wire' else 'interface') == boundary)
        selected = sum(matches(row) for row in local_rows[side])
        total = sum(matches(row) for row in all_rows[side])
        require(total >= selected, 'inconsistent transaction witness accounting')
        stages.append(dict(side=side, boundary=boundary, observed=selected,
                           outside_window=total-selected))
    status = 'all_boundaries_observed'
    if any(not row['observed'] for row in stages):
        if any(not row['observed'] and row['outside_window'] for row in stages):
            status = 'ambiguous_window'
        elif not stages[0]['observed'] or any(
                not before['observed'] and after['observed']
                for before, after in zip(stages, stages[1:])):
            status = 'inconsistent_or_unobserved_origin'
        else:
            status = 'missing_downstream_witness'
    return dict(stages=stages, status=status)


def host_exchanges(rows, request_direction, response_direction):
    eligible = [row for row in rows
                if (row['op'] == 1 and row['direction'] == request_direction) or
                   (row['op'] == 2 and row['direction'] == response_direction)]
    return exchange_timing(eligible)


# AF_PACKET and net_dev_start_xmit observe adjacent points on the same host.
# Without a shared skb identifier in AF_PACKET this is a timing candidate,
# not an exact packet identity. Refuse ambiguous candidates rather than
# picking the nearest one.
TX_MATCH_RADIUS_S = 0.0005


def client_tx_candidates(rows, clocks, trace, helpers, windows):
    epochs = [e for _, e in clocks]
    xmits = []
    for line in trace.splitlines():
        match = helpers['LINE'].search(line)
        if not match or match[2] != 'net_dev_start_xmit':
            continue
        fields = dict(helpers['FIELD'].findall(match[3]))
        if fields.get('dev') == 'wlp2s0':
            xmits.append((float(match[1]), fields))
    xmits.sort(key=lambda x: x[0])
    times = [t for t, _ in xmits]
    by_cookie = {}
    for i, (_, fields) in enumerate(xmits):
        by_cookie.setdefault(fields['skbaddr'], []).append(i)
    submissions, _ = helpers['data_token_submissions'](trace)
    descriptors = {}
    for row in submissions:
        descriptors.setdefault(row['cookie'], []).append(row)
    proposals = {}
    for j, packet in enumerate(rows):
        if packet['direction'] != 'tx':
            continue
        epoch = packet['epoch']
        i = bisect.bisect_right(epochs, epoch) - 1
        if not 0 <= i < len(clocks)-1:
            packet['tx_candidate'] = {'status': 'outside_clock_anchors'}
            continue
        (m0, e0), (m1, e1) = clocks[i:i+2]
        mono = m0 + (m1-m0)*(epoch-e0)/(e1-e0)
        bounds = [w for w in windows if w['authorized_at'] <= mono < w['observed_until']]
        if len(bounds) != 1:
            packet['tx_candidate'] = {'status': 'outside_authorized_window'}
            continue
        lo = bisect.bisect_left(times, mono-TX_MATCH_RADIUS_S)
        hi = bisect.bisect_right(times, mono+TX_MATCH_RADIUS_S)
        indices = [k for k in range(lo, hi) if xmits[k][1]['protocol'] == '0x0800']
        proposals[j] = (mono, indices, bounds[0])
    claims = {}
    for _, indices, _ in proposals.values():
        for k in indices:
            claims[k] = claims.get(k, 0) + 1
    for j, (mono, indices, window) in proposals.items():
        packet = rows[j]
        if len(indices) != 1 or claims[indices[0]] != 1:
            packet['tx_candidate'] = {'status': 'ambiguous_netdev' if indices else 'no_netdev_candidate',
                                      'candidate_count': len(indices)}
            continue
        k = indices[0]
        t, fields = xmits[k]
        cookie = fields['skbaddr']
        reuse = by_cookie[cookie]
        pos = bisect.bisect_right(reuse, k)
        limit = min(window['observed_until'],
                    times[reuse[pos]] if pos < len(reuse) else float('inf'))
        matching = [d for d in descriptors.get(cookie, [])
                    if t <= d['submitted_at'] < limit
                    and d['length'] == fields['len'] and d['protocol'] == fields['protocol']]
        evidence = {'netdev_at': t, 'clock_delta_us': round((t-mono)*1e6, 3),
                    'cookie': cookie, 'length': int(fields['len'])}
        if len(matching) != 1:
            packet['tx_candidate'] = dict(evidence, status='ambiguous_descriptor' if matching else
                                          'no_descriptor_candidate', candidate_count=len(matching))
            continue
        descriptor = matching[0]
        packet['tx_candidate'] = dict(evidence, status='matched_candidate',
                                      host_queue_ms=round((descriptor['submitted_at']-t)*1000, 3),
                                      descriptor=descriptor)


def join_boundaries(wired, client, ap, *, station=None, all_rows=None):
    """Keep local witnesses separate; cross-host epoch is not a causal clock."""
    by_xid = {t['xid']: dict(t, client_packets=[], ap_packets=[]) for t in wired}
    for side, rows in (('client', client), ('ap', ap)):
        for row in rows:
            tx = by_xid.setdefault(row['xid'], dict(xid=row['xid'], packets=[], wire_exchanges=[],
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
        tx['client_exchanges'] = host_exchanges(tx['client_packets'], 'tx', 'rx')
        tx['ap_exchanges'] = host_exchanges(tx['ap_packets'], 'rx', 'tx')
        if all_rows is not None:
            tx['message_paths'] = {kind: result for kind in sorted(kinds)
                                   if (result := message_path(tx, kind, station, all_rows)) is not None}
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
    def exchange(t, iface, kind, op):
        return dict(epoch=t, interface=iface, message=kind, op=op,
                    udp_src=68 if op == 1 else 67, udp_dst=67 if op == 1 else 68)
    witness = exchange_timing([exchange(1.0, a, 'discover', 1), exchange(1.1, b, 'discover', 1),
                               exchange(1.5, a, 'discover', 1), exchange(2.0, a, 'offer', 2),
                               exchange(2.1, a, 'request', 1), exchange(2.2, a, 'ack', 2),
                               exchange(2.3, a, 'ack', 2), exchange(2.4, b, 'offer', 2)])
    assert [(r['requests_seen'], r['since_first_ms'], r['since_latest_ms']) for r in witness] == [
        (2, 1000.0, 500.0), (1, 100.0, 100.0), (0, None, None), (1, 1300.0, 1300.0)]
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
    first, one, clipped = boundary_window(local, clocks, {'authorized_at': 10.1, 'observed_until': 11.0}, station)
    second, two, clipped2 = boundary_window(local, clocks, {'authorized_at': 11.0, 'observed_until': 11.9}, station)
    assert first == [100.1, 101.0] and second == [101.0, 101.9]
    assert len(one) == len(two) == 1 and not clipped and not clipped2
    tail, tail_rows, clipped = boundary_window(local, clocks, {'authorized_at': 11.0,
                                                               'observed_until': 13.0,
                                                               'right_censored': True}, station)
    assert tail == [101.0, 102.0] and tail_rows == two and clipped
    try:
        boundary_window(local, clocks, {'authorized_at': 11.0, 'observed_until': 13.0}, station)
    except ValueError:
        pass
    else:
        raise AssertionError('closed lifetime outside capture accepted')
    joined = join_boundaries([], one, [])
    assert joined[0]['boundary_counts']['discover'] == {'client_tx': 1, 'client_rx': 0, 'ap_tx': 0, 'ap_rx': 0}
    assert join_boundaries([], two, [dict(two[0], direction='tx')])[0]['boundary_counts']['offer']['ap_tx'] == 1
    request = one[0]
    reflection = dict(request, interface='ap-mld0', direction='tx')
    ingress = dict(reflection, direction='rx')
    direct = dict(request, interface=SERVER_INTERFACE)
    mirror = dict(request, interface='enp4s0f4u2u2u4')
    wire = group([direct, mirror], 100, 101, station)
    def paths(wire, client, ap, all_rows):
        return join_boundaries(wire, client, ap, station=station, all_rows=all_rows)[0]['message_paths']['discover']
    complete = paths(wire, one, [ingress, reflection],
                     {'client': one, 'ap': [ingress, reflection], 'wire': [direct, mirror]})
    assert complete['status'] == 'all_boundaries_observed'
    assert [row['observed'] for row in complete['stages']] == [1, 1, 1]
    missing = paths([], one, [reflection], {'client': one, 'ap': [reflection], 'wire': []})
    assert missing['status'] == 'missing_downstream_witness'
    assert [row['observed'] for row in missing['stages']] == [1, 0, 0]
    assert paths([], one, [], {'client': one, 'ap': [ingress], 'wire': [direct]})['status'] == 'ambiguous_window'
    assert paths(wire, one, [reflection], {'client': one, 'ap': [reflection], 'wire': [direct, mirror]})['status'] == 'inconsistent_or_unobserved_origin'
    response = two[0]
    reply = dict(response, interface='ap-mld0', direction='tx', epoch=101.2)
    assert host_exchanges([ingress, reflection, reply], 'rx', 'tx')[0]['requests_seen'] == 1

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
    # A slow round trip gives a wider interval, not a contradiction.
    wide = clock_probe('10.000 110.200 10.400\n10.500 110.700 10.900\n11.000 111.200 11.400')
    assert abs(wide[2] - 0.2) < 1e-8
    try:
        clock_probe('10.000 110.200 10.400\n10.500 111.700 10.900\n11.000 111.200 11.400')
    except ValueError:
        pass
    else:
        raise AssertionError('disjoint clock bounds accepted')
    mapped, error = wire_clock(probe0, probe1, 115.0)
    assert abs(mapped - 15.0) < 1e-8 and 0.009 < error < 0.011
    certain, ambiguous = wire_group_with_uncertainty(packets, (1.0, 0.05), (2.0, 0.05), station)
    assert len(ambiguous) == 1 and len(certain[0]['packets']) == 4
    helpers = runpy.run_path(str(Path(__file__).with_name('summarize-reconnect-datapath.py')))
    tx = lambda t, cookie: f'task [000] .... {t:.6f}: net_dev_start_xmit: dev=wlp2s0 skbaddr={cookie} protocol=0x0800 len=329'
    descriptor = lambda t, cookie: f'task [000] .... {t:.6f}: mt7925_lab_data_txd: cookie={cookie} length=329 protocol=0x0800 wcid=2'
    a, b = '00000000abcdef01', '00000000abcdef02'
    rows = [dict(request, epoch=e) for e in [100.5, 101.5, 101.7]]
    trace = '\n'.join([tx(10.50001, a), descriptor(10.8, a),
                        tx(11.50001, a), tx(11.70001, b), tx(11.70002, a)])
    # Keep token pairing independent in the fixture; real trace uses the
    # production helper and requires a return before a cookie is reused.
    client_tx_candidates(rows, clocks, trace, helpers,
                         [{'authorized_at': 10.1, 'observed_until': 11.9}])
    assert [r['tx_candidate']['status'] for r in rows] == [
        'matched_candidate', 'no_descriptor_candidate', 'ambiguous_netdev']
    assert rows[0]['tx_candidate']['host_queue_ms'] == 299.99
    rows = [dict(request, epoch=100.5), dict(request, epoch=100.50002)]
    client_tx_candidates(rows, clocks, trace, helpers,
                         [{'authorized_at': 10.1, 'observed_until': 11.9}])
    assert all(r['tx_candidate']['status'] == 'ambiguous_netdev' for r in rows)
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
    client_trace = read('client-control-trace.txt')
    cw = helpers['parse_trace'](client_trace, 'client', 1)
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
        client_tx_candidates(*local['client'][:2], client_trace, helpers, cw)
    windows = []
    assigned = {'client': 0, 'ap': 0}
    for i, (c, w) in enumerate(zip(cw, aw), 1):
        begin = clock_epoch(clocks, c['authorized_at'])
        finish = clock_epoch(clocks, c['observed_until'])
        station = w['station']
        transactions = group(packets, begin, finish, station)
        window = dict(association=i, station=station, wire_epoch=[begin, finish])
        if boundaries:
            client_epoch, client_rows, client_clipped = boundary_window(*local['client'][:2], c, station)
            ap_epoch, ap_rows, ap_clipped = boundary_window(*local['ap'][:2], w, station)
            start = wire_clock(probe_before, probe_after, client_epoch[0])
            stop = wire_clock(probe_before, probe_after, client_epoch[1])
            transactions, ambiguous = wire_group_with_uncertainty(packets, start, stop, station)
            window.update(client_epoch=client_epoch, ap_epoch=ap_epoch,
                          endpoint_window_clipped={'client': client_clipped, 'ap': ap_clipped},
                          wire_epoch=[start[0], stop[0]],
                          wire_epoch_uncertainty_s=[start[1], stop[1]],
                          wire_boundary_ambiguous=ambiguous,
                          link_down_notifications={side: [t for t in local[side][2]
                              if w['authorized_at'] <= t < w['observed_until']]
                              for side, w in (('client', c), ('ap', w))})
            assigned['client'] += len(client_rows)
            assigned['ap'] += len(ap_rows)
            transactions = join_boundaries(transactions, client_rows, ap_rows, station=station,
                                           all_rows={'client': local['client'][0],
                                                     'ap': local['ap'][0], 'wire': packets})
            if client_clipped or (ap_clipped and ap_epoch[1] - ap_epoch[0] <
                                  client_epoch[1] - client_epoch[0]):
                for transaction in transactions:
                    for path in transaction['message_paths'].values():
                        if path['status'] == 'missing_downstream_witness':
                            path['status'] = 'ambiguous_capture_end'
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
