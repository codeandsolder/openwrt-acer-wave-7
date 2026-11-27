"""Strict metadata-only packet observer records and local clock mapping."""
import bisect
import ipaddress
import re


def require(ok, message):
    if not ok:
        raise ValueError(message)


def parse_observer(text, iface, label, decode):
    """Reject loss, bad clocks, unexpected interfaces and malformed records."""
    lines = text.splitlines()
    require(len(lines) >= 4, 'incomplete boundary observer')
    ready = re.fullmatch(rf'{label}_OBSERVER_READY iface=(\S+) ifindex=(\d+) duration=(\d+)', lines[0])
    end = re.fullmatch(rf'{label}_OBSERVER_END iface=(\S+) seen=(\d+) decoded=(\d+) malformed=(\d+) packets=(\d+) drops=(\d+)', lines[-1])
    require(ready and end and ready[1] == end[1] == iface and int(ready[2]) > 0,
            'boundary observer identity or markers')
    rows, clocks, link_downs = [], [], []
    for line in lines[1:-1]:
        fields = line.split()
        require(fields, 'empty boundary observer record')
        if fields[0] == f'{label}_LINK_DOWN':
            require(len(fields) == 3 and re.fullmatch(r'\d+\.\d+', fields[1]) and
                    fields[2] == f'ifindex={ready[2]}', 'invalid link-down witness')
            link_downs.append(float(fields[1]))
            continue
        if fields[0] == f'{label}_CLOCK':
            require(len(fields) == 4 and all(re.fullmatch(r'\d+\.\d+', f) for f in fields[1:]),
                    'invalid boundary clock')
            before, epoch, after = map(float, fields[1:])
            require(0 <= after - before < 0.05, 'uncertain boundary clock anchor')
            clocks.append(((before + after) / 2, epoch))
            continue
        require(len(fields) >= 6 and fields[0] == f'{label}_PACKET',
                'invalid boundary packet record')
        _, epoch, name, direction, ips, ipd, *metadata = fields
        require(name == iface and direction in {'tx', 'rx'} and re.fullmatch(r'\d+\.\d+', epoch),
                'invalid boundary packet interface or direction')
        for addr in (ips, ipd):
            ipaddress.IPv4Address(addr)
        rows.append(dict(epoch=float(epoch), interface=iface, direction=direction,
                         ipv4_src=ips, ipv4_dst=ipd, **decode(metadata)))
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
    if timestamp == mono[-1]:
        return clocks[-1][1]
    i = bisect.bisect_right(mono, timestamp) - 1
    require(i >= 0 and i + 1 < len(clocks), 'authorization outside clock capture')
    lo, hi = clocks[i:i + 2]
    require(0 < hi[0] - lo[0] < 2.5, 'clock sample gap')
    return lo[1] + (hi[1] - lo[1]) * (timestamp - lo[0]) / (hi[0] - lo[0])
