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
