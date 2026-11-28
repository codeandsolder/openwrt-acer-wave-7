#!/usr/bin/env python3
"""Validate opt-in AP load samples and correlate host service with radio progress.

The counters and hardware pointers are not atomically sampled. Report their
actual read windows, not a fictional simultaneous queue conservation proof.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import re


def helper(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


load = helper('load-ap-delta')
srng = helper('srng-pointer-delta')
tx = srng.tx
require = load.require
SAMPLES = 120
DEVICES = (tx.IPQ, tx.QCN)
PATHS = {f'/sys/kernel/debug/ath12k/{d}/device_dp_stats' for d in DEVICES}
STAMP = r'(\d+\.\d+)'


def sample(boot, start, end, lines):
    sections, section = {}, None
    for line in lines:
        if line.startswith('==== '):
            section = line[5:]
            require(section not in sections, 'duplicate sample section')
            sections[section] = []
        else:
            require(section is not None, 'missing sample section')
            sections[section].append(line)
    require(sections.keys() == PATHS | {'CPU', 'SRNG'}, 'incomplete sample sections')
    cpu = {}
    for line in sections['CPU']:
        if m := load.CPU.fullmatch(line):
            index = int(m[1])
            fields = tuple(map(int, m[2].split()))
            require(index not in cpu and len(fields) >= 8, 'invalid CPU sample')
            cpu[index] = fields[:8]
    require(cpu and sorted(cpu) == list(range(len(cpu))), 'incomplete CPU sample')
    header = [boot, f'{start} 0']
    raw = '\n'.join(header + [line for path in sorted(PATHS)
                              for line in ['===' + path, *sections[path]]])
    _, _, rx = load.rx.parse(raw)
    logical = {d: tx.parse(raw, d)[2] for d in DEVICES}
    _, _, release, mapping, rings = srng.parse('\n'.join(header + sections['SRNG']))
    return dict(start_s=start, end_s=end, cpu=cpu, rx=rx, tx=logical,
                release=release, mapping=mapping, rings=rings)


def parse(text):
    lines = iter(text.splitlines())
    begin = re.fullmatch(r'LOAD_SERIES_BEGIN boot=([0-9a-f-]{36}) samples=120', next(lines, ''))
    require(begin and load.rx.BOOT.fullmatch(begin[1]), 'missing load series identity')
    boot = begin[1]
    samples = []
    for i in range(SAMPLES):
        start = re.fullmatch(rf'LOAD_SAMPLE {i} {STAMP}', next(lines, ''))
        require(start, 'missing sample or sequence')
        body = []
        for line in lines:
            if line.startswith('LOAD_SAMPLE_END '):
                break
            body.append(line)
        else:
            raise ValueError('incomplete sample')
        end = re.fullmatch(rf'LOAD_SAMPLE_END {i} {STAMP}', line)
        require(end, 'invalid sample closing marker')
        a, b = float(start[1]), float(end[1])
        require(0 <= a <= b and b - a <= .5, 'sample read window too wide')
        if samples:
            require(.9 <= a - samples[-1]['end_s'] <= 2, 'sample discontinuity')
        samples.append(sample(boot, a, b, body))
        if i == 0:
            require(next(lines, '') == 'LOAD_SERIES_READY', 'missing readiness')
    require(next(lines, '') == f'LOAD_SERIES_END boot={boot} samples=120' and next(lines, None) is None,
            'invalid closing series identity')
    return boot, samples


def interval(a, b):
    require(a['release'] == b['release'] and a['mapping'] == b['mapping'] and
            a['rings'].keys() == b['rings'].keys(), 'changed SRNG map')
    ticks = load.subtract(a['cpu'], b['cpu'])
    cpu = {}
    for index, counts in ticks.items():
        total = sum(counts)
        require(total > 0, 'empty CPU interval')
        cpu[index] = dict(busy_pct=100 * (total - counts[3] - counts[4]) / total,
                          softirq_pct=100 * counts[6] / total)
    radios = {}
    for d in DEVICES:
        rx = load.subtract(a['rx'][d], b['rx'][d])
        old, new = a['tx'][d], b['tx'][d]
        queued = load.subtract(dict(enumerate(old['tx_enqueued'])), dict(enumerate(new['tx_enqueued'])))
        completed = load.subtract(dict(enumerate(old['tx_completed'])), dict(enumerate(new['tx_completed'])))
        radios[d] = dict(tx_enqueued=queued, tx_completed=completed, pending=new['pending'],
                         rx_received=sum(v for k, v in rx.items() if k.startswith('REO Rx Received/')),
                         reo_oor=rx.get('REO errors/Frame OOR', 0),
                         ba_duplicates=rx.get('REO errors/BA dup', 0),
                         rx_errors={k: v for k, v in rx.items() if v and not k.startswith('REO Rx Received/')})
    occupancy = {}
    for name, old in a['rings'].items():
        new = b['rings'][name]
        require(all(old[k] == new[k] for k in ('id', 'entry', 'size')), 'changed SRNG geometry')
        occupancy[name] = dict(entries=new['size'] // new['entry'],
                               sampled_fill=(new['hp'] - new['tp']) % new['size'] // new['entry'],
                               hardware=new)
    return dict(start_s=a['start_s'], start_read_end_s=a['end_s'], end_s=b['start_s'],
                end_read_end_s=b['end_s'], cpu=cpu, radios=radios, ipq_ring_samples=occupancy)


def summarize(text, before, after):
    boot, samples = parse(text)
    phase = load.compare(before, after)
    start, end = phase['radio']['start_s'], phase['radio']['end_s']
    require(phase['radio']['boot'] == boot, 'series boot differs from phase')
    require(samples[0]['start_s'] <= start + 5 and samples[-1]['end_s'] >= end,
            'series does not cover load phase')
    rows = [interval(a, b) for a, b in zip(samples, samples[1:])]
    # One continuous observation spans all three TCP phases. Never count
    # inter-phase or idle-tail intervals as load. Report the edge gaps.
    contained = [r for r in rows if start <= r['start_s'] and r['end_read_end_s'] <= end]
    require(contained and contained[-1]['end_read_end_s'] - contained[0]['start_s'] >= .65 * (end - start),
            'insufficient sampled load coverage')
    return dict(boot=boot, phase_start_s=start, phase_end_s=end,
                leading_unsampled_s=contained[0]['start_s'] - start,
                trailing_unsampled_s=end - contained[-1]['end_read_end_s'],
                intervals=contained, all_intervals=rows,
                note='independent, non-atomic host counters and IPQ AHB ring pointer samples; not exact instantaneous occupancy')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('series', type=Path)
    p.add_argument('--before', required=True, type=Path)
    p.add_argument('--after', required=True, type=Path)
    args = p.parse_args()
    print(json.dumps(summarize(*(f.read_text() for f in (args.series, args.before, args.after))), indent=2))


if __name__ == '__main__':
    main()
