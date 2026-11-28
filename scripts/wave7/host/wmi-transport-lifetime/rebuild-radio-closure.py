#!/usr/bin/env python3
"""Rebuild the complete ath12k module closure with the original Kbuild commands.

Reproduce a private copy of an already built backports tree and apply a patch. Every C object in both
module inventories is recompiled, since shared HAL/ops layouts may change.
The original compiler wrapper and linker flags are retained. The source and
include roots must refer to the working copy, not its ancestor.
"""
import argparse
import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import shlex
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('parent', type=Path)
    p.add_argument('tree', type=Path)
    p.add_argument('patch', type=Path)
    p.add_argument('--jobs', type=int, default=4)
    a = p.parse_args()
    root = a.tree.resolve()
    parent = a.parent.resolve()
    if parent == root or parent in root.parents or root in parent.parents:
        p.error('parent and candidate must be disjoint trees')
    if not parent.is_dir() or not root.is_dir():
        p.error('expected existing parent and candidate trees')
    rel = Path('drivers/net/wireless/ath/ath12k')
    modules = [rel / 'ath12k', rel / 'wifi7/ath12k_wifi7']
    logs = root.parent / 'radio-build-logs'
    logs.mkdir(exist_ok=True)
    if a.jobs < 1:
        p.error('jobs must be positive')

    patch = a.patch.read_bytes()
    paths = [Path(s.decode()) for s in re.findall(rb'^\+\+\+ b/(.+)$', patch, re.M)]
    if not paths or len(paths) != len(set(paths)) or any(
        path.is_absolute() or '..' in path.parts or path.parts[:len(rel.parts)] != rel.parts
        or path.suffix not in ('.c', '.h') for path in paths
    ):
        raise ValueError('patch must change only unique ath12k C/header files')
    sync = ['rsync', '-a', '--checksum', '--delete', str(parent) + '/', str(root) + '/']
    subprocess.run(sync, check=True)
    subprocess.run(['patch', '--batch', '--fuzz=0', '-p1'], input=patch, cwd=root, check=True)
    changed = subprocess.check_output(sync[:2] + [
        '--dry-run', '--itemize-changes', '--no-times', '--omit-dir-times'
    ] + sync[2:], text=True).splitlines()
    if len(changed) != len(paths) or {line.split(maxsplit=1)[1] for line in changed} != set(map(str, paths)):
        raise ValueError(f'unexpected input delta: {changed}')

    def raw(target):
        path = parent / target.parent / ('.' + target.name + '.cmd')
        return shlex.split(path.read_text().splitlines()[0].split(':=', 1)[1].strip())

    # Kbuild records absolute backports paths even when the parent itself
    # was produced by replaying an older tree. Identify that root from the
    # mandatory backport include argument, not from its directory name.
    roots = set()
    for mod in modules:
        for obj in (parent / mod.with_suffix('.mod')).read_text().splitlines():
            for arg in raw(Path(obj)):
                if arg.startswith('-I') and arg.rstrip('/').endswith('/backport-include'):
                    roots.add(arg[2:].rstrip('/').removesuffix('/backport-include'))
    if len(roots) != 1:
        raise ValueError(f'ambiguous recorded backports source roots: {roots}')
    original = roots.pop()

    def recorded(target):
        args = []
        for arg in raw(target):
            if arg.startswith(('-fmacro-prefix-map=', '-ffile-prefix-map=', '-fdebug-prefix-map=')):
                flag, src, dst = arg.split('=', 2)
                arg = '='.join((flag, src.replace(original + '/', str(root) + '/'), dst))
            else:
                arg = arg.replace(original + '/', str(root) + '/')
            args.append(arg)
        return args

    def run(target):
        args = recorded(target)
        if '-c' in args and Path(args[0]).name != 'sccache':
            raise RuntimeError(f'{target}: compiler is not wrapped by sccache')
        log = logs / (str(target).replace('/', '_') + '.log')
        with log.open('w') as f:
            f.write(shlex.join(args) + '\n')
            f.flush()
            subprocess.run(args, cwd=root, stdout=f, stderr=subprocess.STDOUT, check=True)
        print(f'PASS {target}', flush=True)

    objects = []
    for mod in modules:
        objects.extend(Path(s) for s in (root / mod.with_suffix('.mod')).read_text().splitlines() if s)
    if len(objects) != len(set(objects)) or not objects:
        raise RuntimeError('invalid module inventories')
    for obj in objects:
        if not (root / obj.with_suffix('.c')).is_file():
            raise RuntimeError(f'missing C source: {obj}')
    with ThreadPoolExecutor(max_workers=a.jobs) as executor:
        list(executor.map(run, objects))
    for mod in modules:
        run(mod.with_suffix('.o'))
    run(Path('Module.symvers'))
    for mod in modules:
        run(mod.with_suffix('.mod.o'))
        run(mod.with_suffix('.ko'))
    def digest(path):
        return hashlib.sha256(path.read_bytes()).digest()

    if digest(root / 'Module.symvers') != digest(parent / 'Module.symvers'):
        raise ValueError('module ABI changed')
    changed_modules = {mod.with_suffix('.ko') for mod in modules}
    for path in parent.rglob('*.ko'):
        relative = path.relative_to(parent)
        if relative not in changed_modules and digest(path) != digest(root / relative):
            raise ValueError(f'unrelated module changed: {relative}')
    print(f'RADIO_CLOSURE_PASS objects={len(objects)} modules={len(modules)}', flush=True)

if __name__ == '__main__':
    main()
