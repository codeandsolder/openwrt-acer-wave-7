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


def irq_profile(text, boot):
    """Attest the complete reversible IRQ profile, including boot and restore."""
    lines = text.splitlines()
    require(len(lines) == 14, 'incomplete IRQ profile')
    original, applied, restored = {}, {}, {}
    plan = {3: '1', 4: '2', 5: '3', 8: '2'}
    for line in lines[:4]:
        m = re.fullmatch(r'IRQ_PROFILE_ORIGINAL irq=(\d+) group=(\d+) configured=0-3 effective=0', line)
        require(m is not None, 'invalid original IRQ affinity')
        irq, group = map(int, m.groups())
        require(irq not in original and group in plan, 'unexpected IRQ group')
        original[irq] = group
    require(set(original.values()) == set(plan), 'incomplete IRQ group coverage')
    for line in lines[4:8]:
        m = re.fullmatch(r'IRQ_PROFILE_APPLIED irq=(\d+) cpu=([1-3])', line)
        require(m is not None, 'invalid applied IRQ affinity')
        irq, cpu = int(m[1]), m[2]
        require(irq in original and irq not in applied and cpu == plan[original[irq]], 'incorrect applied IRQ affinity')
        applied[irq] = cpu
    require(lines[8] == f'IRQ_PROFILE_READY boot={boot} seconds=335', 'IRQ profile boot mismatch')
    for line in lines[9:13]:
        m = re.fullmatch(r'IRQ_PROFILE_RESTORE irq=(\d+) configured=0-3 effective=0', line)
        require(m is not None, 'invalid restored IRQ affinity')
        irq = int(m[1])
        require(irq in applied and irq not in restored, 'unexpected restored IRQ')
        restored[irq] = '0'
    require(restored.keys() == applied.keys() and lines[13] == 'IRQ_PROFILE_END rc=0',
            'IRQ restore not attested')
    return applied


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
    profile = manifest.get('band_profile')
    if profile is not None:
        bands = runpy.run_path(str(Path(__file__).with_name('band-profile.py')))
        high, ch, width, center = bands['PROFILES'][profile]
        freq = (5000 if high == 5 else 5950) + 5*ch
        require(ap_geometry[1] == 'channel 1 (2412 MHz), width: 20 MHz, center1: 2412 MHz' and
                ap_geometry[4] == f'channel {ch} ({freq} MHz), width: {width} MHz, center1: {center} MHz',
                'unexpected RF profile geometry')
        require(band in ('24', str(high)), 'wrong band label')
    else:
        require(band != '6', '6 GHz requires RF profile')
    pm = iperf.pm_values(archive['pm-selected.txt'])
    pm_profile = result['pm_load_profile']
    requested_pm = path / 'client-pm-profile.txt'
    require((requested_pm.read_text().strip() if requested_pm.exists() else None) == pm_profile,
            'requested client PM profile not attested')
    identity = dict(stack=stack, kernel=kernel[0], firmware=firmware[0], geometry=ap_geometry, wireless_policy=manifest['policy_sha256']['etc/config/wireless'],
                    preference=archive['association-preference.txt'], pm=pm, pm_control_profile=pm_profile,
                    variant=(path / 'client-variant.txt').read_text().strip(),
                    iperf_source=result['source'], active_link_mask=result['active_link_mask'], kernel_ap=state['kernel'], radio_ap=state['radio'])
    if profile is not None:
        identity['band_profile'] = profile
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
        identity[f'htt_rate_{mode}'] = 'htt_rate' in extra
        identity[f'htt_mlo_{mode}'] = 'htt_mlo' in extra
        identity[f'reo_command_{mode}'] = 'reo_command' in extra
        identity[f'tx_attempt_{mode}'] = 'tx_attempt' in extra
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
        if 'tx_attempt' in extra:
            phases[mode]['tx_attempt'] = extra['tx_attempt']
        if 'reo_command' in extra:
            phases[mode]['reo_command'] = extra['reo_command']
        if 'htt_rate' in extra:
            phases[mode]['htt_rate'] = extra['htt_rate']
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
    irq = Path(f'{prefix}.ap-irq-profile.txt')
    applied = irq_profile(irq.read_text(), boot) if irq.exists() else None
    if applied is not None:
        for mode in load.MODES:
            affinity = identity[f'affinity_{mode}']
            require(all(affinity.get(n) == cpu for n, cpu in applied.items()),
                    'measured affinity does not match applied IRQ profile')
    return dict(path=str(path), boot=boot, revision=state['rev'], image_sha256=manifest['image_sha256'],
                identity=identity, phases=phases, irq_profile=applied)


def compare(a, b, *, describe_unmatched=False, compare_pm=False, compare_irq=False):
    mismatches = sorted(k for k in a['identity'].keys() | b['identity'].keys()
                        if a['identity'].get(k) != b['identity'].get(k))
    if compare_pm:
        require(a.get('boot') == b.get('boot') and a.get('image_sha256') == b.get('image_sha256'),
                'PM contrast requires the same AP image and boot')
        require(mismatches == ['pm', 'pm_control_profile'] and all(
            x['identity'].get('pm_control_profile') in iperf.PM_POLICIES for x in (a,b)),
                f'PM contrast has uncontrolled differences: {mismatches}')
    elif compare_irq:
        require(a.get('boot') == b.get('boot') and a.get('image_sha256') == b.get('image_sha256'),
                'IRQ contrast requires the same AP image and boot')
        require(mismatches == sorted(['diagnostic_profiles', *(f'affinity_{mode}' for mode in load.MODES)]),
                f'IRQ contrast has uncontrolled differences: {mismatches}')
        require(a.get('irq_profile') is None and b.get('irq_profile'), 'missing IRQ experiment attestation')
        before, after = a['identity'], b['identity']
        require(sorted(before['diagnostic_profiles'] + ['irq-profile.txt']) == after['diagnostic_profiles'],
                'unexpected diagnostic profile changes')
        for mode in load.MODES:
            original, applied = before[f'affinity_{mode}'], after[f'affinity_{mode}']
            require(original.keys() == applied.keys() and all(v == '0' for v in original.values()),
                    'unexpected baseline affinity')
            require(applied == (original | b['irq_profile']), 'uncontrolled IRQ affinity changes')
    else:
        require(not mismatches or describe_unmatched, f'unmatched experimental conditions: {mismatches}')
    changes = {}
    for mode in load.MODES:
        p, q = a['phases'][mode], b['phases'][mode]
        changes[mode] = dict(goodput_pct={k: 100 * (q['directions'][k]['mbps'] / v['mbps'] - 1)
            for k, v in p['directions'].items()}, rtt_ms={family: {
                'before': p['latency'][family]['rtt_ms'], 'after': q['latency'][family]['rtt_ms']}
                for family in ('v4', 'v6')})
    return dict(matched=not mismatches, matched_except_pm=compare_pm, matched_except_irq=compare_irq, mismatches=mismatches,
                baseline=a, candidate=b, changes=changes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('candidate', type=Path, nargs='?')
    parser.add_argument('--describe-run', action='store_true', help='qualify a new independent baseline')
    parser.add_argument('--band', required=True, choices=('24', '5', '6'))
    parser.add_argument('--describe-unmatched', action='store_true',
                        help='report descriptive contrasts, explicitly identifying unmatched conditions')
    parser.add_argument('--candidate-band', choices=('24', '5', '6'),
                        help='explicitly unmatched cross-band contrast')
    parser.add_argument('--compare-pm', action='store_true',
                        help='compare explicit requested PM policies on the same AP boot')
    parser.add_argument('--compare-irq', action='store_true',
                        help='compare an attested reversible IRQ profile on the same AP boot')
    args = parser.parse_args()
    require(sum((args.compare_pm, args.compare_irq, args.describe_unmatched)) <= 1, 'choose one comparison mode')
    require(args.candidate_band is None or (args.describe_unmatched and not args.describe_run),
            'cross-band contrast must be explicitly unmatched')
    if args.describe_run:
        require(args.candidate is None and not args.describe_unmatched and not args.compare_pm and not args.compare_irq, 'baseline mode takes one run')
        print(json.dumps(read_run(args.baseline.resolve(), args.band), indent=2))
        return
    require(args.candidate is not None, 'comparison requires two runs')
    print(json.dumps(compare(read_run(args.baseline.resolve(), args.band),
                             read_run(args.candidate.resolve(), args.candidate_band or args.band),
                             describe_unmatched=args.describe_unmatched, compare_pm=args.compare_pm,
                             compare_irq=args.compare_irq), indent=2))


if __name__ == '__main__':
    main()
