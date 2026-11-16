"""Offline unit checks for Qualcomm's explicit filter bit extractions."""
import importlib.util
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


if __name__ == "__main__":
    unittest.main()
