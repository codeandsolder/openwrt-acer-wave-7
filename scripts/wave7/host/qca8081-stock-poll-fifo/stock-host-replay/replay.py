#!/usr/bin/env python3
"""Replay the pinned stock port-2 SGMII decision path in an offline ARM fixture.

Only selected original instructions and literal tables are copied. All hardware,
kernel and unselected control paths stop at explicit mock boundaries. No device IO.
"""
import argparse
import gzip
import hashlib
import json
import lzma
import os
from pathlib import Path
import struct
import resource
import runpy
import subprocess
import tempfile
import zlib

SHA = "5829156f0bfd9cb2021d267e73fa91950a23234e209720195fa639d0eaf4484b"
BASE = 0x01000000
RANGES = [
    (0x74f4, 0x77d4), (0x77d4, 0x79d8), (0x7a5c, 0x7b18),
    (0x7e794, 0x7e7c4), (0x8ed0, 0x8fd0), (0xa338, 0xa464),
    (0xabb8, 0xad10), (0xad10, 0xb744),
    (0x9aa98, 0x9abbc), (0x9ac74, 0x9adb8),
]
# Include the actual stock mode-recording operation and port-to-UNIPHY map.
RANGES += [(0x6b2c, 0x6b8c), (0x6d954, 0x6d9dc),
           (0x66874, 0x66aac), (0x67640, 0x67910), (0x679d4, 0x67adc),
           (0x6c210, 0x6c24c), (0x6c36c, 0x6c510), (0x6d73c, 0x6d7d0),
           (0x6f3b4, 0x6f3f8), (0x6f5bc, 0x6f684), (0x6f6e4, 0x6f750),
           (0x6f7c8, 0x6f818), (0x6f8a8, 0x6f900), (0x6faf8, 0x6fb50),
           (0x6fe7c, 0x700e8), (0x918e8, 0x91950), (0x788d8, 0x7890c), (0x6104, 0x6210), (0x63ec, 0x64ec),
           (0x7c7dc, 0x7c808), (0x69cc4, 0x69ddc)]
RANGES += [(0x88c4, 0x8990)]
LOCAL_MOCKS = {0x6ddc: "tx_pause", 0x6f38: "rx_pause", 0x8990: "selector_return"}
FIT_SHA = "a9e7d543e61bdbd91521798875a097733b54393f72d78278eaeac0059241f833"
KERNEL_SHA = "666960caa4e2f52af4d42f150233aabc4ff8621076c6616c46a15a8e91fd1f9f"
DTS_SHA = "7160c6eafba802464dd014ee4d9147573b88441d8dad41c78b62f43a8653ff8f"

def provenance(fit, dts):
    assert hashlib.sha256(fit.read_bytes()).hexdigest() == FIT_SHA, "unknown stock FIT"
    assert hashlib.sha256(dts.read_bytes()).hexdigest() == DTS_SHA, "unknown stock DT snapshot"
    parse = runpy.run_path(str(Path(__file__).resolve().parent.parent / "verify-fit.py"))["properties"]
    _, props = parse(fit)
    node = "/images/kernel@1"
    packed = props[(node, "data")]
    assert props[(node, "compression")] == b"lzma\0"
    hashes = {props[(sub, "algo")].rstrip(b"\0"): props[(sub, "value")]
              for sub in (node+"/hash@1", node+"/hash@2")}
    assert hashes == {b"crc32": struct.pack(">I", zlib.crc32(packed)),
                      b"sha1": hashlib.sha1(packed).digest()}
    kernel = lzma.decompress(packed, format=lzma.FORMAT_ALONE)
    assert hashlib.sha256(kernel).hexdigest() == KERNEL_SHA
    start = kernel.index(b"IKCFG_ST")+8
    end = kernel.index(b"IKCFG_ED", start)
    config = gzip.decompress(kernel[start:end]).decode()
    assert "CONFIG_HZ=100" in config.splitlines()
    text = dts.read_text()
    assert 'compatible = "qcom,ess-switch-ipq53xx";' in text
    assert "switch_mac_mode1 = <0x0c>;" in text
    return {"module_sha256": SHA, "fit_sha256": FIT_SHA,
            "kernel_sha256": KERNEL_SHA, "dts_sha256": DTS_SHA,
            "kernel_hz": 100, "work_delay_jiffies": 100,
            "stock_dt_compatible": "qcom,ess-switch-ipq53xx",
            "stock_dt_initial_wrapper1": 12}


class Elf:
    def __init__(self, data):
        self.data = data
        h = struct.unpack_from("<16sHHIIIIIHHHHHH", data)
        assert h[0][:7] == b"\x7fELF\x01\x01\x01" and h[2] == 40, "expected little-endian ARM ELF32"
        off, es, count, names = h[6], h[11], h[12], h[13]
        self.sections = [struct.unpack_from("<10I", data, off + i * es) for i in range(count)]
        names = self.bytes(self.sections[names])
        self.names = [self.string(names, s[0]) for s in self.sections]
        self.by_name = dict(zip(self.names, self.sections, strict=True))

    @staticmethod
    def string(data, off):
        return data[off:data.index(b"\0", off)].decode()

    def bytes(self, section):
        return self.data[section[4]:section[4]+section[5]]

    def symbols(self):
        symtab = self.by_name[".symtab"]
        strings = self.bytes(self.sections[symtab[6]])
        for name, value, size, info, other, ndx in struct.iter_unpack("<IIIBBH", self.bytes(symtab)):
            yield self.string(strings, name) or (self.names[ndx] if ndx < len(self.names) else ""), value, ndx

def word(data, off):
    return struct.unpack_from("<I", data, off)[0]

def put(data, off, value):
    struct.pack_into("<I", data, off, value & 0xffffffff)

def branch(op, pc, target):
    distance = target - pc - 8
    assert distance % 4 == 0 and -(1 << 25) <= distance < (1 << 25)
    return (op & 0xff000000) | ((distance // 4) & 0xffffff)

def included(off):
    return any(lo <= off < hi for lo, hi in RANGES)

def run(argv, **kw):
    return subprocess.run(argv, check=True, **kw)

def main():
    if not __debug__:
        raise RuntimeError("Replay assertions must remain enabled")
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("module", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--stock-fit", required=True, type=Path)
    p.add_argument("--stock-dts", required=True, type=Path)
    args = p.parse_args()
    metadata = provenance(args.stock_fit, args.stock_dts)
    # An output directory is an immutable evidence bundle, not a cache.
    dest = args.out.resolve()
    dest.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix=".replay-", dir=dest) as work:
        execute(args.module, Path(work), dest, metadata)

def execute(module, out, dest, metadata):
    original = module.read_bytes()
    assert hashlib.sha256(original).hexdigest() == SHA, "unknown stock module"
    stock = Elf(original)
    code = stock.bytes(stock.by_name[".text"])
    # UDF outside allowlisted ranges. Literal strings are copied intact;
    # BSS is zero, and contains no live kernel pointers.
    image = bytearray(struct.pack("<I", 0xe7f000f0) * (0x150000 // 4))
    for lo, hi in RANGES:
        assert hi <= len(code)
        image[lo:hi] = code[lo:hi]
    data_offsets = {".rodata": 0x100000, ".rodata.str1.1": 0x110000, ".bss": 0x130000, ".data": 0x140000}
    for name, off in data_offsets.items():
        sec = stock.by_name[name]
        image[off:off+sec[5]] = bytes(sec[5]) if name == ".bss" else stock.bytes(sec)
    # Reproduce the initialized notification state, not its setup path.
    put(image, data_offsets[".bss"] + 0x7abc, 1)
    (out / "stock.bin").write_bytes(image)
    (out / "stock.S").write_text('.section .stock,"ax",%progbits\n.balign 4\n.incbin "stock.bin"\n')
    (out / "layout.ld").write_text("ENTRY(_start)\nSECTIONS { . = 0x10000; .text : { *(.text*) *(.rodata*) } . = ALIGN(0x10000); .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } . = 0x01000000; .stock : { *(.stock) } /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment) } }\n")
    env = dict(os.environ, SCCACHE_NO_AUTO_START_SERVER="1", SCCACHE_START_SERVER="0")
    flags = ["sccache", "clang", "--target=arm-linux-gnueabi", "-march=armv7-a", "-marm", "-mfloat-abi=soft",
             "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-fno-pic", "-fno-pie", "-fno-unwind-tables",
             "-fno-asynchronous-unwind-tables", "-O2", "-Wall", "-Wextra", "-Werror"]
    run(flags+["-c", str(Path(__file__).with_name("fixture.c").resolve()), "-o", "fixture.o"], cwd=out, env=env)
    run(flags+["-c", "stock.S", "-o", "stock.o"], cwd=out, env=env)
    run(["ld.lld", "-T", "layout.ld", "-o", "fixture.unrelocated", "fixture.o", "stock.o"], cwd=out)
    binary = bytearray((out / "fixture.unrelocated").read_bytes())
    linked = Elf(binary)
    syms = {n: v for n, v, _ in linked.symbols()}
    sec = linked.by_name[".stock"]
    assert sec[3] == BASE and sec[5] == len(image)
    symbols = list(stock.symbols())
    applied = []
    for off, info in struct.iter_unpack("<II", stock.bytes(stock.by_name[".rel.text"])):
        if not included(off):
            continue
        name, value, ndx = symbols[info >> 8]
        typ = info & 255
        old = word(image, off)
        if typ == 2:  # R_ARM_ABS32
            if name == ".text":
                assert included(old) or old in LOCAL_MOCKS, hex(old)
                target = BASE + old
            elif name in data_offsets:
                target = BASE + data_offsets[name] + old
            else:
                target = syms["mock_" + name] + old
            put(image, off, target)
        elif typ in (28, 29):  # R_ARM_CALL/JUMP24
            assert old & 0xffffff == 0xfffffe, (hex(off), hex(old))
            if ndx == stock.names.index(".text") and included(value):
                target = BASE + value
            elif "mock_" + name in syms:
                target = syms["mock_" + name]
            else:
                # Unknown reachable calls are fatal; absence of a mock never
                # silently falls through to vendor code or a guessed result.
                target = syms["mock_unexpected"]
            put(image, off, branch(old, BASE+off, target))
        else:
            raise ValueError((hex(off), typ, name))
        applied.append({"offset": hex(off), "name": name, "type": typ, "target": hex(target)})
    for off, name in LOCAL_MOCKS.items():
        assert not included(off)
        put(image, off, branch(0xea000000, BASE+off, syms["mock_"+name]))
    binary[sec[4]:sec[4]+sec[5]] = image
    fixture = out / "fixture"
    fixture.write_bytes(binary)
    fixture.chmod(0o755)
    (dest / "relocations.json").write_text(json.dumps(applied, indent=2)+"\n")
    proc = subprocess.run(["qemu-arm", str(fixture)], stdout=subprocess.PIPE, timeout=30, cwd=out)
    trace = proc.stdout
    assert len(trace) % 16 == 0
    events = list(struct.iter_unpack("<4I", trace))
    names = ["CASE", "POLL", "BRIDGE", "TX", "RX", "DELAY", "MODE_RECORD", "MODE_APPLY",
             "GATE", "RATE", "MAC_SPEED", "DUPLEX", "TX_PAUSE", "RX_PAUSE", "REG_READ", "REG_WRITE",
             "NOTIFY", "FDB", "MODE_STATUS", "END", "ERROR", "MII_READ", "MMD_READ",
             "MMD_WRITE", "DEBUG_READ", "DEBUG_WRITE", "BUS_LOCK", "WORK_LOCK", "WORK_QUEUE", "MAC_TYPE"]
    result = [{"event": names[e], "a": a, "b": b, "c": c} for e,a,b,c in events]
    if proc.returncode:
        print(result[-12:])
        proc.check_returncode()
    summary = check(result)
    (dest / "trace.json").write_text(json.dumps([e for e in result[:next(i for i,e in enumerate(result) if e['event']=='CASE' and e['a']==100)]], indent=2)+"\n")
    (dest / "matrix.json").write_text(json.dumps(summary, indent=2)+"\n")
    metadata.update({"trace_binary_sha256": hashlib.sha256(trace).hexdigest(),
                     "relocations": len(applied), "events": len(result),
                     "fixture_sha256": hashlib.sha256(binary).hexdigest()})
    (dest / "provenance.json").write_text(json.dumps(metadata, indent=2)+"\n")
    print(f"{len(applied)} relocations; {len(result)} events; stock ARM replay PASS: {summary}")

def check(events):
    cases, inputs = {}, {}
    for e in events:
        if e["event"] == "CASE":
            assert e["a"] not in cases
            case = cases[e["a"]] = []
            inputs[e["a"]] = (e["b"],e["c"])
        else:
            case.append(e)
    def ops(i):
        return [e["event"] for e in cases[i]]
    def values(i, name):
        return [(e["a"],e["b"],e["c"]) for e in cases[i] if e["event"] == name]
    assert set(cases) == set(range(25)) | set(range(100,2404))
    for i in range(9):
        assert ops(i)[0] == "POLL" and ops(i)[-1] == "END"
    for i in (0, 1, 7):
        assert ops(i) == ["POLL", "END"], (i, ops(i))
    assert ops(2) == ["POLL", "BRIDGE"] + ["DELAY"]*10 + ["RX","MODE_STATUS","NOTIFY","FDB","END"], ops(2)
    assert ops(3) == ["POLL","TX","MODE_STATUS","TX","RX","BRIDGE","NOTIFY","END"], ops(3)
    for i in (4, 5, 6, 8):
        assert values(i, "GATE") == [(22,0,0),(23,0,0),(22,1,0),(23,1,0)], (i, values(i,"GATE"))
        assert values(i, "REG_READ") == [(1,0x480,0xa5a5884c)]
        assert values(i, "REG_WRITE") == [(1,0x480,0xa5a5804c),(1,0x480,0xa5a5884c)]
        assert ops(i).index("REG_WRITE") > max(j for j,e in enumerate(ops(i)) if e=="GATE")
        assert ops(i)[-6:] == ["REG_WRITE","TX","RX","BRIDGE","NOTIFY","END"], ops(i)
    assert values(4, "RATE") == [(2,125000000,0),(3,125000000,0)]
    assert len(values(4,"DELAY")) == 20
    assert values(5, "RATE") == [] and values(5,"DUPLEX") == [(0,0,0)]
    assert values(6, "RATE") == [] and values(6,"TX_PAUSE") == [(1,0,0)]
    assert values(8, "RATE") == [(2,312500000,0),(3,312500000,0)]
    assert ops(8).index("MODE_APPLY") < ops(8).index("GATE")
    assert values(8,"MODE_RECORD") == [(6,0,0)]
    assert all(e["a"] == 0x0ccccb60 for e in events if e["event"]=="DELAY")
    # Full stock PHY path and scheduler. Every low-level bus operation
    # must happen under its corresponding lock, checked by the fixture.
    for i in range(9,18):
        assert ops(i)[0:2] == ["WORK_LOCK","POLL"], (i,ops(i))
        assert ops(i)[-3:] == ["WORK_LOCK","WORK_QUEUE","END"], (i,ops(i))
        assert values(i, "WORK_QUEUE") == [(4,100,0)]
        assert values(i, "WORK_LOCK") == [(1,0,0),(0,0,0)]
        assert len(values(i, "POLL")) == 1
        assert len([e for e in cases[i] if e["event"]=="MMD_READ" and e["b"]==0x19072])==1
        assert values(i,"BUS_LOCK").count((1,0,0)) == values(i,"BUS_LOCK").count((0,0,0))
    # Link-up while already up and repeated unchanged reconnect each
    # write FIFO_RSTN=1 before the host sees the PHY result.
    for i in (9,10,13):
        assert (25,0x19072,0x8844) in values(i,"MMD_WRITE")
        assert not values(i,"REG_WRITE") and not values(i,"GATE")
    # Both steady down and down-edge poll clear bit11, and rewrite the
    # random slave seed whenever the capability gates permit it.
    for i in (11,12,15,16):
        assert values(i,"MMD_WRITE") == [(25,0x19072,0x8044)]
        assert values(i,"DEBUG_WRITE")[0] == (24,9,0xa0c6)
    assert not values(9,"MODE_STATUS")
    assert values(10,"TX") == [(0,0,0),(1,0,0)]
    assert values(11,"BRIDGE") == [(0,0,0)]
    assert not values(12,"BRIDGE")
    # All-ones FIFO read: no write. Stock still proceeds to link-up.
    assert not values(14,"MMD_WRITE") and values(14,"TX") == [(0,0,0),(1,0,0)]
    # Master/slave fault clears seed-enable after the seed rewrite.
    assert values(15,"DEBUG_WRITE") == [(24,9,0xa0c6),(24,9,0xa0c4)]
    # Unreadable copper status is swallowed by stock get_status; its
    # caller sees zero-initialized link=0 and executes the down path.
    assert values(16,"BRIDGE") == [(0,0,0)]
    # A true 1000 -> 2500 transition runs the mode apply and rate change,
    # unlike the preserved same-mode reconnect.
    assert values(17,"RATE") == [(2,312500000,0),(3,312500000,0)]
    assert values(17,"REG_WRITE") == [(1,0x480,0xa5a5804c),(1,0x480,0xa5a5884c)]
    assert ops(17).index("MMD_WRITE") < ops(17).index("MODE_APPLY") < ops(17).index("REG_WRITE")
    assert ops(18) == ["POLL","TX","MODE_STATUS","MODE_RECORD","MODE_APPLY","TX","RX","BRIDGE","NOTIFY","END"]
    # Original phylib read_status, separate from the host worker.
    for i, link, speed, duplex, level in (
        (19,1,1000,1,0x8844), (20,0,10,0,0x8044), (21,0,10,0,0x8044)
    ):
        assert values(i,"MMD_WRITE") == [(25,0x19072,level)]
        assert values(i,"END") == [(link,speed,duplex)]
        assert not any(e in ops(i) for e in ("GATE","REG_WRITE","WORK_QUEUE","NOTIFY","BRIDGE"))
        assert values(i,"BUS_LOCK").count((1,0,0)) == values(i,"BUS_LOCK").count((0,0,0))
    # Original wrapper selector instructions, with the DT-specific
    # feature as an explicit simulation input rather than assumed GMAC.
    for i, mac, mode in ((22,1,4),(23,2,6),(24,1,6)):
        assert values(i,"MAC_TYPE")==[(mac,0,0)]
        assert values(i,"END")==[(mode,0,0)]
        assert ops(i)==["MAC_TYPE","END"]
    def decode(n):
        return n>>16,(n&0xffff)>>4,(n>>2)&1,(n>>1)&1,n&1
    summary = dict(named_cases=25,matrix_cases=0,steady_down=0,steady_up=0,down_edge=0,
                   unchanged_up_edge=0,changed_up_edge=0,mode_applies=0,
                   rate_changes=0,adapter_pulses=0)
    tuples = set()
    for i,(a,b) in inputs.items():
        if i < 100:
            continue
        old, new = decode(a),decode(b)
        assert (old,new) not in tuples
        tuples.add((old,new))
        ol,os,od,ot,orr=old
        nl,ns,nd,nt,nrr=new
        o = ops(i)
        assert o[0] == "POLL" and o[-1] == "END"
        assert values(i,"POLL") == [(nl,ns,0)]
        summary["matrix_cases"]+=1
        if ol==nl:
            summary["steady_up" if nl else "steady_down"]+=1
            assert o == ["POLL","END"], (i,old,new,o)
            assert values(i,"END") == [(ol,os,od)]
            continue
        mode_changed = (os == 2500) != (ns == 2500)
        assert len(values(i,"MODE_APPLY")) == int(mode_changed)
        summary["mode_applies"]+=int(mode_changed)
        if ol:
            summary["down_edge"]+=1
            assert values(i,"BRIDGE") == [(0,0,0)]
            assert values(i,"RX") == [(0,0,0)]
            assert len(values(i,"DELAY")) == 10
            assert not (values(i,"TX") or values(i,"GATE") or values(i,"REG_WRITE"))
            assert values(i,"END") == [(0,os,od)]
            continue
        changed=(os,od,ot,orr)!=(ns,nd,nt,nrr)
        assert values(i,"TX") == [(0,0,0),(1,0,0)]
        assert values(i,"RX")==values(i,"BRIDGE")==[(1,0,0)]
        assert values(i,"END") == [(1,ns,nd)]
        if not changed:
            summary["unchanged_up_edge"]+=1
            assert not (values(i,"GATE") or values(i,"RATE") or values(i,"REG_WRITE"))
            continue
        summary["changed_up_edge"]+=1
        assert values(i,"GATE")==[(22,0,0),(23,0,0),(22,1,0),(23,1,0)]
        assert values(i,"REG_WRITE")==[(1,0x480,0xa5a5804c),(1,0x480,0xa5a5884c)]
        summary["adapter_pulses"]+=1
        if os!=ns:
            rate={10:2500000,100:25000000,1000:125000000,2500:312500000}[ns]
            assert values(i,"RATE")==[(2,rate,0),(3,rate,0)]
            assert len(values(i,"DELAY"))==20
            summary["rate_changes"]+=1
        else:
            assert not values(i,"RATE") and not values(i,"DELAY")
        assert values(i,"DUPLEX")==([(nd,0,0)] if od!=nd else [])
        # Stock forces pause enable for half-duplex on reconfiguration.
        desired_tx=nt if nd else 1
        desired_rx=nrr if nd else 1
        assert values(i,"TX_PAUSE")==([(desired_tx,0,0)] if ot!=desired_tx else [])
        assert values(i,"RX_PAUSE")==([(desired_rx,0,0)] if orr!=desired_rx else [])
    assert summary["matrix_cases"]==2304 and summary["unchanged_up_edge"]==24
    return summary



if __name__ == "__main__":
    main()
