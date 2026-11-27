#!/usr/bin/env python3
"""Verify a native AP image and emit an exact runtime qualification manifest."""
import argparse
import hashlib
import json
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


def describe(image, sha256, revision, kernel, builder, host_tree, scratch):
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
        require(actual_radio == pinned_radio and len(actual_radio) == 46, 'radio closure differs from pin')
        require(not any(p.is_symlink() for p in radio.rglob('*')), 'radio symlink')
        return dict(image=image.name, image_sha256=sha256, revision=revision, kernel=kernel,
                    builder_commit=builder, fit_sha256=digest(t / 'kernel'), rootfs_sha256=digest(t / 'root'),
                    radio_release=radio_release, radio_sha256=actual_radio, module_sha256=module_hashes,
                    policy_sha256={p: digest(root / p) for p in POLICY})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('image', 'host-tree', 'scratch', 'output'):
        parser.add_argument('--' + arg, required=True, type=Path)
    for arg in ('sha256', 'revision', 'kernel', 'builder'):
        parser.add_argument('--' + arg, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), 'manifest already exists')
    data = describe(args.image, args.sha256, args.revision, args.kernel, args.builder,
                    args.host_tree, args.scratch)
    args.output.write_text(json.dumps(data, sort_keys=True, indent=2) + '\n')
    print('NATIVE_IMAGE_MANIFEST_PASS', args.revision, args.kernel, args.sha256)


if __name__ == '__main__':
    main()
