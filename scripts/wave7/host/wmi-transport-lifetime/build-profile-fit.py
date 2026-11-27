#!/usr/bin/env python3
"""Build a native profiling kernel FIT while retaining the accepted NAND DTB."""
import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import subprocess
import tempfile
import zlib


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def command(*args):
    return subprocess.check_output([str(x) for x in args], text=True)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fit_properties(path):
    result = {}

    def walk(node):
        for prop in command('fdtget', '-p', path, node).splitlines():
            key = (node, prop)
            require(key not in result, f'duplicate property: {key}')
            result[key] = bytes(int(x, 16) for x in command('fdtget', '-t', 'bx', path, node, prop).split())
        for child in command('fdtget', '-l', path, node).splitlines():
            walk(node.rstrip('/') + '/' + child)

    walk('/')
    return result


def verify_hashes(properties):
    for image in ('kernel-1', 'fdt-1'):
        node = '/images/' + image
        data = properties[node, 'data']
        for n, algorithm, expected in (
                (1, b'crc32\0', zlib.crc32(data).to_bytes(4, 'big')),
                (2, b'sha1\0', hashlib.sha1(data).digest())):
            child = f'{node}/hash-{n}'
            require(properties[child, 'algo'] == algorithm and properties[child, 'value'] == expected,
                    f'invalid FIT hash: {child}')


def verify_transition(old, new):
    verify_hashes(old)
    verify_hashes(new)
    allowed = {('/', 'timestamp'), ('/images/kernel-1', 'data'),
               ('/images/kernel-1/hash-1', 'value'), ('/images/kernel-1/hash-2', 'value')}
    require(new.keys() == old.keys(), 'FIT property inventory changed')
    require(all(new[key] == old[key] for key in old.keys() - allowed), 'FIT board or boot metadata changed')



def build(parent, image, output, tools, repo, kernel, epoch):
    require(not output.exists(), 'output already exists')
    old = fit_properties(parent)
    verify_hashes(old)
    require(old['/images/kernel-1', 'compression'] == b'lzma\0', 'native kernel compression')
    require(old['/images/kernel-1', 'arch'] == b'arm64\0', 'native kernel arch')
    require(old['/images/kernel-1', 'load'] == old['/images/kernel-1', 'entry'] == bytes.fromhex('41000000'),
            'native load/entry')
    require(old['/configurations', 'default'] == b'config@mi04.1-c2\0', 'native default config')
    raw = image.read_bytes()
    require(len(raw) >= 64 and raw[56:60] == b'ARM\x64', 'not an ARM64 Image')
    dtb = old['/images/fdt-1', 'data']
    with tempfile.TemporaryDirectory(prefix='.profile-fit-', dir=output.parent) as tmp:
        t = Path(tmp)
        (t / 'board.dtb').write_bytes(dtb)
        command('sh', repo / 'scripts/wave7/verify-boot-mode-dtb.sh', 'nand', t / 'board.dtb', '/usr/bin/dtc')
        command(tools / 'lzma', 'e', image, '-lc1', '-lp2', '-pb2', t / 'image.lzma')
        require(lzma.decompress((t / 'image.lzma').read_bytes(), format=lzma.FORMAT_ALONE) == raw,
                'kernel compression roundtrip')
        command('sh', repo / 'scripts/mkits.sh', '-A', 'arm64', '-C', 'lzma',
                '-a', '0x41000000', '-e', '0x41000000', '-c', 'config@mi04.1-c2',
                '-D', 'acer_wave7', '-v', kernel, '-k', t / 'image.lzma',
                '-d', t / 'board.dtb', '-o', t / 'image.its')
        subprocess.run([str(tools / 'mkimage'), '-f', str(t / 'image.its'), str(t / 'image.fit')],
                       env={**os.environ, 'SOURCE_DATE_EPOCH': str(epoch)}, check=True, stdout=subprocess.DEVNULL)
        new = fit_properties(t / 'image.fit')
        verify_transition(old, new)
        require(new['/images/kernel-1', 'data'] == (t / 'image.lzma').read_bytes(), 'FIT payload mismatch')
        output.write_bytes((t / 'image.fit').read_bytes())
    return dict(parent_fit_sha256=sha(parent.read_bytes()), fit_sha256=sha(output.read_bytes()),
                image_sha256=sha(raw), dtb_sha256=sha(dtb), fit_bytes=output.stat().st_size)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('parent', 'image', 'output', 'host-tree'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--kernel', required=True)
    parser.add_argument('--epoch', type=int, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[4]
    print(json.dumps(build(args.parent, args.image, args.output, args.host_tree / 'staging_dir/host/bin',
                           repo, args.kernel, args.epoch), indent=2))


if __name__ == '__main__':
    main()
