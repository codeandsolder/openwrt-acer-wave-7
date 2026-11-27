#!/usr/bin/env python3
"""Exercise the actual observer and kernel packet filter on an isolated veth."""
import argparse
import json
from pathlib import Path
import selectors
import socket
import struct
import subprocess

LEFT, RIGHT = 'obs-left', 'obs-right'
CLIENT = bytes.fromhex('020102030405')
CLIENT_ID = bytes.fromhex('020102030406')
COOKIE = bytes.fromhex('63825363')


def ip_checksum(data):
    words = struct.unpack(f'!{len(data) // 2}H', data)
    acc = sum(words)
    while acc >> 16:
        acc = (acc & 0xffff) + (acc >> 16)
    return ~acc & 0xffff


def bootp(xid, op, options):
    return struct.pack('!BBBBIHH4s4s4s4s16s64s128s', op, 1, 6, 0,
                       xid, 0, 0, bytes(4), bytes.fromhex('c0a84c91'),
                       bytes(4), bytes(4), CLIENT + bytes(10), bytes(64),
                       bytes(128)) + options


def frame(src, dst, payload, sport=68, dport=67, proto=17,
          frag=0, ipopts=b''):
    udp = struct.pack('!HHHH', sport, dport, 8 + len(payload), 0) + payload
    header = struct.pack('!BBHHHBBH4s4s', 0x45 + len(ipopts) // 4, 0,
                         20 + len(ipopts) + len(udp), 0, frag, 64, proto, 0,
                         bytes.fromhex('c0a84c02'), bytes.fromhex('c0a84c91')) + ipopts
    header = header[:10] + struct.pack('!H', ip_checksum(header)) + header[12:]
    return dst + src + bytes.fromhex('0800') + header + udp


def echo_frame(src, dst, kind, ident, seq, *, code=0, frag=0, ipopts=b''):
    icmp = struct.pack('!BBHHH', kind, code, 0, ident, seq) + bytes(56)
    icmp = icmp[:2] + struct.pack('!H', ip_checksum(icmp)) + icmp[4:]
    header = struct.pack('!BBHHHBBH4s4s', 0x45 + len(ipopts) // 4, 0,
                         20 + len(ipopts) + len(icmp), 123, frag, 64, 1, 0,
                         bytes.fromhex('c0a84c02'), bytes.fromhex('c0a84c91')) + ipopts
    header = header[:10] + struct.pack('!H', ip_checksum(header)) + header[12:]
    return dst + src + bytes.fromhex('0800') + header + icmp

def mac(iface):
    link, = json.loads(subprocess.check_output(['ip', '-j', 'link', 'show', 'dev', iface]))
    return bytes.fromhex(link['address'].replace(':', ''))


def start(binary, iface, profile='dhcp4'):
    label = 'DHCP' if profile == 'dhcp4' else 'ICMP4'
    p = subprocess.Popen([binary, iface, '2', profile], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    with selectors.DefaultSelector() as selector:
        selector.register(p.stdout, selectors.EVENT_READ)
        if not selector.select(3):
            p.kill()
            raise RuntimeError('observer readiness timed out')
        ready = p.stdout.readline()
    if not ready.startswith(f'{label}_OBSERVER_READY iface={iface} '):
        p.kill()
        _, err = p.communicate(timeout=3)
        raise RuntimeError(f'missing readiness: {ready!r} {err!r}')
    return p


def finish(process, iface, malformed, expected, link_downs=0, profile='dhcp4'):
    label = 'DHCP' if profile == 'dhcp4' else 'ICMP4'
    out, err = process.communicate(timeout=6)
    assert process.returncode == bool(malformed), (process.returncode, out, err)
    assert not err, err
    all_rows = out.splitlines()
    anchors = [tuple(map(float, row.split()[1:])) for row in all_rows
               if row.startswith(f'{label}_CLOCK ')]
    assert len(anchors) >= 2
    assert all(before <= after and after - before < 0.05 and realtime > before
               for before, realtime, after in anchors)
    assert all(a[0] < b[0] for a, b in zip(anchors, anchors[1:]))
    down = [row for row in all_rows if row.startswith(f'{label}_LINK_DOWN ')]
    assert len(down) == link_downs, down
    rows = [row for row in all_rows if not row.startswith((f'{label}_CLOCK ', f'{label}_LINK_DOWN '))]
    end = dict(item.split('=') for item in rows[-1].split()[1:])
    assert rows[-1].startswith(f'{label}_OBSERVER_END ')
    assert end == {'iface': iface, 'seen': str(len(expected) + malformed),
                   'decoded': str(len(expected)), 'malformed': str(malformed),
                   'packets': str(len(expected) + malformed), 'drops': '0'}, (end, out)
    assert len(rows) == len(expected) + 1
    actual = []
    for row in rows[:-1]:
        fields = row.split()
        assert fields[0] == f'{label}_PACKET' and fields[2] == iface
        assert float(fields[1]) > 0
        assert fields[4:6] == ['192.168.76.2', '192.168.76.145']
        if profile == 'dhcp4':
            assert fields[10] == '02:01:02:03:04:05'
            assert fields[11] == '192.168.76.145'
            actual.append((fields[3], int(fields[6]), int(fields[7]),
                           int(fields[8]), int(fields[9], 16), int(fields[12])))
        else:
            assert len(fields) == 11
            actual.append((fields[3], *map(int, fields[6:])))
    assert actual == expected, (actual, expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--parent-netns', required=True)
    args = parser.parse_args()
    binary = str(args.binary.resolve(strict=True))
    # Must be run under unshare -Urn, never create devices in the host namespace.
    assert str(Path('/proc/self/ns/net').readlink()) != args.parent_netns
    subprocess.run(['ip', 'link', 'add', LEFT, 'type', 'veth', 'peer', 'name',
                    RIGHT], check=True)
    for iface in (LEFT, RIGHT):
        subprocess.run(['ip', 'link', 'set', iface, 'up'], check=True)
    left_mac, right_mac = mac(LEFT), mac(RIGHT)
    with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3)) as left, \
         socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3)) as right:
        left.bind((LEFT, 0))
        right.bind((RIGHT, 0))
        req = bootp(1, 1, COOKIE + bytes([53, 1, 1, 61, 7, 1]) + CLIENT_ID + bytes([255]))
        rep = bootp(2, 2, COOKIE + bytes([0, 53, 1, 5, 255]))
        relay = bootp(3, 1, b'')
        packets = [
            (left, frame(left_mac, right_mac, req)),
            (right, frame(right_mac, left_mac, rep, 67, 68, ipopts=bytes([1, 1, 1, 0]))),
            (left, frame(left_mac, right_mac, relay, 67, 67)),
            (left, frame(left_mac, right_mac, req, 68, 68)),
            (left, frame(left_mac, right_mac, req, 53, 67)),
            (left, frame(left_mac, right_mac, req, proto=6)),
            (left, frame(left_mac, right_mac, req, frag=1)),
        ]
        for malformed, fixtures in ((0, packets), (3, [
            (left, frame(left_mac, right_mac, req, frag=0x2000)),
            (left, frame(left_mac, right_mac, bootp(4, 1, COOKIE + bytes([53, 2, 1, 2, 255])))),
            (left, frame(left_mac, right_mac, bootp(5, 1, COOKIE + bytes([53, 1, 1])))),
        ])):
            a, b = start(binary, LEFT), start(binary, RIGHT)
            try:
                for sock, data in fixtures:
                    assert sock.send(data) == len(data)
                l = [('tx', 68, 67, 1, 1, 1), ('rx', 67, 68, 2, 2, 5),
                     ('tx', 67, 67, 1, 3, 0)] if not malformed else []
                r = [('rx' if row[0] == 'tx' else 'tx', *row[1:]) for row in l]
                finish(a, LEFT, malformed, l)
                finish(b, RIGHT, malformed, r)
            finally:
                for p in (a, b):
                    if p.poll() is None:
                        p.kill()
                        p.wait()
        echo_cases = [
            (left, echo_frame(left_mac, right_mac, 8, 321, 17)),
            (right, echo_frame(right_mac, left_mac, 0, 321, 17, ipopts=bytes([1,1,1,0]))),
            (left, echo_frame(left_mac, right_mac, 3, 321, 17)),
            (left, echo_frame(left_mac, right_mac, 8, 321, 17, frag=1)),
            packets[0],
        ]
        for malformed, fixtures in ((0, echo_cases), (2, [
            (left, echo_frame(left_mac, right_mac, 8, 321, 18, code=1)),
            (left, echo_frame(left_mac, right_mac, 8, 321, 19, frag=0x2000)),
        ])):
            a, b = start(binary, LEFT, 'echo4'), start(binary, RIGHT, 'echo4')
            try:
                for sock, data in fixtures:
                    assert sock.send(data) == len(data)
                l = [('tx', 8, 321, 17, 84, 123), ('rx', 0, 321, 17, 88, 123)] if not malformed else []
                r = [('rx' if row[0] == 'tx' else 'tx', *row[1:]) for row in l]
                finish(a, LEFT, malformed, l, profile='echo4')
                finish(b, RIGHT, malformed, r, profile='echo4')
            finally:
                for p in (a, b):
                    if p.poll() is None:
                        p.kill()
                        p.wait()
        # Exercise the actual packet-notifier down/up path without replacing
        # the bound netdev. Both directions must still be observed afterwards.
        a, b = start(binary, LEFT), start(binary, RIGHT)
        try:
            subprocess.run(['ip', 'link', 'set', LEFT, 'down'], check=True)
            subprocess.run(['ip', 'link', 'set', LEFT, 'up'], check=True)
            # Sender sockets also retain their asynchronous ENETDOWN.
            left.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            right.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            for sock, data in packets[:2]:
                assert sock.send(data) == len(data)
            l = [('tx', 68, 67, 1, 1, 1), ('rx', 67, 68, 2, 2, 5)]
            r = [('rx' if row[0] == 'tx' else 'tx', *row[1:]) for row in l]
            finish(a, LEFT, 0, l, 1)
            finish(b, RIGHT, 0, r)
        finally:
            for p in (a, b):
                if p.poll() is None:
                    p.kill()
                    p.wait()
        a = start(binary, LEFT)
        try:
            subprocess.run(['ip', 'link', 'del', LEFT], check=True)
            out, err = a.communicate(timeout=6)
            assert a.returncode != 0 and 'DHCP_OBSERVER_END' not in out, (out, err)
        finally:
            if a.poll() is None:
                a.kill()
                a.wait()
    print('PACKET_BOUNDARY_ACTUAL_VETH_PASS')


if __name__ == '__main__':
    main()
