#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["unicorn==2.1.4", "pyelftools==0.33"]
# ///
"""Run the pinned stock ARM SerDes mode/NWAY instructions against a mock bus.

No hardware I/O. Only explicitly selected stock function ranges execute.
Port identity and the initialized SDK state are fixed at the mock boundary;
the register RMW helpers and their callers execute the original instructions.
"""
import argparse
from collections import defaultdict
import hashlib
from io import BytesIO
import json
from pathlib import Path
import struct

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import (
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
    UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC,
)

SHA = "e2efdabbbc2c852ee9bf6b50a40c0759fbc470b95da77a7f524816ddb3db6120"
TEXT, RODATA, MOCK, STACK = 0x100000, 0x200000, 0x300000, 0x400000
STOP, GUARD, ABILITY = MOCK + 0x1000, MOCK + 0x2000, STACK + 0x100
REAL = {
    "dal_rtl8367d_port_macForceLinkExt_set", "dal_rtl8367d_port_macForceLink_set",
    "dal_rtl8367d_port_macForceLink_get", "dal_rtl8367d_port_sgmiiNway_set",
    "rtl8367d_setAsicReg", "rtl8367d_getAsicReg",
    "rtl8367d_setAsicRegBit", "rtl8367d_getAsicRegBit",
    "rtl8367d_setAsicRegBits", "rtl8367d_getAsicRegBits",
}
MOCKS = {
    "rtk_switch_initialState_get", "rtk_switch_isExtPort",
    "rtk_switch_isHsgPort", "rtk_switch_isSgmiiPort",
    "rtk_switch_port_L2P_get", "dal_rtl8367d_port_phyComboPortMedia_get",
    "rtl8367d_smi_write", "rtl8367d_smi_read", "memset", "__stack_chk_fail",
}
ARGS = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)


class Replay:
    def __init__(self, original):
        assert hashlib.sha256(original).hexdigest() == SHA, "unknown stock module"
        elf = ELFFile(BytesIO(original))
        symbols = elf.get_section_by_name(".symtab")
        self.functions = {s.name: (s["st_value"], s["st_size"])
                          for s in symbols.iter_symbols() if s.name in REAL}
        assert self.functions.keys() == REAL
        self.ranges = list(self.functions.values())
        self.mock_addr = {name: MOCK + i * 4 for i, name in enumerate(sorted(MOCKS))}
        self.hooks = {v: k for k, v in self.mock_addr.items()}
        code = bytearray(elf.get_section_by_name(".text").data())
        self.rodata = elf.get_section_by_name(".rodata").data()
        for rel in elf.get_section_by_name(".rel.text").iter_relocations():
            offset = rel["r_offset"]
            if not self.allowed(offset):
                continue
            symbol = symbols.get_symbol(rel["r_info_sym"])
            name = symbol.name
            old, = struct.unpack_from("<I", code, offset)
            kind = rel["r_info_type"]
            if kind == 2:  # R_ARM_ABS32
                if name == "__stack_chk_guard":
                    target = GUARD + old
                elif isinstance(symbol["st_shndx"], int):
                    section = elf.get_section(symbol["st_shndx"]).name
                    if section == ".text":
                        assert self.allowed(symbol["st_value"] + old)
                        target = TEXT + symbol["st_value"] + old
                    elif section == ".rodata":
                        target = RODATA + symbol["st_value"] + old
                    else:
                        raise AssertionError((hex(offset), name, section))
                else:
                    raise AssertionError((hex(offset), name))
                struct.pack_into("<I", code, offset, target)
            elif kind in (28, 29):  # R_ARM_CALL / R_ARM_JUMP24
                assert old & 0xffffff == 0xfffffe
                if name in self.functions:
                    target = TEXT + self.functions[name][0]
                else:
                    # Unknown call sites are explicit traps, not fake successes.
                    target = self.mock_addr.get(name, MOCK + 0x3000)
                distance = target - (TEXT + offset) - 8
                assert distance % 4 == 0 and abs(distance) < (1 << 25)
                struct.pack_into("<I", code, offset,
                                 (old & 0xff000000) | ((distance // 4) & 0xffffff))
            else:
                raise AssertionError((hex(offset), kind, name))
        self.code = bytes(code)

    def allowed(self, offset):
        return any(start <= offset < start + size for start, size in self.ranges)

    def case(self, mode, initial_misc, initial_nway, *, enable=0, fail_at=None, ability=None, initial_ability=0):
        uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        for start, size in ((TEXT, 0x20000), (RODATA, 0x2000),
                            (MOCK, 0x4000), (STACK, 0x10000)):
            uc.mem_map(start, size)
        uc.mem_write(TEXT, self.code)
        uc.mem_write(RODATA, self.rodata)
        uc.mem_write(GUARD, struct.pack("<I", 0x12345678))
        uc.mem_write(ABILITY, struct.pack("<7I", *(ability if ability is not None else
                                                  (1, 4 if mode == 10 else 2, 1, 1, 0, 1, 1))))
        direct = defaultdict(int, {0x1d11: initial_misc, 0x130c: 0x4020,
                                   0x13e8: 0xa5a5, 0x3f7: 0xffff,
                                   0x12c6: initial_ability})
        sds = defaultdict(int, {(13, 2): initial_nway})
        bus = []
        events = []
        reads_writes = 0
        failed = False
        stopped = False

        def hook(emulator, address, size, _):
            nonlocal reads_writes, failed, stopped
            if address == STOP:
                stopped = True
                emulator.emu_stop()
                return
            if self.allowed(address - TEXT):
                return
            name = self.hooks.get(address)
            assert name is not None, f"unexpected execution at 0x{address:x}"
            a, b, c, _ = (emulator.reg_read(r) for r in ARGS)
            result = 0
            if name == "rtk_switch_initialState_get":
                result = 1
            elif name in ("rtk_switch_isExtPort", "rtk_switch_isHsgPort",
                          "rtk_switch_isSgmiiPort"):
                assert a == 16
            elif name == "rtk_switch_port_L2P_get":
                assert a == 16
                result = 6
            elif name == "dal_rtl8367d_port_phyComboPortMedia_get":
                assert a == 4
                emulator.mem_write(b, struct.pack("<I", 0))
            elif name == "memset":
                emulator.mem_write(a, bytes([b & 255]) * c)
                result = a
            elif name in ("rtl8367d_smi_read", "rtl8367d_smi_write"):
                reads_writes += 1
                if reads_writes == fail_at:
                    failed = True
                    result = 1
                elif name.endswith("_read"):
                    emulator.mem_write(b, struct.pack("<I", direct[a]))
                    bus.append(("read", a, direct[a]))
                else:
                    assert b <= 0xffff, (hex(a), hex(b))
                    bus.append(("write", a, b))
                    direct[a] = b
                    if a == 0x6600:
                        lane = b & 0x3f
                        assert lane == 13 and b & 0x80
                        index = direct[0x6601]
                        if b & 0x40:
                            value = direct[0x6602]
                            sds[lane, index] = value
                            events.append(("sds-write", index, value))
                        else:
                            direct[0x6602] = sds[lane, index]
                            events.append(("sds-read", index, direct[0x6602]))
                    elif a not in (0x6601, 0x6602):
                        events.append(("write", a, b))
            else:
                raise AssertionError(f"unexpected mock {name}")
            emulator.reg_write(UC_ARM_REG_R0, result)
            emulator.reg_write(UC_ARM_REG_PC, emulator.reg_read(UC_ARM_REG_LR))

        uc.hook_add(UC_HOOK_CODE, hook)

        def call(name, *args):
            nonlocal stopped
            stopped = False
            for reg, arg in zip(ARGS, (*args, 0, 0, 0)):
                uc.reg_write(reg, arg)
            uc.reg_write(UC_ARM_REG_SP, STACK + 0xf000)
            uc.reg_write(UC_ARM_REG_LR, STOP)
            uc.emu_start(TEXT + self.functions[name][0], STOP + 4, count=100000)
            assert stopped, f"did not return: {name}"
            return uc.reg_read(UC_ARM_REG_R0)

        if ability is not None:
            ret = call("dal_rtl8367d_port_macForceLink_set", 16, ABILITY)
            return ret, None, events, bus, failed
        ret = call("dal_rtl8367d_port_macForceLinkExt_set", 16, mode, ABILITY)
        if ret:
            return ret, None, events, bus, failed
        split = len(events)
        nway = call("dal_rtl8367d_port_sgmiiNway_set", 16, enable)
        return nway, split, events, bus, failed


def verify(events, split, mode, misc, nway, enable):
    # Exact tuning table for the two interface modes was independently
    # verified by compare-stock-tuning.py. Validate the order around it.
    config = events[:split]
    assert config[0] == ("write", 0x03f7, 0xfffd)
    misc |= 1 << 9
    assert config[1] == ("write", 0x1d11, misc)
    assert len([e for e in config if e[0] == "sds-write"]) == 10
    expected_regs = [0x427, 0x428, 0x425, 0x424, 0x423, 0x410,
                     0x504 if mode == 10 else 0x484, 0x421, 0x422, 4]
    assert [e[1] for e in config[2:12]] == expected_regs
    assert config[12] == ("write", 0x13e8, (0xa5a5 & ~0xc0) | 0x40)
    misc |= 1 << 10
    assert config[13] == ("write", 0x1d11, misc)
    misc |= 1 << 11
    assert config[14] == ("write", 0x1d11, misc)
    assert config[15] == ("write", 0x1d11,
                          (misc & ~31) | (18 if mode == 10 else 2))
    assert all(e[0] != "sds-write" for e in config[16:])
    assert [e[1] for e in config[16:] if e[0] == "write"] == [
        0x12c6, 0x12c6, 0x12ce, 0x12c6]
    assert events[split:] == [
        ("write", 0x130c, 0x4000), ("sds-read", 2, nway),
        ("sds-write", 2, (nway & ~512) | (enable << 9) | 256),
        ("write", 0x130c, 0x4020),
    ]


def main():
    assert __debug__
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("module", type=Path)
    args = parser.parse_args()
    replay = Replay(args.module.read_bytes())
    count = 0
    for mode in (9, 10):
        for misc in (0, 0x1f, 0x0e12, 0xa5a5, 0xffff):
            for nway in (0, 0x200, 0x55aa, 0xffff):
                for enable in (0, 1):
                    result, split, events, _, failed = replay.case(
                        mode, misc, nway, enable=enable)
                    assert result == 0 and split is not None and not failed
                    verify(events, split, mode, misc, nway, enable)
                    count += 1
    force_count = 0
    for speed, encoded in ((0, 0), (1, 1), (2, 2), (4, 0x1001)):
        for duplex in (0, 1):
            for link in (0, 1):
                for tx_pause in (0, 1):
                    for rx_pause in (0, 1):
                        for initial in (0, 0x1075, 0xa5a5, 0xffff):
                            ability = (1, speed, duplex, link, 0, tx_pause, rx_pause)
                            result, _, writes, _, failed = replay.case(
                                10, 0, 0, ability=ability, initial_ability=initial)
                            assert result == 0 and not failed, (ability, result)
                            val = encoded | duplex << 2 | tx_pause << 6 | rx_pause << 5
                            expected = [("write", 0x12c6, initial & ~16),
                                        ("write", 0x12c6, val),
                                        ("write", 0x12ce, 0xffff)]
                            if link:
                                expected.append(("write", 0x12c6, val | 16))
                            assert writes == expected, (ability, writes, expected)
                            force_count += 1
    result, split, events, bus, _ = replay.case(10, 0x1f, 0x200)
    assert result == 0
    print(json.dumps({"module_sha256": SHA, "cases": count, "mac_force_cases": force_count,
                      "hsgmii_initialization": events[:split],
                      "hsgmii_nway_disable": events[split:],
                      "smi_transactions": len(bus)}, indent=2))


if __name__ == "__main__":
    main()
