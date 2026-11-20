#!/usr/bin/env python3
"""Verify FIT semantic delta and both payload hashes, offline."""
import hashlib
import lzma
from pathlib import Path
import struct
import sys
import zlib


def properties(path):
    data = Path(path).read_bytes()
    magic, total, off_struct, off_strings, _, version, _, _, strings_size, struct_size = struct.unpack_from(">10I", data)
    assert magic == 0xd00dfeed and version == 17 and total <= len(data)
    assert off_struct + struct_size <= total and off_strings + strings_size <= total
    pos, end = off_struct, off_struct + struct_size
    strings = data[off_strings:off_strings + strings_size]
    stack, props, nodes = [], {}, set()
    def u32(offset):
        return struct.unpack_from(">I", data, offset)[0]
    while pos < end:
        token = u32(pos)
        pos += 4
        if token == 1:
            stop = data.index(0, pos, end)
            stack.append(data[pos:stop].decode("ascii"))
            pos = (stop + 4) & ~3
            node = "/".join(stack) or "/"
            assert node not in nodes
            nodes.add(node)
        elif token == 2:
            assert stack
            stack.pop()
        elif token == 3:
            size, nameoff = struct.unpack_from(">II", data, pos)
            pos += 8
            assert pos + size <= end and nameoff < len(strings)
            name = strings[nameoff:strings.index(0, nameoff)].decode("ascii")
            key = ("/".join(stack) or "/", name)
            assert key not in props and stack
            props[key] = data[pos:pos+size]
            pos = (pos + size + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            assert not stack
            return nodes, props
        else:
            raise ValueError(f"invalid FIT token {token}")
    raise ValueError("missing end token")


def check_hashes(props):
    for name in ("kernel-1", "fdt-1"):
        node=f"/images/{name}"
        payload=props[(node,"data")]
        for index, algorithm, digest in (
            (1,b"crc32\0", struct.pack(">I",zlib.crc32(payload))),
            (2,b"sha1\0",hashlib.sha1(payload).digest()),
        ):
            sub=f"{node}/hash-{index}"
            assert props[(sub,"algo")]==algorithm
            assert props[(sub,"value")]==digest
    assert props[("/configurations","default")]==b"config@mi04.1-c2\0"
    assert props[("/images/kernel-1","compression")]==b"lzma\0"


def main():
    old, new, expected=map(Path,sys.argv[1:])
    old_nodes, old_props=properties(old)
    new_nodes, new_props=properties(new)
    check_hashes(old_props)
    check_hashes(new_props)
    assert old_nodes==new_nodes and old_props.keys()==new_props.keys()
    delta={k for k in old_props if old_props[k]!=new_props[k]}
    required={("/images/kernel-1","data"),("/images/kernel-1/hash-1","value"),
              ("/images/kernel-1/hash-2","value")}
    assert required <= delta <= required|{("/","timestamp")},delta
    kernel=lzma.decompress(new_props[("/images/kernel-1","data")],format=lzma.FORMAT_ALONE)
    assert kernel==expected.read_bytes()
    assert kernel[0x38:0x3c]==b"ARMd"
    print("FIT_SEMANTIC_DELTA_PASS kernel payload/hashes and optional timestamp only")
    print("kernel_payload_sha256="+hashlib.sha256(kernel).hexdigest())
    print("dtb_sha256="+hashlib.sha256(new_props[("/images/fdt-1","data")]).hexdigest())


if __name__=="__main__":
    main()
