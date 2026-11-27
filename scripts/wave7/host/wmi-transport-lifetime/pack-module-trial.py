#!/usr/bin/env python3
"""Repack an exact verified parent with a pinned radio module closure replacement."""
import argparse
import json
import os
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
FIT_SHA = helpers['FIT_SHA']
IDENTITIES = helpers['IDENTITIES']
MODDIR = helpers['MODDIR']
RADIO = helpers['RADIO']
PROFILES = {
    'ahb-irq': dict(
        parent_sha='ae9aa226c79d6263f9afaff4ec813ad34d1345966bba8fd81617073521498fb4',
        parent_rev='r0+38346-65f3c6bcfc-ap-dhcp-guard8',
        modules={'ath12k.ko': (
            '477ea1d123a13791fd204958a9be4fd62f7d471f8f849810bb2faed473e5d015',
            'acf054be38922d52bc483e1ac0c053c8f5fdebfa3030cf8068e84e5b5783b9cc')},
        patch_commit='0bd0f2a020', patch_key='trial_ahb_irq_patch_commit',
        filename='wave7-ahb-tx-completion-irq-dhcp-guard8-sysupgrade.bin',
    ),
    'tx-ownership': dict(
        parent_sha='d519a6acb4ec1d88a7a2284528748b69187e4122d668d59c77488948f3165fde',
        parent_rev='r0+38346-8b8a3f32c2-ap-dhcp-guard8',
        modules={'ath12k_wifi7.ko': (
            '20d87569ae03ce05efdb6bbbc4a33b8168aaf5212be0f5fa626bceba6e785e4c',
            '0bc014d15197ddb538f66ac7ec1f98dfc9399da30e8c30e76d8e1098ce5292ae')},
        patch_commit='c6c3a6bd6e', patch_key='trial_tx_ownership_patch_commit',
        filename='wave7-tx-publish-ownership-dhcp-guard8-sysupgrade.bin',
    ),
    'wbm-route': dict(
        parent_sha='d519a6acb4ec1d88a7a2284528748b69187e4122d668d59c77488948f3165fde',
        parent_rev='r0+38346-8b8a3f32c2-ap-dhcp-guard8',
        modules={
            'ath12k.ko': (
                'acf054be38922d52bc483e1ac0c053c8f5fdebfa3030cf8068e84e5b5783b9cc',
                '99549926cd9054a44ea3f6aeba534d681af68e6375e380f858a55a290386c826'),
            'ath12k_wifi7.ko': (
                '20d87569ae03ce05efdb6bbbc4a33b8168aaf5212be0f5fa626bceba6e785e4c',
                'c9b69a269ebef16fde007aafd4dc1cdcbf646519463754ecf2e1cd8d1dddfd5a'),
        },
        patch_commit='4ef38d5214', patch_key='trial_wbm_route_patch_commit',
        filename='wave7-ipq5332-wbm-route-dhcp-guard8-sysupgrade.bin',
    ),
}


def module_key(name):
    return 'trial_' + Path(name).stem + '_sha256'



def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile', choices=PROFILES, required=True)
    for arg in ('parent', 'modules', 'host-tree', 'out'):
        p.add_argument('--' + arg, type=Path, required=True)
    a = p.parse_args()
    profile_spec = PROFILES[a.profile]
    modules = profile_spec['modules']
    patch_key = profile_spec['patch_key']
    repo = Path(__file__).resolve().parents[4]
    builder = cmd('git', '-C', repo, 'rev-parse', 'HEAD').strip()
    check(not cmd('git', '-C', repo, 'status', '--porcelain').strip(), 'dirty builder')
    cmd('git', '-C', repo, 'merge-base', '--is-ancestor', profile_spec['patch_commit'], builder)
    check(sha(a.parent) == profile_spec['parent_sha'], 'parent image digest')
    for name, (_, after) in modules.items():
        check(sha(a.modules / name) == after, f'candidate module digest: {name}')
    check(a.out.parent.is_dir() and not a.out.exists(), 'output path')
    rev = 'r0+38346-' + builder[:10] + '-ap-dhcp-guard8'
    tools = a.host_tree / 'staging_dir/host/bin'
    unsq, mksq, fwtool = (tools / s for s in ('unsquashfs4', 'mksquashfs4', 'fwtool'))
    with tempfile.TemporaryDirectory(prefix='.module-trial-', dir=a.out.parent) as td:
        t = Path(td)
        with tarfile.open(a.parent) as tf:
            check(tf.extractfile('sysupgrade-acer_wave7/CONTROL').read() == b'BOARD=acer_wave7\n', 'parent board')
            for name in ('kernel', 'root'):
                (t / name).write_bytes(tf.extractfile('sysupgrade-acer_wave7/' + name).read())
        check(sha(t / 'kernel') == FIT_SHA, 'parent FIT')
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
        module_delta = set()
        for name, (before, _) in modules.items():
            module = root / MODDIR / name
            check(sha(module) == before, f'parent module digest: {name}')
            module.write_bytes((a.modules / name).read_bytes())
            module_delta.add(module.relative_to(root).as_posix())
        for rel in IDENTITIES[:4]:
            f = root / rel
            old = f.read_text()
            check(profile_spec['parent_rev'] in old, f'missing parent revision in {rel}')
            f.write_text(old.replace(profile_spec['parent_rev'], rev))
        profile = root / IDENTITIES[4]
        fields = dict(line.split('=', 1) for line in profile.read_text().splitlines())
        check(fields['revision'] == profile_spec['parent_rev'], 'parent profile')
        for name, (before, _) in modules.items():
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
        output = t / 'image.bin'
        env = os.environ.copy()
        env['TOPDIR'] = str(a.host_tree)
        env['SOURCE_DATE_EPOCH'] = cmd('git', '-C', repo, 'show', '-s', '--format=%ct', builder).strip()
        cmd('sh', a.host_tree / 'scripts/sysupgrade-tar.sh', '--board', 'acer_wave7', '--kernel', t / 'kernel', '--rootfs', t / 'new.sq', output, env=env)
        meta['version']['revision'] = rev
        meta['wave7_parent_image_sha256'] = profile_spec['parent_sha']
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
                      parent_sha256=profile_spec['parent_sha'], image_sha256=sha(output), fit_sha256=FIT_SHA,
                      radio_release=fields['trial_radio_release'], firmware=radio_manifest,
                      module_sha256={k: sha(root / MODDIR / k) for k in ('ath12k.ko', 'ath12k_wifi7.ko')},
                      delta=delta, roundtrip_identical=True)
        a.out.mkdir(mode=0o700)
        shutil.move(output, a.out / profile_spec['filename'])
        (a.out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        (a.out / 'radio.sha256').write_text(''.join(f'{v}  {k}\n' for k,v in radio_manifest.items()))
        (a.out / 'SHA256SUMS').write_text(''.join(f'{sha(a.out / f)}  {f}\n' for f in (profile_spec['filename'], 'report.json', 'radio.sha256')))
        print(json.dumps({k:v for k,v in report.items() if k != 'firmware'}, indent=2))


if __name__ == '__main__':
    main()
