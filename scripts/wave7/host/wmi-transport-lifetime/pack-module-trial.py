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



def fixed_lab_primary(data):
    """Pin only the 5 GHz lab primary channel; never touch 2.4 GHz coexistence."""
    text = data.decode("utf-8")
    sections = re.split(r"(?m)(?=^config )", text)
    matches = [i for i, section in enumerate(sections)
               if section.startswith("config wifi-device 'radio1'\n")]
    check(len(matches) == 1, 'unique radio1 device')
    i = matches[0]
    section = sections[i]
    for name, value in (('band', '5g'), ('channel', '36'), ('htmode', 'EHT80')):
        check(re.findall(r"(?m)^\s*option " + name + r" '([^']+)'$", section) == [value],
              'fixed lab radio1 ' + name)
    check(not re.search(r"(?m)^\s*(?:option|list) (?:noscan|hostapd_options)\b", section),
          'unexpected existing scan override')
    check(section.count("\toption htmode 'EHT80'\n") == 1, 'radio1 stanza format')
    sections[i] = section.replace("\toption htmode 'EHT80'\n",
                                  "\toption htmode 'EHT80'\n\toption noscan '1'\n")
    return ''.join(sections).encode("utf-8")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spec', type=Path, required=True)
    for arg in ('parent', 'modules', 'host-tree', 'out'):
        p.add_argument('--' + arg, type=Path, required=True)
    for arg in ('replacement-fit', 'kernel-closure', 'kernel-config'):
        p.add_argument('--' + arg, type=Path)
    a = p.parse_args()
    profile_spec = json.loads(a.spec.read_text())
    base_keys = {'parent_sha', 'parent_rev', 'parent_builder', 'fit_sha', 'kernel', 'modules', 'patch_commit', 'patch_key', 'filename'}
    kernel_keys = {'replacement_fit_sha', 'kernel_closure_sha', 'kernel_config_sha'}
    policy_trial = 'lab_primary_channel' in profile_spec
    if policy_trial:
        check(set(profile_spec['lab_primary_channel']) == {'before', 'after'} and
              all(re.fullmatch(r'[a-f0-9]{64}', v)
                  for v in profile_spec['lab_primary_channel'].values()) and
              profile_spec['lab_primary_channel']['before'] != profile_spec['lab_primary_channel']['after'],
              'lab wireless policy pins')
    kernel_trial = set(profile_spec) == base_keys | kernel_keys
    check(kernel_trial or set(profile_spec) == base_keys |
          ({'lab_primary_channel'} if policy_trial else set()), 'spec keys')
    kernel_inputs = (a.replacement_fit, a.kernel_closure, a.kernel_config)
    check(all(x is not None for x in kernel_inputs) if kernel_trial else all(x is None for x in kernel_inputs), 'kernel trial inputs')
    check(re.fullmatch(r'\d+\.\d+\.\d+', profile_spec['kernel']), 'kernel pin')
    moddir = Path('lib/modules') / profile_spec['kernel']
    parent_fit_sha = profile_spec['fit_sha']
    fit_sha = profile_spec.get('replacement_fit_sha', parent_fit_sha)
    check(re.fullmatch(r'r0\+\d+-[a-f0-9]{10}-ap-dhcp-guard8', profile_spec['parent_rev']), 'parent revision')
    check(re.fullmatch(r'[a-z0-9_-]+\.bin', profile_spec['filename']), 'image filename')
    check(re.fullmatch(r'trial_[a-z0-9_]+_commit', profile_spec['patch_key']), 'patch key')
    check(all(re.fullmatch(r'[a-f0-9]{64}', profile_spec[k]) for k in ('parent_sha', 'fit_sha')), 'image pins')
    check(all(re.fullmatch(r'[a-f0-9]{40}', profile_spec[k]) for k in ('parent_builder', 'patch_commit')), 'commit pins')
    modules = profile_spec['modules']
    check((modules or policy_trial) and all(re.fullmatch(r'[a-zA-Z0-9_-]+\.ko', n) and len(pair) == 2 and (kernel_trial or pair[0] != pair[1]) and all(re.fullmatch(r'[a-f0-9]{64}', h) for h in pair) for n, pair in modules.items()), 'module pins')
    if kernel_trial:
        check(all(re.fullmatch(r'[a-f0-9]{64}', profile_spec[key]) for key in kernel_keys), 'kernel pins')
        check(fit_sha != parent_fit_sha and sha(a.replacement_fit) == fit_sha, 'replacement FIT pin')
        check(sha(a.kernel_closure) == profile_spec['kernel_closure_sha'] and
              sha(a.kernel_config) == profile_spec['kernel_config_sha'], 'kernel evidence pins')
        closure = json.loads(a.kernel_closure.read_text())
        check(closure['kernel'] == profile_spec['kernel'] and closure['module_count'] == len(modules), 'complete kernel closure')
        check({m['filename']: [m['parent_sha256'], m['sha256']] for m in closure['modules'].values()} == modules, 'kernel module closure pins')
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
        check(sha(t / 'kernel') == parent_fit_sha, 'parent FIT')
        if kernel_trial:
            fit_helpers = runpy.run_path(str(Path(__file__).with_name('build-profile-fit.py')))
            fit_helpers['verify_transition'](fit_helpers['fit_properties'](t / 'kernel'),
                                             fit_helpers['fit_properties'](a.replacement_fit))
            shutil.copyfile(a.replacement_fit, t / 'kernel')
            check(sha(t / 'kernel') == fit_sha, 'replacement FIT copied')
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
        if kernel_trial:
            check({f.name for f in (root / moddir).glob('*.ko')} == modules.keys(), 'full parent module inventory')
        module_delta = set()
        for name, (before, _) in modules.items():
            module = root / moddir / name
            check(module.is_file() and not module.is_symlink() and sha(module) == before, f'parent module digest: {name}')
            check(cmd('modinfo', '-F', 'vermagic', module) == cmd('modinfo', '-F', 'vermagic', a.modules / name), f'module vermagic: {name}')
            check(cmd('modinfo', '-F', 'depends', module) == cmd('modinfo', '-F', 'depends', a.modules / name), f'module depends: {name}')
            module.write_bytes((a.modules / name).read_bytes())
            if before != modules[name][1]:
                module_delta.add(module.relative_to(root).as_posix())
        policy_delta = set()
        if policy_trial:
            wireless = root / 'etc/config/wireless'
            pins = profile_spec['lab_primary_channel']
            check(sha(wireless) == pins['before'], 'parent wireless policy digest')
            wireless.write_bytes(fixed_lab_primary(wireless.read_bytes()))
            check(sha(wireless) == pins['after'], 'candidate wireless policy digest')
            policy_delta.add('etc/config/wireless')
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
        if kernel_trial:
            fields.update(trial_fit_sha256=fit_sha, trial_kernel_config_sha256=profile_spec['kernel_config_sha'],
                          trial_kernel_closure_sha256=profile_spec['kernel_closure_sha'])
        if policy_trial:
            fields['trial_lab_primary_channel'] = '36'
            fields['trial_lab_wireless_sha256'] = profile_spec['lab_primary_channel']['after']
        profile.write_text(''.join(f'{k}={v}\n' for k,v in fields.items()))
        cmd('sh', '-c', '. "$1"; wave7_ap_check_image "$2"', 'sh', root / 'lib/wave7/overlay-reset.sh', root)
        current = read_manifest(root)
        delta = sorted(k for k in original.keys() | current.keys() if original.get(k) != current.get(k))
        check(set(delta) == set(IDENTITIES) | module_delta | policy_delta, 'unexpected root delta: ' + str(delta))
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
        if policy_trial:
            meta['wave7_trial_lab_primary_channel'] = profile_spec['lab_primary_channel']
        if kernel_trial:
            meta['wave7_trial_kernel'] = {key: profile_spec[key] for key in sorted(kernel_keys)}
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
        if policy_trial:
            report['lab_primary_channel'] = profile_spec['lab_primary_channel']
        if kernel_trial:
            report.update({key: profile_spec[key] for key in sorted(kernel_keys)})
        a.out.mkdir(mode=0o700)
        shutil.move(output, a.out / profile_spec['filename'])
        (a.out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        (a.out / 'radio.sha256').write_text(''.join(f'{v}  {k}\n' for k,v in radio_manifest.items()))
        (a.out / 'SHA256SUMS').write_text(''.join(f'{sha(a.out / f)}  {f}\n' for f in (profile_spec['filename'], 'report.json', 'radio.sha256')))
        print(json.dumps({k:v for k,v in report.items() if k != 'firmware'}, indent=2))


if __name__ == '__main__':
    main()
