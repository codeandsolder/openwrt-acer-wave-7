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

The proven OpenWrt 6.18.60 lab image is revision cfb425bcad. Six
supervised vendor OTA trials culminated in a successful running initramfs
router, with all three Q6 processors, both MLO links, wired LAN and 27
factory SMEM MTD partitions verified. Its live /tmp/wave7-keep-boot marker
is intentionally armed; do not casually reboot this running router.

A checksum-verified RAM-boot FIT copy is stored on Asus at
/home/jan/firmware/wave7/trials/wave7-cfb425bcad-known-good.itb
(SHA-256 9b3a4a2b7fa5d7a59e7004eedca6ca89039ca1619c22fbb58c4dc016617a7353).
The successfully tested NAND-writing OTA is
/home/jan/firmware/wave7/trials/wave7-current-61860-cfb425bcad-etc-modes.bin.
These are distinct from the untested BCH-8 NAND ECC validation variant.

The complete sixth-trial observer snapshot and logs are stored privately
on Asus and Acer in
/home/jan/firmware/wave7/logs/current-61860-cfb425bcad-20261109/.

For the separate, read-only QPIC ECC investigation, see nand-ecc.md.
For the controlled UART/U-Boot RAM boot plan, see ram-boot.md.
