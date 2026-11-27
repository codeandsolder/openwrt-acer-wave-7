#!/usr/bin/env python3
"""Check actual Kbuild C invocations for every object in the module closure."""
import argparse
import json
from pathlib import Path
import shlex


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('--require-flag', action='append', required=True)
    p.add_argument('--compiler-wrapper', type=Path, default=Path('/usr/local/bin/sccache'))
    a = p.parse_args()
    root = a.source.resolve()
    objects = set()
    for module in (root / 'modules.order').read_text().splitlines():
        manifest = (root / module).with_suffix('.mod')
        objects.update(manifest.read_text().split())
    failures = []
    compiled = 0
    for obj in sorted(objects):
        path = root / obj
        # Assembly inputs do not consume C-only flags.
        if not path.with_suffix('.c').exists():
            continue
        record = path.with_name('.' + path.name + '.cmd')
        cmd = record.read_text().splitlines()[0].split(' := ', 1)[1]
        argv = shlex.split(cmd)
        compiled += 1
        missing = [flag for flag in a.require_flag if flag not in argv]
        if argv[0] != str(a.compiler_wrapper) or missing:
            failures.append({'object': obj, 'wrapper': argv[0], 'missing': missing})
    print(json.dumps({'c_objects': compiled, 'failures': failures}, indent=2))
    if not compiled or failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
