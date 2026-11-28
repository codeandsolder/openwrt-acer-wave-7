#!/usr/bin/env python3
"""Verify a native AP image and emit an exact runtime qualification manifest."""
import argparse
import hashlib
import json
import lzma
import runpy
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile


MODULES = ('ath12k.ko', 'ath12k_wifi7.ko', 'mac80211.ko', 'cfg80211.ko')
POLICY = ('etc/wave7-role-profile', 'etc/openwrt_version', 'etc/config/network',
          'etc/config/dhcp', 'etc/config/dropbear', 'etc/config/wireless',
          'etc/config/firewall', 'etc/dropbear/authorized_keys', 'etc/shadow',
          'etc/init.d/wave7-firstboot-failsafe', 'lib/preinit/05_wave7_firstboot_watchdog',
          'lib/preinit/76_wave7_ap_overlay_reset', 'lib/wave7/role-firstboot.sh',
          'lib/wave7/overlay-reset.sh')


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def command(*args):
    return subprocess.run([str(x) for x in args], check=True, capture_output=True, text=True).stdout


def fields(path):
    items = [line.split('=', 1) for line in path.read_text().splitlines()]
    result = dict(items)
    require(len(items) == len(result), f'duplicate profile field: {path}')
    return result


def describe(image, sha256, revision, kernel, builder, host_tree, scratch, closure=None, notes=None):
    require(re.fullmatch(r'r0\+\d+-[a-f0-9]{10}-ap-dhcp-guard8', revision), 'revision format')
    require(re.fullmatch(r'\d+\.\d+\.\d+', kernel), 'kernel version format')
    require(re.fullmatch(r'[a-f0-9]{40}', builder), 'builder format')
    require(digest(image) == sha256, 'image SHA256 mismatch')
    tools = host_tree / 'staging_dir/host/bin'
    repo = Path(__file__).resolve().parents[4]
    radio_release = (repo / 'scripts/wave7/radio-release.txt').read_text().strip()
    require(re.fullmatch(r'[a-zA-Z0-9_.-]+', radio_release), 'radio release pin')
    with tempfile.TemporaryDirectory(prefix='native-manifest-', dir=scratch) as work:
        t = Path(work)
        with tarfile.open(image) as tf:
            entries = tf.getmembers()
            require(len(entries) == 4 and len({m.name for m in entries}) == 4, 'unexpected tar inventory')
            require(tf.getmember('sysupgrade-acer_wave7').isdir(), 'board directory')
            control = tf.getmember('sysupgrade-acer_wave7/CONTROL')
            require(control.isfile() and tf.extractfile(control).read() == b'BOARD=acer_wave7\n', 'board control')
            for name in ('kernel', 'root'):
                member = tf.getmember('sysupgrade-acer_wave7/' + name)
                require(member.isfile(), f'not regular {name}')
                with (t / name).open('wb') as f:
                    shutil.copyfileobj(tf.extractfile(member), f)
        command(tools / 'fwtool', '-i', t / 'metadata.json', image)
        meta = json.loads((t / 'metadata.json').read_text())
        require(meta['version']['target'] == 'qualcommbe/ipq53xx' and meta['version']['board'] == 'acer_wave7', 'target metadata')
        require(meta['version']['revision'] == revision and 'acer,wave7' in meta['supported_devices'], 'revision metadata')
        require(meta['wave7_role'] == 'secondary-ap' and meta['wave7_mode'] == 'dhcp', 'AP metadata')
        listing = command(tools / 'unsquashfs4', '-ll', t / 'root')
        special = [line for line in listing.splitlines() if re.match(r'^[cbps]', line)]
        require(len(special) == 1 and special[0].endswith(' squashfs-root/dev/console') and special[0].startswith('crw'), 'unexpected special nodes')
        (t / 'exclude').write_text('dev/console\n')
        root = t / 'extracted'
        command(tools / 'unsquashfs4', '-no-progress', '-d', root, '-exclude-file', t / 'exclude', t / 'root')
        for path in POLICY:
            f = root / path
            require(f.is_file() and not f.is_symlink(), f'missing policy {path}')
        profile = fields(root / 'etc/wave7-role-profile')
        require(profile['revision'] == revision and profile['builder_commit'] == builder, 'role profile identity')
        require(profile['trial_radio_release'] == radio_release, 'role radio release pin')
        require(meta['wave7_parent_image_sha256'] == profile['base_image_sha256'], 'parent image identity')
        require((root / 'etc/openwrt_version').read_text().strip() == revision, 'root revision')
        for key, value in {'role': 'secondary-ap', 'mode': 'dhcp', 'dhcpv4_server': 'off',
                           'dhcpv6_server': 'off', 'router_advertisements': 'off', 'dns_service': 'off',
                           'root_password_authentication': 'off', 'root_public_key_authentication': 'on'}.items():
            require(profile[key] == value, f'role policy {key}')
        require(re.search(r'^root:!:', (root / 'etc/shadow').read_text(), re.M), 'root password not locked')
        command('sh', '-c', '. "$1"; wave7_ap_check_image "$2"', 'sh', root / 'lib/wave7/overlay-reset.sh', root)
        mods = root / 'lib/modules'
        require([p.name for p in mods.iterdir() if p.is_dir()] == [kernel], 'kernel module directory mismatch')
        module_hashes = {}
        for name in MODULES:
            f = mods / kernel / name
            require(f.is_file() and not f.is_symlink(), f'missing module {name}')
            require(command('modinfo', '-F', 'vermagic', f).split()[0] == kernel, f'module version {name}')
            module_hashes[name] = digest(f)
        radio = root / 'lib/firmware/ath12k'
        actual_radio = {p.relative_to(radio).as_posix(): digest(p) for p in sorted(radio.rglob('*')) if p.is_file() and not p.is_symlink()}
        pinned_radio = {}
        for name in ('firmware.sha256', 'diagnostic-firmware.sha256'):
            for line in (repo / 'scripts/wave7' / name).read_text().splitlines():
                sha, path = line.split('  ', 1)
                require(path not in pinned_radio, 'duplicate radio pin')
                pinned_radio[path] = sha
        band_profile = meta.get('wave7_trial_lab_band_profile')
        band_identity = {}
        if band_profile is not None:
            band = runpy.run_path(str(repo / 'scripts/wave7/host/wmi-transport-lifetime/band-profile.py'))
            name = band_profile['name']
            require(set(band_profile) == {'name', 'before', 'after'} and name in band['PROFILES'],
                    'band profile schema')
            require(profile['trial_lab_band_profile'] == name and
                    profile['trial_lab_wireless_sha256'] == band_profile['after'] ==
                    digest(root / 'etc/config/wireless'), 'band policy identity')
            pinned_radio = band['radio_pins'](pinned_radio, name)
            _, fit = band['properties']((t / 'kernel').read_bytes())
            fit_helper = runpy.run_path(str(repo / 'scripts/wave7/host/wmi-transport-lifetime/build-profile-fit.py'))
            fit_helper['verify_hashes'](fit)
            _, dt = band['properties'](fit['/images/fdt-1', 'data'])
            frequency = band['PROFILES'][name][0]
            require(dt[band['RADIO'], 'qcom,board_id'] == (0x91 if frequency == 6 else 0x53).to_bytes(4, 'big'),
                    'band board ID')
            for i, hog in enumerate(band['HOGS']):
                node = band['TLMM'] + '/' + hog
                props = {k[1]: v for k, v in dt.items() if k[0] == node}
                require(props == {'gpio-hog': b'', 'gpios': (49+i).to_bytes(4, 'big') + bytes(4),
                                  'line-name': hog.encode() + b'\0',
                                  'output-high' if i == (frequency == 6) else 'output-low': b''},
                        'band GPIO identity')
            band_identity = {'band_profile': name}
        else:
            require('trial_lab_band_profile' not in profile, 'unattested band profile')
        require(actual_radio == pinned_radio and len(actual_radio) == 46, 'radio closure differs from pin')
        require(not any(p.is_symlink() for p in radio.rglob('*')), 'radio symlink')
        diagnostics = {}
        require((closure is None) == (notes is None), 'kernel closure and notes must be paired')
        if 'wave7_trial_kernel' in meta:
            require(closure is not None, 'diagnostic kernel requires full runtime identity')
            evidence = json.loads(closure.read_text())
            require(evidence['kernel'] == kernel, 'closure kernel mismatch')
            require(digest(closure) == profile['trial_kernel_closure_sha256'] ==
                    meta['wave7_trial_kernel']['kernel_closure_sha'], 'closure pin mismatch')
            require(digest(t / 'kernel') == profile['trial_fit_sha256'] ==
                    meta['wave7_trial_kernel']['replacement_fit_sha'], 'diagnostic FIT pin mismatch')
            require(re.fullmatch(r'[a-f0-9]{64}', profile['trial_kernel_config_sha256']) and
                    profile['trial_kernel_config_sha256'] == meta['wave7_trial_kernel']['kernel_config_sha'],
                    'diagnostic config pin mismatch')
            files = sorted((mods / kernel).rglob('*.ko'))
            require(all(f.is_file() and not f.is_symlink() and f.parent == mods / kernel for f in files),
                    'unexpected diagnostic module path')
            actual = {f.name: digest(f) for f in files}
            require(len(actual) == evidence['module_count'] and actual ==
                    {v['filename']: v['sha256'] for v in evidence['modules'].values()}, 'full module closure mismatch')
            raw_notes = notes.read_bytes()
            fit = runpy.run_path(str(repo / 'scripts/wave7/host/wmi-transport-lifetime/build-profile-fit.py'))
            properties = fit['fit_properties'](t / 'kernel')
            fit['verify_hashes'](properties)
            raw = lzma.decompress(properties['/images/kernel-1', 'data'], format=lzma.FORMAT_ALONE)
            require(len(raw_notes) >= 36 and b'GNU\0' in raw_notes and raw.count(raw_notes) == 1,
                    'kernel notes not uniquely present in FIT Image')
            diagnostics = dict(full_module_sha256=actual, kernel_notes_sha256=digest(notes))
        else:
            require(closure is None, 'unexpected diagnostic identity arguments')
        return dict(image=image.name, image_sha256=sha256, revision=revision, kernel=kernel,
                    builder_commit=builder, fit_sha256=digest(t / 'kernel'), rootfs_sha256=digest(t / 'root'),
                    radio_release=radio_release, radio_sha256=actual_radio, module_sha256=module_hashes,
                    policy_sha256={p: digest(root / p) for p in POLICY}, **diagnostics, **band_identity)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('image', 'host-tree', 'scratch', 'output'):
        parser.add_argument('--' + arg, required=True, type=Path)
    for arg in ('sha256', 'revision', 'kernel', 'builder'):
        parser.add_argument('--' + arg, required=True)
    parser.add_argument("--kernel-closure", type=Path)
    parser.add_argument("--kernel-notes", type=Path)
    args = parser.parse_args()
    require(not args.output.exists(), 'manifest already exists')
    data = describe(args.image, args.sha256, args.revision, args.kernel, args.builder,
                    args.host_tree, args.scratch, args.kernel_closure, args.kernel_notes)
    args.output.write_text(json.dumps(data, sort_keys=True, indent=2) + '\n')
    print('NATIVE_IMAGE_MANIFEST_PASS', args.revision, args.kernel, args.sha256)


if __name__ == '__main__':
    main()
