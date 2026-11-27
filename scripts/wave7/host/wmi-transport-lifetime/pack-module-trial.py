#!/usr/bin/env python3
"""Repack an exact verified parent with a pinned radio module closure replacement."""
import argparse
import json
import os
import re
from pathlib import Path
import runpy
import shutil
import tarfile
import tempfile

# Reuse the audited native packing and manifest helpers, not its donor stage.
helpers = runpy.run_path(str(Path(__file__).with_name('pack-radio-trial.py')))
sha = helpers['sha']
check = helpers['check']
cmd = helpers['cmd']
modes = helpers['modes']
read_manifest = helpers['read_manifest']
verify_special_nodes = helpers['verify_special_nodes']
IDENTITIES = helpers['IDENTITIES']
RADIO = helpers['RADIO']


def module_key(name):
    return 'trial_' + Path(name).stem + '_sha256'



def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spec', type=Path, required=True)
    for arg in ('parent', 'modules', 'host-tree', 'out'):
        p.add_argument('--' + arg, type=Path, required=True)
    a = p.parse_args()
    profile_spec = json.loads(a.spec.read_text())
    check(set(profile_spec) == {'parent_sha', 'parent_rev', 'parent_builder', 'fit_sha', 'kernel', 'modules', 'patch_commit', 'patch_key', 'filename'}, 'spec keys')
    check(re.fullmatch(r'\d+\.\d+\.\d+', profile_spec['kernel']), 'kernel pin')
    moddir = Path('lib/modules') / profile_spec['kernel']
    fit_sha = profile_spec['fit_sha']
    check(re.fullmatch(r'r0\+\d+-[a-f0-9]{10}-ap-dhcp-guard8', profile_spec['parent_rev']), 'parent revision')
    check(re.fullmatch(r'[a-z0-9_-]+\.bin', profile_spec['filename']), 'image filename')
    check(re.fullmatch(r'trial_[a-z0-9_]+_commit', profile_spec['patch_key']), 'patch key')
    check(all(re.fullmatch(r'[a-f0-9]{64}', profile_spec[k]) for k in ('parent_sha', 'fit_sha')), 'image pins')
    check(all(re.fullmatch(r'[a-f0-9]{40}', profile_spec[k]) for k in ('parent_builder', 'patch_commit')), 'commit pins')
    modules = profile_spec['modules']
    check(modules and all(re.fullmatch(r'[a-zA-Z0-9_-]+\.ko', n) and len(pair) == 2 and pair[0] != pair[1] and all(re.fullmatch(r'[a-f0-9]{64}', h) for h in pair) for n, pair in modules.items()), 'module pins')
    patch_key = profile_spec['patch_key']
    repo = Path(__file__).resolve().parents[4]
    builder = cmd('git', '-C', repo, 'rev-parse', 'HEAD').strip()
    check(not cmd('git', '-C', repo, 'status', '--porcelain').strip(), 'dirty builder')
    spec_rel = a.spec.resolve().relative_to(repo)
    check(cmd('git', '-C', repo, 'show', f'HEAD:{spec_rel}') == a.spec.read_text(), 'spec must be committed')
    cmd('git', '-C', repo, 'merge-base', '--is-ancestor', profile_spec['patch_commit'], builder)
    check(sha(a.parent) == profile_spec['parent_sha'], 'parent image digest')
    for name, (_, after) in modules.items():
        check(sha(a.modules / name) == after, f'candidate module digest: {name}')
    check(a.out.parent.is_dir() and not a.out.exists(), 'output path')
    rev = profile_spec['parent_rev'].split('-', 1)[0] + '-' + builder[:10] + '-ap-dhcp-guard8'
    tools = a.host_tree / 'staging_dir/host/bin'
    unsq, mksq, fwtool = (tools / s for s in ('unsquashfs4', 'mksquashfs4', 'fwtool'))
    with tempfile.TemporaryDirectory(prefix='.module-trial-', dir=a.out.parent) as td:
        t = Path(td)
        with tarfile.open(a.parent) as tf:
            check(tf.extractfile('sysupgrade-acer_wave7/CONTROL').read() == b'BOARD=acer_wave7\n', 'parent board')
            for name in ('kernel', 'root'):
                (t / name).write_bytes(tf.extractfile('sysupgrade-acer_wave7/' + name).read())
        check(sha(t / 'kernel') == fit_sha, 'parent FIT')
        cmd(fwtool, '-i', t / 'metadata.json', a.parent)
        meta = json.loads((t / 'metadata.json').read_text())
        check(meta['version']['revision'] == profile_spec['parent_rev'] and 'acer,wave7' in meta['supported_devices'], 'parent metadata')
        verify_special_nodes(unsq, t / 'root')
        old_modes = modes(cmd(unsq, '-ll', t / 'root'))
        (t / 'exclude').write_text('dev/console\n')
        root = t / 'stage'
        old_umask = os.umask(0)
        try:
            check('created 0 devices' in cmd(unsq, '-no-progress', '-d', root, '-exclude-file', t / 'exclude', t / 'root'), 'parent extract')
        finally:
            os.umask(old_umask)
        original = read_manifest(root)
        check([p.name for p in (root / 'lib/modules').iterdir() if p.is_dir()] == [profile_spec['kernel']], 'parent kernel directory')
        module_delta = set()
        for name, (before, _) in modules.items():
            module = root / moddir / name
            check(module.is_file() and not module.is_symlink() and sha(module) == before, f'parent module digest: {name}')
            check(cmd('modinfo', '-F', 'vermagic', module) == cmd('modinfo', '-F', 'vermagic', a.modules / name), f'module vermagic: {name}')
            check(cmd('modinfo', '-F', 'depends', module) == cmd('modinfo', '-F', 'depends', a.modules / name), f'module depends: {name}')
            module.write_bytes((a.modules / name).read_bytes())
            module_delta.add(module.relative_to(root).as_posix())
        for rel in IDENTITIES[:4]:
            f = root / rel
            old = f.read_text()
            check(profile_spec['parent_rev'] in old, f'missing parent revision in {rel}')
            f.write_text(old.replace(profile_spec['parent_rev'], rev))
        profile = root / IDENTITIES[4]
        fields = dict(line.split('=', 1) for line in profile.read_text().splitlines())
        check(fields['revision'] == profile_spec['parent_rev'] and fields['builder_commit'] == profile_spec['parent_builder'], 'parent profile')
        for name, (before, _) in modules.items():
            if module_key(name) in fields:
                check(fields[module_key(name)] == before, f'parent profile module: {name}')
        fields.update(source_revision=profile_spec['parent_rev'], revision=rev, builder_commit=builder,
                      base_image_sha256=profile_spec['parent_sha'])
        for name, (_, after) in modules.items():
            fields[module_key(name)] = after
        fields[patch_key] = cmd('git', '-C', repo, 'rev-parse', profile_spec['patch_commit']).strip()
        profile.write_text(''.join(f'{k}={v}\n' for k,v in fields.items()))
        cmd('sh', '-c', '. "$1"; wave7_ap_check_image "$2"', 'sh', root / 'lib/wave7/overlay-reset.sh', root)
        current = read_manifest(root)
        delta = sorted(k for k in original.keys() | current.keys() if original.get(k) != current.get(k))
        check(set(delta) == set(IDENTITIES) | module_delta, 'unexpected root delta: ' + str(delta))
        check(original.keys() == current.keys() and all(original[k][0] == current[k][0] and original[k][2] == current[k][2] for k in original), 'root inventory/types/modes')
        cmd(mksq, root, t / 'new.sq', '-nopad', '-noappend', '-root-owned', '-comp', 'xz', '-Xpreset', '9', '-Xe', '-Xlc', '0', '-Xlp', '2', '-Xpb', '2', '-b', '256k', '-p', '/dev d 755 0 0', '-p', '/dev/console c 600 0 0 5 1', '-no-xattrs', '-block-readers', '4', '-small-readers', '4')
        check((t / 'new.sq').stat().st_size <= 29204480, 'rootfs limit')
        verify_special_nodes(unsq, t / 'new.sq')
        check(modes(cmd(unsq, '-ll', t / 'new.sq')) == old_modes, 'archive owner/mode mismatch')
        old_umask = os.umask(0)
        try:
            cmd(unsq, '-no-progress', '-d', t / 'roundtrip', '-exclude-file', t / 'exclude', t / 'new.sq')
        finally:
            os.umask(old_umask)
        check(read_manifest(t / 'roundtrip') == current, 'rootfs roundtrip mismatch')
        radio_manifest = {f.relative_to(root / RADIO).as_posix(): sha(f) for f in sorted((root / RADIO).rglob('*')) if f.is_file()}
        pinned_radio = {}
        for manifest in ('firmware.sha256', 'diagnostic-firmware.sha256'):
            for line in (repo / 'scripts/wave7' / manifest).read_text().splitlines():
                digest, path = line.split('  ', 1)
                check(path not in pinned_radio, 'duplicate radio pin')
                pinned_radio[path] = digest
        check(radio_manifest == pinned_radio and len(radio_manifest) == 46, 'radio closure differs from pin')
        check(not any(p.is_symlink() for p in (root / RADIO).rglob('*')), 'radio symlink')
        check(fields['trial_radio_release'] == (repo / 'scripts/wave7/radio-release.txt').read_text().strip(), 'radio release pin')
        output = t / 'image.bin'
        env = os.environ.copy()
        env['TOPDIR'] = str(a.host_tree)
        env['SOURCE_DATE_EPOCH'] = cmd('git', '-C', repo, 'show', '-s', '--format=%ct', builder).strip()
        cmd('sh', a.host_tree / 'scripts/sysupgrade-tar.sh', '--board', 'acer_wave7', '--kernel', t / 'kernel', '--rootfs', t / 'new.sq', output, env=env)
        meta['version']['revision'] = rev
        meta['wave7_parent_image_sha256'] = profile_spec['parent_sha']
        meta.setdefault('wave7_trial_radio', {})
        for name, (_, after) in modules.items():
            meta['wave7_trial_radio'][module_key(name)] = after
        meta['wave7_trial_radio'][patch_key] = fields[patch_key]
        (t / 'new-meta').write_text(json.dumps(meta))
        cmd(fwtool, '-I', t / 'new-meta', output)
        cmd(fwtool, '-i', t / 'check-meta', output)
        check(json.loads((t / 'check-meta').read_text()) == meta, 'metadata mismatch')
        with tarfile.open(output) as tf:
            check(tf.extractfile('sysupgrade-acer_wave7/CONTROL').read() == b'BOARD=acer_wave7\n', 'candidate board')
            check(tf.extractfile('sysupgrade-acer_wave7/kernel').read() == (t / 'kernel').read_bytes(), 'candidate FIT')
            check(tf.extractfile('sysupgrade-acer_wave7/root').read().startswith((t / 'new.sq').read_bytes()), 'candidate root')
        check(output.stat().st_size < 30000000, 'image size')
        report = dict(status='OFFLINE_VERIFIED', revision=rev, builder_commit=builder,
                      parent_sha256=profile_spec['parent_sha'], image_sha256=sha(output), fit_sha256=fit_sha,
                      radio_release=fields['trial_radio_release'], firmware=radio_manifest,
                      module_sha256={k: sha(root / moddir / k) for k in sorted(modules)},
                      delta=delta, roundtrip_identical=True)
        a.out.mkdir(mode=0o700)
        shutil.move(output, a.out / profile_spec['filename'])
        (a.out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        (a.out / 'radio.sha256').write_text(''.join(f'{v}  {k}\n' for k,v in radio_manifest.items()))
        (a.out / 'SHA256SUMS').write_text(''.join(f'{sha(a.out / f)}  {f}\n' for f in (profile_spec['filename'], 'report.json', 'radio.sha256')))
        print(json.dumps({k:v for k,v in report.items() if k != 'firmware'}, indent=2))


if __name__ == '__main__':
    main()
