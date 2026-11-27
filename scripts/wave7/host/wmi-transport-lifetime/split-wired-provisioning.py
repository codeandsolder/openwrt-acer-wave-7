#!/usr/bin/env python3
"""Split metadata-only tshark field output into NDP and DHCPv4 records."""
import argparse
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
    print('WIRED_PROVISIONING_SPLIT_SELFTEST_PASS')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ndp', type=Path)
    p.add_argument('--dhcp', type=Path)
    p.add_argument('--selftest', action='store_true')
    a = p.parse_args()
    if a.selftest:
        selftest()
        return
    if not a.ndp or not a.dhcp:
        p.error('both output paths required')
    with a.ndp.open('x') as ndp, a.dhcp.open('x') as dhcp:
        for line in sys.stdin:
            kind, row = split_line(line)
            (ndp if kind == 'ndp' else dhcp).write('\t'.join(row) + '\n')


if __name__ == '__main__':
    main()
