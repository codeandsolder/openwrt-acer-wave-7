#!/usr/bin/env python3
"""Build a single-module, kernel-identical Wave 7 sysupgrade A/B candidate."""
from __future__ import annotations

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

ACCEPTED_SHA = "a952779383ba6d6c0847951354af2d59a96e46b9422fba4fb0cda6e92a9877da"
ACCEPTED_REV = "r0+38249-3b1851eda6"
TRIAL_REV = "r0+38249-napi-5e3df9b898"
ACCEPTED_MODULE_SHA = "b403cd3c9cb7dd0de320247355828297aa27471d050fb482f6cafd1b4b94df6b"
NEW_MODULE_SHA = "aebb8c344f049f6fbef8695f55cc5148f40018b5c50f90b149ddc5fcd31a27a7"
WIFI7_MODULE_SHA = "99ed3ca29fbd1d73ad58d5794932ed74dcd46d3ec082272f088fd595588faeb6"
EXPECTED_COMMIT = "5e3df9b898"
MODULE = "lib/modules/6.18.60/ath12k.ko"
WIFI7 = "lib/modules/6.18.60/ath12k_wifi7.ko"
IDENTITIES = ("etc/openwrt_release", "etc/openwrt_version", "usr/lib/os-release", "etc/banner")
MARKER = "etc/wave7-napi-trial"


def check(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(args: list[str | Path], *, env: dict[str, str] | None = None) -> str:
    command = [str(x) for x in args]
    proc = subprocess.run(command, capture_output=True, text=True, env=env)
    if proc.returncode:
        raise RuntimeError(f"{command!r}: rc={proc.returncode}\n"
                           f"{proc.stdout[-1800:]}\n{proc.stderr[-1800:]}")
    return proc.stdout + proc.stderr


def manifest(root: Path) -> dict[str, tuple]:
    files = {}
    for p in sorted(root.rglob("*")):
        if p.is_dir() and not p.is_symlink():
            continue
        rel = p.relative_to(root).as_posix()
        mode = stat.S_IMODE(p.lstat().st_mode)
        if p.is_symlink():
            files[rel] = ("symlink", os.readlink(p), mode)
        elif p.is_file():
            files[rel] = ("file", digest(p.read_bytes()), mode)
        else:
            raise RuntimeError(f"Unexpected file type: {rel}")
    return files


def special_nodes(unsquashfs: Path, root: Path) -> None:
    lines = run([unsquashfs, "-ll", root]).splitlines()
    special = [x for x in lines if x and x[0] in "cbps"]
    check(len(special) == 1 and special[0].startswith("crw")
          and special[0].endswith("/dev/console"),
          "Unexpected special nodes in SquashFS")


def verify_modules(root: Path, new_module: Path, *, accepted: bool) -> None:
    module = root / MODULE
    wifi7 = root / WIFI7
    check(digest(module.read_bytes()) ==
          (ACCEPTED_MODULE_SHA if accepted else NEW_MODULE_SHA),
          "Unexpected main ath12k module")
    check(digest(wifi7.read_bytes()) == WIFI7_MODULE_SHA,
          "Unexpected other ath12k_wifi7 module")
    for name in (MODULE, WIFI7):
        mod = root / name
        vm = run(["modinfo", "-F", "vermagic", mod]).strip()
        check(vm == "6.18.60 SMP mod_unload aarch64",
              f"Unexpected module vermagic: {name}: {vm}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--accepted-image", type=Path, required=True)
    ap.add_argument("--candidate-module", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    repo = Path(__file__).resolve().parents[4]
    host = repo / "staging_dir/host/bin"
    unsquashfs = host / "unsquashfs4"
    mksquashfs = host / "mksquashfs4"
    fwtool = host / "fwtool"

    check(a.out != a.accepted_image and not a.out.exists(),
          "Refusing to overwrite an input or existing output")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    baseline = a.accepted_image.read_bytes()
    check(digest(baseline) == ACCEPTED_SHA, "Accepted sysupgrade SHA mismatch")
    mod = a.candidate_module.read_bytes()
    check(digest(mod) == NEW_MODULE_SHA, "Candidate ath12k.ko SHA mismatch")
    run(["git", "-C", repo, "merge-base", "--is-ancestor",
         EXPECTED_COMMIT, "HEAD"])

    with tempfile.TemporaryDirectory(prefix=".napi-build-", dir=a.out.parent) as d:
        tmp = Path(d)
        with tarfile.open(a.accepted_image) as tf:
            names = {x.name for x in tf.getmembers()}
            accepted_names = {"sysupgrade-acer_wave7",
                              "sysupgrade-acer_wave7/CONTROL",
                              "sysupgrade-acer_wave7/kernel",
                              "sysupgrade-acer_wave7/root"}
            check(names == accepted_names, "Unexpected accepted tar members")
            check(tf.extractfile("sysupgrade-acer_wave7/CONTROL").read()
                  == b"BOARD=acer_wave7\n", "Wrong device")
            kernel = tf.extractfile("sysupgrade-acer_wave7/kernel").read()
            squashfs = tf.extractfile("sysupgrade-acer_wave7/root").read()

        meta_in = tmp / "accepted-meta.json"
        run([fwtool, "-i", meta_in, a.accepted_image])
        meta = json.loads(meta_in.read_text())
        check(meta["version"]["revision"] == ACCEPTED_REV,
              "Unexpected accepted fwtool revision")
        check("acer,wave7" in meta["supported_devices"], "Unexpected board")
        check(meta["version"]["target"] == "qualcommbe/ipq53xx",
              "Unexpected target")
        accepted_squashfs = tmp / "accepted-root.squashfs"
        accepted_squashfs.write_bytes(squashfs)
        special_nodes(unsquashfs, accepted_squashfs)
        exclusions = tmp / "exclude.txt"
        exclusions.write_text("dev/console\n")

        root = tmp / "root"
        extract = run([unsquashfs, "-d", root, "-exclude-file",
                       exclusions, accepted_squashfs])
        check("created 0 devices" in extract, "Unexpected rootfs device extraction")
        verify_modules(root, a.candidate_module, accepted=True)
        old = manifest(root)

        (root / MODULE).write_bytes(mod)
        for rel in IDENTITIES:
            p = root / rel
            contents = p.read_text()
            check(contents.count(ACCEPTED_REV) >= 1,
                  f"Unexpected version identity: {rel}")
            p.write_text(contents.replace(ACCEPTED_REV, TRIAL_REV))
        (root / MARKER).write_text(
            f"accepted={ACCEPTED_SHA}\n"
            f"candidate-module={NEW_MODULE_SHA}\n"
            f"source-commit={EXPECTED_COMMIT}\n"
            f"kernel=byte-identical-accepted\n"
            f"other-modules=byte-identical-accepted\n"
            f"firmware=byte-identical-accepted\n"
        )
        verify_modules(root, a.candidate_module, accepted=False)
        new = manifest(root)
        changes = sorted(name for name in old.keys() | new.keys()
                         if old.get(name) != new.get(name))
        check(changes == sorted([*IDENTITIES, MODULE, MARKER]),
              f"Unexpected rootfs changes: {changes}")
        check(old[WIFI7] == new[WIFI7], "Unexpected Wi-Fi 7 module mutation")

        candidate_squashfs = tmp / "napi-root.squashfs"
        run([mksquashfs, root, candidate_squashfs,
             "-nopad", "-noappend", "-root-owned", "-comp", "xz",
             "-Xpreset", "9", "-Xe", "-Xlc", "0", "-Xlp", "2",
             "-Xpb", "2", "-b", "256k",
             "-p", "/dev d 755 0 0",
             "-p", "/dev/console c 600 0 0 5 1",
             "-no-xattrs", "-block-readers", "4", "-small-readers", "4"])
        special_nodes(unsquashfs, candidate_squashfs)
        sbinfo = run([unsquashfs, "-s", candidate_squashfs])
        check("Compression xz" in sbinfo and "Block size 262144" in sbinfo,
              "SquashFS compression changed")
        verified = tmp / "verified-root"
        extraction = run([unsquashfs, "-d", verified, "-exclude-file",
                          exclusions, candidate_squashfs])
        check("created 0 devices" in extraction, "Unexpected rootfs reextract")
        check(manifest(verified) == new, "Rebuilt filesystem differs from staged data")
        verify_modules(verified, a.candidate_module, accepted=False)

        kernel_itb = tmp / "kernel.itb"
        kernel_itb.write_bytes(kernel)
        candidate_tar = tmp / "candidate.bin"
        env = os.environ.copy()
        env["TOPDIR"] = str(repo)
        env["SOURCE_DATE_EPOCH"] = "1794749579"
        run(["sh", repo / "scripts/sysupgrade-tar.sh",
             "--board", "acer_wave7", "--kernel", kernel_itb,
             "--rootfs", candidate_squashfs, candidate_tar], env=env)
        meta["version"]["revision"] = TRIAL_REV
        meta["wave7_test_type"] = "napi_irq_balance_exact_ath12k_module"
        meta_out = tmp / "metadata.json"
        meta_out.write_text(json.dumps(meta, separators=(",", ":")) + "\n")
        run([fwtool, "-I", meta_out, candidate_tar])
        meta_check = tmp / "metadata-check.json"
        run([fwtool, "-i", meta_check, candidate_tar])
        check(json.loads(meta_check.read_text()) == meta, "Candidate fwtool metadata differs")
        with tarfile.open(candidate_tar) as tf:
            check(tf.extractfile("sysupgrade-acer_wave7/CONTROL").read()
                  == b"BOARD=acer_wave7\n", "Candidate board differs")
            check(tf.extractfile("sysupgrade-acer_wave7/kernel").read()
                  == kernel, "Kernel FIT differs")
            check(tf.extractfile("sysupgrade-acer_wave7/root").read()
                  .startswith(candidate_squashfs.read_bytes()),
                  "SquashFS payload differs")
        check(candidate_tar.stat().st_size < 30_000_000,
              "Unexpected candidate image size")

        report = {
            "status": "SINGLE_MODULE_SYSUPGRADE_OFFLINE_VERIFIED",
            "accepted_image_sha256": ACCEPTED_SHA,
            "candidate_image_sha256": digest(candidate_tar.read_bytes()),
            "candidate_bytes": candidate_tar.stat().st_size,
            "accepted_kernel_sha256": digest(kernel),
            "candidate_kernel_sha256": digest(kernel),
            "accepted_module_sha256": ACCEPTED_MODULE_SHA,
            "new_module_sha256": NEW_MODULE_SHA,
            "unchanged_wifi7_module_sha256": WIFI7_MODULE_SHA,
            "rootfs_changes": changes,
            "unexpected_changes": [],
            "trial_revision": TRIAL_REV,
            "source_commit": EXPECTED_COMMIT,
            "router_untouched": True,
        }
        shutil.move(candidate_tar, a.out)
        a.out.with_suffix(".report.json").write_text(json.dumps(report, indent=2) + "\n")
        a.out.with_suffix(".sha256").write_text(
            report["candidate_image_sha256"] + "  " + a.out.name + "\n")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
