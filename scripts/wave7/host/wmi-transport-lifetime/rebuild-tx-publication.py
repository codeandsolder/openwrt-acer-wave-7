#!/usr/bin/env python3
"""Rebuild the Wi-Fi 7 TX publication change on a verified parent closure.

Reproduce the exact parent tree by content, then apply only the one-file patch.
All untouched objects are reused from the parent, not a partial rebuild.
"""
import argparse
import hashlib
from pathlib import Path
import re
import shlex
import subprocess

REL = Path('drivers/net/wireless/ath/ath12k/wifi7')
SOURCE = REL / 'dp_tx.c'
MODULE = REL / 'ath12k_wifi7'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('parent', type=Path)
    parser.add_argument('tree', type=Path)
    parser.add_argument('patch', type=Path)
    a = parser.parse_args()
    parent, tree = a.parent.resolve(), a.tree.resolve()
    if parent == tree or parent in tree.parents or tree in parent.parents:
        raise ValueError('parent and candidate must be disjoint trees')
    if not parent.is_dir() or not tree.is_dir():
        raise ValueError('expected two existing private backports trees')
    sync = ['rsync', '-a', '--checksum', '--delete', str(parent) + '/', str(tree) + '/']
    subprocess.run(sync, check=True)
    patch = a.patch.read_bytes()
    if re.findall(rb'^\+\+\+ b/(.+)$', patch, re.M) != [str(SOURCE).encode()]:
        raise ValueError('only the TX translation unit may change')
    subprocess.run(['patch', '--batch', '-p1'], input=patch, cwd=tree, check=True)
    changed = subprocess.check_output(sync[:2] + ['--dry-run', '--itemize-changes'] + sync[2:], text=True).splitlines()
    if len(changed) != 1 or changed[0].split(maxsplit=1)[1] != str(SOURCE):
        raise ValueError(f'unexpected input delta: {changed}')
    objects = [Path(p) for p in (tree / MODULE.with_suffix('.mod')).read_text().splitlines() if p]
    if SOURCE.with_suffix('.o') not in objects:
        raise ValueError('missing TX object from module inventory')
    old_symvers = digest(parent / 'Module.symvers')
    for target in [SOURCE.with_suffix('.o'), MODULE.with_suffix('.o'), Path('Module.symvers'), MODULE.with_suffix('.mod.o'), MODULE.with_suffix('.ko')]:
        cmdfile = tree / target.parent / ('.' + target.name + '.cmd')
        cmd = cmdfile.read_text().splitlines()[0].split(':=', 1)[1].strip()
        argv = shlex.split(re.sub(r'/home/jan/build/wave7/[^ /]+/compiled-backports', str(tree), cmd))
        if '-c' in argv and Path(argv[0]).name != 'sccache':
            raise ValueError('compiler must use sccache')
        subprocess.run(argv, cwd=tree, check=True)
        print(f'PASS {target}', flush=True)
    if digest(tree / 'Module.symvers') != old_symvers:
        raise ValueError('module ABI changed')
    for obj in objects:
        if obj != SOURCE.with_suffix('.o') and digest(tree / obj) != digest(parent / obj):
            raise ValueError(f'untouched object changed: {obj}')
    common = REL.parent / 'ath12k.ko'
    if digest(tree / common) != digest(parent / common):
        raise ValueError('common module changed')
    print('TX_PUBLICATION_CLOSURE_PASS', flush=True)


if __name__ == '__main__':
    main()
