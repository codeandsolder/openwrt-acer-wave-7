#!/usr/bin/env python3
"""Read-only decoder of the firmware-captured Qualcomm QNoC syndrome.

Translate DSP virtual addresses through the UserPD1 ELF's physical
PT_LOAD mapping and the root Q6 ELF devcoredump. This never reads MMIO.
"""
import argparse
import json
import struct
from pathlib import Path

FW067_NOC_CONFIG_GLOBAL = 0xB0497FDC
DESCRIPTOR_STRIDE = 0x60
# Layout order: ERRVALID, ERRCLR, then the eight 32-bit ERRLOG words.
# The firmware handler reads each offset from the table instead of
# embedding the hardware register offset in every MMIO instruction.
QNOCC4_OFFSETS = (0x10, 0x18, 0x20, 0x24, 0x28, 0x2C, 0x30, 0x34, 0x38, 0x3C)
NAMES = (
    "ERRVALID", "ERRLOG0_LO", "ERRLOG0_HI", "ERRLOG1_LO", "ERRLOG1_HI",
    "ERRLOG2_LO", "ERRLOG2_HI", "ERRLOG3_LO", "ERRLOG3_HI",
)
SNAPSHOT_OFFSETS = (0x48, 0x28, 0x2C, 0x30, 0x34, 0x38, 0x3C, 0x40, 0x44)
REG_INDEX_OFFSETS = (0x06, 0x08, 0x0A, 0x0C, 0x0E, 0x10, 0x12, 0x14, 0x16, 0x18)


def qualcomm_noc_filter_fields(errlog0_low, errlog1_high):
    """Decode only fields defined by Qualcomm's published NoC driver.

    Ref: qualcomm-linux/trusted-firmware-a, qcom-next,
    drivers/qti/icb/noc_error.c:qti_noc_error_handle_filter().
    Qualcomm explicitly derives errcode via (ERRLOG0_LOW >> 8) & 7,
    extid via ERRLOG1_HIGH & 0xffffff00, and calls the excluded
    low byte the MID field. No SoC-specific route/target lookup here.
    """
    return {
        "errcode_numeric": (errlog0_low >> 8) & 0x7,
        "mid": f"0x{errlog1_high & 0xff:02x}",
        "extid": f"0x{errlog1_high & 0xffffff00:08x}",
        "mapped_initiator": None,
        "mapped_target": None,
    }




# Older Qualcomm Gladiator observer (not this QNoC4 incarnation) uses
# this FlexNoC transport encoding. Retain its names as *candidate*
# interpretation only; the numeric errcode has a separate, direct
# Qualcomm QNoC4 confirmation in qualcomm_noc_filter_fields().
_LEGACY_QCOM_OBS_ERROR_CODES = (
    "target/slave error", "address decode error", "unsupported request",
    "disconnected target or domain", "security violation",
    "hidden security violation", "timeout", "reserved",
)
_LEGACY_QCOM_OBS_OPCODES = (
    "incremental read", "wrapped read", "linked read", "exclusive read",
    "write", "wrapped write", "conditional write", "reserved",
    "preamble", "urgency packet",
)


def legacy_qcom_observer_interpretation(errlog0_low):
    """Candidate packet semantics from Qualcomm's older OBS decoder.

    Qualcomm msm gladiator_erp_v2.c (historical, different logger
    generation) defines OBS_TRANS_OPCODE_MASK=0x1e, shift=1 and
    OBS_ERROR_TYPE_MASK=0x700, shift=8. These *might* describe the
    same FlexNoC packet encoding as IPQ5332 QNoC4, but the latter's
    per-SoC protocol equivalence is not yet established.
    """
    opcode=(errlog0_low >> 1) & 0xF
    errcode=(errlog0_low >> 8) & 0x7
    return {
        "status": "candidate_other_qualcomm_observer_generation_not_verified_qnoc4",
        "raw_opcode": opcode,
        "candidate_opcode": (
            _LEGACY_QCOM_OBS_OPCODES[opcode]
            if opcode < len(_LEGACY_QCOM_OBS_OPCODES) else None
        ),
        "candidate_errcode": _LEGACY_QCOM_OBS_ERROR_CODES[errcode],
        "raw_lock_bit": errlog0_low & 1,
        "raw_len1": (errlog0_low >> 16) & 0x7f,
        "source": (
            "Qualcomm kernel/msm drivers/soc/qcom/gladiator_erp_v2.c "
            "(legacy OBS decoder, not confirmed for IPQ5332 QNoC4)"
        ),
    }



def load_segments(blob):
    if blob[:6] != b"\x7fELF\x01\x01":
        raise ValueError("expected ELF32 little endian")
    phoff = struct.unpack_from("<I", blob, 0x1C)[0]
    entsize, count = struct.unpack_from("<HH", blob, 0x2A)
    if entsize < 32 or count > 512:
        raise ValueError("invalid program-header table")
    segs = []
    for i in range(count):
        off = phoff + i * entsize
        if off + 32 > len(blob):
            raise ValueError("truncated ELF program-header table")
        kind, fileoff, va, pa, filesz, memsz, _, _ = struct.unpack_from("<IIIIIIII", blob, off)
        if kind == 1 and memsz and pa:
            segs.append((va, pa, fileoff, filesz, memsz))
    if not segs:
        raise ValueError("no loadable physical ELF segments")
    return segs


def decode(firmware, core, global_addr=FW067_NOC_CONFIG_GLOBAL):
    fw_segments = load_segments(firmware)
    core_segments = load_segments(core)

    def read(virtual, length):
        for va, pa, _, _, memsz in fw_segments:
            if va <= virtual and virtual + length <= va + memsz:
                phys = pa + virtual - va
                for _, cp, coff, csize, _ in core_segments:
                    if cp <= phys and phys + length <= cp + csize:
                        start = coff + phys - cp
                        if start + length > len(core):
                            raise ValueError("truncated coredump segment")
                        return core[start:start+length]
        raise ValueError(f"missing snapshot of virtual address {virtual:#010x} + {length}")

    def u32(a): return struct.unpack("<I", read(a, 4))[0]
    def u16(a): return struct.unpack("<H", read(a, 2))[0]
    def name(a): return read(a, 48).split(b"\0", 1)[0].decode("ascii")

    header = u32(global_addr)
    count, entries = u32(header), u32(header + 4)
    if not 1 <= count <= 16:
        raise ValueError(f"invalid NoC instance count: {count}")
    output = {"firmware_noc_global": f"{global_addr:#010x}", "instance_count": count,
              "instances": []}
    for i in range(count):
        desc = entries + i * DESCRIPTOR_STRIDE
        offsets_ptr = u32(desc + 4)
        offsets = [u16(offsets_ptr + off) for off in REG_INDEX_OFFSETS]
        values = [u32(desc + off) for off in SNAPSHOT_OFFSETS]
        base = u32(desc + 8)
        clear_offset = offsets[1]
        rec = {
            "name": name(u32(desc)),
            "index": i,
            "mmio_base": f"{base:#010x}",
            "qnoc4_layout_matches_firmware": tuple(offsets) == QNOCC4_OFFSETS,
            "registers": {label: {"offset": f"{off:#04x}", "snapshot": f"{v:#010x}"}
                          for label, off, v in zip(NAMES, offsets[:1] + offsets[2:], values)},
            "error_clear": {
                "register_offset": f"{clear_offset:#04x}",
                "mmio_address": (
                    f"{base + clear_offset:#010x}"
                    if clear_offset != 0xffff and base + clear_offset <= 0xffffffff
                    else None
                ),
                "snapshot": None,
            },
        }
        if rec["qnoc4_layout_matches_firmware"]:
            # Reversed Acer 067 UserPD1 handler:
            # 0xb032a6bc: R24=1;
            # 0xb032a844: R3=[descriptor+8] (MMIO base);
            # 0xb032a84c: R4=memuh([descriptor+4]+8) (ERRCLR offset);
            # 0xb032a850: memw(R3+R4)=R24.
            # This is the intended write in the error-handling path,
            # not a measurement that the write reached the hardware.
            rec["error_clear"]["static_firmware_handler"] = {
                "write_value": "0x00000001",
                "write_instruction": "0xb032a850",
                "interpretation": "handler_writes_clear_after_snapshot_not_live_mmio_observation",
            }
            rec["logged_u64"] = {
                f"ERRLOG{j}": f"0x{values[2*j+2]:08x}{values[2*j+1]:08x}"
                for j in range(4)
            }
            if values[0] & 1:
                rec["qti_source_backed_filter_fields"] = qualcomm_noc_filter_fields(
                    errlog0_low=values[1], errlog1_high=values[4],
                )
                rec["legacy_observer_protocol_hypothesis"] = (
                    legacy_qcom_observer_interpretation(values[1])
                )
        output["instances"].append(rec)
    return output


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--firmware-mdt", type=Path, required=True)
    ap.add_argument("--core", type=Path, required=True, action="append")
    ap.add_argument("--config-global", type=lambda s: int(s, 0), default=FW067_NOC_CONFIG_GLOBAL)
    opts = ap.parse_args()
    firmware = opts.firmware_mdt.read_bytes()
    for filename in opts.core:
        info = decode(firmware, filename.read_bytes(), opts.config_global)
        info["source_core"] = str(filename)
        print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
