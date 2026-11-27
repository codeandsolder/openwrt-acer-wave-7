#!/usr/bin/env python3
"""Split metadata-only tshark field output into NDP and DHCPv4 records."""
import argparse
from collections import Counter
import re
import sys
from pathlib import Path


# NDP columns remain exactly as previously decoded, followed by DHCP fields.
# DHCP: time, ethernet src/dst, interface, IPv4 src/dst, UDP src/dst,
# BOOTP op, transaction ID, client hardware address, offered address, type.
NDP = 11
DHCP = 9
DHCP_FIELDS = [0, 1, 2, 6, *range(NDP, NDP + DHCP)]


def split_line(line):
    row = line.rstrip('\n').split('\t')
    if len(row) != NDP + DHCP:
        raise ValueError(f'expected {NDP + DHCP} fields, got {len(row)}')
    if not re.fullmatch(r'\d+\.\d+', row[0]) or not row[6]:
        raise ValueError('missing timestamp or interface')
    if row[5] in {'133', '134', '135', '136'}:
        return 'ndp', row[:NDP]
    if row[NDP+2:NDP+4] in (['67', '68'], ['68', '67'], ['67', '67']):
        # Preserve undecoded/BOOTP traffic as such; never infer a DHCP type.
        return 'dhcp', [row[i] for i in DHCP_FIELDS]
    raise ValueError('packet outside capture protocol filter')


# dumpcap reports received counts by interface, independent of the decoder.
# A successful subprocess exit alone does not establish capture completeness.
INTERFACES = {'enp4s0f4u2u4', 'enp4s0f4u2u2u4'}
STATUS = re.compile(
    r"^Packets received/dropped on interface '([^']+)': (\d+)/(\d+) "
    r"\(pcap:(\d+)/dumpcap:(\d+)/flushed:(\d+)/ps_ifdrop:(\d+)\)",
    re.M)


def verify_capture(stats, ndp, dhcp=None):
    """Require every captured packet to appear exactly once in decoded metadata."""
    totals = re.findall(r'^Packets captured: (\d+)$', stats, re.M)
    rows = STATUS.findall(stats)
    if len(totals) != 1 or len(rows) != len(INTERFACES):
        raise ValueError('incomplete or duplicate capture statistics')
    if {r[0] for r in rows} != INTERFACES or any(
            any(map(int, r[2:])) for r in rows):
        raise ValueError('missing capture interface or dropped packets')
    expected = Counter({r[0]: int(r[1]) for r in rows})
    observed = Counter()
    for data, width, iface_index in ((ndp, NDP, 6), (dhcp, 13, 3)):
        if data is None:
            continue
        for line in data.splitlines():
            fields = line.split('\t')
            if len(fields) != width or fields[iface_index] not in INTERFACES:
                raise ValueError('malformed decoded packet or unknown interface')
            observed[fields[iface_index]] += 1
    if sum(expected.values()) != int(totals[0]) or observed != expected:
        raise ValueError(f'capture accounting mismatch: captured={totals[0]} '
                         f'expected={dict(expected)} decoded={dict(observed)}')
    return dict(expected)


def selftest():
    ndp = ['1795809666.510814750', '00:01:02:03:04:05', '33:33:00:00:00:02',
           'fe80::1', 'ff02::2', '133', 'lab0', '255', '', '', '']
    assert split_line('\t'.join(ndp + [''] * DHCP) + '\n') == ('ndp', ndp)
    dhcp = ['0.0.0.0', '255.255.255.255', '68', '67', '1', '0x12345678',
            '00:01:02:03:04:05', '0.0.0.0', '1']
    base = ndp[:3] + ['', '', '', 'lab1', '', '', '', '']
    assert split_line('\t'.join(base + dhcp) + '\n') == ('dhcp', base[:3] + ['lab1'] + dhcp)
    for kind in ('2', '3', '5', '6', ''):
        dhcp[-1] = kind
        assert split_line('\t'.join(base + dhcp))[1][-1] == kind
    for bad in ('', '\t'.join(base), '\t'.join(base + [''] * DHCP)):
        try:
            split_line(bad)
        except ValueError:
            pass
        else:
            raise AssertionError('malformed packet accepted')
    a, b = sorted(INTERFACES)
    def stats(x, y, dropped=0):
        return (f'Packets captured: {x + y}\n'
                f"Packets received/dropped on interface '{a}': {x}/{dropped} "
                '(pcap:0/dumpcap:0/flushed:0/ps_ifdrop:0)\n'
                f"Packets received/dropped on interface '{b}': {y}/0 "
                '(pcap:0/dumpcap:0/flushed:0/ps_ifdrop:0)\n')
    ndp[6] = a
    base[6] = b
    ndp_text = '\t'.join(ndp) + '\n'
    dhcp_text = '\t'.join(base[:3] + [b] + dhcp) + '\n'
    assert verify_capture(stats(1, 1), ndp_text, dhcp_text) == {a: 1, b: 1}
    assert verify_capture(stats(1, 0), ndp_text) == {a: 1, b: 0}
    assert verify_capture(stats(0, 0), '', '') == {a: 0, b: 0}
    for st, n, d in (
            (stats(1, 1), ndp_text, ''),
            (stats(1, 1), ndp_text * 2, ''),
            (stats(1, 1, 1), ndp_text, dhcp_text),
            (stats(1, 1).replace('captured: 2', 'captured: 3'), ndp_text, dhcp_text),
            (stats(1, 1).splitlines()[0], ndp_text, dhcp_text),
            (stats(1, 1), ndp_text, dhcp_text + dhcp_text),
            (stats(1, 1), ndp_text, dhcp_text.replace(b, 'unknown'))):
        try:
            verify_capture(st, n, d)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid capture accepted')
    print('WIRED_PROVISIONING_SPLIT_SELFTEST_PASS')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ndp', type=Path)
    p.add_argument('--dhcp', type=Path)
    p.add_argument('--selftest', action='store_true')
    p.add_argument('--verify-status', type=Path)
    a = p.parse_args()
    if a.selftest:
        selftest()
        return
    if not a.ndp or not a.dhcp:
        p.error('both output paths required')
    if a.verify_status:
        verify_capture(a.verify_status.read_text(), a.ndp.read_text(), a.dhcp.read_text())
        return
    with a.ndp.open('x') as ndp, a.dhcp.open('x') as dhcp:
        for line in sys.stdin:
            kind, row = split_line(line)
            (ndp if kind == 'ndp' else dhcp).write('\t'.join(row) + '\n')


if __name__ == '__main__':
    main()
