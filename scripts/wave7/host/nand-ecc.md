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

## Raw page reconstruction: four independent ART pages

An extra read-only comparison was performed against the same archived ART
partition on pages 2, 3, 4, and 16. The existing AArch64 `nanddump`
binary was copied temporarily from the OpenWrt build to the running
router's tmpfs and used with `-n -o --bb=dumpbad -s <page*2048>
-l 2048 -f <file> /dev/mtd18`. Each sample is 2176 bytes (2048 main
plus 128 OOB). ECC failure count stayed at 10 throughout these *raw*
reads. All temporary binaries and raw sample files were deleted from
router tmpfs afterward; private copies are retained on Acer.

To undo the wrong BCH-4 driver's raw-output DMA scatter, split the 2176
bytes into a 2048-byte data buffer and 128-byte OOB buffer, then reconstruct
four consecutive 528-byte physical read segments. For each codeword
`i=0..3` concatenate:

- data `[516*i : 516*i+464]` (464 bytes)
- OOB `[12*i : 12*i+1]` (one bad-block-marker byte)
- data `[516*i+464 : 516*i+(500 if i==3 else 516)]`
- OOB `[12*i+1 : 12*i+(28 if i==3 else 12)]`

The actual NAND physical format is hypothesized to be 532 bytes per
BCH-8 codeword. At offsets `532*i` within the recovered physical
stream, the inferred main data are 452 bytes, followed by a one-byte
bad-block marker, then 64 data bytes (48 for the last codeword).
This yields 516+516+516+500=2048 source bytes to compare against the
factory backup. Interpreting the same stream as BCH-4 instead uses a
528-byte stride and 464+52 (last 464+36) main-byte split.

| ART page | BCH-8 reconstructed bytes matching backup | BCH-4 interpretation |
| --- | ---: | ---: |
| 2 | 2030 / 2048 | 1747 / 2048 |
| 3 | 2046 / 2048 | 1988 / 2048 |
| 4 | 2047 / 2048 | 2039 / 2048 |
| 16 | 2046 / 2048 | 1925 / 2048 |
| **Total** | **8169 / 8192** | **7699 / 8192** |

This quantitatively favors the BCH-8 codeword format on *four*
independent pages without any flash writes. It is not equivalent to
successfully decoding BCH-8 parity: there are still 23 mismatching
bytes across these samples. Some occur at DMA transfer boundaries;
their cause requires actual hardware with BCH-8 enabled. The
BCH-4-configured raw transfer fetches only 4×528=2112 of the
4×532=2128 BCH-8 physical codeword bytes, and cannot fully recover
the final codeword's parity. Do **not** assume that the measured raw
byte discrepancies are all genuine NAND wear or correctable ECC errors.

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
When testing, start by comparing pages 2/3/4/16 of the same ART
partition to the archived bytes and checking `ecc_failures` before/after.
Only then consider changing UBI policy or using NAND for a persistent root.

### After a supervised BCH-8 hardware boot

Run the source-controlled, read-only comparison deployed on **Asus**
(after the BCH-8 image `d72fd34a45` is actually running):

```sh
/home/jan/scripts/wave7/verify-factory-art.sh   /home/jan/firmware/wave7/reference/factory-art-20261028.bin   d72fd34a45
```

The 2 MiB reference is the exact private Oct 28 physical ART backup,
checksum-matched between Acer and Asus and stored with mode 0600.
The tool refuses unexpected kernel revisions, ECC strength other than
8, or an ART partition other than `mtd18 0:art`. It verifies all 27
SMEM partitions, reads pages 2/3/4/16 from the live device **without
writes**, compares to the exact private backup, checks ECC counters
before/after, and prints `ART_BCH8_FACTORY_MATCH=1` only for exact
matches with no additional ECC failures. It keeps temporary compare
files only under a temporary `/tmp/wave7-art-ecc-*` directory and
cleans them up on exit. Save the
command's stdout/stderr in the supervised trial's normal evidence
folder when it is finally used.

Private ART dumps, radio MACs and backup binaries are **not** part of
the public source tree. Experiment scratch is kept in
`/home/jan/projects/acer-wave7-firmware/work/nand-compat-20261109/`.
