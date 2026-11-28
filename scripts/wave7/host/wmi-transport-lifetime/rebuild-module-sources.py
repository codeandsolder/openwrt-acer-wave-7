#!/usr/bin/env python3
"""Rebuild changed translation units of one module on a verified parent closure.

Reproduce the exact parent tree by content, then apply only the patch with an exact source allowlist.
All untouched objects are reused from the parent, not a partial rebuild.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
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
    parser.add_argument('--source', required=True, type=Path, action='append')
    parser.add_argument('--module', required=True, type=Path, help='module path without suffix')
    a = parser.parse_args()
    sources, module = set(a.source), a.module
    if len(sources) != len(a.source):
        raise ValueError('duplicate selected source')
    for path in (*sources, module):
        if path.is_absolute() or '..' in path.parts or path.parts[:4] != ('drivers', 'net', 'wireless', 'ath'):
            raise ValueError(f'invalid module source path: {path}')
    if any(source.suffix != '.c' for source in sources) or module.suffix:
        raise ValueError('expected C source and module without suffix')
    parent, tree = a.parent.resolve(), a.tree.resolve()
    if parent == tree or parent in tree.parents or tree in parent.parents:
        raise ValueError('parent and candidate must be disjoint trees')
    if not parent.is_dir() or not tree.is_dir():
        raise ValueError('expected two existing private backports trees')
    sync = ['rsync', '-a', '--checksum', '--delete', str(parent) + '/', str(tree) + '/']
    subprocess.run(sync, check=True)
    patch = a.patch.read_bytes()
    patch_sources = re.findall(rb'^\+\+\+ b/(.+)$', patch, re.M)
    if len(patch_sources) != len(sources) or set(patch_sources) != {str(source).encode() for source in sources}:
        raise ValueError('only the selected translation units may change')
    subprocess.run(['patch', '--batch', '-p1'], input=patch, cwd=tree, check=True)
    changed = subprocess.check_output(sync[:2] + ['--dry-run', '--itemize-changes', '--no-times', '--omit-dir-times'] + sync[2:], text=True).splitlines()
    if len(changed) != len(sources) or {line.split(maxsplit=1)[1] for line in changed} != {str(source) for source in sources}:
        raise ValueError(f'unexpected input delta: {changed}')
    objects = [Path(p) for p in (tree / module.with_suffix('.mod')).read_text().splitlines() if p]
    selected = {source.with_suffix('.o') for source in sources}
    if not selected <= set(objects):
        raise ValueError('missing selected objects from module inventory')
    old_symvers = digest(parent / 'Module.symvers')
    def rebuild(target):
        cmdfile = parent / target.parent / ('.' + target.name + '.cmd')
        cmd = cmdfile.read_text().splitlines()[0].split(':=', 1)[1].strip()
        argv = shlex.split(cmd.replace(str(parent), str(tree)))
        if '-c' in argv and Path(argv[0]).name != 'sccache':
            raise ValueError('compiler must use sccache')
        subprocess.run(argv, cwd=tree, check=True)
        print(f'PASS {target}', flush=True)

    with ThreadPoolExecutor(max_workers=len(selected)) as executor:
        list(executor.map(rebuild, sorted(selected)))
    for target in [module.with_suffix('.o'), Path('Module.symvers'), module.with_suffix('.mod.o'), module.with_suffix('.ko')]:
        rebuild(target)
    if digest(tree / 'Module.symvers') != old_symvers:
        raise ValueError('module ABI changed')
    for obj in objects:
        if obj not in selected and digest(tree / obj) != digest(parent / obj):
            raise ValueError(f'untouched object changed: {obj}')
    for original in parent.rglob('*.ko'):
        rel = original.relative_to(parent)
        if rel != module.with_suffix('.ko') and digest(tree / rel) != digest(original):
            raise ValueError(f'untouched module changed: {rel}')
    print('MODULE_SOURCE_CLOSURE_PASS', flush=True)


if __name__ == '__main__':
    main()
