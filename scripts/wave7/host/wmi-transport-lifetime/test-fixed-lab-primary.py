#!/usr/bin/env python3
"""The lab-only scan override is a one-stanza, one-line mutation."""
import runpy
from pathlib import Path

h = runpy.run_path(str(Path(__file__).with_name('pack-module-trial.py')))
transform = h['fixed_lab_primary']
base = b"""config wifi-device 'radio0'
	option band '2g'
	option channel '1'
	option htmode 'EHT20'

config wifi-device 'radio1'
	option band '5g'
	option channel '36'
	option htmode 'EHT80'

config wifi-iface 'lab'
	option device 'radio0 radio1'
"""
expected = base.replace(b"option htmode 'EHT80'\n", b"option htmode 'EHT80'\n\toption noscan '1'\n")
assert transform(base) == expected
for bad in (expected, base.replace(b"radio1'", b"radio0'"),
            base.replace(b"channel '36'", b"channel '40'"),
            base.replace(b"band '5g'", b"band '2g'"),
            base.replace(b"htmode 'EHT80'", b"htmode 'EHT40'"),
            base + base,
            base.replace(b"option htmode 'EHT80'", b"option htmode 'EHT80'\n\tlist hostapd_options 'foo=bar'")):
    try:
        transform(bad)
    except (ValueError, AssertionError, RuntimeError, SystemExit):
        pass
    else:
        raise AssertionError('unsafe wireless configuration accepted')
print('FIXED_LAB_PRIMARY_PASS')
