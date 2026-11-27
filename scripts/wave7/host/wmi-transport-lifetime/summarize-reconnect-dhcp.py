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
        if begin <= row['epoch'] <= end and row['client'] == station:
            by_xid.setdefault(row['xid'], []).append(row)
    return [dict(xid=xid, packets=rows, messages={kind: {iface: sum(r['message'] == kind and r['interface'] == iface for r in rows) for iface in sorted(INTERFACES)} for kind in sorted({r['message'] for r in rows})}) for xid, rows in by_xid.items()]


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
    mono = [m for m,_ in clocks]
    require(mono == sorted(set(mono)), 'nonmonotonic clock')
    def epoch(t):
        i = bisect.bisect_right(mono,t)-1
        require(i>=0 and i+1<len(clocks), 'authorization outside clock sample')
        lo,hi = clocks[i:i+2]
        require(hi[0]-lo[0]<2.5, 'clock sample gap')
        return lo[1]+(hi[1]-lo[1])*(t-lo[0])/(hi[0]-lo[0])
    windows=[]
    for i,(c,w) in enumerate(zip(cw,aw),1):
        begin,finish=epoch(c['authorized_at']),epoch(c['observed_until'])
        windows.append(dict(association=i,station=w['station'],wire_epoch=[begin,finish],transactions=group(packets,begin,finish,w['station'])))
    print(json.dumps(dict(band=a.band,wire_packets=len(packets),undecoded=sum(r['message']=='undecoded' for r in packets),association_windows=windows),indent=2))


if __name__ == '__main__':
    main()
