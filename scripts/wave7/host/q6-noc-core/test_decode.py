"""Offline unit checks for Qualcomm's explicit filter bit extractions."""
import importlib.util
import struct
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "q6nocdecoder", Path(__file__).with_name("decode.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class QualcommFilterFieldsTest(unittest.TestCase):
    def test_actual_umacnoc_syndrome(self):
        self.assertEqual(module.qualcomm_noc_filter_fields(0x00012105, 0x0000841d), {
            "errcode_numeric": 1,
            "mid": "0x1d",
            "extid": "0x00008400",
            "mapped_initiator": None,
            "mapped_target": None,
        })

    def test_legacy_qualcomm_observer_only_a_hypothesis(self):
        hint = module.legacy_qcom_observer_interpretation(0x00012105)
        self.assertEqual(hint["raw_opcode"], 2)
        self.assertEqual(hint["candidate_opcode"], "linked read")
        self.assertEqual(hint["candidate_errcode"], "address decode error")
        self.assertEqual(hint["raw_lock_bit"], 1)
        self.assertEqual(hint["raw_len1"], 1)
        self.assertIn("not_verified_qnoc4", hint["status"])
        # Reserved/extended protocol opcodes must not be assigned a
        # fabricated packet name based on this older Qualcomm mapping.
        self.assertIsNone(module.legacy_qcom_observer_interpretation(0x1e)["candidate_opcode"])

    def test_boundary_masks(self):
        self.assertEqual(module.qualcomm_noc_filter_fields(0x700, 0xffffffff), {
            "errcode_numeric": 7,
            "mid": "0xff",
            "extid": "0xffffff00",
            "mapped_initiator": None,
            "mapped_target": None,
        })
        self.assertEqual(module.qualcomm_noc_filter_fields(0, 0), {
            "errcode_numeric": 0,
            "mid": "0x00",
            "extid": "0x00000000",
            "mapped_initiator": None,
            "mapped_target": None,
        })




def build_two_instance_elf_pair(clear_offset=0x18):
    """Synthetic physical dump and VA mapping; exercises real decoder logic."""
    page=bytearray(0x1000)
    base=0x1000

    def put32(address,value):
        struct.pack_into("<I",page,address-base,value)

    def put16(address,value):
        struct.pack_into("<H",page,address-base,value)

    put32(0x1010,0x1020)  # Global pointer to descriptor array metadata.
    put32(0x1020,2)
    put32(0x1024,0x1100)
    for i,name in enumerate((b"UMACNOC",b"WCSS_CFGBUS")):
        desc=0x1100+0x60*i
        put32(desc,0x1300+0x40*i)
        page[0x300+0x40*i:0x300+0x40*i+len(name)]=name
        put32(desc+4,0x1400)
        put32(desc+8,0xe5140000 if not i else 0xe5008000)
        values=(1,0x12105,0x7f,0x3b,0x841d,0x2000,0,0,0) if not i else (0,)*9
        for offset,value in zip(module.SNAPSHOT_OFFSETS,values):
            put32(desc+offset,value)
    for position,offset in zip(module.REG_INDEX_OFFSETS,
                               (0x10,clear_offset,0x20,0x24,0x28,0x2c,
                                0x30,0x34,0x38,0x3c)):
        put16(0x1400+position,offset)

    def elf(payload):
        blob=bytearray(0x100+len(payload))
        blob[:6]=b"\x7fELF\x01\x01"
        struct.pack_into("<I",blob,0x1c,52)
        struct.pack_into("<HH",blob,0x2a,32,1)
        struct.pack_into("<IIIIIIII",blob,52,1,0x100,base,base,
                         len(payload),len(payload),7,0)
        blob[0x100:]=payload
        return bytes(blob)
    return elf(page),elf(page)


class FirmwareClearRegisterTest(unittest.TestCase):
    def test_clear_mmio_is_derived_from_firmware_descriptor(self):
        fw,core=build_two_instance_elf_pair()
        result=module.decode(fw,core,global_addr=0x1010)
        a,b=result["instances"]
        self.assertTrue(a["qnoc4_layout_matches_firmware"])
        self.assertTrue(b["qnoc4_layout_matches_firmware"])
        self.assertEqual(a["error_clear"]["register_offset"],"0x18")
        self.assertEqual(a["error_clear"]["mmio_address"],"0xe5140018")
        self.assertEqual(b["error_clear"]["mmio_address"],"0xe5008018")
        self.assertIsNone(a["error_clear"]["snapshot"])
        self.assertEqual(a["error_clear"]["static_firmware_handler"]["write_value"],
                         "0x00000001")
        self.assertIn("not_live_mmio_observation",
                      a["error_clear"]["static_firmware_handler"]["interpretation"])
        self.assertEqual(a["logged_u64"]["ERRLOG1"],"0x0000841d0000003b")
        self.assertEqual(a["qti_source_backed_filter_fields"]["mid"],"0x1d")

    def test_unrecognized_clear_offset_does_not_claim_firmware_path(self):
        fw,core=build_two_instance_elf_pair(clear_offset=0x1c)
        rec=module.decode(fw,core,global_addr=0x1010)["instances"][0]
        self.assertFalse(rec["qnoc4_layout_matches_firmware"])
        self.assertEqual(rec["error_clear"]["mmio_address"],"0xe514001c")
        self.assertNotIn("static_firmware_handler",rec["error_clear"])

    def test_invalid_register_index_remains_unmapped(self):
        fw,core=build_two_instance_elf_pair(clear_offset=0xffff)
        rec=module.decode(fw,core,global_addr=0x1010)["instances"][0]
        self.assertFalse(rec["qnoc4_layout_matches_firmware"])
        self.assertIsNone(rec["error_clear"]["mmio_address"])


if __name__ == "__main__":
    unittest.main()
