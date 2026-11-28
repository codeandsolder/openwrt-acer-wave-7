#!/usr/bin/env python3
"""Deterministic tests for sampled datapath evidence, including bad seals."""
import importlib.util
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('series', Path(__file__).with_name('load-series.py'))
series = importlib.util.module_from_spec(spec)
spec.loader.exec_module(series)
BOOT = '96f67cfc-e011-49e1-aff7-1832e25fcf3e'


def row(i):
    start = 10 + i * 1.05
    lines = [f'LOAD_SAMPLE {i} {start:.2f}', '==== CPU',
             f'cpu0 {i*10} 0 {i*10} {i*70} 0 0 {i*10} 0 0 0']
    for device in series.DEVICES:
        lines += [f'==== /sys/kernel/debug/ath12k/{device}/device_dp_stats',
                  f'err ring pkts: {i}', 'Invalid RBM: 0', 'RXDMA errors:', 'FCS: 0',
                  'REO errors:', f'Frame OOR: {2*i}', f'BA dup: {i}',
                  'HAL REO errors:', 'ring0: 0', 'DEVICE TX STATS:',
                  f'tx_enqueued: 0:{i*11} 1:0 2:0 3:0',
                  f'tx_completed: 0:{i*10} 1:0 2:0 3:0',
                  f'radio0 tx_pending: {i}', 'REO Rx Received:', f'Ring1: 0:{i*100}',
                  'REO excep MSDU buf type:0', 'Rx WBM REL SRC Errors:', 'Reo: 0:0']
    lines += ['==== SRNG', 'rx_release=5 rx_rbm=10 rx_buffer_rbm=10']
    for ring in range(4):
        ptr = i * 8
        lines += [f'map tcl={ring} wbm={ring} rbm={ring+5}',
                  f'TCL{ring} id={24+ring} hp={ptr+8} tp={ptr} sw={ptr+8} shadow={ptr} cached={ptr} entry=8 size=4096',
                  f'WBM{ring} id={128+ring} hp={ptr} tp={ptr} sw={ptr} shadow={ptr} cached={ptr} entry=8 size=4096']
    lines += ['WBM_RX5 id=133 hp=0 tp=0 sw=0 shadow=0 cached=0 entry=8 size=8192',
              f'LOAD_SAMPLE_END {i} {start+.05:.2f}']
    if i == 0:
        lines += ['LOAD_SERIES_READY']
    return '\n'.join(lines)


text = '\n'.join([f'LOAD_SERIES_BEGIN boot={BOOT} samples=25',
                  *(row(i) for i in range(25)), f'LOAD_SERIES_END boot={BOOT} samples=25'])
boot, samples = series.parse(text)
assert boot == BOOT and len(samples) == 25
r = series.interval(*samples[:2])
assert r['cpu'][0] == dict(busy_pct=30, softirq_pct=10)
assert r['ipq_ring_samples']['TCL0']['sampled_fill'] == 1
assert r['radios'][series.DEVICES[0]]['rx_received'] == 100
assert r['radios'][series.DEVICES[1]]['reo_oor'] == 2
assert r['radios'][series.DEVICES[1]]['ba_duplicates'] == 1
assert r['radios'][series.DEVICES[0]]['tx_enqueued'][0] == 11
with patch.object(series.load, 'compare', return_value={'radio': {'boot': BOOT, 'start_s': 9.9, 'end_s': 27.1}}):
    result = series.summarize(text, '', '')
assert len(result['intervals']) == 16 and len(result['all_intervals']) == 24
assert result['trailing_unsampled_s'] < 1
for invalid in (
        text.replace('LOAD_SAMPLE 1 ', 'LOAD_SAMPLE 0 ', 1),
        text.replace('LOAD_SAMPLE_END 0 10.05', 'LOAD_SAMPLE_END 0 11.05', 1),
        text.replace('LOAD_SERIES_READY\n', '', 1),
        text.replace('LOAD_SERIES_END', 'LOAD_SERIES_ERROR'),
        text.replace('==== SRNG\n', '==== CPU\n', 1),
        text.replace('TCL0 id=24 hp=8', 'TCL0 id=24 hp=9', 1),
        text.replace('radio0 tx_pending: 0\n', '', 1),
        text.replace('cpu0 0 0 0 0 0 0 0 0 0 0\n', '', 1)):
    try:
        series.parse(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError('bad series accepted')
for invalid in (
        {'boot': BOOT, 'start_s': 9.9, 'end_s': 40},
        {'boot': BOOT, 'start_s': 1, 'end_s': 27},
        {'boot': '86' + BOOT[2:], 'start_s': 9.9, 'end_s': 27}):
    with patch.object(series.load, 'compare', return_value={'radio': invalid}):
        try:
            series.summarize(text, '', '')
        except ValueError:
            pass
        else:
            raise AssertionError('bad phase accepted')
try:
    series.interval(samples[1], samples[0])
except ValueError:
    pass
else:
    raise AssertionError('counter reset accepted')
print('LOAD_SERIES_SELFTEST_PASS 2 valid 12 invalid')
