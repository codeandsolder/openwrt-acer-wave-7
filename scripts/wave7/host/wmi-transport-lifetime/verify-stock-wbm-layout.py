#!/usr/bin/env python3
"""Extract the pinned Acer 067 BE release map and verify its ARM32 consumers."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

WIFI_SHA = '0e91547a5b42bfc54f9a822c33345a95e6a48e71a6dcefc0b68f1713fa29a18a'
HAL_SHA = '4e2f8a9cdd6732a01528083a1db7956be555764706551be9c8d5dd78ba00298a'


class Elf:
    def __init__(self, path, digest):
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f'wrong original module: {path.name}')
        if data[:6] != b'\x7fELF\x01\x01' or struct.unpack_from('<HH', data, 16) != (1, 40):
            raise ValueError('not an ARM32 LE relocatable ELF')
        offset = struct.unpack_from('<I', data, 32)[0]
        entsize, count, names = struct.unpack_from('<HHH', data, 46)
        if entsize != 40:
            raise ValueError('unexpected ELF section header size')
        self.headers = [struct.unpack_from('<10I', data, offset + i*entsize) for i in range(count)]
        self.sections = [data[h[4]:h[4]+h[5]] for h in self.headers]
        def name(blob, off):
            return blob[off:blob.index(b'\0',off)].decode('ascii')
        self.names = {name(self.sections[names], h[0]):i for i,h in enumerate(self.headers)}
        symtab = self.names['.symtab']
        strings = self.sections[self.headers[symtab][6]]
        self.symbols = [(name(strings, n), val, sec) for n,val,_,_,_,sec in struct.iter_unpack('<IIIBBH',self.sections[symtab])]
        self.relocs = {addr:(info & 255,self.symbols[info >> 8]) for addr,info in struct.iter_unpack('<II', self.sections[self.names['.rel.text']])}
        self.text = self.sections[self.names['.text']]

    def word(self, address):
        return struct.unpack_from('<I', self.text, address)[0]

    def check(self, address, word):
        if self.word(address) != word:
            raise ValueError(f'unexpected instruction at {address:#x}')

    def relocation(self, address, kind, expected):
        actual, sym = self.relocs[address]
        if actual != kind or sym[0] != expected:
            raise ValueError(f'unexpected relocation at {address:#x}')
        return sym


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('module_directory', type=Path)
    a = p.parse_args()
    wifi = Elf(a.module_directory/'wifi_3_0.ko', WIFI_SHA)
    hal = Elf(a.module_directory/'qca_ol.ko', HAL_SHA)
    # BE attach: load RX ring ID in r1, call actual setter, then materialize
    # the relocated table pointer and store it in cfg+0x2b4.
    mov = wifi.word(0xc9108)
    if mov & 0xffffff00 != 0xe3a01000:
        raise ValueError('not MOV r1, immediate')
    rx = mov & 0xff
    wifi.relocation(0xc9110,28,'wlan_cfg_set_rx_rel_ring_id')
    low = wifi.relocation(0xc911c,43,'.LANCHOR1')
    high = wifi.relocation(0xc9124,44,'.LANCHOR1')
    if low != high or low[2] != wifi.names['.data']:
        raise ValueError('inconsistent relocated table')
    for addr, word in {0xc911c:0xe3003000,0xc9124:0xe3403000,0xc9128:0xe58232b4,
                       0x4f4a4:0xe3510004,0x4f4fc:0xe590c2b4,0x4f510:0xe7dc7104,
                       0x4f518:0xe5de8001,0x4f534:0xe1a03007,0x4f538:0xe3a02005,
                       0x4f5b0:0xe1a03008,0x4f5b8:0xe3a0200d,0x4f620:0xe0837107,
                       0x4f624:0xe5d72002,0x4f628:0xe12fff34}.items():
        wifi.check(addr,word)
    wifi.relocation(0x4f548,28,'dp_srng_init')
    wifi.relocation(0x4f5c0,28,'dp_srng_init')
    # The helper accepts logical IDs 0..4 and indexes four-byte map rows.
    offset = low[1]
    rows = [dict(tcl=tcl,wbm=wbm,rbm=rbm,reserved=reserved) for tcl,wbm,rbm,reserved in struct.iter_unpack('<BBBB', wifi.sections[low[2]][offset:offset+20])]
    if len(rows) != 5 or any(r['reserved'] for r in rows) or rx in {r['wbm'] for r in rows}:
        raise ValueError('invalid stock table')
    # Cookie-conversion control: the stock function packs one bit per WBM
    # release ring into the register, including the bit at position six.
    for addr,word in {0xd73f0:0xe5d42006,0xd7404:0xe7e002d2,
                      0xd741c:0xe1833300,0xd7448:0xe1837087,
                      0xd7454:0xe3043094}.items():
        hal.check(addr,word)
    print(json.dumps(dict(wifi_sha256=WIFI_SHA,hal_sha256=HAL_SHA,table_offset=hex(offset),rx_release=rx,tx=rows,rx_cookie_enable_bit=rx+1),indent=2))

if __name__ == '__main__':
    main()
