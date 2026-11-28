#!/usr/bin/env python3
"""Analyze independent sender and receiver intervals in sealed load evidence."""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import runpy
import statistics

here = Path(__file__).parent
spec = importlib.util.spec_from_file_location('load_result', here / 'load-result.py')
load = importlib.util.module_from_spec(spec)
spec.loader.exec_module(load)
seal = runpy.run_path(str(here / 'verify-wbm-parent.py'))['seal']
require = load.require


def intervals(report, endpoint, direction):
    sender = (endpoint == 'asus') == (direction == 'downlink')
    sockets = {c['socket']: c['local_port' if endpoint == 'asus' else 'remote_port']
               for c in report['start']['connected']}
    rows = []
    flow_ports = None
    last = None
    measuring = False
    for interval in report['intervals']:
        streams = [s for s in interval['streams'] if s['sender'] == sender]
        require(len(streams) == 4 and len({s['socket'] for s in streams}) == 4,
                'incomplete interval stream group')
        ports = {sockets[s['socket']] for s in streams}
        require(flow_ports is None or ports == flow_ports, 'changed stream group')
        flow_ports = ports
        suffix = '_bidir_reverse' if direction == 'uplink' and report['start']['test_start']['bidir'] else ''
        total = interval['sum' + suffix]
        require(total['sender'] == sender and all(s['omitted'] == total['omitted'] for s in streams),
                'interval direction or omit mismatch')
        if total['omitted']:
            require(not measuring, 'omit interval after measurement start')
            continue
        measuring = True
        secs = total['seconds']
        start, end = total['start'], total['end']
        require(all(math.isfinite(x) for x in (start, end, secs)) and
                0 < secs <= 5 and end > start and
                (last is None or abs(start-last) < .02), 'invalid interval coverage')
        last = end
        require(total['bytes'] == sum(s['bytes'] for s in streams) and total['bytes'] >= 0,
                'interval byte totals disagree')
        require(math.isclose(total['bits_per_second'], total['bytes']*8/secs,
                             rel_tol=.001, abs_tol=.01), 'invalid interval rate')
        flows = {}
        for s in streams:
            require(s['bytes'] >= 0 and math.isfinite(s['seconds']) and s['seconds'] > 0,
                    'invalid stream interval')
            rec = dict(bytes=s['bytes'], mbps=s['bytes']*8/s['seconds']/1e6)
            if sender:
                require(all(isinstance(s[k], int) and s[k] >= 0
                            for k in ('retransmits', 'rtt', 'snd_cwnd', 'snd_wnd')),
                        'invalid TCP sender telemetry')
                rec.update(retransmits=s['retransmits'], rtt_ms=s['rtt']/1000,
                           cwnd_bytes=s['snd_cwnd'], rwnd_bytes=s['snd_wnd'])
            flows[str(sockets[s['socket']])] = rec
        row = dict(start_s=start, end_s=end, duration_s=secs, bytes=total['bytes'],
                   mbps=total['bits_per_second']/1e6, flows=flows)
        if sender:
            require(total['retransmits'] == sum(s['retransmits'] for s in streams),
                    'interval retransmit totals disagree')
            row['retransmits'] = total['retransmits']
            row['median_rtt_ms'] = statistics.median(s['rtt']/1000 for s in streams)
        rows.append(row)
    require(rows and sum(r['duration_s'] for r in rows) >= 13, 'incomplete measurement')
    duration = sum(r['duration_s'] for r in rows)
    mean = sum(r['bytes'] for r in rows)*8/duration/1e6
    result = dict(endpoint=endpoint, sender=sender, duration_s=duration, mean_mbps=mean,
                  weighted_stddev_mbps=math.sqrt(sum(r['duration_s']*(r['mbps']-mean)**2
                                                   for r in rows)/duration),
                  zero_progress_s=sum(r['duration_s'] for r in rows if r['bytes'] == 0),
                  minimum_interval_mbps=min(r['mbps'] for r in rows),
                  maximum_interval_mbps=max(r['mbps'] for r in rows), intervals=rows)
    if sender:
        result.update(retransmits=sum(r['retransmits'] for r in rows),
                      median_of_interval_rtt_ms=statistics.median(r['median_rtt_ms'] for r in rows))
    return result


def summarize(path, band, *, describe_unqualified=False):
    seal(path)
    status = (path/'status').read_text().strip()
    require(status == 'exit=0' or (describe_unqualified and status == 'exit=1'), 'unqualified run')
    require('verified=1' in (path/'client-restore-status.txt').read_text().splitlines(),
            'client restoration not verified')
    prefix = path / f'band-{band}'
    tag = Path(f'{prefix}.tag').read_text().strip()
    archive = load.load_archive(f'{prefix}.client.tar', tag)
    qualified = load.summarize(f'{prefix}.client.tar', tag, prefix,
                               describe_unqualified=describe_unqualified)
    result = {}
    for mode in load.MODES:
        asus = json.loads(Path(f'{prefix}.load-{mode}.json').read_text())
        wyse = json.loads(archive[f'load-{mode}.server.json.txt'])
        result[mode] = {}
        for direction in ('uplink', 'downlink'):
            if direction not in qualified['cases'][mode]:
                continue
            a = intervals(asus, 'asus', direction)
            w = intervals(wyse, 'wyse', direction)
            tx, rx = (a, w) if direction == 'downlink' else (w, a)
            require(tx['sender'] and not rx['sender'] and
                    tx['intervals'][0]['flows'].keys() == rx['intervals'][0]['flows'].keys(),
                    'endpoint stream identities disagree')
            result[mode][direction] = dict(sender=tx, receiver=rx,
                    qualified=qualified['cases'][mode][direction])
    return dict(path=str(path), band=band, phases=result,
                qualified=status == 'exit=0' and qualified['qualified'], outer_status=status,
                client_gates=qualified['client_gates'], pre_load=qualified['pre_load'],
                post_load=qualified['post_load'],
                note='Local iperf interval clocks are independent; do not align endpoint intervals by index.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--band', choices=('24', '5'), required=True)
    parser.add_argument('--describe-unqualified', action='store_true')
    args = parser.parse_args()
    print(json.dumps(summarize(args.run.resolve(), args.band,
                               describe_unqualified=args.describe_unqualified), indent=2))


if __name__ == '__main__':
    main()
