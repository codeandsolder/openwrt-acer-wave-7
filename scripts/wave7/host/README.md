# Acer Wave 7 supervised boot-test harness

These scripts are the source-controlled canonical copies of the small
supervised vendor sysupgrade/observation harness deployed on Asus under
/home/jan/scripts/wave7/. The Asus copies have been updated to match.

- wave7-openwrt-watch.sh TRIAL_TAG EXPECT_KERNEL EXPECT_REV: read-only
  observer. Requires the exact Linux version and ten-character git revision;
  collects boot/driver/network logs and reports radio-ready only if all three
  remote processors are running, both MLO links are visible, the wired peer
  is reachable, and the router's current-boot keep marker exists.
  It also records the actual MTD/UBI inventory. The companion
  verify-factory-mtd.sh validates all 27 recorded factory NAND partitions
  by name, size and erase geometry against factory-mtd.tsv, extracted
  from the intact 2026-10-28 full NAND backup, ignoring additional
  kernel-created UBI-volume MTD entries. It prints NAND_SMEMPART_READY=1
  only when the complete physical NAND layout matches; discrepancies
  are included in the capture. NAND discovery remains independent of
  the separate radio-ready decision.
- wave7-fallback-watch.sh TRIAL_TAG: independently observes recovery to
  the stock vendor kernel and preserves pstore/raw ramoops evidence.
- wave7-trial-flash.sh TRIAL_TAG WRAPPED_IMAGE EXPECT_KERNEL EXPECT_REV:
  NAND-writing guarded updater. Refuses unless the router is running the
  original vendor kernel 5.4.213 with bootfail=0, verifies the local and
  on-router image SHA, validates the OTA wrapper, starts both managed watchers,
  arms bootfail=4, then invokes sysupgrade.

The flash entry point is NOT the RAM-only boot mechanism; it will write
the NAND rootfs UBI volume. Do not run it as a diagnostic/preflight and do
not reboot a known-working OpenWrt initramfs just to satisfy its vendor
precondition. It does not provide a working U-Boot serial/TFTP recovery route.

The **current proven OpenWrt 6.18.60 lab image is d72fd34a45**
(BCH-8/512). Seven supervised vendor OTA trials culminated in a
successful NAND ECC-corrected initramfs router at 2026-11-09 16:35 CET:
all 27 factory SMEM MTD partitions and ART calibration pages 2/3/4/16
match the 2026-10-28 backup byte-for-byte, with 0 ECC failures and 5
corrected bits. Three Q6 processors and both MLO links were running,
LAN and the wired peer were reachable, and the live keep-boot marker
was set before the failsafe deadline. This validates NAND reads and
the AP, **not persistent rootfs or future power-cycle behavior**.

The tested **BCH-8 RAM-boot FIT** on Asus is
/home/jan/firmware/wave7/trials/wave7-d72fd34a45-bch8.itb
(SHA-256 01c6a24ba77d05f0c032003bb6319bbdead918e864aa1ce86cb2de5e777e0d2e).
The audited NAND-writing OTA, already used in successful trial seven, is
/home/jan/firmware/wave7/trials/wave7-current-61860-d72fd34a45-bch8.bin
(SHA-256 2581fc54b4c6b281dc02def9bfdad85d90a3201f2ee8861a879d08c550b220d8).

The previous working **BCH-4 image** cfb425bcad remains stored
separately on Asus at
/home/jan/firmware/wave7/trials/wave7-cfb425bcad-known-good.itb
(SHA-256 9b3a4a2b7fa5d7a59e7004eedca6ca89039ca1619c22fbb58c4dc016617a7353).
Its radio worked, but its NAND ECC setting demonstrably read factory
ART data incorrectly; preserve it as historical recovery only.

Successful seventh-trial observer snapshot, ART validator logs, update
log and recovery watcher are preserved on both Asus and Acer in
/home/jan/firmware/wave7/logs/bch8-trial-20261109/.

For the separate, read-only QPIC ECC investigation, see nand-ecc.md.
For the controlled UART/U-Boot RAM boot plan, see ram-boot.md.
For persistent NAND root and vendor-preserving overlay design, see storage-boot-plan.md.

The distinct experimental production `wave7-nand-squashfs` branch builds
a 22.55MB vendor OTA containing the **normal OpenWrt FIT and SquashFS**,
not the vendor SquashFS. It passed full offline UBI byte/CRC verification
and passed its first native NAND-root hardware boot on 2026-11-09. See storage-boot-plan.md for SHA256s
and staged hardware-verified artifact; the previous working `d72fd34a45` BCH-8 initramfs
remains the proven recovery baseline.
