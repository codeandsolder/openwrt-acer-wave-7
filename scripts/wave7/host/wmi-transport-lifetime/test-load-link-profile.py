#!/usr/bin/env python3
"""Check topology qualification independently of the TCP traffic itself."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('load', Path(__file__).with_name('load-result.py'))
load = importlib.util.module_from_spec(spec)
spec.loader.exec_module(load)


def rejects(fn, *args):
    try:
        fn(*args)
    except ValueError:
        return
    raise AssertionError(f'accepted invalid evidence {args}')


for expected in (1, 2, 3):
    for observed in (0, 1, 2, 3, 4, 7):
        text = f'epoch=123.456 active=0x00{observed} valid=0x3 dormant=0x0000\n'
        if observed == expected:
            load.check_link(text, expected)
        else:
            rejects(load.check_link, text, expected)
    for valid, dormant in ((1, 0), (2, 0), (7, 0), (3, 1), (3, 2)):
        rejects(load.check_link, f'active=0x{expected} valid=0x{valid} dormant=0x{dormant}', expected)

single = 'upstream-prefix22-authorize-single-link-trace'
for band, bssid, active in [('24', r'70\:5A\:6F\:5A\:BB\:16', 1), ('5', r'4E\:5A\:6F\:5A\:BB\:16', 2)]:
    files = {'module-stack.txt': f'STACK_CANDIDATE_PASS variant={single} boot=example\n',
             'association-preference.txt': bssid + '\n\n0\n'}
    assert load.load_link_profile(files, band) == active
    rejects(load.load_link_profile, files, '5' if band == '24' else '24')
    rejects(load.load_link_profile, files, 'invalid')
    bad = dict(files, **{'module-stack.txt': ''})
    rejects(load.load_link_profile, bad, band)
    bad = dict(files, **{'module-stack.txt': files['module-stack.txt'] * 2})
    rejects(load.load_link_profile, bad, band)
    dual = dict(files, **{'module-stack.txt': 'STACK_CANDIDATE_PASS variant=dual-example boot=example\n'})
    assert load.load_link_profile(dual, band) == 3
print('LOAD_LINK_PROFILE_SELFTEST_PASS')
