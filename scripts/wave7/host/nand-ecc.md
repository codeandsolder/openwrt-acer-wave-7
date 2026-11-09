# Wave 7 factory SPI-NAND ECC compatibility

The Wave 7's **current hardware-validated** Linux 6.18.60
`d72fd34a45` image uses **BCH-8 ECC per 512 bytes** for the GigaDevice
512 MiB SPI NAND (2 KiB page, 128-byte OOB, 128 KiB eraseblocks).
The previous working MLO image `cfb425bcad` inherited the vendor's
**BCH-4/512** setting. That geometry was wrong: the driver warned about
weak ECC and returned byte-corrupted factory data. The fix is a single
`nand-ecc-strength = <8>` board DTS change; the upstream QPIC
controller already supports BCH-8.

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

## Real hardware validation — PASS, 2026-11-09

The seventh guarded vendor OTA trial booted FIT revision `d72fd34a45`
on real IPQ5332 hardware at 16:35 CET. No custom controller changes
or experimental NAND writes beyond the normal vendor OTA were needed.

- `/sys/class/mtd/mtd18/ecc_strength` reported **8**.
- **All 27 physical SMEM partitions** matched the factory inventory
  by name, size and erase geometry.
- The source-controlled read-only `verify-factory-art.sh` compared
  pages 2, 3, 4 and 16 of current `/dev/mtd18` (`0:art`) against the
  2026-10-28 factory backup, with **four exact 2048-byte matches**.
- ECC counters went from **0 failures, 0 corrected bits** to
  **0 failures, 5 corrected bits**. The hardware corrected raw
  flash errors, producing exact factory data without any uncorrectable
  ECC failures.
- Kernel 6.18.60, procd/ubusd, wired LAN and peer 192.168.76.2,
  all three Qualcomm Q6 UserPDs and 2-link WPA3-SAE Wi-Fi 7 MLO
  (2412 and 5180 MHz) worked. The keep-boot marker was explicitly
  armed at uptime 93.7 seconds after these checks; the router
  remained online beyond 189 seconds.
- Full seventh-trial evidence, SHA-verified on **both Acer and Asus**:
  `/home/jan/firmware/wave7/logs/bch8-trial-20261109/`, particularly
  `art-verify.log`, `openwrt-capture.txt`, `supervised-flash.log`
  and `openwrt-watch.log`.

The working BCH-8 FIT is SHA256
`01c6a24ba77d05f0c032003bb6319bbdead918e864aa1ce86cb2de5e777e0d2e`.
The corresponding NAND-writing OTA is SHA256
`2581fc54b4c6b281dc02def9bfdad85d90a3201f2ee8861a879d08c550b220d8`.
They are stored separately in Asus `/home/jan/firmware/wave7/trials/`.
Functional source commit `d72fd34a45` is now part of the canonical
Wave 7 OpenWrt branch; later commits contain documentation and tools.

### Read-only UBI slot metadata — 2026-11-09

On the working BCH-8 kernel, read **only** the first two 128KiB PEBs
from each existing rootfs MTD device; no UBI attach was attempted.
The live `/proc/mtd` order is `mtd21=rootfs` and
`mtd22=rootfs_1` (use partition names, not assumed indices, when
automating later). Physical samples are stored privately at
`/home/jan/projects/acer-wave7-firmware/work/nand-compat-20261109/ubi-header-inventory/`.

All four EC headers have UBI# magic, version 1, VID offset 2048,
data offset 4096, and **valid UBI CRCs**. All four corresponding VID
headers have UBI! magic and **valid CRCs**; they are the two redundant
`layout volume` logical eraseblocks 0 and 1. The UBI volume table
records also have valid CRCs:

| Active MTD partition | EC count | Image sequence | wifi_fw PEBs | kernel PEBs | ubi_rootfs PEBs |
| --- | ---: | --- | ---: | ---: | ---: |
| rootfs (mtd21) | 91 | 758524c0 | 87 | 143 | 230 |
| rootfs_1 (mtd22) | 8 | 2736642e | 87 | 50 | 230 |

Volume types are static `wifi_fw` and `kernel`, dynamic
`ubi_rootfs`. The larger `kernel` allocation strongly suggests
`rootfs` contains the current OpenWrt FIT and `rootfs_1` remains
the vendor alternate, but **neither the bootloader's chosen slot nor
the complete logical volume contents were proven by these headers**.
ECC failures stayed at **0** for both samples; standby `rootfs_1`
reported 4 corrected bits. This confirms readable ECC-corrected UBI
metadata without scanning the entire NAND.

Importantly, CRC-valid UBI headers do not establish safe attach/write
behavior. UBI attach can mutate flash metadata and should not be used
as an incidental read-only diagnostic. Continue using raw partition
reads and header/VID verification while designing persistent boot.

### Repeatable read-only ART check

On Asus, with the matching BCH-8 firmware actually running, execute:

```sh
/home/jan/scripts/wave7/verify-factory-art.sh   /home/jan/firmware/wave7/reference/factory-art-20261028.bin   d72fd34a45
```

The private 2 MiB ART factory reference on Asus is mode 0600 and
checksum-verified against Acer's full 2026-10-28 NAND backup.
The checker rejects the wrong kernel, release, ECC setting or ART
partition **before reading NAND**. This negative guard was exercised
against `cfb425bcad` and returned 3 as intended.

This **does not** establish that a persistent NAND rootfs or
explicit UBI attachment is safe: UBI automatic attach stays disabled,
and the system still runs from initramfs. The next storage
investigation should validate the remaining NAND boot partitions,
read behavior of UBI volumes and bad-block metadata without erases
or rootfs migrations. External MT7925 MLO station association has
not yet been repeated with 6.18.60 because the test laptop is offline.

Private ART dumps, radio MACs and backup binaries are **not** part of
the public source tree. Experiment scratch is kept in
`/home/jan/projects/acer-wave7-firmware/work/nand-compat-20261109/`.
