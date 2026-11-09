# Wave 7 factory SPI-NAND ECC compatibility

The *working* 6.18.60 `cfb425bcad` release enumerates GigaDevice
512 MiB SPI NAND (2 KiB page, 128-byte OOB, 128 KiB erase blocks) and
all 27 factory physical SMEM partitions, but its original board device
tree inherited the vendor's **4-bit ECC per 512 bytes** setting.
Linux 6.18.60 warns that the detected chip requires stronger ECC.

## Reproducible read-only evidence

- Original 2026-10-28 factory NAND backup:
  `/home/jan/projects/acer-wave7-firmware/device-backup-2026-10-28/wave7-full-nand-2026-10-28.tar.zst`,
  member `wave7-backup-2026-10-28-r3/raw-physical/mtd18_0:ART.bin`.
- Running router `/dev/mtd18` is the unchanged factory ART partition.
  A 4 KiB plain MTD read of its first two pages succeeded, but differed
  from the backup in 41 bytes despite its matching first 12 bytes.
  The read increased `mtd18/ecc_failures`; reading other 2 KiB ART
  pages produced additional uncorrectable ECC reports. No MTD data was
  written or UBI attached during the experiment.
- A populated ART page (page 2, offset 4096) had 305 mismatching bytes
  with the factory backup under BCH-4. Aligning successive 512-byte
  regions with shifts **0, -4, -8, -12 bytes** changes their match
  counts to 507, 506, 501, 500 (out of 512), respectively. This
  strongly implicates a wrong ECC codeword size rather than wear.
- The QPIC driver has **528-byte BCH-4 codewords** (516 data + 12)
  versus **532-byte BCH-8 codewords** (516 data + 16). The 4-byte
  difference per codeword matches the measured shifts exactly.
- The kernel's GigaDevice chip table identifies the compatible 4 Gbit,
  2 KiB-page/128-byte OOB GD5F4GM8 family as requiring `NAND_ECCREQ(8,512)`.
  The upstream QPIC driver already implements BCH-8 (13 ECC parity bytes,
  2 spare bytes) and needs no generic codeword rewrites.

## Candidate and safe validation

The `wave7-ecc8-validation` source branch changes only
`nand-ecc-strength = <8>` in the Acer board DTS, retaining 512-byte
steps and all radio/network/UBI settings. **It is an untested candidate,
not the live router's current ECC configuration.**

Do not change the running router's boot state merely to test ECC.
Keep the last known-good FIT (`cfb425bcad`, SHA256
`9b3a4a2b7fa5d7a59e7004eedca6ca89039ca1619c22fbb58c4dc016617a7353`)
available separately. Once a controlled UART RAM boot is possible,
boot the BCH-8 FIT without NAND writes and compare the same ART pages
read-only against the factory backup. Success requires exact binary
agreement, zero ECC failures and correct 27-partition SMEM inventory.
Check old bootloader/ART partitions as well as rootfs; do not erase,
format, reattach or upgrade factory NAND as a diagnostic substitute.

Private ART dumps, radio MACs and backup binaries are **not** part of
the public source tree. Experiment scratch is kept in
`/home/jan/projects/acer-wave7-firmware/work/nand-compat-20261109/`.
