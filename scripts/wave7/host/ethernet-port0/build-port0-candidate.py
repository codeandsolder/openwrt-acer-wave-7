#!/usr/bin/env python3
"""Build a strictly audited RTL8367D port0 trial from an accepted Wave 7 image.

Keep the accepted 6.18.60 compressed kernel, all modules, and the QDSS
firmware unchanged. Add only the missing switch PHY0/DSA port0, default
bridge membership, a distinct revision, and a diagnostic marker.
"""
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

BASE_SHA = "598d7ed97e106cbdfe6b279aa4338dce5aa7d3b9136d1314ca35ab81ca84e095"
BASE_REV = "r0+38249-qdss-952743842b"
TRIAL_REV = "r0+38249-port0-16a784ae"
EXPECTED_DTB_SHA = "5573844a088b5150cfaa163488ddd4962c0809d8655ec61018f29bf5087480e4"
BOARD = "sysupgrade-acer_wave7"
IDENTITIES = ("etc/openwrt_release", "etc/openwrt_version", "usr/lib/os-release", "etc/banner")
PHY = "/soc@0/mdio@90000/ethernet-switch@1d/mdio/ethernet-phy@0"
PORT = "/soc@0/mdio@90000/ethernet-switch@1d/ports/port@0"
MARKER = "etc/wave7-port0-trial"


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise RuntimeError(reason)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(*args: object, env: dict[str, str] | None = None) -> str:
    argv = [str(arg) for arg in args]
    p = subprocess.run(argv, text=True, capture_output=True, env=env)
    if p.returncode:
        raise RuntimeError(f"{argv!r}: rc={p.returncode}\n{p.stdout[-1200:]}\n{p.stderr[-1200:]}")
    return p.stdout


def fit_data(fit: Path, image: str) -> bytes:
    return bytes(int(v, 16) for v in run("fdtget", "-t", "bx", fit, f"/images/{image}", "data").split())


def prop(dtb: Path, node: str, name: str, kind: str = "x") -> list[str]:
    return run("fdtget", "-t", kind, dtb, node, name).strip().split()


def canonical_dts(dtb: Path, path: Path) -> str:
    run("dtc", "-q", "-I", "dtb", "-O", "dts", "-o", path, dtb)
    return path.read_text()


def manifest(root: Path) -> dict[str, tuple]:
    result = {}
    for file in sorted(root.rglob("*")):
        if file.is_dir() and not file.is_symlink():
            continue
        rel = file.relative_to(root).as_posix()
        mode = stat.S_IMODE(file.lstat().st_mode)
        if file.is_symlink():
            result[rel] = ("symlink", os.readlink(file), mode)
        elif file.is_file():
            result[rel] = ("file", sha(file.read_bytes()), mode)
        else:
            raise RuntimeError(f"Unexpected filesystem node {rel}")
    return result


def check_special_nodes(unsquashfs: Path, sq: Path) -> None:
    lines = [x for x in run(unsquashfs, "-ll", sq).splitlines() if x and x[0] in "cbps"]
    require(len(lines) == 1 and lines[0].startswith("crw") and lines[0].endswith("/dev/console"),
            f"Unexpected special nodes: {lines}")


def patch_dtb(original: Path, updated: Path, tmp: Path) -> dict:
    require(sha(original.read_bytes()) == EXPECTED_DTB_SHA, "Unexpected QDSS baseline device tree")
    old = canonical_dts(original, tmp / "original.dts")
    matches = [int(v, 16) for v in re.findall(r"\bphandle\s*=\s*<0x([0-9a-f]+)>;", old)]
    require(matches and len(matches) == len(set(matches)), "Missing/duplicate original phandles")
    number = max(matches) + 1
    require(number <= 0xFFFF, "Unexpected device-tree phandle allocation")
    for name, index in (("ethernet-phy@1", "1"), ("ethernet-phy@2", "2")):
        require(prop(original, PHY.rsplit("/", 1)[0] + "/" + name, "reg") == [index],
                "Previous RTL8367D PHY map changed")
    require("port@0" not in run("fdtget", "-l", original, PORT.rsplit("/", 1)[0]).split(),
            "RTL8367D port0 already declared")
    shutil.copy2(original, updated)
    for node in (PHY, PORT):
        run("fdtput", "-c", updated, node)
    run("fdtput", "-t", "x", updated, PHY, "reg", "0")
    run("fdtput", "-t", "x", updated, PHY, "phandle", f"{number:x}")
    run("fdtput", "-t", "x", updated, PORT, "reg", "0")
    run("fdtput", "-t", "s", updated, PORT, "label", "lan1")
    run("fdtput", "-t", "x", updated, PORT, "phy-handle", f"{number:x}")
    require(prop(updated, PHY, "reg") == ["0"], "PHY0 reg missing")
    require(prop(updated, PORT, "reg") == ["0"], "Port0 reg missing")
    require(prop(updated, PORT, "label", "s") == ["lan1"], "Port0 label missing")
    require(prop(updated, PORT, "phy-handle") == [f"{number:x}"], "Port0 PHY phandle mismatch")
    reverse = tmp / "reverse.dtb"
    shutil.copy2(updated, reverse)
    run("fdtput", "-r", reverse, PORT)
    run("fdtput", "-r", reverse, PHY)
    restored = canonical_dts(reverse, tmp / "restored.dts")
    require(restored == old, "Device-tree changes outside PHY0 and port0")
    return {"original_dtb_sha256": sha(original.read_bytes()),
            "new_dtb_sha256": sha(updated.read_bytes()), "added_phy_phandle": number,
            "other_dtb_changes": 0}


def mkfit(tmp: Path, kernel: bytes, dtb: Path, accepted: Path, mkimage: Path) -> Path:
    for name, data in (("compression", ["lzma"]), ("description", ["ARM64", "OpenWrt", "Linux-6.18.60"])):
        require(prop(accepted, "/images/kernel-1", name, "s") == data,
                "Accepted FIT kernel metadata changed")
    require(prop(accepted, "/configurations", "default", "s") == ["config@mi04.1-c2"],
            "Accepted FIT configuration changed")
    (tmp / "kernel.lzma").write_bytes(kernel)
    shutil.copy2(dtb, tmp / "board.dtb")
    (tmp / "port0.its").write_text('''/dts-v1/;
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
            data = /incbin/("board.dtb");
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
    result = tmp / "new.itb"
    run(mkimage, "-f", tmp / "port0.its", result)
    require(fit_data(result, "kernel-1") == kernel, "Compressed kernel bytes changed")
    require(fit_data(result, "fdt-1") == dtb.read_bytes(), "Port0 DTB corrupted in FIT")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--build-tree", required=True, type=Path)
    a = ap.parse_args()
    repo = Path(__file__).resolve().parents[4]
    build = a.build_tree.resolve()
    host = build / "staging_dir/host/bin"
    tools = {name: host / name for name in ("unsquashfs4", "mksquashfs4", "fwtool", "mkimage")}
    require(all(p.is_file() for p in tools.values()), "Required OpenWrt host tool missing")
    require(a.base.resolve() != a.out.resolve() and not a.out.exists(), "Output already exists or overwrites base")
    require(sha(a.base.read_bytes()) == BASE_SHA, "Exact accepted QDSS baseline SHA mismatch")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".port0-", dir=a.out.parent) as d:
        tmp = Path(d)
        with tarfile.open(a.base) as tf:
            require({m.name for m in tf.getmembers()} ==
                    {BOARD, BOARD + "/CONTROL", BOARD + "/kernel", BOARD + "/root"},
                    "Unexpected sysupgrade member list")
            require(tf.extractfile(BOARD + "/CONTROL").read() == b"BOARD=acer_wave7\n",
                    "Unexpected sysupgrade board")
            fit = tmp / "base.itb"
            fit.write_bytes(tf.extractfile(BOARD + "/kernel").read())
            sq = tmp / "base.squashfs"
            sq.write_bytes(tf.extractfile(BOARD + "/root").read())
        old_dtb = tmp / "old.dtb"
        old_dtb.write_bytes(fit_data(fit, "fdt-1"))
        new_dtb = tmp / "port0.dtb"
        dt_report = patch_dtb(old_dtb, new_dtb, tmp)
        kernel = fit_data(fit, "kernel-1")
        new_fit = mkfit(tmp, kernel, new_dtb, fit, tools["mkimage"])

        meta_file = tmp / "old-metadata.json"
        run(tools["fwtool"], "-i", meta_file, a.base)
        meta = json.loads(meta_file.read_text())
        require(meta["version"]["revision"] == BASE_REV, "Unexpected accepted revision")
        require("acer,wave7" in meta["supported_devices"], "Wrong board")
        check_special_nodes(tools["unsquashfs4"], sq)
        excl = tmp / "exclude"
        excl.write_text("dev/console\n")
        root = tmp / "root"
        require("created 0 devices" in run(tools["unsquashfs4"], "-d", root, "-exclude-file", excl, sq),
                "Unexpected extraction of device nodes")
        before = manifest(root)
        net = root / "etc/config/network"
        old_net = net.read_text()
        target = "\tlist ports 'lan2'\n"
        require(old_net.count(target) == 1 and "\tlist ports 'lan1'" not in old_net,
                "Persisted LAN configuration is unexpected")
        net.write_text(old_net.replace(target, "\tlist ports 'lan1'\n" + target))
        board = root / "etc/board.d/02_network"
        original_board = board.read_text()
        target = 'ucidef_set_interface "lan" device "lan" protocol "static"'
        require(original_board.count(target) == 1, "Existing board defaults changed")
        from_source = (repo / "target/linux/qualcommbe/ipq53xx/base-files/etc/board.d/02_network").read_text()
        require(from_source == original_board.replace(target,
                'ucidef_set_interface "lan" device "lan lan1 lan2 game" protocol "static"'),
                "Installed board defaults differ from committed patch")
        board.write_text(from_source)
        for rel in IDENTITIES:
            p = root / rel
            contents = p.read_text()
            require(BASE_REV in contents and TRIAL_REV not in contents, f"Unexpected {rel} revision")
            p.write_text(contents.replace(BASE_REV, TRIAL_REV))
        marker = root / MARKER
        require(not marker.exists(), "Existing port0 trial marker found")
        source_commit = run("git", "-C", repo, "rev-parse", "HEAD").strip()
        marker.write_text(f"base_image_sha256={BASE_SHA}\nbase_dtb_sha256={dt_report['original_dtb_sha256']}\n"
                          f"port0_dtb_sha256={dt_report['new_dtb_sha256']}\nsource_commit={source_commit}\n")
        marker.chmod(0o644)
        after = manifest(root)
        changed = sorted(x for x in before.keys() | after.keys() if before.get(x) != after.get(x))
        expected = sorted([MARKER, "etc/config/network", "etc/board.d/02_network", *IDENTITIES])
        require(changed == expected, f"Rootfs whitelist mismatch: {changed}")
        result_sq = tmp / "new.squashfs"
        run(tools["mksquashfs4"], root, result_sq, "-nopad", "-noappend", "-root-owned",
            "-comp", "xz", "-Xpreset", "9", "-Xe", "-Xlc", "0", "-Xlp", "2", "-Xpb", "2",
            "-b", "256k", "-p", "/dev d 755 0 0", "-p", "/dev/console c 600 0 0 5 1",
            "-no-xattrs", "-block-readers", "4", "-small-readers", "4")
        check_special_nodes(tools["unsquashfs4"], result_sq)
        verify = tmp / "verify"
        require("created 0 devices" in run(tools["unsquashfs4"], "-d", verify, "-exclude-file", excl, result_sq),
                "Unexpected generated device nodes")
        require(manifest(verify) == after, "Rootfs changed during compression")
        output = tmp / "candidate.bin"
        env = dict(os.environ, TOPDIR=str(build), SOURCE_DATE_EPOCH="1794749579")
        run("sh", build / "scripts/sysupgrade-tar.sh", "--board", "acer_wave7",
            "--kernel", new_fit, "--rootfs", result_sq, output, env=env)
        meta["version"]["revision"] = TRIAL_REV
        meta["wave7_test_type"] = "rtl8367d_port0_from_accepted_qdss"
        meta["wave7_source_commit"] = source_commit
        m = tmp / "metadata.json"
        m.write_text(json.dumps(meta, separators=(",", ":")) + "\n")
        run(tools["fwtool"], "-I", m, output)
        readback = tmp / "readback.json"
        run(tools["fwtool"], "-i", readback, output)
        require(json.loads(readback.read_text()) == meta, "Firmware metadata readback differs")
        with tarfile.open(output) as tf:
            require(tf.extractfile(BOARD + "/CONTROL").read() == b"BOARD=acer_wave7\n",
                    "Final board mismatch")
            final_fit = tmp / "verified.itb"
            final_fit.write_bytes(tf.extractfile(BOARD + "/kernel").read())
            require(fit_data(final_fit, "kernel-1") == kernel, "Compressed kernel changed")
            require(fit_data(final_fit, "fdt-1") == new_dtb.read_bytes(), "FIT device tree differs")
            require(tf.extractfile(BOARD + "/root").read().startswith(result_sq.read_bytes()),
                    "Generated squashfs differs")
        require(output.stat().st_size < 30_000_000, "Unexpected sysupgrade image size")
        report = {"status": "PORT0_SYSUPGRADE_OFFLINE_VERIFIED", "base_sha256": BASE_SHA,
                  "candidate_sha256": sha(output.read_bytes()), "candidate_revision": TRIAL_REV,
                  "size": output.stat().st_size, "source_commit": source_commit,
                  "kernel_sha256": sha(kernel), "device_tree": dt_report,
                  "changed_rootfs_paths": changed, "other_rootfs_changes": 0,
                  "hardware_flash_performed": False}
        shutil.move(output, a.out)
        a.out.with_suffix(".report.json").write_text(json.dumps(report, indent=2) + "\n")
        a.out.with_suffix(".sha256").write_text(report["candidate_sha256"] + "  " + a.out.name + "\n")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
