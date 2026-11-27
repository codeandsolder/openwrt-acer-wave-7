#!/usr/bin/env python3
"""Repack the accepted REO-LUT image with only the validated AHB IRQ module."""
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
PARENT_SHA = 'ae9aa226c79d6263f9afaff4ec813ad34d1345966bba8fd81617073521498fb4'
PARENT_REV = 'r0+38346-65f3c6bcfc-ap-dhcp-guard8'
OLD_MODULE = '477ea1d123a13791fd204958a9be4fd62f7d471f8f849810bb2faed473e5d015'
NEW_MODULE = 'acf054be38922d52bc483e1ac0c053c8f5fdebfa3030cf8068e84e5b5783b9cc'
FIT_SHA = helpers['FIT_SHA']
IDENTITIES = helpers['IDENTITIES']
MODDIR = helpers['MODDIR']
RADIO = helpers['RADIO']
PATCH_COMMIT = '0bd0f2a020'
FILENAME = 'wave7-ahb-tx-completion-irq-dhcp-guard8-sysupgrade.bin'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ('parent', 'module', 'host-tree', 'out'):
        p.add_argument('--' + arg, type=Path, required=True)
    a = p.parse_args()
    repo = Path(__file__).resolve().parents[4]
    builder = cmd('git', '-C', repo, 'rev-parse', 'HEAD').strip()
    check(not cmd('git', '-C', repo, 'status', '--porcelain').strip(), 'dirty builder')
    cmd('git', '-C', repo, 'merge-base', '--is-ancestor', PATCH_COMMIT, builder)
    check(sha(a.parent) == PARENT_SHA, 'parent image digest')
    check(sha(a.module) == NEW_MODULE, 'candidate module digest')
    check(a.out.parent.is_dir() and not a.out.exists(), 'output path')
    rev = 'r0+38346-' + builder[:10] + '-ap-dhcp-guard8'
    tools = a.host_tree / 'staging_dir/host/bin'
    unsq, mksq, fwtool = (tools / s for s in ('unsquashfs4', 'mksquashfs4', 'fwtool'))
    with tempfile.TemporaryDirectory(prefix='.irq-trial-', dir=a.out.parent) as td:
        t = Path(td)
        with tarfile.open(a.parent) as tf:
            check(tf.extractfile('sysupgrade-acer_wave7/CONTROL').read() == b'BOARD=acer_wave7\n', 'parent board')
            for name in ('kernel', 'root'):
                (t / name).write_bytes(tf.extractfile('sysupgrade-acer_wave7/' + name).read())
        check(sha(t / 'kernel') == FIT_SHA, 'parent FIT')
        cmd(fwtool, '-i', t / 'metadata.json', a.parent)
        meta = json.loads((t / 'metadata.json').read_text())
        check(meta['version']['revision'] == PARENT_REV and 'acer,wave7' in meta['supported_devices'], 'parent metadata')
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
        module = root / MODDIR / 'ath12k.ko'
        check(sha(module) == OLD_MODULE, 'parent module digest')
        module.write_bytes(a.module.read_bytes())
        for rel in IDENTITIES[:4]:
            f = root / rel
            old = f.read_text()
            check(PARENT_REV in old, f'missing parent revision in {rel}')
            f.write_text(old.replace(PARENT_REV, rev))
        profile = root / IDENTITIES[4]
        fields = dict(line.split('=', 1) for line in profile.read_text().splitlines())
        check(fields['revision'] == PARENT_REV and fields['trial_ath12k_sha256'] == OLD_MODULE, 'parent profile')
        fields.update(source_revision=PARENT_REV, revision=rev, builder_commit=builder,
                      base_image_sha256=PARENT_SHA, trial_ath12k_sha256=NEW_MODULE,
                      trial_ahb_irq_patch_commit=cmd('git', '-C', repo, 'rev-parse', PATCH_COMMIT).strip())
        profile.write_text(''.join(f'{k}={v}\n' for k,v in fields.items()))
        cmd('sh', '-c', '. "$1"; wave7_ap_check_image "$2"', 'sh', root / 'lib/wave7/overlay-reset.sh', root)
        current = read_manifest(root)
        delta = sorted(k for k in original.keys() | current.keys() if original.get(k) != current.get(k))
        check(set(delta) == set(IDENTITIES) | {module.relative_to(root).as_posix()}, 'unexpected root delta: ' + str(delta))
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
        meta['wave7_parent_image_sha256'] = PARENT_SHA
        meta['wave7_trial_radio']['trial_ath12k_sha256'] = NEW_MODULE
        meta['wave7_trial_radio']['trial_ahb_irq_patch_commit'] = fields['trial_ahb_irq_patch_commit']
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
                      parent_sha256=PARENT_SHA, image_sha256=sha(output), fit_sha256=FIT_SHA,
                      radio_release=fields['trial_radio_release'], firmware=radio_manifest,
                      module_sha256={k: sha(root / MODDIR / k) for k in ('ath12k.ko', 'ath12k_wifi7.ko')},
                      delta=delta, roundtrip_identical=True)
        a.out.mkdir(mode=0o700)
        shutil.move(output, a.out / FILENAME)
        (a.out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        (a.out / 'radio.sha256').write_text(''.join(f'{v}  {k}\n' for k,v in radio_manifest.items()))
        (a.out / 'SHA256SUMS').write_text(''.join(f'{sha(a.out / f)}  {f}\n' for f in (FILENAME, 'report.json', 'radio.sha256')))
        print(json.dumps({k:v for k,v in report.items() if k != 'firmware'}, indent=2))


if __name__ == '__main__':
    main()
