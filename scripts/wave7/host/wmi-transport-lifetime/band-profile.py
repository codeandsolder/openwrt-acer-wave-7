#!/usr/bin/env python3
"""Immutable Wave 7 lab RF profiles, derived from the stock mi04.1-c2 board."""
import argparse
import hashlib
import re
import runpy
import struct
import subprocess
import tempfile
from pathlib import Path

PROFILES = {
    '5g80': (5, 36, 80, 5210),
    '5g160': (5, 36, 160, 5250),
    '6g80': (6, 5, 80, 5985),
    '6g160': (6, 5, 160, 6025),
}
PINS = {
    'QCN6432/hw1.0/board.bin': (
        'f63bb6540a01b18dd342493f7cac32573ceb5888b048a92da6600a21633f42f7',
        'bdfdf48ff3c3859997dd4afceaa72c561d72926923138bdb20f142a28b78f811'),
    'QCN6432/hw1.0/caldata_1.bin': (
        'ee077ea46ebe8d9dae38af54bf4a03881742e2ac80a24a7e852f6398817e1aa5',
        '5e2cc782f6f0cd002b5243d27f99f432de3c88d72b5baa5b0544033359df0e3b'),
}
TLMM = '/soc@0/pinctrl@1000000'
RADIO = '/soc@0/wifi'
HOGS = ('wave7-rf-select-49', 'wave7-rf-select-50')


def require(ok, why):
    if not ok:
        raise ValueError(why)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def radio_pins(base, profile):
    band = PROFILES[profile][0]
    result = dict(base)
    for path, pair in PINS.items():
        require(result.get(path) == pair[0], 'unexpected parent pin ' + path)
        result[path] = pair[band == 6]
    return result


def wireless(data, profile):
    band, channel, width, _ = PROFILES[profile]
    sections = re.split(r'(?m)(?=^config )', data.decode())
    matches = [i for i, s in enumerate(sections)
               if s.startswith("config wifi-device 'radio1'\n")]
    require(len(matches) == 1, 'unique radio1')
    i = matches[0]
    s = sections[i]
    for key, value in (('band', '5g'), ('channel', '36'), ('htmode', 'EHT80'),
                       ('noscan', '1'), ('country', 'PL')):
        require(re.findall(r"(?m)^\s*option " + key + r" '([^']+)'$", s) == [value],
                'unexpected parent radio1 ' + key)
        require(s.count(f"\toption {key} '{value}'\n") == 1, 'noncanonical radio1')
    require(not re.search(r'(?m)^\s*(?:option|list) (?:hostapd_options|he_6ghz_reg_pwr_type)\b', s),
            'unexpected regulatory override')
    s = s.replace("\toption htmode 'EHT80'\n", f"\toption htmode 'EHT{width}'\n")
    if band == 6:
        s = s.replace("\toption band '5g'\n", "\toption band '6g'\n")
        s = s.replace("\toption channel '36'\n", f"\toption channel '{channel}'\n")
        # No 5 GHz HT40 scan override in 6 GHz; explicitly select indoor LPI.
        s = s.replace("\toption noscan '1'\n", "\toption he_6ghz_reg_pwr_type '0'\n")
    sections[i] = s
    return ''.join(sections).encode()


def properties(data):
    """Parse FDT property inventory, including large inline FIT payloads."""
    magic, total, start, strings, _, version, _, _, slen, length = struct.unpack_from('>10I', data)
    require(magic == 0xd00dfeed and total <= len(data) and version >= 17, 'FDT header')
    require(start + length <= total and strings + slen <= total, 'FDT bounds')
    result, nodes, stack = {}, set(), []
    pos = start
    while pos < start + length:
        token, = struct.unpack_from('>I', data, pos)
        pos += 4
        if token == 1:
            end = data.index(b'\0', pos, start + length)
            stack.append(data[pos:end].decode())
            pos = (end + 4) & ~3
            node = '/'.join(stack) or '/'
            require(node not in nodes, 'duplicate node')
            nodes.add(node)
        elif token == 2:
            require(bool(stack), 'FDT unbalanced')
            stack.pop()
        elif token == 3:
            size, offset = struct.unpack_from('>II', data, pos)
            pos += 8
            require(bool(stack) and offset < slen and pos + size <= start + length, 'FDT property bounds')
            end = data.index(b'\0', strings + offset, strings + slen)
            key = ('/'.join(stack) or '/', data[strings + offset:end].decode())
            require(key not in result, 'duplicate property')
            result[key] = data[pos:pos + size]
            pos = (pos + size + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            require(not stack, 'FDT unbalanced')
            return nodes, result
        else:
            raise ValueError('unknown FDT token')
    raise ValueError('missing FDT end')


def expected_dtb(before, profile):
    band = PROFILES[profile][0]
    nodes, props = before
    require(props[TLMM, 'compatible'] == b'qcom,ipq5332-tlmm\0', 'wrong GPIO controller')
    require(props[RADIO, 'compatible'] == b'qcom,qcn6432-wifi\0', 'wrong external radio')
    require(props[RADIO, 'qcom,board_id'] == struct.pack('>I', 0x53), 'unexpected parent board ID')
    require(props.get((TLMM, 'status'), b'okay\0') == b'okay\0', 'disabled GPIO controller')
    result = dict(props)
    result[RADIO, 'qcom,board_id'] = struct.pack('>I', 0x91 if band == 6 else 0x53)
    expected_nodes = set(nodes)
    # GPIO hogs are requested by gpiolib before the radio driver can probe.
    # Active-high descriptors, 49/50 from stock legacy GPIO508/509.
    for index, name in enumerate(HOGS):
        node = TLMM + '/' + name
        require(node not in nodes, 'parent already has RF profile')
        expected_nodes.add(node)
        result[node, 'gpio-hog'] = b''
        result[node, 'gpios'] = struct.pack('>II', 49 + index, 0)
        result[node, 'line-name'] = name.encode() + b'\0'
        high = (index == (band == 6))
        result[node, 'output-high' if high else 'output-low'] = b''
    return expected_nodes, result


def reservations(data):
    _, total, start, _, offset = struct.unpack_from('>5I', data)
    require(40 <= offset < start <= total <= len(data), 'FDT reservation bounds')
    result = []
    while offset + 16 <= start:
        address, size = struct.unpack_from('>QQ', data, offset)
        offset += 16
        if not (address or size):
            return result
        result.append((address, size))
    raise ValueError('missing FDT reservation terminator')


def verify_dtb(before, after, profile):
    require(properties(after) == expected_dtb(properties(before), profile), 'unexpected DT transition')
    require(reservations(before) == reservations(after), 'DT memory reservations changed')


def verify_fit(before, after, profile):
    helper = runpy.run_path(str(Path(__file__).with_name('build-profile-fit.py')))
    old_nodes, old = properties(before)
    new_nodes, new = properties(after)
    helper['verify_hashes'](old)
    helper['verify_hashes'](new)
    allowed = {('/', 'timestamp'), ('/images/fdt-1', 'data'),
               ('/images/fdt-1/hash-1', 'value'), ('/images/fdt-1/hash-2', 'value')}
    require(new_nodes == old_nodes and new.keys() == old.keys(), 'FIT inventory changed')
    require(all(new[k] == old[k] for k in old.keys() - allowed), 'FIT kernel/metadata changed')
    require(reservations(before) == reservations(after), 'FIT memory reservations changed')
    verify_dtb(old['/images/fdt-1', 'data'], new['/images/fdt-1', 'data'], profile)


def command(*args):
    subprocess.run([str(x) for x in args], check=True, stdout=subprocess.DEVNULL)


def build_fit(parent, output, profile, tools, repo, kernel, epoch):
    require(not output.exists(), 'output exists')
    helper = runpy.run_path(str(Path(__file__).with_name('build-profile-fit.py')))
    _, old = properties(parent.read_bytes())
    helper['verify_hashes'](old)
    require(old['/images/kernel-1', 'compression'] == b'lzma\0', 'kernel compression')
    require(old['/configurations', 'default'] == b'config@mi04.1-c2\0', 'board config')
    original = old['/images/fdt-1', 'data']
    band = PROFILES[profile][0]
    with tempfile.TemporaryDirectory(prefix='.band-fit-', dir=output.parent) as tmp:
        t = Path(tmp)
        dtb = t / 'board.dtb'
        dtb.write_bytes(original)
        expected_dtb(properties(original), profile)
        if band == 6:
            # libfdt path lookup for an unaddressed node can match a sibling
            # with a unit address. Recompile the unique board-ID property
            # and verify the exact node/property inventory instead.
            dts = subprocess.check_output(['dtc', '-I', 'dtb', '-O', 'dts', str(dtb)], text=True)
            require(dts.count('qcom,board_id = <0x53>;') == 1, 'unique stock board ID')
            (t / 'board.dts').write_text(dts.replace('qcom,board_id = <0x53>;',
                                                    'qcom,board_id = <0x91>;'))
            command('dtc', '-I', 'dts', '-O', 'dtb', '-o', dtb, t / 'board.dts')
        for index, name in enumerate(HOGS):
            node = TLMM + '/' + name
            command('fdtput', '-c', dtb, node)
            command('fdtput', dtb, node, 'gpio-hog')
            command('fdtput', '-t', 'i', dtb, node, 'gpios', 49 + index, 0)
            command('fdtput', '-t', 's', dtb, node, 'line-name', name)
            command('fdtput', dtb, node, 'output-high' if index == (band == 6) else 'output-low')
        verify_dtb(original, dtb.read_bytes(), profile)
        command('sh', repo / 'scripts/wave7/verify-boot-mode-dtb.sh', 'nand', dtb, '/usr/bin/dtc')
        (t / 'image.lzma').write_bytes(old['/images/kernel-1', 'data'])
        command('sh', repo / 'scripts/mkits.sh', '-A', 'arm64', '-C', 'lzma',
                '-a', '0x41000000', '-e', '0x41000000', '-c', 'config@mi04.1-c2',
                '-D', 'acer_wave7', '-v', kernel, '-k', t / 'image.lzma',
                '-d', dtb, '-o', t / 'image.its')
        import os
        subprocess.run([str(tools / 'mkimage'), '-f', str(t / 'image.its'), str(t / 'image.fit')],
                       env={**os.environ, 'SOURCE_DATE_EPOCH': str(epoch)}, check=True,
                       stdout=subprocess.DEVNULL)
        candidate = (t / 'image.fit').read_bytes()
        verify_fit(parent.read_bytes(), candidate, profile)
        output.write_bytes(candidate)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile', choices=PROFILES, required=True)
    p.add_argument('--parent', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--host-tree', type=Path, required=True)
    p.add_argument('--kernel', required=True)
    p.add_argument('--epoch', type=int, required=True)
    a = p.parse_args()
    build_fit(a.parent, a.output, a.profile, a.host_tree / 'staging_dir/host/bin',
              Path(__file__).resolve().parents[4], a.kernel, a.epoch)
    print('BAND_FIT_PASS', a.profile, sha(a.output.read_bytes()))
