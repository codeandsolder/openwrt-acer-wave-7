#!/usr/bin/env python3
"""Rebuild one changed translation unit on a verified parent closure.

Reproduce the exact parent tree by content, then apply only the one-file patch.
All untouched objects are reused from the parent, not a partial rebuild.
"""
import argparse
import hashlib
from pathlib import Path
import re
import shlex
import subprocess



def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('parent', type=Path)
    parser.add_argument('tree', type=Path)
    parser.add_argument('patch', type=Path)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--module', required=True, type=Path, help='module path without suffix')
    a = parser.parse_args()
    source, module = a.source, a.module
    for path in (source, module):
        if path.is_absolute() or '..' in path.parts or path.parts[:4] != ('drivers', 'net', 'wireless', 'ath'):
            raise ValueError(f'invalid module source path: {path}')
    if source.suffix != '.c' or module.suffix:
        raise ValueError('expected C source and module without suffix')
    parent, tree = a.parent.resolve(), a.tree.resolve()
    if parent == tree or parent in tree.parents or tree in parent.parents:
        raise ValueError('parent and candidate must be disjoint trees')
    if not parent.is_dir() or not tree.is_dir():
        raise ValueError('expected two existing private backports trees')
    sync = ['rsync', '-a', '--checksum', '--delete', str(parent) + '/', str(tree) + '/']
    subprocess.run(sync, check=True)
    patch = a.patch.read_bytes()
    if re.findall(rb'^\+\+\+ b/(.+)$', patch, re.M) != [str(source).encode()]:
        raise ValueError('only the selected translation unit may change')
    subprocess.run(['patch', '--batch', '-p1'], input=patch, cwd=tree, check=True)
    changed = subprocess.check_output(sync[:2] + ['--dry-run', '--itemize-changes', '--no-times', '--omit-dir-times'] + sync[2:], text=True).splitlines()
    if len(changed) != 1 or changed[0].split(maxsplit=1)[1] != str(source):
        raise ValueError(f'unexpected input delta: {changed}')
    objects = [Path(p) for p in (tree / module.with_suffix('.mod')).read_text().splitlines() if p]
    if source.with_suffix('.o') not in objects:
        raise ValueError('missing selected object from module inventory')
    old_symvers = digest(parent / 'Module.symvers')
    for target in [source.with_suffix('.o'), module.with_suffix('.o'), Path('Module.symvers'), module.with_suffix('.mod.o'), module.with_suffix('.ko')]:
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
        if obj != source.with_suffix('.o') and digest(tree / obj) != digest(parent / obj):
            raise ValueError(f'untouched object changed: {obj}')
    for original in parent.rglob('*.ko'):
        rel = original.relative_to(parent)
        if rel != module.with_suffix('.ko') and digest(tree / rel) != digest(original):
            raise ValueError(f'untouched module changed: {rel}')
    print('SINGLE_SOURCE_CLOSURE_PASS', flush=True)


if __name__ == '__main__':
    main()
