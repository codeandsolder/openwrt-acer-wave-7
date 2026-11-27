#!/usr/bin/env python3
"""Require content-sealed, same-boot WBM qualification before TX publication trial."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy


def require(ok, message):
    if not ok:
        raise ValueError(message)


def seal(path):
    seen = set()
    for line in (path / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        require(re.fullmatch(r'[0-9a-f]{64}', digest) and name not in seen and '/' not in name, 'invalid seal')
        file = path / name
        require(file.is_file() and not file.is_symlink(), f'invalid evidence file {name}')
        with file.open('rb') as f:
            require(hashlib.file_digest(f, 'sha256').hexdigest() == digest, f'evidence hash mismatch {name}')
        seen.add(name)
    require(seen == {f.name for f in path.iterdir() if f.is_file() and f.name != 'SHA256SUMS'}, 'incomplete seal')
    return seen


def verify_ping(load, text, target, count):
    observation = load['ping'](text, count, strict=True)
    sequences = [int(n) for n in re.findall(rf'^\[[0-9.]+\] \d+ bytes from {re.escape(target)}: icmp_seq=(\d+)\b', text, re.M)]
    require(sorted(sequences) == list(range(1, count + 1)), f'incomplete or duplicate replies: {target}')
    return observation


def selftest():
    load = runpy.run_path(str(Path(__file__).with_name('load-result.py')))
    target = 'fd76:7::2'
    rows = [f'[100.1] 64 bytes from {target}: icmp_seq={i} ttl=64 time=1.0 ms' for i in range(1, 4)]
    footer = '3 packets transmitted, 3 received, 0% packet loss\nrtt min/avg/max/mdev = 1.0/1.0/1.0/0.0 ms'
    require(verify_ping(load, '\n'.join(rows + [footer]), target, 3)['received'] == 3, 'valid fixture rejected')
    for invalid in ([rows[0], rows[0], rows[2], footer], rows[1:] + [footer],
                    [r.replace(target, 'fd76:7::3') for r in rows] + [footer],
                    rows + [footer.replace('3 received', '2 received')]):
        try:
            verify_ping(load, '\n'.join(invalid), target, 3)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid hold accepted')
    print('WBM_QUALIFICATION_SELFTEST_PASS')


RECONNECT_VARIANTS = {
    'band-group-refresh': 'upstream-prefix22-authorize-delayed-links-reconnect-band-group-refresh-trace',
    'teardown-privilege': 'upstream-prefix22-authorize-delayed-links-reconnect-teardown-privilege-trace',
    'roc-window': 'upstream-prefix22-authorize-delayed-links-reconnect-roc-window-trace',
}


def verified(path, boot, band, reconnect, reconnect_variant='band-group-refresh'):
    names = seal(path)
    prefix = f'band-{band}'
    required = {'status', 'client-restore-status.txt', 'client-original-after.txt', 'client-variant.txt',
                f'{prefix}.tag', f'{prefix}.client.tar', f'{prefix}.client-exit.txt',
                f'{prefix}.tx-ring-delta.json', f'{prefix}.qcn-tx-ring-delta.json',
                f'{prefix}.srng-delta.json', f'{prefix}.rx-delta.json'}
    require(required <= names, f'missing evidence: {required - names}')
    require((path / 'status').read_text().strip() == 'exit=0', 'client test failed')
    require('verified=1' in (path / 'client-restore-status.txt').read_text().splitlines(), 'restore not verified')
    require('STACK_ORIGINAL_PASS' in (path / 'client-original-after.txt').read_text(), 'original stack not attested')
    require((path / f'{prefix}.client-exit.txt').read_text().strip() == '0', 'client exit failed')
    variant = RECONNECT_VARIANTS[reconnect_variant] if reconnect else 'upstream-prefix22-authorize-single-link-trace'
    require((path / 'client-variant.txt').read_text().strip() == variant, 'wrong client variant')
    rings = []
    for kind in ('tx-ring-delta', 'qcn-tx-ring-delta'):
        data = json.loads((path / f'{prefix}.{kind}.json').read_text())
        require(data['boot'] == boot and data['drained'] and data['pending_after'] == 0, 'not same-boot drained')
        require([r['tcl'] for r in data['rings']] == list(range(4)), 'invalid logical ring list')
        require(sum(r['queued'] for r in data['rings']) + data['pending_before'] == sum(r['completed'] for r in data['rings']), 'TX conservation failed')
        if not reconnect:
            require(data['pending_before'] == 0 and data['rings'][3]['queued'] == data['rings'][3]['completed'] > 0, 'TCL3 not exercised')
            if kind == 'tx-ring-delta':
                require(data['irq_delta']['3'] > 0, 'fourth completion interrupt missing')
        rings.append(data)
    physical = json.loads((path / f'{prefix}.srng-delta.json').read_text())
    require(physical['boot'] == boot and set(physical['correlation']) == set('0123'), 'physical evidence mismatch')
    if not reconnect:
        r = physical['correlation']['3']
        require(r['physical'] == 3 and r['rbm'] == 8 and r['queued'] == r['completed'] == rings[0]['rings'][3]['queued'] > 0 and r['tcl_produced_matches'] and r['wbm_consumed_matches'] and r['drained'], 'TCL3 physical proof absent')
    rx = json.loads((path / f'{prefix}.rx-delta.json').read_text())
    require(rx['boot'] == boot and set(rx['increments']) == {'ahb-c000000.wifi', 'ahb-soc@0:wifi'} and all(d.get('RX totals/Invalid RBM', 0) == 0 for d in rx['increments'].values()), 'invalid RX RBM increments')
    tag = (path / f'{prefix}.tag').read_text().strip()
    require(re.fullmatch(r'0498-\d{8}-\d{6}', tag), 'invalid client archive tag')
    load = runpy.run_path(str(Path(__file__).with_name('load-result.py')))
    archive = load['load_archive'](path / f'{prefix}.client.tar', tag)
    def read(name):
        return archive[name].strip()
    require(read('status') == 'exit=0', 'client archive status failed')
    result = {'path': str(path), 'band': band, 'reconnect': reconnect,
              'ipq_tx': sum(r['completed'] for r in rings[0]['rings']),
              'qcn_tx': sum(r['completed'] for r in rings[1]['rings']),
              'ring3_exercised': [r['rings'][3]['queued'] > 0 for r in rings]}
    holds = [{'192.168.76.1': 'short-hold-1.txt', '192.168.76.2': 'short-hold-2.txt'}]
    if reconnect:
        require(read('reconnect-count.txt') == 'expected=2' and
                read('reconnect-cycles.txt') == 'cycle=1 result=pass\ncycle=2 result=pass' and
                read('reconnect-result.txt') == 'reconnect_pass=1', 'reconnect cycles incomplete')
        require(read('short-dual-hold-result.txt') == 'short_dual_hold_pass=1', 'initial dual hold failed')
        holds[0]['fd76:7::2'] = 'short-hold-v6.txt'
        timings = []
        for cycle in (1, 2):
            cycle_prefix = 'reconnect' if cycle == 1 else 'reconnect-2'
            hold_prefix = 'reconnect-hold' if cycle == 1 else 'reconnect-hold-2'
            holds.append({'192.168.76.1': f'{hold_prefix}-ap.txt',
                          '192.168.76.2': f'{hold_prefix}-asus.txt',
                          'fd76:7::2': f'{hold_prefix}-v6.txt'})
            for phase in ('before', 'after'):
                load['check_link'](read(f'{cycle_prefix}-links-{phase}.txt'))
            timing = re.fullmatch(r'down_start=(\d+\.\d+)\nup_start=(\d+\.\d+)\nup_complete=(\d+\.\d+) rc=0',
                                  read(f'{cycle_prefix}-timing.txt'))
            require(timing, 'incomplete reconnect timing')
            down, up, complete = map(float, timing.groups())
            require(down <= up <= complete and (not timings or down >= timings[-1]['completed_epoch']),
                    'invalid reconnect clock order')
            timings.append({'activation_s': round(complete - up, 3), 'completed_epoch': complete})
        result['reconnect_timing'] = timings
        for name in ('early-only-snapshot.txt', 'early-only-final.txt'):
            require(all(re.search(rf'^mac80211_{key}=0x0*{value}$', read(name), re.M)
                        for key, value in (('active_links', 3), ('valid_links', 3), ('dormant_links', 0))),
                    'initial hold missing dual-link state')
        # The two observed station lifetimes must agree; the AP final lifetime
        # may be right-censored, which is not evidence of peer retirement.
        helpers = runpy.run_path(str(Path(__file__).with_name('summarize-reconnect-datapath.py')))
        trace_names = [f'{prefix}.{side}-control-trace.txt' for side in ('client', 'ap')]
        lifecycle = f'{prefix}.client-trace.txt'
        require(set(trace_names + [lifecycle]) <= names, 'missing lifetime evidence')
        client_trace, ap_trace = [(path / name).read_text() for name in trace_names]
        cw = helpers['parse_trace'](client_trace, 'client', 3)
        aw = helpers['parse_trace'](ap_trace, 'ap', 3, True)
        require(len(cw) == len(aw) == 3, 'wrong number of authorized lifetimes')
        bindings = helpers['wtbl_pair_bindings'](cw)
        memberships = helpers['mld_lifetimes'](helpers['mld_records'](client_trace), cw, client_trace)
        require(all(row['complete_pair'] is True for row in bindings), 'incomplete WTBL pair')
        require(all(row['membership_matches'] is True and row['record_retired'] is True for row in memberships),
                'scheduler membership/retirement incomplete')
        lifecycle_trace = (path / lifecycle).read_text()
        refresh = helpers['band_group_refresh_windows'](lifecycle_trace, client_trace, cw)
        require(all(all(move['group_refresh_before_sta'] for move in row['migrations']) for row in refresh),
                'BSS group refresh not acknowledged before station MLD update')
        if band == '24':
            require(all(row['migrations'] for row in refresh), '2.4 GHz-first band migration not exercised')
        result['lifetimes'] = {'client': len(cw), 'ap': len(aw),
                               'ap_right_censored': [row['right_censored'] for row in aw],
                               'wtbl_complete': [row['complete_pair'] for row in bindings],
                               'scheduler_retired': [row['record_retired'] for row in memberships],
                               'band_migrations': [len(row['migrations']) for row in refresh]}
        if reconnect_variant in {'teardown-privilege', 'roc-window'}:
            require(not any(row['right_censored'] for row in aw), 'AP peer not retired')
            evidence = helpers['teardown_tx_windows'](client_trace, lifecycle_trace, cw)
            require(not evidence['unassigned'] and not evidence['unmatched'],
                    'unassigned teardown TX evidence')
            result['teardown'] = []
            for w, row in zip(cw, evidence['windows'], strict=True):
                require(len(row['frames']) == row['acked'] == 1 and row['zero_attempts'] == 0,
                        'protected teardown not acknowledged exactly once')
                frame = row['frames'][0]
                grant = frame['privilege_witness']
                require(grant and frame.get('return', {}).get('count', 0) > 0,
                        'missing exact-band grant or token return')
                peers = [p for p in w['wtbl'] if p['stage'] == 7
                         and p['wcid'] == int(frame['wcid']) and p['link'] == int(frame['link'])]
                require(len(peers) == 1 and peers[0]['bss'] == int(grant['bss'])
                        and peers[0]['host_band'] == int(grant['dbdc']),
                        'grant does not belong to teardown peer')
                result['teardown'].append(dict(ack_ms=min(t['latency_ms'] for t in frame['tx_status']
                                                        if t['ack_error'] == '0'),
                                                token_ms=frame['return']['latency_ms'],
                                                band=int(grant['dbdc']), bss=int(grant['bss'])))
    else:
        require(read('short-hold-result.txt') == 'short_hold_all_replies=1', 'group test hold failed')
    result['holds'] = []
    for targets in holds:
        observations = {}
        for target, filename in targets.items():
            observations[target] = verify_ping(load, read(filename), target, 440)
        result['holds'].append(observations)
    return result



def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('boot', nargs='?')
    p.add_argument('--selftest', action='store_true')
    p.add_argument('group', type=Path, nargs='?')
    p.add_argument('--reconnect-variant', choices=RECONNECT_VARIANTS, default='band-group-refresh')
    p.add_argument('--reconnect24', type=Path)
    p.add_argument('--reconnect5', type=Path)
    a = p.parse_args()
    if a.selftest:
        selftest()
        return
    require(a.boot, 'boot ID required')
    require(re.fullmatch(r'[0-9a-f-]{36}', a.boot), 'invalid boot ID')
    require(a.group or a.reconnect24 or a.reconnect5, 'no test evidence selected')
    results = [verified(a.group, a.boot, '24', False)] if a.group else []
    for band, path in [('24', a.reconnect24), ('5', a.reconnect5)]:
        if path:
            results.append(verified(path, a.boot, band, True, a.reconnect_variant))
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
