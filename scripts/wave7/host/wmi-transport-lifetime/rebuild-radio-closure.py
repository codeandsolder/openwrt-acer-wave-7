#!/usr/bin/env python3
"""Rebuild the complete ath12k module closure with the original Kbuild commands.

Use a private copy of an already built backports tree. Every C object in both
module inventories is recompiled, since shared HAL/ops layouts may change.
The original compiler wrapper and linker flags are retained. The source and
include roots must refer to the working copy, not its ancestor.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import shlex
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('tree', type=Path)
    p.add_argument('--jobs', type=int, default=4)
    a = p.parse_args()
    root = a.tree.resolve()
    rel = Path('drivers/net/wireless/ath/ath12k')
    modules = [rel / 'ath12k', rel / 'wifi7/ath12k_wifi7']
    logs = root.parent / 'radio-build-logs'
    logs.mkdir(exist_ok=True)
    if a.jobs < 1:
        p.error('jobs must be positive')

    def recorded(target):
        path = root / target.parent / ('.' + target.name + '.cmd')
        line = path.read_text().splitlines()[0]
        cmd = line.split(':=', 1)[1].strip()
        # The previous tree may itself have been copied. Rewrite any recorded
        # backports checkout root but preserve the canonical debug-prefix RHS.
        cmd = re.sub(r'/home/jan/build/wave7/[^ /]+/compiled-backports', str(root), cmd)
        return shlex.split(cmd)

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
    print(f'RADIO_CLOSURE_PASS objects={len(objects)} modules={len(modules)}', flush=True)

if __name__ == '__main__':
    main()
