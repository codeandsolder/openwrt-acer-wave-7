#!/usr/bin/env python3
"""Compare independently sealed, matched TCP load measurements across AP builds."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import runpy


def module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


load = module('load-ap-delta')
iperf = module('load-result')
seal = runpy.run_path(str(Path(__file__).with_name('verify-wbm-parent.py')))['seal']
require = load.require


def geometry(text):
    # iw reports the primary, center and width separately. An unchanged
    # 80 MHz block is not enough to establish the same control channel.
    lines = text.splitlines()
    require(lines.count('Interface ap-mld0') == 1, 'ambiguous AP interface')
    lines = lines[lines.index('Interface ap-mld0') + 1:]
    values = [v.strip() for v in lines if re.fullmatch(
        r'\s+(?:- link ID .*|channel .*|txpower .*|Radios: .*)', v)]
    require(len(values) == 7, 'missing AP link geometry')
    for link, offset in ((0, 0), (1, 3)):
        require(re.fullmatch(rf'- link ID\s+{link} link addr (?:[0-9a-f]{{2}}:){{5}}[0-9a-f]{{2}}',
                             values[offset]), 'unexpected AP link identity')
        require(re.fullmatch(r'channel \d+ \(\d+ MHz\), width: \d+ MHz, center1: \d+ MHz(?:, center2: \d+ MHz)?',
                             values[offset + 1]), 'malformed AP channel geometry')
        require(re.fullmatch(r'txpower -?\d+\.\d+ dBm', values[offset + 2]), 'malformed AP txpower')
    require(values[6] == 'Radios: 0 1', 'unexpected AP radio mapping')
    return values


def survey_geometry(lines):
    # Counter qualification is independent of geometry qualification.
    # A rejected firmware survey must not hide a changed primary channel.
    result = []
    for side in ('BEFORE', 'AFTER'):
        marker, end = f'GEOMETRY_{side}', f'GEOMETRY_{side}_END rc=0'
        require(lines.count(marker) == lines.count(end) == 1,
                'missing or failed survey geometry observation')
        i, j = lines.index(marker), lines.index(end)
        require(i < j, 'misordered survey geometry observation')
        result.append(geometry('\n'.join(lines[i+1:j])))
    require(result[0] == result[1], 'geometry changed during survey')
    return result[0]


def read_run(path, band):
    names = seal(path)
    prefix = path / f'band-{band}'
    require((path / 'status').read_text().strip() == 'exit=0', 'failed run')
    require('verified=1' in (path / 'client-restore-status.txt').read_text().splitlines(),
            'client restoration not verified')
    require('STACK_ORIGINAL_PASS' in (path / 'client-original-after.txt').read_text(),
            'client restoration not attested')
    tag = Path(f'{prefix}.tag').read_text().strip()
    archive = iperf.load_archive(f'{prefix}.client.tar', tag)
    result = iperf.summarize(f'{prefix}.client.tar', tag, prefix)
    stack = dict(re.findall(r'^candidate (\w+) sha256=([0-9a-f]{64})$', archive['module-stack.txt'], re.M))
    require(stack.keys() == {'mt76', 'mt76_connac_lib', 'mt792x_lib', 'mt7925_common', 'mt7925e'} and
            'STACK_CANDIDATE_PASS' in archive['module-stack.txt'], 'missing client module identity')
    kernel = re.findall(r'^kernel=(\S+)$', archive['firmware.txt'], re.M)
    firmware = sorted(set(re.findall(r'WM Firmware Version: (.*)$', archive['firmware.txt'], re.M)))
    require(len(kernel) == 1 and len(firmware) == 1, 'ambiguous client firmware')
    before = (path / 'ap-before.txt').read_text()
    boot = before.splitlines()[0]
    ap_geometry = geometry(before)
    state = dict(line.split('=', 1) for line in (path.parent / 'last-state.txt').read_text().splitlines())
    manifest = json.loads((path.parents[2] / 'native-manifest.json').read_text())
    require(state['boot'] == boot and state['rev'] == manifest['revision'] and
            state['builder'] == manifest['builder_commit'] and
            (path.parent / 'status').read_text().strip() == 'SOAK_PASS', 'AP identity mismatch')
    pm = dict(re.findall(r'^(runtime-pm|deep-sleep|idle-timeout)=(\d+)$', archive['pm-selected.txt'], re.M))
    require(len(pm) == 3, 'missing client power settings')
    identity = dict(stack=stack, kernel=kernel[0], firmware=firmware[0], geometry=ap_geometry, wireless_policy=manifest['policy_sha256']['etc/config/wireless'],
                    preference=archive['association-preference.txt'], pm=pm,
                    variant=(path / 'client-variant.txt').read_text().strip(),
                    iperf_source=result['source'], active_link_mask=result['active_link_mask'], kernel_ap=state['kernel'], radio_ap=state['radio'])
    phases = {}
    for mode in load.MODES:
        pre = Path(f'{prefix}.load-{mode}-ap-before.txt').read_text()
        post = Path(f'{prefix}.load-{mode}-ap-after.txt').read_text()
        for snapshot in (pre, post):
            _, sections = load.sections(snapshot)
            if 'CHANNEL_SURVEY' in sections:
                require(survey_geometry(sections['CHANNEL_SURVEY']) == ap_geometry,
                        'AP geometry changed from preflight')
        d = load.compare(pre, post)
        require(d['radio']['boot'] == boot, 'phase boot mismatch')
        extra = d['extra']
        require('affinity' in extra, 'missing effective IRQ affinity')
        identity[f'affinity_{mode}'] = extra['affinity']
        identity[f'link_stats_{mode}'] = 'link_station' in extra
        identity[f'rx_error_stats_{mode}'] = 'rx_error_attribution' in extra
        identity[f'channel_survey_{mode}'] = 'channel_survey' in extra
        identity[f'htt_tx_{mode}'] = 'htt_tx' in extra
        identity[f'htt_mlo_{mode}'] = 'htt_mlo' in extra
        identity[f'reo_command_{mode}'] = 'reo_command' in extra
        traffic = result['cases'][mode]
        station = d['station_delta']
        reo = {}
        for dev, counters in d['radio']['increments'].items():
            received = sum(v for k, v in counters.items() if k.startswith('REO Rx Received/'))
            oor = counters.get('REO errors/Frame OOR', 0)
            reo[dev] = dict(received=received, oor=oor, ba_dup=counters.get('REO errors/BA dup', 0),
                            oor_per_1000_received=1000 * oor / received if received else None)
        directions = {}
        for direction in ('uplink', 'downlink'):
            if direction in traffic:
                t = traffic[direction]
                directions[direction] = dict(mbps=t['receiver_mbps'], retransmits=t['sender_retransmits'],
                    retransmits_per_MiB=t['sender_retransmits'] * 2**20 / t['receiver_bytes'])
        phases[mode] = dict(directions=directions, latency=traffic['latency'], reo=reo,
                            tx_failed=station['tx failed'], tx_packets=station['tx packets'],
                            tx_failed_per_1000=1000 * station['tx failed'] / station['tx packets'] if station['tx packets'] else None,
                            tx_airtime_us=station['tx duration'], cpu=d['cpu'], cpu_cost=d['cpu_cost'],
                            rates=d['station_rates'])
        if 'reo_command' in extra:
            phases[mode]['reo_command'] = extra['reo_command']
        if 'htt_mlo' in extra:
            phases[mode]['htt_mlo'] = extra['htt_mlo']
        if 'htt_tx' in extra:
            phases[mode]['htt_tx'] = extra['htt_tx']
        if 'channel_survey' in extra:
            phases[mode]['channel_survey'] = extra['channel_survey']
    identity['diagnostic_profiles'] = sorted(n.split('.ap-', 1)[1] for n in names
        if n.startswith(f'band-{band}.ap-') and
        (n.endswith('-profile.txt') or n.endswith('-series.txt')))
    # AQL on/off, if used, must actually agree, not just share a filename.
    aql = Path(f'{prefix}.ap-aql-profile.txt')
    if aql.exists():
        m = re.search(r'^AQL_PROFILE_READY .* enabled=([01]) ', aql.read_text(), re.M)
        require(m, 'missing AQL profile state')
        identity['aql_enabled'] = int(m[1])
    return dict(path=str(path), boot=boot, revision=state['rev'], image_sha256=manifest['image_sha256'],
                identity=identity, phases=phases)


def compare(a, b, *, describe_unmatched=False):
    mismatches = sorted(k for k in a['identity'].keys() | b['identity'].keys()
                        if a['identity'].get(k) != b['identity'].get(k))
    require(not mismatches or describe_unmatched, f'unmatched experimental conditions: {mismatches}')
    changes = {}
    for mode in load.MODES:
        p, q = a['phases'][mode], b['phases'][mode]
        changes[mode] = dict(goodput_pct={k: 100 * (q['directions'][k]['mbps'] / v['mbps'] - 1)
            for k, v in p['directions'].items()}, rtt_ms={family: {
                'before': p['latency'][family]['rtt_ms'], 'after': q['latency'][family]['rtt_ms']}
                for family in ('v4', 'v6')})
    return dict(matched=not mismatches, mismatches=mismatches,
                baseline=a, candidate=b, changes=changes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('candidate', type=Path, nargs='?')
    parser.add_argument('--describe-run', action='store_true', help='qualify a new independent baseline')
    parser.add_argument('--band', required=True, choices=('24', '5'))
    parser.add_argument('--describe-unmatched', action='store_true',
                        help='report descriptive contrasts, explicitly identifying unmatched conditions')
    args = parser.parse_args()
    if args.describe_run:
        require(args.candidate is None and not args.describe_unmatched, 'baseline mode takes one run')
        print(json.dumps(read_run(args.baseline.resolve(), args.band), indent=2))
        return
    require(args.candidate is not None, 'comparison requires two runs')
    print(json.dumps(compare(read_run(args.baseline.resolve(), args.band),
                             read_run(args.candidate.resolve(), args.band),
                             describe_unmatched=args.describe_unmatched), indent=2))


if __name__ == '__main__':
    main()
