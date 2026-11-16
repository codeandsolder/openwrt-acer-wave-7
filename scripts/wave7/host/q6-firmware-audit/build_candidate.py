#!/usr/bin/env python3
"""Repack accepted Acer Wave7 sysupgrade with coherent WBE1.4 signed blobs.

No building or installing a kernel, live router access, sysupgrade flashing,
or mutations to the checked-out OpenWrt files overlay. Uses the exact native
Acer kernel and OpenWrt's stock SquashFS and sysupgrade-tar builders.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile

from audit import IMAGES, inspect_family
from signing_gate import assess

ACCEPTED_SHA = "a952779383ba6d6c0847951354af2d59a96e46b9422fba4fb0cda6e92a9877da"
ACCEPTED_REV = "r0+38249-3b1851eda6"
TRIAL_REV = "r0+38249-wbe14-01734-test"
SOURCE_VERSION = "WLAN.WBE.1.4-01734-QCAHKSWPL_SILICONZ-1"
STEMS = (
    ("IPQ5332", "q6_fw0", "IPQ5332"),
    ("IPQ5332", "q6_fw1", "IPQ5332"),
    ("IPQ5332", "iu_fw", "IPQ5332"),
    ("QCN6432", "q6_fw2", "QCN6432"),
    ("QCN6432", "iu_fw", "QCN6432"),
    ("QCN6432", "q6_fw2", "IPQ5332"),  # Acer's actual PD2 DTS path
)
FIRMWARE_NAME = re.compile(r"^(q6_fw[012]|iu_fw)\.(mdt|mbn|b[0-9]{2})$")
IDENTITY_FILES = (
    "etc/openwrt_release", "etc/openwrt_version", "usr/lib/os-release",
    "etc/banner",
)
MARKER = "etc/wave7-firmware-trial"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def check(cond, message):
    if not cond:
        raise RuntimeError(message)


def cmd(args, *, env=None):
    proc = subprocess.run(args, capture_output=True, text=True, env=env)
    if proc.returncode:
        raise RuntimeError(f"{args[0]} rc={proc.returncode}\n"
                           f"{proc.stdout[-1800:]}\n{proc.stderr[-1800:]}")
    return proc.stdout + proc.stderr


def read_manifest(root):
    result = {}
    for p in sorted(root.rglob("*")):
        if p.is_dir() and not p.is_symlink():
            continue
        rel = p.relative_to(root).as_posix()
        if p.is_symlink():
            result[rel] = ("symlink", os.readlink(p), stat.S_IMODE(p.lstat().st_mode))
        elif p.is_file():
            result[rel] = ("file", sha(p.read_bytes()), stat.S_IMODE(p.stat().st_mode))
        else:
            raise RuntimeError(f"unexpected special node in extracted staging: {rel}")
    return result


def check_source_sha(root):
    for soc in ("IPQ5332", "QCN6432"):
        d = root / soc / "hw1.0"
        entries = (d / "manifest.tsv").read_text().splitlines()
        check(len(entries) == (22 if soc == "IPQ5332" else 11),
              f"unexpected GitHub manifest count for {soc}")
        for line in entries:
            name, size, expected_git_sha, _ = line.split("\t")
            data = (d / name).read_bytes()
            check(len(data) == int(size), f"GitHub source size changed: {soc}/{name}")
            digest = hashlib.sha1(b"blob " + str(len(data)).encode()
                                  + b"\0" + data).hexdigest()
            check(digest == expected_git_sha, f"source provenance mismatch: {soc}/{name}")


def stage_image(root, candidate, source_soc, stem, destination_soc):
    src = candidate / source_soc / "hw1.0"
    dst = root / "lib/firmware/ath12k" / destination_soc / "hw1.0"
    check(dst.is_dir(), f"missing accepted DTS firmware destination: {dst}")
    existing_mbn = (dst / f"{stem}.mbn").is_file()
    original = [
        x for x in dst.iterdir()
        if x.is_file() and (x.name == f"{stem}.mdt" or x.name == f"{stem}.mbn"
                            or re.fullmatch(re.escape(stem) + r"\.b\d\d", x.name))
    ]
    check(original, f"no accepted image to replace: {destination_soc}/{stem}")
    for file in original:
        file.unlink()
    files = sorted([
        x for x in src.iterdir()
        if x.is_file() and (x.name == f"{stem}.mdt"
                            or re.fullmatch(re.escape(stem) + r"\.b\d\d", x.name))
    ])
    check(any(f.name == f"{stem}.mdt" for f in files),
          f"missing candidate MDT: {source_soc}/{stem}")
    for f in files:
        shutil.copy2(f, dst / f.name)
    if existing_mbn:
        shutil.copy2(src / f"{stem}.mdt", dst / f"{stem}.mbn")
    return len(files) + int(existing_mbn)


def is_allowed_change(rel):
    if rel in IDENTITY_FILES or rel == MARKER:
        return True
    parts = Path(rel).parts
    return (len(parts) == 6 and parts[:3] == ("lib", "firmware", "ath12k")
            and parts[3] in ("IPQ5332", "QCN6432") and parts[4] == "hw1.0"
            and bool(FIRMWARE_NAME.fullmatch(parts[5])))


def firmware_identity(root):
    for rel in IDENTITY_FILES:
        p = root / rel
        text = p.read_text()
        check(ACCEPTED_REV in text, f"accepted root identity mismatch: {rel}")
        p.write_text(text.replace(ACCEPTED_REV, TRIAL_REV))
    (root / MARKER).write_text(
        "Wave7 trial: coherent Qualcomm WBE1.4-01734 signed firmware\n"
        f"accepted-base-revision={ACCEPTED_REV}\n"
        f"trial-revision={TRIAL_REV}\n"
        "root-kernel=accepted-unmodified\n"
        "per-board-data=acer-unmodified\n"
    )


def verify_special_nodes(unsquashfs, path):
    listing = cmd([str(unsquashfs), "-ll", str(path)])
    special = [line for line in listing.splitlines()
               if line and line[0] in ("c", "b", "p", "s")]
    check(len(special) == 1 and special[0].startswith("crw")
          and special[0].endswith("/dev/console"),
          f"special nodes changed; expected only /dev/console: {special}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--accepted-image", required=True, type=Path)
    ap.add_argument("--candidate", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    repo = Path(__file__).resolve().parents[4]
    host = repo / "staging_dir/host/bin"
    unsquashfs = host / "unsquashfs4"
    mksquashfs = host / "mksquashfs4"
    fwtool = host / "fwtool"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    check(not args.out.exists(), f"refusing to overwrite existing image: {args.out}")
    original = args.accepted_image.read_bytes()
    check(sha(original) == ACCEPTED_SHA, "accepted baseline image SHA mismatch")
    check_source_sha(args.candidate)

    with tempfile.TemporaryDirectory(prefix=".build-", dir=args.out.parent) as td:
        tmp = Path(td)
        with tarfile.open(args.accepted_image) as tf:
            names = {m.name for m in tf.getmembers()}
            needed = {"sysupgrade-acer_wave7/CONTROL",
                      "sysupgrade-acer_wave7/kernel",
                      "sysupgrade-acer_wave7/root"}
            check(needed <= names and len(names - needed - {"sysupgrade-acer_wave7"})
                  == 0, f"unexpected sysupgrade archive entries: {sorted(names)}")
            check(tf.extractfile("sysupgrade-acer_wave7/CONTROL").read()
                  == b"BOARD=acer_wave7\n", "wrong accepted board")
            kernel = tf.extractfile("sysupgrade-acer_wave7/kernel").read()
            compressed_root = tf.extractfile("sysupgrade-acer_wave7/root").read()

        accepted_root = tmp / "accepted-root.squashfs"
        accepted_root.write_bytes(compressed_root)
        verify_special_nodes(unsquashfs, accepted_root)
        meta_in = tmp / "accepted-meta.json"
        cmd([str(fwtool), "-i", str(meta_in), str(args.accepted_image)])
        metadata = json.loads(meta_in.read_text())
        check(metadata["version"]["revision"] == ACCEPTED_REV,
              "accepted metadata revision mismatch")
        check("acer,wave7" in metadata["supported_devices"],
              "accepted image device support mismatch")
        check(metadata["version"]["target"] == "qualcommbe/ipq53xx",
              "accepted image target mismatch")

        # Exclude the one verified device inode during unprivileged
        # extraction, then recreate it from OpenWrt's -p definition.
        # Excluding a known device is preferable to treating all other
        # unsquashfs exit-code-2 failures as harmless warnings.
        exclude = tmp / "exclude-console.txt"
        exclude.write_text("dev/console\n")
        root = tmp / "root"
        extracted = cmd([str(unsquashfs), "-d", str(root),
                         "-exclude-file", str(exclude), str(accepted_root)])
        check("created 0 devices" in extracted,
              "unprivileged extraction did not exclude only /dev/console")
        baseline_manifest = read_manifest(root)
        signing = assess(
            root / "lib/firmware/ath12k/IPQ5332/hw1.0/q6_fw0.b01",
            args.candidate / "IPQ5332/hw1.0/q6_fw0.b01",
        )
        check(signing["root_fingerprint_equal"],
              "candidate uses a different Qualcomm signing root; "
              "do not package into a production Acer trial")
        firmware_identity(root)
        changed_firmware = 0
        for source_soc, stem, dest_soc in STEMS:
            changed_firmware += stage_image(
                root, args.candidate, source_soc, stem, dest_soc
            )
        after_manifest = read_manifest(root)
        changed = sorted(k for k in baseline_manifest.keys() | after_manifest.keys()
                         if baseline_manifest.get(k) != after_manifest.get(k))
        unexpected = [k for k in changed if not is_allowed_change(k)]
        check(not unexpected, f"unexpected modification to accepted root: {unexpected}")
        for rel in ("lib/firmware/ath12k/IPQ5332/hw1.0/board.bin",
                    "lib/firmware/ath12k/IPQ5332/hw1.0/caldata.bin",
                    "lib/firmware/ath12k/IPQ5332/hw1.0/regdb.bin",
                    "lib/firmware/ath12k/QCN6432/hw1.0/board.bin",
                    "lib/firmware/ath12k/QCN6432/hw1.0/caldata_1.bin",
                    "lib/firmware/ath12k/QCN6432/hw1.0/fw_ini_cfg.bin",
                    "lib/firmware/ath12k/QCN6432/hw1.0/regdb.bin"):
            check(baseline_manifest[rel] == after_manifest[rel],
                  f"Acer board identity/calibration changed: {rel}")
        check(changed_firmware >= 30, "incomplete firmware update set")

        new_firmware = inspect_family(root / "lib/firmware/ath12k",
                                      IMAGES, (0x4A900000, 0x4CA00000))
        check(new_firmware["userpd_release"] == SOURCE_VERSION,
              "mixed firmware generation after staging")
        radio_alias = root / "lib/firmware/ath12k/IPQ5332/hw1.0/q6_fw2.b02"
        canonical = root / "lib/firmware/ath12k/QCN6432/hw1.0/q6_fw2.b02"
        check(radio_alias.read_bytes() == canonical.read_bytes(),
              "external Q6 firmware alias mismatch")
        for rel in ("IPQ5332/hw1.0/iu_fw.mbn",
                    "IPQ5332/hw1.0/q6_fw1.mbn",
                    "QCN6432/hw1.0/iu_fw.mbn",
                    "QCN6432/hw1.0/q6_fw2.mbn"):
            p = root / "lib/firmware/ath12k" / rel
            check(p.read_bytes() == p.with_suffix(".mdt").read_bytes(),
                  f"stale MDT alias {rel}")

        root_squashfs = tmp / "candidate-root.squashfs"
        mkargs = [
            str(mksquashfs), str(root), str(root_squashfs),
            "-nopad", "-noappend", "-root-owned", "-comp", "xz",
            "-Xpreset", "9", "-Xe", "-Xlc", "0", "-Xlp", "2",
            "-Xpb", "2", "-b", "256k",
            "-p", "/dev d 755 0 0",
            "-p", "/dev/console c 600 0 0 5 1",
            "-no-xattrs", "-block-readers", "4", "-small-readers", "4",
        ]
        cmd(mkargs)
        verify_special_nodes(unsquashfs, root_squashfs)
        sb = cmd([str(unsquashfs), "-s", str(root_squashfs)])
        check("Compression xz" in sb and "Block size 262144" in sb,
              "candidate SquashFS compression or blocksize changed")
        check("Xattrs are not stored" in sb, "candidate rootfs xattrs changed")
        verified_root = tmp / "verified-root"
        uncompressed = cmd([str(unsquashfs), "-d", str(verified_root),
                            "-exclude-file", str(exclude), str(root_squashfs)])
        check("created 0 devices" in uncompressed,
              "unexpected rootfs reextract")
        check(read_manifest(verified_root) == after_manifest,
              "candidate rootfs SquashFS contents differ from staged files")

        kernel_path = tmp / "accepted-kernel.itb"
        kernel_path.write_bytes(kernel)
        output_part = tmp / "candidate-tar.bin"
        env = os.environ.copy()
        env["TOPDIR"] = str(repo)
        env["SOURCE_DATE_EPOCH"] = "1794749579"  # accepted 2026-11-15 image timestamp UTC
        cmd(["sh", str(repo / "scripts/sysupgrade-tar.sh"),
             "--board", "acer_wave7", "--kernel", str(kernel_path),
             "--rootfs", str(root_squashfs), str(output_part)], env=env)
        metadata["version"]["revision"] = TRIAL_REV
        metadata["wave7_test_firmware"] = SOURCE_VERSION
        meta_out = tmp / "candidate-metadata.json"
        meta_out.write_text(json.dumps(metadata, separators=(",", ":")) + "\n")
        cmd([str(fwtool), "-I", str(meta_out), str(output_part)])
        extracted_meta = tmp / "check-metadata.json"
        cmd([str(fwtool), "-i", str(extracted_meta), str(output_part)])
        check(json.loads(extracted_meta.read_text()) == metadata,
              "fwtool appended metadata mismatch")
        with tarfile.open(output_part) as tf:
            check(tf.extractfile("sysupgrade-acer_wave7/CONTROL").read()
                  == b"BOARD=acer_wave7\n", "repacked CONTROL differs")
            check(tf.extractfile("sysupgrade-acer_wave7/kernel").read() == kernel,
                  "kernel modified during repack")
            check(tf.extractfile("sysupgrade-acer_wave7/root").read()
                  .startswith(root_squashfs.read_bytes()),
                  "candidate SquashFS payload changed in tar")
        check(output_part.stat().st_size < 30_000_000,
              "candidate image unexpectedly oversized")
        image_sha = sha(output_part.read_bytes())
        result = {
            "status": "NATIVE_SYSUPGRADE_PACKED_AND_OFFLINE_VERIFIED",
            "accepted_sysupgrade_sha256": ACCEPTED_SHA,
            "accepted_kernel_sha256": sha(kernel),
            "candidate_kernel_sha256": sha(kernel),
            "candidate_sysupgrade_sha256": image_sha,
            "candidate_rootfs_squashfs_sha256": sha(root_squashfs.read_bytes()),
            "candidate_rootfs_bytes": root_squashfs.stat().st_size,
            "candidate_sysupgrade_bytes": output_part.stat().st_size,
            "source_repo_commit": cmd(["git", "-C", str(repo), "rev-parse", "HEAD"]).strip(),
            "trial_revision": TRIAL_REV,
            "firmware_release": SOURCE_VERSION,
            "signing_roots_equal": signing["root_fingerprint_equal"],
            "signing_intermediates_equal": signing["intermediate_fingerprint_equal"],
            "signed_complete_image_families": 5,
            "load_segments": new_firmware["used_physical_intervals"],
            "firmware_files_copied": changed_firmware,
            "changed_rootfs_files": changed,
            "unexpected_rootfs_changes": unexpected,
            "kernel_reused_byte_identical": True,
            "acer_board_calibration_regdb_unchanged": True,
            "no_router_access_or_flash": True,
        }
        shutil.move(str(output_part), str(args.out))
        report = args.out.with_suffix(".report.json")
        report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        args.out.with_suffix(".sha256").write_text(
            image_sha + "  " + args.out.name + "\n"
        )
        print("CANDIDATE_PACKED_OFFLINE_VERIFIED")
        print("CANDIDATE_SHA256", image_sha)
        print("CANDIDATE_BYTES", result["candidate_sysupgrade_bytes"])
        print("KERNEL_UNCHANGED", sha(kernel))
        print("WBE14_USERPD_MATCH_AND_ACER_BDF_UNCHANGED")
        print("CHANGED_ONLY_ALLOWED_FILES", len(changed))
        print("ROUTER_UNTOUCHED")


if __name__ == "__main__":
    main()
