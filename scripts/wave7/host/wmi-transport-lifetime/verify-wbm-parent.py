#!/usr/bin/env python3
"""Require content-sealed, same-boot WBM qualification before TX publication trial."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tarfile


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


def verified(path, boot, band, reconnect):
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
    variant = 'upstream-prefix22-authorize-delayed-links-reconnect-band-group-refresh-trace' if reconnect else 'upstream-prefix22-authorize-single-link-trace'
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
    with tarfile.open(path / f'{prefix}.client.tar') as tar:
        def read(name):
            member = tar.getmember(f'{tag}/{name}')
            require(member.isfile() and member.size < 100000, f'invalid client result {name}')
            return tar.extractfile(member).read().decode().strip()
        if reconnect:
            require(read('reconnect-count.txt') == 'expected=2' and read('reconnect-cycles.txt') == 'cycle=1 result=pass\ncycle=2 result=pass' and read('reconnect-result.txt') == 'reconnect_pass=1', 'reconnect cycles incomplete')
        else:
            require(read('short-hold-result.txt') == 'short_hold_all_replies=1', 'group test hold failed')
    return { 'path': str(path), 'band': band, 'reconnect': reconnect,
             'ipq_tx': sum(r['completed'] for r in rings[0]['rings']), 'qcn_tx': sum(r['completed'] for r in rings[1]['rings']) }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('boot')
    p.add_argument('group', type=Path)
    p.add_argument('--reconnect24', type=Path)
    p.add_argument('--reconnect5', type=Path)
    a = p.parse_args()
    require(re.fullmatch(r'[0-9a-f-]{36}', a.boot), 'invalid boot ID')
    results = [verified(a.group, a.boot, '24', False)]
    for band, path in [('24', a.reconnect24), ('5', a.reconnect5)]:
        if path:
            results.append(verified(path, a.boot, band, True))
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
