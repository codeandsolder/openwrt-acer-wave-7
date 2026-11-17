#!/usr/bin/env python3
"""Build an exact-accepted-kernel, minimally modified QDSS sysupgrade image.

Rebuilds the FIT with the identical accepted compressed kernel and a DTB
surgically extended for the dedicated ETR reservation; rebuilds the accepted
SquashFS using *both* matched native ath12k modules from one package,
a separate QDSS profile, and trial identities. Reject all unrelated changes.

The two modules share ath12k_base and must never come from different builds.
"""
from __future__ import annotations

import argparse
import difflib
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
import zlib

EXPECTED_BASELINE_SHA = "18e285b7dbfac4075a4f675b23c9b97cbf51c50aced6c16a82d1aab439dc0622"
EXPECTED_BASELINE_REV = "r0+38249-napi-5e3df9b898"
BASELINE_FIT_KERNEL_SHA = "0c24a7ea0f78c4b9480e46d4a4cdb8078b2e5665c9c24a7e0568562a9dac1de3"
BASELINE_DTB_SHA = "6d5689602412f6ee2b2cb1e2bffe69a10751fd68de82cfa6ca84fe1d78c6a671"
BASELINE_MODULE_SHA = "aebb8c344f049f6fbef8695f55cc5148f40018b5c50f90b149ddc5fcd31a27a7"
WIFI7_SHA = "99ed3ca29fbd1d73ad58d5794932ed74dcd46d3ec082272f088fd595588faeb6"
PROFILE_SHA = "354b04763d2e95cdc25241f1543a9bd34d171e6d8d32d385242070edc5b4d6a4"
TRIAL_REV = "r0+38249-qdss-48b2476bd6"
ROOT_MODULE = "lib/modules/6.18.60/ath12k.ko"
ROOT_WIFI7 = "lib/modules/6.18.60/ath12k_wifi7.ko"
ROOT_PROFILE = "lib/firmware/ath12k/IPQ5332/hw1.0/qdss_trace_umacnoc.bin"
TRIAL_MARKER = "etc/wave7-qdss-trial"
IDENTITIES = ("etc/openwrt_release", "etc/openwrt_version", "usr/lib/os-release", "etc/banner")
ROOT_BOARD = "sysupgrade-acer_wave7"
KERNEL_DESC = "ARM64 OpenWrt Linux-6.18.60"
DTB_DESC = "ARM64 OpenWrt acer_wave7 device tree blob"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(*args: str | Path, env: dict[str, str] | None = None) -> str:
    cmd = [str(a) for a in args]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if proc.returncode:
        raise RuntimeError(
            f"{cmd!r} returned {proc.returncode}\n"
            f"{proc.stdout[-1600:]}\n{proc.stderr[-1600:]}"
        )
    return proc.stdout


def fdt_property(path: Path, node: str, key: str, kind: str = "s") -> list[str]:
    return run("fdtget", "-t", kind, path, node, key).strip().split()


def fit_data(itb: Path, image: str) -> bytes:
    text = run("fdtget", "-t", "bx", itb, f"/images/{image}", "data")
    return bytes(int(x, 16) for x in text.split())


def canonical_dts(dtb: Path, target: Path) -> str:
    run("dtc", "-q", "-I", "dtb", "-O", "dts", "-o", target, dtb)
    return target.read_text()


def patch_exact_board_dtb(accepted: Path, candidate: Path, tmp: Path) -> dict:
    old = canonical_dts(accepted, tmp / "accepted.dts")
    values = [int(x, 16) for x in re.findall(r"\bphandle\s*=\s*<0x([0-9a-f]+)>;", old)]
    require(values and len(set(values)) == len(values), "Invalid or duplicate existing phandles")
    new_phandle = max(values) + 1
    require(new_phandle <= 0xFFFF, "Unexpected phandle max")

    expected_old_map = ["30", "30", "31", "32", "33"]
    require(fdt_property(accepted, "/soc@0/wifi@c000000", "memory-region", "x")
            == expected_old_map, "Accepted radio memory phandles changed")
    names = fdt_property(accepted, "/soc@0/wifi@c000000", "memory-region-names")
    require(names == ["host-ddr-mem", "q6-region", "m3-dump",
                      "q6-caldb", "mlo-global-mem"],
            "Accepted radio memory names changed")
    require(fdt_property(accepted, "/reserved-memory/wifi-reserved@4cb00000",
                         "reg", "x") == ["0", "4cb00000", "0", "300000"],
            "Accepted Wi-Fi spare memory range changed")
    shutil.copy2(accepted, candidate)
    spare = "/reserved-memory/wifi-reserved@4cb00000"
    etr = "/reserved-memory/wifi-etr@4cd00000"
    wifi = "/soc@0/wifi@c000000"
    run("fdtput", "-t", "x", candidate, spare, "reg", "0", "4cb00000", "0", "200000")
    run("fdtput", "-c", candidate, etr)
    run("fdtput", "-t", "x", candidate, etr, "reg", "0", "4cd00000", "0", "100000")
    run("fdtput", candidate, etr, "no-map")
    run("fdtput", "-t", "x", candidate, etr, "phandle", f"{new_phandle:x}")
    run("fdtput", "-t", "x", candidate, wifi, "memory-region",
        *expected_old_map, f"{new_phandle:x}")
    run("fdtput", "-t", "s", candidate, wifi, "memory-region-names",
        *names, "q6-etr-dump")

    patched = canonical_dts(candidate, tmp / "candidate.dts")
    # Strip exactly the new node and restore the two modified properties.
    # The complete canonical DTB must then match the accepted DTB, including
    # every address, unrelated property, and original phandle.
    node = (f"\t\twifi-etr@4cd00000 {{\n"
            f"\t\t\tphandle = <0x{new_phandle:02x}>;\n"
            f"\t\t\tno-map;\n"
            f"\t\t\treg = <0x00 0x4cd00000 0x00 0x100000>;\n"
            f"\t\t}};\n\n")
    require(patched.count(node) == 1, "ETR node differs from audited template")
    reverse = patched.replace(node, "")
    transitions = [
        ("reg = <0x00 0x4cb00000 0x00 0x200000>;",
         "reg = <0x00 0x4cb00000 0x00 0x300000>;"),
        (f"memory-region = <0x30 0x30 0x31 0x32 0x33 0x{new_phandle:02x}>;",
         "memory-region = <0x30 0x30 0x31 0x32 0x33>;"),
        ('memory-region-names = "host-ddr-mem", "q6-region", "m3-dump", '
         '"q6-caldb", "mlo-global-mem", "q6-etr-dump";',
         'memory-region-names = "host-ddr-mem", "q6-region", "m3-dump", '
         '"q6-caldb", "mlo-global-mem";'),
    ]
    for new_value, old_value in transitions:
        require(reverse.count(new_value) == 1, f"Unexpected DT transform: {new_value}")
        reverse = reverse.replace(new_value, old_value)
    if reverse != old:
        diff = "".join(difflib.unified_diff(old.splitlines(True), reverse.splitlines(True)))
        raise RuntimeError(f"Unexpected DT changes outside ETR reservation:\n{diff[:1800]}")
    require(fdt_property(candidate, etr, "reg", "x") ==
            ["0", "4cd00000", "0", "100000"], "ETR physical range mismatch")
    require(fdt_property(candidate, wifi, "memory-region-names") ==
            names + ["q6-etr-dump"], "ETR name mismatch")
    return {"new_etr_phandle": new_phandle, "accepted_dtb_sha256": digest(accepted.read_bytes()),
            "diagnostic_dtb_sha256": digest(candidate.read_bytes()),
            "whitelisted_dts_changes": ["add 1MiB q6-etr", "reduce Wi-Fi spare to 2MiB",
                                         "add IPQ5332 ETR reference and name"]}


def mkfit(tmp: Path, compressed_kernel: bytes, new_board: Path,
          accepted_fit: Path, mkimage: Path) -> tuple[Path, dict]:
    require(digest(compressed_kernel) == BASELINE_FIT_KERNEL_SHA,
            "Accepted compressed kernel digest changed")
    require(fdt_property(accepted_fit, "/", "description") ==
            ["ARM64", "OpenWrt", "FIT", "(Flattened", "Image", "Tree)"],
            "Unexpected FIT description")
    require(fdt_property(accepted_fit, "/images/kernel-1", "compression") ==
            ["lzma"], "Unexpected FIT kernel compression")
    require(fdt_property(accepted_fit, "/images/kernel-1", "description") ==
            KERNEL_DESC.split(), "Unexpected kernel description")
    require(fdt_property(accepted_fit, "/images/kernel-1", "load", "x") ==
            ["41000000"], "Unexpected kernel load address")
    require(fdt_property(accepted_fit, "/images/kernel-1", "entry", "x") ==
            ["41000000"], "Unexpected kernel entry address")
    require(fdt_property(accepted_fit, "/images/fdt-1", "description") ==
            DTB_DESC.split(), "Unexpected DTB description")
    require(fdt_property(accepted_fit, "/configurations", "default") ==
            ["config@mi04.1-c2"], "Unexpected boot config")
    (tmp / "kernel.lzma").write_bytes(compressed_kernel)
    its = tmp / "diagnostic-fit.its"
    its.write_text('''/dts-v1/;
/ {
    description = "ARM64 OpenWrt FIT (Flattened Image Tree)";
    #address-cells = <1>;
    images {
        kernel-1 {
            description = "ARM64 OpenWrt Linux-6.18.60";
            data = /incbin/("kernel.lzma");
            type = "kernel"; arch = "arm64"; os = "linux";
            compression = "lzma";
            load = <0x41000000>; entry = <0x41000000>;
            hash-1 { algo = "crc32"; };
            hash-2 { algo = "sha1"; };
        };
        fdt-1 {
            description = "ARM64 OpenWrt acer_wave7 device tree blob";
            data = /incbin/("diagnostic-board.dtb");
            type = "flat_dt"; arch = "arm64";
            compression = "none";
            hash-1 { algo = "crc32"; };
            hash-2 { algo = "sha1"; };
        };
    };
    configurations {
        default = "config@mi04.1-c2";
        config@mi04.1-c2 {
            description = "OpenWrt acer_wave7";
            kernel = "kernel-1"; fdt = "fdt-1";
        };
    };
};
''')
    shutil.copy2(new_board, tmp / "diagnostic-board.dtb")
    out = tmp / "qdss-kernel.itb"
    run(mkimage, "-f", its, out)
    require(fit_data(out, "kernel-1") == compressed_kernel,
            "Regenerated FIT kernel bytes changed")
    require(fit_data(out, "fdt-1") == new_board.read_bytes(),
            "Regenerated FIT DTB differs")
    for img, data in (("kernel-1", compressed_kernel), ("fdt-1", new_board.read_bytes())):
        crc = zlib.crc32(data).to_bytes(4, "big").hex()
        sha1 = hashlib.sha1(data).hexdigest()
        for name, expected in (("hash-1", crc), ("hash-2", sha1)):
            val = bytes(int(v, 16) for v in
                        fdt_property(out, f"/images/{img}/{name}", "value", "bx")).hex()
            require(val == expected, f"FIT {img}/{name} hash mismatch")
    return out, {"accepted_compressed_kernel_sha256": digest(compressed_kernel),
                 "fit_sha256": digest(out.read_bytes())}


def manifest(root: Path) -> dict[str, tuple]:
    entries = {}
    for p in sorted(root.rglob("*")):
        if p.is_dir() and not p.is_symlink():
            continue
        rel = p.relative_to(root).as_posix()
        mode = stat.S_IMODE(p.lstat().st_mode)
        if p.is_symlink():
            entries[rel] = ("symlink", os.readlink(p), mode)
        elif p.is_file():
            entries[rel] = ("file", digest(p.read_bytes()), mode)
        else:
            raise RuntimeError(f"Unexpected filesystem entry: {rel}")
    return entries


def special_nodes(tool: Path, squashfs: Path) -> None:
    text = run(tool, "-ll", squashfs)
    special = [line for line in text.splitlines() if line and line[0] in "cbps"]
    require(len(special) == 1 and special[0].startswith("crw") and
            special[0].endswith("/dev/console"), "Unexpected squashfs special nodes")


def module_vermagic(path: Path) -> str:
    return run("modinfo", "-F", "vermagic", path).strip()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--accepted-image", type=Path, required=True)
    ap.add_argument("--module-package", type=Path, required=True)
    ap.add_argument("--diagnostic-profile", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    repo = Path(__file__).resolve().parents[4]
    host = repo / "staging_dir/host/bin"
    tools = dict(apk=host / "apk", unsquashfs=host / "unsquashfs4",
                 mksquashfs=host / "mksquashfs4", fwtool=host / "fwtool",
                 mkimage=host / "mkimage")
    require(all(f.is_file() for f in tools.values()), "Missing OpenWrt host tools")
    require(a.out.resolve() not in {a.accepted_image.resolve(),
                                   a.module_package.resolve()},
            "Candidate output would overwrite an input")
    require(not a.out.exists(), "Candidate output exists; refusing overwrite")
    require(digest(a.accepted_image.read_bytes()) == EXPECTED_BASELINE_SHA,
            "Accepted NAPI sysupgrade digest mismatch")
    require(digest(a.diagnostic_profile.read_bytes()) == PROFILE_SHA,
            "Diagnostic trace profile digest mismatch")
    require(a.module_package.name.startswith("kmod-ath12k-") and
            a.module_package.name.endswith(".apk"), "Expected native kmod-ath12k APK")
    run("git", "-C", repo, "merge-base", "--is-ancestor", "456ebb8907", "HEAD")

    a.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".qdss-build-", dir=a.out.parent) as base:
        tmp = Path(base)
        with tarfile.open(a.accepted_image) as tf:
            require({m.name for m in tf.getmembers()} ==
                    {ROOT_BOARD, ROOT_BOARD + "/CONTROL",
                     ROOT_BOARD + "/kernel", ROOT_BOARD + "/root"},
                    "Unexpected tar payload")
            require(tf.extractfile(ROOT_BOARD + "/CONTROL").read() ==
                    b"BOARD=acer_wave7\n", "Unexpected board")
            accepted_fit = tmp / "accepted.itb"
            accepted_fit.write_bytes(tf.extractfile(ROOT_BOARD + "/kernel").read())
            accepted_sq = tmp / "accepted.squashfs"
            accepted_sq.write_bytes(tf.extractfile(ROOT_BOARD + "/root").read())

        accepted_dtb = tmp / "accepted.dtb"
        accepted_dtb.write_bytes(fit_data(accepted_fit, "fdt-1"))
        require(digest(accepted_dtb.read_bytes()) == BASELINE_DTB_SHA,
                "Accepted FIT DTB changed")
        fit_kernel = fit_data(accepted_fit, "kernel-1")
        updated_dtb = tmp / "updated.dtb"
        dt_report = patch_exact_board_dtb(accepted_dtb, updated_dtb, tmp)
        fit, fit_report = mkfit(tmp, fit_kernel, updated_dtb,
                                accepted_fit, tools["mkimage"])

        metadata_file = tmp / "accepted-fwtool.json"
        run(tools["fwtool"], "-i", metadata_file, a.accepted_image)
        metadata = json.loads(metadata_file.read_text())
        require(metadata["version"]["revision"] == EXPECTED_BASELINE_REV,
                "Unexpected accepted revision")
        require("acer,wave7" in metadata["supported_devices"], "Unsupported device")
        require(metadata["version"]["target"] == "qualcommbe/ipq53xx",
                "Unexpected target")

        module_pkg = tmp / "module-package"
        module_pkg.mkdir()
        run(tools["apk"], "--allow-untrusted", "extract", "--destination",
            module_pkg, a.module_package)
        candidate_module = module_pkg / ROOT_MODULE
        require(candidate_module.is_file(), "Packaged native ath12k module missing")
        module_sha = digest(candidate_module.read_bytes())
        require(module_sha != BASELINE_MODULE_SHA, "Module did not change")
        require(module_vermagic(candidate_module) ==
                "6.18.60 SMP mod_unload aarch64", "Invalid module vermagic")
        require(b"umacnoc_qdss" in candidate_module.read_bytes(),
                "Candidate module lacks QDSS controls")
        package_wifi7 = module_pkg / ROOT_WIFI7
        require(package_wifi7.is_file(), "Rebuilt kmod lacks companion wifi7 module")
        require(module_vermagic(package_wifi7) ==
                "6.18.60 SMP mod_unload aarch64", "Invalid wifi7 vermagic")
        package_wifi7_sha = digest(package_wifi7.read_bytes())
        require(package_wifi7_sha != WIFI7_SHA,
                "Unexpected companion identity: re-check source build")
        # Both modules share struct ath12k_base; QDSS enlarges embedded
        # ath12k_qmi by 64 bytes. Mixing a rebuilt main module with an
        # accepted companion caused a real Oops at boot (2026-11-17).
        # Assert the DWARF struct layout from both source-built modules.
        build_dir = (repo /
            "build_dir/target-aarch64_cortex-a53_musl/linux-qualcommbe_ipq53xx"
            "/mac80211-regular/backports-7.2/drivers/net/wireless/ath/ath12k")
        layouts = [
            run("pahole", "--hex", "-C", "ath12k_base", build_dir / name)
            for name in ("ath12k.ko", "wifi7/ath12k_wifi7.ko")
        ]
        require(layouts[0] == layouts[1],
                "ath12k_base internal ABI differs between compiled module pair")
        require("wmi_ab" in layouts[0] and "drv_priv[]" in layouts[0],
                "Incomplete ath12k_base DWARF layout")

        special_nodes(tools["unsquashfs"], accepted_sq)
        excl = tmp / "exclude"
        excl.write_text("dev/console\n")
        oldroot = tmp / "old-root"
        require("created 0 devices" in run(tools["unsquashfs"], "-d", oldroot,
                "-exclude-file", excl, accepted_sq),
                "Unexpected original special-node extraction")
        before = manifest(oldroot)
        require(digest((oldroot / ROOT_MODULE).read_bytes()) ==
                BASELINE_MODULE_SHA, "Baseline ath12k module differs")
        require(digest((oldroot / ROOT_WIFI7).read_bytes()) ==
                WIFI7_SHA, "Baseline wifi7 module differs")
        require(not (oldroot / ROOT_PROFILE).exists(), "Trace profile already installed")
        require(not (oldroot / TRIAL_MARKER).exists(), "Unexpected prior QDSS marker")

        (oldroot / ROOT_MODULE).write_bytes(candidate_module.read_bytes())
        (oldroot / ROOT_WIFI7).write_bytes(package_wifi7.read_bytes())
        diag = oldroot / ROOT_PROFILE
        diag.parent.mkdir(parents=True, exist_ok=True)
        diag.write_bytes(a.diagnostic_profile.read_bytes())
        diag.chmod(0o644)
        for rel in IDENTITIES:
            p = oldroot / rel
            contents = p.read_text()
            require(contents.count(EXPECTED_BASELINE_REV) >= 1,
                    f"Unexpected accepted revision string: {rel}")
            p.write_text(contents.replace(EXPECTED_BASELINE_REV, TRIAL_REV))
        marker = oldroot / TRIAL_MARKER
        marker.write_text(
            f"base_image_sha256={EXPECTED_BASELINE_SHA}\n"
            f"base_kernel_data_sha256={BASELINE_FIT_KERNEL_SHA}\n"
            f"base_dtb_sha256={BASELINE_DTB_SHA}\n"
            f"qdss_dtb_sha256={dt_report['diagnostic_dtb_sha256']}\n"
            f"ath12k_sha256={module_sha}\n"
            f"ath12k_wifi7_sha256={package_wifi7_sha}\n"
            f"qdss_profile_sha256={PROFILE_SHA}\n"
            f"kernel=byte-identical-napi-accepted\n"
            f"non-ath12k-modules=byte-identical-napi-accepted\n"
            f"q6-firmware=byte-identical-napi-accepted\n"
            f"source_commit={run('git', '-C', repo, 'rev-parse', 'HEAD').strip()}\n"
        )
        marker.chmod(0o644)
        after = manifest(oldroot)
        changed = sorted(x for x in before.keys() | after.keys()
                         if before.get(x) != after.get(x))
        expected = sorted([ROOT_MODULE, ROOT_WIFI7, ROOT_PROFILE, TRIAL_MARKER, *IDENTITIES])
        require(changed == expected, f"Unexpected rootfs changes: {changed}")

        new_sq = tmp / "candidate.squashfs"
        run(tools["mksquashfs"], oldroot, new_sq,
            "-nopad", "-noappend", "-root-owned", "-comp", "xz",
            "-Xpreset", "9", "-Xe", "-Xlc", "0", "-Xlp", "2", "-Xpb", "2",
            "-b", "256k", "-p", "/dev d 755 0 0",
            "-p", "/dev/console c 600 0 0 5 1",
            "-no-xattrs", "-block-readers", "4", "-small-readers", "4")
        special_nodes(tools["unsquashfs"], new_sq)
        require("Compression xz" in run(tools["unsquashfs"], "-s", new_sq),
                "Unexpected SquashFS compression")
        verifyroot = tmp / "verified-root"
        require("created 0 devices" in run(tools["unsquashfs"], "-d",
                verifyroot, "-exclude-file", excl, new_sq),
                "Unexpected generated special nodes")
        require(manifest(verifyroot) == after, "SquashFS contents changed during rebuild")

        output_tar = tmp / "candidate.bin"
        env = os.environ.copy()
        env.update(TOPDIR=str(repo), SOURCE_DATE_EPOCH="1794749579")
        run("sh", repo / "scripts/sysupgrade-tar.sh",
            "--board", "acer_wave7", "--kernel", fit,
            "--rootfs", new_sq, output_tar, env=env)
        metadata["version"]["revision"] = TRIAL_REV
        metadata["wave7_test_type"] = "qdss_umacnoc_minimal_kernel_fdt_plus_native_ath12k"
        meta_out = tmp / "metadata.json"
        meta_out.write_text(json.dumps(metadata, separators=(",", ":")) + "\n")
        run(tools["fwtool"], "-I", meta_out, output_tar)
        verified_meta = tmp / "checked-metadata.json"
        run(tools["fwtool"], "-i", verified_meta, output_tar)
        require(json.loads(verified_meta.read_text()) == metadata,
                "fwtool metadata differs")
        with tarfile.open(output_tar) as tf:
            require(tf.extractfile(ROOT_BOARD + "/CONTROL").read() ==
                    b"BOARD=acer_wave7\n", "Generated board differs")
            actual_fit = tmp / "candidate-verify.itb"
            actual_fit.write_bytes(tf.extractfile(ROOT_BOARD + "/kernel").read())
            require(actual_fit.read_bytes() == fit.read_bytes(),
                    "Candidate FIT differs")
            require(tf.extractfile(ROOT_BOARD + "/root").read()
                    .startswith(new_sq.read_bytes()),
                    "Candidate squashfs differs")
            require(fit_data(actual_fit, "kernel-1") == fit_kernel,
                    "Kernel changed during sysupgrade packaging")
            require(fit_data(actual_fit, "fdt-1") == updated_dtb.read_bytes(),
                    "DTB changed during sysupgrade packaging")
        require(output_tar.stat().st_size < 30_000_000,
                "Unexpected final sysupgrade image size")
        report = {
            "status": "MINIMAL_QDSS_SYSUPGRADE_OFFLINE_VERIFIED",
            "base": EXPECTED_BASELINE_REV,
            "base_image_sha256": EXPECTED_BASELINE_SHA,
            "candidate_rev": TRIAL_REV,
            "candidate_image_sha256": digest(output_tar.read_bytes()),
            "candidate_bytes": output_tar.stat().st_size,
            "kernel": fit_report,
            "device_tree": dt_report,
            "accepted_module_sha256": BASELINE_MODULE_SHA,
            "new_module_sha256": module_sha,
            "accepted_wifi7_sha256": WIFI7_SHA,
            "new_wifi7_sha256": package_wifi7_sha,
            "source_module_shared_abi": "DWARF ath12k_base layout identical",
            "qdss_profile_sha256": PROFILE_SHA,
            "rootfs_changed": changed,
            "unexpected_changes": [],
            "hardware_flash_performed": False,
        }
        shutil.move(output_tar, a.out)
        a.out.with_suffix(".report.json").write_text(json.dumps(report, indent=2) + "\n")
        a.out.with_suffix(".sha256").write_text(
            report["candidate_image_sha256"] + "  " + a.out.name + "\n")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
