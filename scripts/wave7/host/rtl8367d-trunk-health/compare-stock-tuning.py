#!/usr/bin/env python3
"""Compare Acer stock 067 family-D SerDes tables with the patched driver.

The offsets are tied to this exact image SHA, verified from the ARM
jump table in dal_rtl8367d_port_macForceLinkExt_set. Do not apply these
offsets to a different firmware binary.
"""
import hashlib
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

STOCK_SHA = "e2efdabbbc2c852ee9bf6b50a40c0759fbc470b95da77a7f524816ddb3db6120"
TABLES = (
    ("sgmii", 0xD81C, 0xE2FC, 0xB7C),
    ("hsgmii", 0xD8D4, 0xE300, 0xBCC),
)

def compare(module, source):
    data = module.read_bytes()
    if hashlib.sha256(data).hexdigest() != STOCK_SHA:
        raise ValueError("stock module SHA mismatch")
    if data[:6] != b"\x7fELF\x01\x01":
        raise ValueError("not little-endian ELF32")
    sections = subprocess.check_output(["readelf", "-SW", str(module)], text=True)
    def section(name):
        found = re.search(r"^\s*\[\s*\d+\]\s+" + re.escape(name) +
                          r"\s+\S+\s+[0-9a-fA-F]+\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)",
                          sections, re.M)
        if not found:
            raise ValueError(f"missing {name} section")
        return tuple(int(v, 16) for v in found.groups())
    text_off, text_len = section(".text")
    rodata_off, rodata_len = section(".rodata")
    s = source.read_text()
    results = {}
    for mode, branch, literal, offset in TABLES:
        # ARM LDR r9,[pc,#imm12], literal relocation into .rodata.
        insn = struct.unpack_from("<I", data, text_off+branch)[0]
        if (insn & 0xFFFFF000) != 0xE59F9000 or branch+8+(insn&0xFFF) != literal:
            raise ValueError(f"unexpected literal load for {mode}")
        if literal+4 > text_len or struct.unpack_from("<I", data, text_off+literal)[0] != offset:
            raise ValueError(f"unexpected table pointer for {mode}")
        if offset+80 > rodata_len:
            raise ValueError("table exceeds rodata")
        stock = [struct.unpack_from("<II", data, rodata_off+offset+i*8)
                 for i in range(10)]
        match = re.search(r"rtl8365mb_d_sds_jam_" + mode + r"\[\]\s*=\s*\{(.*?)\};",
                          s, re.S)
        if match is None:
            raise ValueError(f"missing driver table {mode}")
        driver = [(int(a,16),int(b,16)) for a,b in re.findall(
            r"\{\s*(0x[0-9a-fA-F]+),\s*(0x[0-9a-fA-F]+)\s*\}",match[1])]
        results[mode] = {
            "stock_rodata_offset": hex(offset),
            "driver_entries": len(driver),
            "stock_entries": len(stock),
            "ordered_exact_match": stock == driver,
            "registers": [{"register": f"0x{reg:04x}", "value": f"0x{val:04x}"}
                          for reg,val in stock],
        }
    return {"stock_module_sha256": STOCK_SHA,
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "modes": results}

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: compare-stock-tuning.py STOCK_MODULE PATCHED_DRIVER_C")
    result = compare(Path(sys.argv[1]),Path(sys.argv[2]))
    print(json.dumps(result, indent=2))
    if not all(m["ordered_exact_match"] for m in result["modes"].values()):
        raise SystemExit(1)
