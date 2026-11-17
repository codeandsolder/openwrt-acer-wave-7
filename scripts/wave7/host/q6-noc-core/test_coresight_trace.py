#!/usr/bin/env python3
"""Regression tests for the CoreSight formatter and structural trace inspector."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core = load("wave7_coresight", "decode-coresight-etr.py")
records = load("wave7_noc_records", "inspect-noc-stream.py")


class CoreSightTests(unittest.TestCase):
    reference = bytes.fromhex("07 aa a6 a7 2b a8 54 52 52 54 07 ca c6 c7 c8 1c")
    expected = {
        3: bytes.fromhex("aa a6 a7 a8 ca c6 c7 c8"),
        21: bytes.fromhex("55 52 53 54"),
    }

    def test_arm_reference_frame(self) -> None:
        streams, report = core.decode(self.reference)
        self.assertEqual(streams, self.expected)
        self.assertEqual(report["frames"], 1)
        self.assertEqual(report["source_id_markers"], {"0x03": 2, "0x15": 1})

    def test_full_and_half_synchronization(self) -> None:
        raw = core.FULL_SYNC + self.reference[:8] + core.HALF_SYNC + self.reference[8:]
        streams, report = core.decode(raw)
        self.assertEqual(streams, self.expected)
        self.assertEqual(report["frame_sync_packets"], {
            "full_32bit": 1,
            "half_16bit": 1,
        })

    def test_unframed_orphan_data_accounting(self) -> None:
        streams, report = core.decode(bytes(16))
        self.assertEqual(streams, {})
        self.assertEqual(report["orphan_bytes_before_first_id"], 15)

    def test_known_id_stream_in_multiple_frames(self) -> None:
        frame = bytes.fromhex("73 2c ec d6 c0 09 62 00 00 1b 20 3c 14 1e 80 06")
        streams, report = core.decode(frame * 5)
        self.assertEqual(set(streams), {0x39})
        self.assertEqual(report["source_id_markers"], {"0x39": 5})
        self.assertEqual(len(streams[0x39]), 70)

    def test_reserved_last_slot_aux_bit(self) -> None:
        frame = bytearray(16)
        frame[14] = 0x03
        frame[15] = 0x80
        with self.assertRaisesRegex(ValueError, "Reserved ID"):
            core.decode(bytes(frame))

    def test_truncation(self) -> None:
        with self.assertRaisesRegex(ValueError, "16-bit"):
            core.decode(b"\x01")
        with self.assertRaisesRegex(ValueError, "16 bytes"):
            core.decode(bytes(14))

    def test_structural_records_and_gaps(self) -> None:
        a = b"\x1b\x20\x3c" + b"A" * 13
        b = b"\x1b\x20\x1c" + b"B" * 13
        c = b"\x1b\x20\x58" + b"C" * 13
        report = records.summarize(a + b + bytes(8) + c,
                                   anchor=b"\x1b\x20", width=16, field_offset=2)
        self.assertEqual(report["anchor_occurrences"], 3)
        self.assertEqual(report["exact_width_adjacent_records"], 1)
        self.assertEqual(report["unclassified_or_gap_anchor_pairs"], 1)
        self.assertEqual(report["family_values"][0]["family_byte"], "0x3c")

    def test_invalid_record_settings(self) -> None:
        for anchor, width, offset in [(b"", 16, 2), (b"\x01\x02", 1, 0),
                                       (b"\x01\x02", 16, 16)]:
            with self.subTest(anchor=anchor, width=width, offset=offset):
                with self.assertRaises(ValueError):
                    records.summarize(b"abc", anchor=anchor,
                                      width=width, field_offset=offset)


if __name__ == "__main__":
    unittest.main()
