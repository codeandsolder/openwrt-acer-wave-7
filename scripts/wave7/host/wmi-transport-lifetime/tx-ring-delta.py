#!/usr/bin/env python3
"""Compare logical TX ring counters from two same-boot AP snapshots."""
import argparse
import json
from pathlib import Path
import re

IPQ = 'ahb-c000000.wifi'
QCN = 'ahb-soc@0:wifi'
DEVICE = f'===/sys/kernel/debug/ath12k/{IPQ}/device_dp_stats'
FIELDS = {'tx_enqueued', 'tx_completed'}


def parse(text, device=IPQ):
    marker = f'===/sys/kernel/debug/ath12k/{device}/device_dp_stats'
    lines = text.splitlines()
    if len(lines) < 3 or not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', lines[0]):
        raise ValueError('missing boot ID')
    if lines.count(marker) != 1:
        raise ValueError(f'missing or duplicate {device}')
    values = {}
    start = lines.index(marker) + 1
    for line in lines[start:]:
        if line.startswith('==='):
            break
        if match := re.fullmatch(r'(tx_enqueued|tx_completed):\s+((?:\d+:\d+\s*)+)', line):
            pairs = [tuple(map(int, p.split(':'))) for p in match[2].split()]
            if match[1] in values or [i for i, _ in pairs] != list(range(4)):
                raise ValueError('invalid ring matrix')
            values[match[1]] = [v for _, v in pairs]
        if match := re.fullmatch(r'radio0 tx_pending: (\d+)', line):
            if 'pending' in values:
                raise ValueError('duplicate pending counter')
            values['pending'] = int(match[1])
    if values.keys() != FIELDS | {'pending'}:
        raise ValueError('incomplete snapshot')
    return lines[0], float(lines[1].split()[0]), values


def compare(before, after, device=IPQ):
    boot, start, a = parse(before, device)
    boot_end, end, b = parse(after, device)
    if boot != boot_end or not start < end:
        raise ValueError('snapshots not from a continuous boot')
    rings = []
    for i in range(4):
        queued = b['tx_enqueued'][i] - a['tx_enqueued'][i]
        completed = b['tx_completed'][i] - a['tx_completed'][i]
        if min(queued, completed) < 0:
            raise ValueError('counter decreased')
        rings.append(dict(tcl=i, queued=queued, completed=completed))
    return dict(boot=boot, start_s=start, end_s=end, pending_before=a['pending'],
                pending_after=b['pending'], rings=rings,
                ring3_exercised=rings[3]['queued'] > 0 and rings[3]['completed'] > 0,
                drained=b['pending'] == 0)



def completion_irqs(text):
    """Physical AHB interrupt lines 1..4 correspond to logical TCL 0..3."""
    lines = text.splitlines()
    if not lines:
        raise ValueError('empty interrupt snapshot')
    cpus = lines[0].split()
    if not cpus or not all(re.fullmatch(r'CPU\d+', cpu) for cpu in cpus):
        raise ValueError('missing interrupt CPU columns')
    counts = {}
    for line in lines[1:]:
        if m := re.fullmatch(r'\s*\d+:\s+(.*?)\s+wbm2host-tx-completions-ring([1-4])\s*', line):
            ring = int(m[2]) - 1
            fields = m[1].split()
            if ring in counts or len(fields) < len(cpus) + 1:
                raise ValueError('duplicate or invalid completion IRQ')
            counts[ring] = sum(map(int, fields[:len(cpus)]))
    if counts.keys() != set(range(4)):
        raise ValueError('missing completion IRQ')
    return cpus, counts


def irq_delta(before, after):
    a_cpu, a = completion_irqs(before)
    b_cpu, b = completion_irqs(after)
    if a_cpu != b_cpu or any(b[i] < a[i] for i in a):
        raise ValueError('interrupt counter discontinuity')
    return {i: b[i] - a[i] for i in a}


def selftest():
    base = '96f67cfc-e011-49e1-aff7-1832e25fcf3e\n1.0 2.0\n' + DEVICE + '\ntx_enqueued: 0:0 1:0 2:0 3:0\ntx_completed: 0:0 1:0 2:0 3:0\nradio0 tx_pending: 0\n'
    good = base.replace('1.0 2.0', '2.0 4.0').replace('3:0', '3:10')
    assert compare(base, good)['ring3_exercised']
    assert compare(base, good)['drained']
    bad = good.replace('tx_completed: 0:0 1:0 2:0 3:10', 'tx_completed: 0:0 1:0 2:0 3:0').replace('pending: 0','pending: 10')
    assert not compare(base, bad)['ring3_exercised']
    assert not compare(base, bad)['drained']
    for invalid in (good.replace('3:10', '2:10'), good.replace('96f67cfc','86f67cfc'), base):
        try:
            compare(base, invalid)
        except ValueError:
            pass
        else:
            raise AssertionError('accepted invalid snapshot')
    irq = ' CPU0 CPU1 CPU2 CPU3\n' + ''.join(f'{60+i}: 0 0 0 0 GIC-0 {479+i} Edge wbm2host-tx-completions-ring{i+1}\n' for i in range(4))
    more = irq.replace('63: 0 0 0 0', '63: 1 2 3 4')
    assert irq_delta(irq, more) == {0: 0, 1: 0, 2: 0, 3: 10}
    for invalid in (irq.replace('ring4', 'ring3'), irq.replace(' CPU3', '')):
        try:
            irq_delta(irq, invalid)
        except ValueError:
            pass
        else:
            raise AssertionError('accepted invalid IRQ snapshot')
    print('TX_RING_DELTA_SELFTEST_PASS')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('before', nargs='?', type=Path)
    p.add_argument('after', nargs='?', type=Path)
    p.add_argument('--selftest', action='store_true')
    p.add_argument('--require-ring3', action='store_true')
    p.add_argument('--device', choices=(IPQ, QCN), default=IPQ)
    p.add_argument('--irq-before', type=Path)
    p.add_argument('--irq-after', type=Path)
    a = p.parse_args()
    if a.selftest:
        selftest()
    elif a.before and a.after:
        report = compare(a.before.read_text(), a.after.read_text(), a.device)
        if bool(a.irq_before) != bool(a.irq_after):
            p.error('provide both IRQ snapshots')
        if a.irq_before and a.device != IPQ:
            p.error('fixed AHB completion IRQ counters belong to IPQ5332')
        if a.irq_before:
            report['irq_delta'] = irq_delta(a.irq_before.read_text(), a.irq_after.read_text())
        print(json.dumps(report, indent=2))
        if not report['drained'] or (a.require_ring3 and (not report['ring3_exercised'] or (a.device == IPQ and report.get('irq_delta', {}).get(3, 0) <= 0))):
            raise SystemExit(1)
    else:
        p.error('provide both snapshots or --selftest')
