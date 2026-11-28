#!/usr/bin/env python3
"""Verify four exact RF transitions and reject malformed or extra overrides."""
import copy
import runpy
import struct
import sys
import tarfile
from pathlib import Path

h = runpy.run_path(str(Path(__file__).with_name('band-profile.py')))
transform = h['wireless']
base = b"""config wifi-device 'radio0'
	option band '2g'
	option channel '1'
	option htmode 'EHT20'

config wifi-device 'radio1'
	option band '5g'
	option channel '36'
	option htmode 'EHT80'
	option noscan '1'
	option country 'PL'

config wifi-iface 'lab'
	option device 'radio0 radio1'
	option encryption 'sae'
	option ieee80211w '2'
"""
for name, (band, channel, width, _) in h['PROFILES'].items():
    expected = base.replace(b"htmode 'EHT80'", f"htmode 'EHT{width}'".encode())
    if band == 6:
        expected = expected.replace(b"band '5g'", b"band '6g'").replace(b"channel '36'", b"channel '5'")
        expected = expected.replace(b"noscan '1'", b"he_6ghz_reg_pwr_type '0'")
    assert transform(base, name) == expected
    for bad in (base + base, base.replace(b"channel '36'", b"channel '40'"),
                base.replace(b"country 'PL'", b"country 'US'"),
                base.replace(b"noscan '1'", b"noscan '0'"),
                base.replace(b"noscan '1'", b"noscan '1'\n\toption hostapd_options 'x'"),
                base.replace(b"noscan '1'", b"noscan '1'\n\toption he_6ghz_reg_pwr_type '1'")):
        try:
            transform(bad, name)
        except ValueError:
            pass
        else:
            raise AssertionError('unsafe profile accepted')
    pins = {k: v[0] for k, v in h['PINS'].items()} | {'other': 'unchanged'}
    assert h['radio_pins'](pins, name) == ({k: v[band == 6] for k,v in h['PINS'].items()} | {'other': 'unchanged'})
    bad = copy.copy(pins)
    bad[next(iter(h['PINS']))] = 'wrong'
    try:
        h['radio_pins'](bad, name)
    except ValueError:
        pass
    else:
        raise AssertionError('unverified parent pin accepted')
print('BAND_PROFILE_POLICY_PASS')
if len(sys.argv) > 1:
    parent = Path(sys.argv[1]).read_bytes()
    for arg in sys.argv[2:]:
        name, path = arg.split('=', 1)
        with tarfile.open(path) as tf:
            fit = tf.extractfile('sysupgrade-acer_wave7/kernel').read()
        h['verify_fit'](parent, fit, name)
        _, props = h['properties'](fit)
        dtb = props['/images/fdt-1', 'data']
        assert h['properties'](dtb)[1][h['RADIO'], 'qcom,board_id'] == struct.pack('>I', 0x91 if name.startswith('6g') else 0x53)
        print('BAND_FIT_TRANSITION_PASS', name)
