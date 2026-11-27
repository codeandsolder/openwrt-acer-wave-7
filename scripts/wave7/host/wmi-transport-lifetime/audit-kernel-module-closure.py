#!/usr/bin/env python3
"""Audit a complete native module inventory against one kernel's built-in exports."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def command(*args):
    return subprocess.check_output([str(x) for x in args], text=True)


def inventory(root):
    modules = {}
    for path in sorted(root.rglob('*.ko')):
        require(path.is_file() and not path.is_symlink(), f'invalid module: {path}')
        require(path.name not in modules, f'duplicate module: {path.name}')
        modules[path.name] = path
    require(modules, f'empty module inventory: {root}')
    return modules


def builtin_symbols(path):
    symbols = set()
    for line in path.read_text().splitlines():
        fields = line.split()
        require(len(fields) >= 4, 'invalid kernel symbol record')
        if fields[2] == 'vmlinux':
            require(fields[1] not in symbols, f'duplicate built-in export: {fields[1]}')
            symbols.add(fields[1])
    require(symbols, 'no built-in kernel symbols')
    return symbols


def audit(parent, candidate, kernel_symvers, nm, kernel):
    old, new = inventory(parent), inventory(candidate)
    require(old.keys() == new.keys(), f'module inventory: missing={sorted(old.keys()-new.keys())}, extra={sorted(new.keys()-old.keys())}')
    builtin = builtin_symbols(kernel_symvers)
    provider = dict.fromkeys(builtin, 'vmlinux')
    modules = {}
    for filename, path in new.items():
        name = command('modinfo', '-F', 'name', path).strip().replace('-', '_')
        require(name and name not in modules, f'module identity: {filename}')
        vermagic = command('modinfo', '-F', 'vermagic', path).strip()
        require(vermagic.split()[0] == kernel and vermagic == command('modinfo', '-F', 'vermagic', old[filename]).strip(), f'vermagic: {filename}')
        depends = set(filter(None, command('modinfo', '-F', 'depends', path).strip().replace('-', '_').split(',')))
        exports = {x.split()[-1].removeprefix('__kstrtab_') for x in command(nm, path).splitlines()
                   if x.split() and x.split()[-1].startswith('__kstrtab_')}
        imports = {x.split()[-1] for x in command(nm, '-u', path).splitlines() if x.split()[-2:-1] == ['U']}
        for symbol in exports:
            require(symbol not in provider, f'duplicate symbol {symbol}: {provider.get(symbol)}, {name}')
            provider[symbol] = name
        modules[name] = dict(filename=filename, sha256=digest(path), parent_sha256=digest(old[filename]),
                             depends=sorted(depends), imports=imports, exports=exports)
    for name, mod in modules.items():
        require(set(mod['depends']) <= modules.keys(), f'missing declared dependency: {name}')
        require(mod['imports'] <= provider.keys(), f'unresolved {name}: {sorted(mod["imports"]-provider.keys())}')
        actual = {provider[symbol] for symbol in mod['imports']} - {'vmlinux', name}
        require(actual <= set(mod['depends']), f'undeclared dependencies {name}: {sorted(actual-set(mod["depends"]))}')
    # A complete dependency inventory must admit a topological load order.
    remaining = set(modules)
    loaded = set()
    while remaining:
        ready = {name for name in remaining if set(modules[name]['depends']) <= loaded}
        require(ready, f'cyclic module dependencies: {sorted(remaining)}')
        loaded.update(ready)
        remaining.difference_update(ready)
    for mod in modules.values():
        mod['imports'] = len(mod['imports'])
        mod['exports'] = len(mod['exports'])
    return dict(kernel=kernel, kernel_symvers_sha256=digest(kernel_symvers), builtin_exports=len(builtin),
                module_count=len(modules), modules=modules)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('parent', 'candidate', 'kernel-symvers'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--nm', required=True)
    parser.add_argument('--kernel', required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.parent, args.candidate, args.kernel_symvers, args.nm, args.kernel),
                     indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
