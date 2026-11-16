"""Targeted, offline regression tests for the firmware-only image repacker."""
import tempfile
import unittest
from pathlib import Path

import build_candidate as b


class BuildCandidateSafetyTest(unittest.TestCase):
    def test_exact_firmware_allowlist(self):
        for name in (
            "lib/firmware/ath12k/IPQ5332/hw1.0/q6_fw0.b11",
            "lib/firmware/ath12k/IPQ5332/hw1.0/q6_fw1.mdt",
            "lib/firmware/ath12k/IPQ5332/hw1.0/q6_fw2.b02",
            "lib/firmware/ath12k/QCN6432/hw1.0/q6_fw2.mbn",
            "lib/firmware/ath12k/QCN6432/hw1.0/iu_fw.b02",
            "etc/wave7-firmware-trial", "usr/lib/os-release",
        ):
            with self.subTest(path=name):
                self.assertTrue(b.is_allowed_change(name))
        for name in (
            "lib/firmware/ath12k/IPQ5332/hw1.0/board.bin",
            "lib/firmware/ath12k/IPQ5332/hw1.0/caldata.bin",
            "lib/firmware/ath12k/QCN6432/hw1.0/caldata_1.bin",
            "lib/firmware/ath12k/QCN6432/hw1.0/regdb.bin",
            "lib/firmware/ath12k/QCN6432/hw1.0/fw_ini_cfg.bin",
            "lib/modules/kernel.ko", "etc/config/wireless", "etc/shadow",
            "etc/os-release",
            "lib/firmware/ath12k/QCN6432/hw1.0/q6_fw2.b02.part",
            "lib/firmware/ath12k/QCN6432/hw1.0/q6_fw2.b100",
        ):
            with self.subTest(path=name):
                self.assertFalse(b.is_allowed_change(name))

    def test_release_identity_updates_target_not_symlink(self):
        with tempfile.TemporaryDirectory(prefix="wave7-fw-audit-test-") as temp:
            root = Path(temp)
            (root / "etc").mkdir()
            (root / "usr/lib").mkdir(parents=True)
            for rel in b.IDENTITY_FILES:
                (root / rel).write_text(f"accepted {b.ACCEPTED_REV}\n")
            (root / "etc/os-release").symlink_to("../usr/lib/os-release")
            b.firmware_identity(root)
            self.assertIn("per-board-data=acer-unmodified",
                          (root / b.MARKER).read_text())
            for rel in b.IDENTITY_FILES:
                self.assertIn(b.TRIAL_REV, (root / rel).read_text())
                self.assertNotIn(b.ACCEPTED_REV, (root / rel).read_text())
            self.assertTrue((root / "etc/os-release").is_symlink())

    def test_split_image_replacement_and_alias(self):
        with tempfile.TemporaryDirectory(prefix="wave7-fw-audit-test-") as temp:
            root = Path(temp) / "root"
            candidate = Path(temp) / "candidate"
            dest = root / "lib/firmware/ath12k/IPQ5332/hw1.0"
            src = candidate / "QCN6432/hw1.0"
            dest.mkdir(parents=True)
            src.mkdir(parents=True)
            for name, blob in (
                ("q6_fw2.mdt", b"old-mdt"), ("q6_fw2.b02", b"old-b02"),
                ("q6_fw2.b03", b"stale"), ("q6_fw2.mbn", b"old-mdt"),
                ("board.bin", b"acer-bdf"),
            ):
                (dest / name).write_bytes(blob)
            for name, blob in (
                ("q6_fw2.mdt", b"new-mdt"), ("q6_fw2.b00", b"new-b00"),
                ("q6_fw2.b02", b"new-b02"),
            ):
                (src / name).write_bytes(blob)
            copied = b.stage_image(root, candidate, "QCN6432", "q6_fw2",
                                   "IPQ5332")
            self.assertEqual(copied, 4)
            self.assertFalse((dest / "q6_fw2.b03").exists())
            self.assertEqual((dest / "board.bin").read_bytes(), b"acer-bdf")
            self.assertEqual((dest / "q6_fw2.mbn").read_bytes(), b"new-mdt")
            self.assertEqual((dest / "q6_fw2.b02").read_bytes(), b"new-b02")


if __name__ == "__main__":
    unittest.main()
