#!/usr/bin/env python3
"""Verify replacement closure against the exact packaged parent and kernel exports."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(f):
    return hashlib.sha256(f.read_bytes()).hexdigest()


def run(*args):
    return subprocess.check_output([str(a) for a in args], text=True)


def inventory(root):
    result = {}
    for f in sorted(root.rglob('*.ko')):
        require(f.name not in result, f'duplicate module {f.name}')
        result[f.name] = f
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'candidate', 'parent', 'kernel-symvers', 'candidate-symvers'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--nm', required=True)
    p.add_argument('--kernel', required=True)
    a = p.parse_args()

    def imports(f):
        return {x.split()[-1] for x in run(a.nm, '-u', f).splitlines() if x.split()[-2:-1] == ['U']}

    def exports(f):
        return {x.split()[-1].removeprefix('__kstrtab_') for x in run(a.nm, f).splitlines()
                if x.split() and x.split()[-1].startswith('__kstrtab_')}

    old, new, parent = map(inventory, (a.baseline, a.candidate, a.parent))
    require(old and old.keys() == new.keys() and old.keys() <= parent.keys(), 'module inventory')
    for name, f in old.items():
        require(digest(f) == digest(parent[name]), f'parent reproduction: {name}')
    selected = {name for name in old if digest(old[name]) != digest(new[name])}
    require(selected, 'empty replacement')
    kernel_symbols = {line.split()[1] for line in a.kernel_symvers.read_text().splitlines()}
    module_symbols = {line.split()[1] for line in a.candidate_symvers.read_text().splitlines()}
    require(module_symbols == set.union(*(exports(f) for f in new.values())), 'candidate export mismatch')
    changed = set.union(*(exports(old[name]) ^ exports(new[name]) for name in selected))
    available = kernel_symbols | module_symbols
    records = []
    for name, f in new.items():
        vermagic = run('modinfo', '-F', 'vermagic', f)
        require(vermagic.split()[0] == a.kernel and vermagic == run('modinfo', '-F', 'vermagic', old[name]), f'vermagic: {name}')
        require(run('modinfo', '-F', 'depends', f) == run('modinfo', '-F', 'depends', old[name]), f'depends: {name}')
        u, v = imports(f), imports(old[name])
        require(not u - available, f'unresolved {name}: {sorted(u - available)}')
        require(name in selected or not u & changed, f'unchanged closure consumer: {name}')
        records.append(dict(name=name, selected=name in selected, imports=len(u),
                            added_imports=sorted(u-v), removed_imports=sorted(v-u),
                            before=digest(old[name]), after=digest(f)))
    external = []
    for name, f in parent.items():
        if name in new:
            continue
        require(not imports(f) & changed, f'outside consumer of changed export: {name}')
        # Do not silently mix an ABI consumer outside the rebuilt closure.
        dependencies = set(run('modinfo', '-F', 'depends', f).strip().split(','))
        require(not dependencies & {Path(n).stem.replace('-', '_') for n in selected}, f'outside closure dependency: {name}')
        external.append(name)
    print(json.dumps(dict(modules=records, external_consumers=external,
                          exports_changed=sorted(changed), parent_reproduced=sorted(old),
                          selected=sorted(selected)), indent=2))


if __name__ == '__main__':
    main()
