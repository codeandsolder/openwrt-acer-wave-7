# QCA8081 stock-poll FIFO experiment

## Primary evidence

Acer stock 067 qca-ssdk.ko SHA256
`5829156f0bfd9cb2021d267e73fa91950a23234e209720195fa639d0eaf4484b`.
The empty notify callback at 0x69644 is not the complete lifecycle:
read_status at 0x69d40 calls get_status, which reads copper status and
calls 0x66960 with reset argument 0 on link up (0x677f0) and 1 on link
down (0x6782c). QCA8081 uses adjacent PHY address+1, MMD1 register
0x9072 mask 0x0800, release on link up. The helper at 0x6f5bc rejects
all-ones read, masks and ORs, and writes even if unchanged.

0491 reproduces stock level writes on status polls, before Linux
interface selection/notification, with exact 004dd101 ID gate and
atomic bus-lock RMW. Unlike stock it propagates errors instead of
ignoring them. This is an experimental correction to the no-notify
inference, not a demonstrated recovery fix. Existing tests of pulse,
PHY reset, PCS recalibration and no-write policy remain valid negatives.

Stock C22.31 mode field mask 0x6000: zero SGMII, 0x2000 SGMII+;
historical healthy and failed 1G values 0x8544, current healthy 2.5G
0xa544. Correct mode status is not electrical RX lock.

## Isolated NAND build and packing

Production baseline commit 0fbc2cc77b2cab0838261cc23a5b310a795913ba.
Keep exact accepted native-recovery Guard8 image
SHA256 1da743efe01ab63043b314a6d44de52e99d65456259f0dae0c1d53a013918f2c
as parent. Its FIT has SHA256
9258ee2d5c2b9d154552d000fc8deb647bc85a02efc9c1086700736473757be4.
The original prepared build tree finishes with the initramfs kernel;
do not substitute that Image for NAND. Re-extract accepted LZMA payload
and DTB; confirm they match the archived NAND binary vmlinux and DTB.
Use a private reflink clone of the prepared kernel (not a hardlink
tree), restore .config.set, and replay the original Image Kbuild argv
with the existing verified ccache-to-sccache shim and toolchain.
Use olddefconfig then Image. Preserve the original build tree, and
stop the build if disk space drops below 3 GiB. Compare clean baseline
raw objcopy payload against the accepted payload before applying 0491.
The actual Nov20 baseline differed by exactly 29 bytes: embedded GNU
build identifier (20 bytes) and three 3-character newc mtime fields.
All other bytes were identical, including code and section layout.
Do not accept broader unexplained differences.

Save baseline .config, symbol export list and System.map; apply 0491
only in clone, run test-policy.py against actual patched source,
rebuild with identical Kbuild argv. Require exact NAND configuration
and export list parity. Use original objcopy flags (-O binary,
-R .reginfo/.notes/.note/.comment/.mdebug/.note.gnu.build-id, -S).
Compress candidate raw payload with existing OpenWrt lzma e -lc1 -lp2
-pb2, then generate FIT with original mkits options (arm64, 6.18.60,
load/entry 0x41000000, config@mi04.1-c2) and byte-identical parent DTB.
verify-fit.py independently verifies both CRC32/SHA1 payload hashes,
identical FIT nodes/properties except kernel data/hashes and optional
timestamp, and LZMA roundtrip. No live target access in the packager.

`build-trial-image.sh PARENT FIT FIT_SHA RAW_KERNEL OUTPUT_DIR`
requires clean source and exact parent hash, retains the already
accepted native RTL8367D module and all root data other than identity
fields, verifies the role migration contract, root metadata/modes,
SquashFS roundtrip, 46 radio hashes, sysupgrade tar/metadata roundtrip.
It generates a fresh revision/manifest (old approval must not match).
Run against artifacts from the verified link, not arbitrary FITs.
The output directory must not exist.

## Hardware acceptance

The built-in PHY driver requires a whole kernel trial. Preserve
accepted parent as explicit rollback. Require independent switch
management before any 1G direct-port flap. Initially accept
ordinary 2.5G, both management paths, Q6/MLO, and full soak. Then
perform a separately guarded 1G late-link/replug test, with CPU MAC
and kernel-owned PHY counters and independent witness, and compare
against the previous matched negative trials. No destructive extra
PHY counter reads; MMD7 0x802a–0x802f are clear-on-read. Source-only
until the full hardware trial actually passes.

## Stock host-side link synchronization

See [the original-instruction ARM replay](stock-host-replay/README.md).
The stock independent one-second worker also polls QCA8081 status and
writes the FIFO level. On same-mode unchanged-parameter link-up the
stock host skips explicit clock cycling and adapter reset. This is a
separate source-backed hypothesis, not a demonstrated hardware fix.
