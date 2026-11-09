# Wave 7 — NAND storage and persistent OpenWrt boot

## Verified on hardware (2026-11-09)

- Current live OpenWrt 6.18.60 `d72fd34a45` uses BCH-8/512 on
  GigaDevice 512MiB SPI-NAND, enumerates all 27 factory SMEM partitions,
  runs wired LAN and two Wi-Fi 7 MLO links. Its **root is initramfs** and
  UBI auto-attachment is disabled. Do not disrupt it for unverified
  storage changes. SHA256 of its FIT:
  `01c6a24ba77d05f0c032003bb6319bbdead918e864aa1ce86cb2de5e777e0d2e`.
- Normal Linux MTD order **during this boot** is `mtd21=rootfs`,
  `mtd22=rootfs_1`, `mtd23=rootfs_overlay`,
  `mtd24=nanddata`. Factory dump from October 28 had different
  index ordering for the two rootfs slots: **always resolve by MTD
  partition name, never hardcoded index**.
- `rootfs` holds valid UBI volumes `wifi_fw` (static),
  `kernel` (static), `ubi_rootfs` (dynamic). Physical eraseblocks
  48..186 hold the **entire kernel static volume** (ID 1,
  LEB 0..138); all **139 EC-header CRCs, VID-header CRCs,
  payload CRCs and LEB sequences match**. Last LEB uses 40,960
  bytes. Reassembled logical payload is exactly **17,563,648
  bytes** and SHA256 identical to the running tested BCH-8 FIT.
  No UBI device was attached or NAND data altered for this proof.
- `ubi_rootfs` on both slots already contains **vendor SquashFS
  4.0/XZ** images: `rootfs` 28,942,855 bytes (4,099 inodes),
  `rootfs_1` 28,986,027 bytes (4,103 inodes), built
  2026-05-30 08:24:02 UTC. Neither contains an OpenWrt SquashFS
  root at present.
- Original full factory backup:
  `/home/jan/projects/acer-wave7-firmware/device-backup-2026-10-28/wave7-full-nand-2026-10-28.tar.zst`.
  Current read-only private samples and exact CRC/hash results:
  `/home/jan/projects/acer-wave7-firmware/work/nand-compat-20261109/ubi-header-inventory/`.

## Separate overlay and vendor data

- `rootfs_overlay` is a 402-PEB UBI partition (128KiB PEBs,
  126,976-byte LEBs), **zero bad blocks and zero ECC failures**.
  One-time read-only inventory of **every PEB header** found
  392 unmapped PEBs and 10 mapped PEBs: 2 layout copies
  (physical 166/168) and 8 data PEBs (volume 0).
  All EC/VID CRCs valid. The volume table is valid and contains
  **`rootfs_data`**, a dynamically allocated 318-LEB volume.
- Existing `rootfs_data` UBIFS superblock is on logical EB0
  (currently physical PEB170, not PEB169). UBIFS magic, node-type 6,
  4KiB superblock and CRC valid. Min I/O size 2,048 bytes,
  LEB size 126,976 bytes, current/max logical EB count 318,
  format version 5, LZO default compression. Its reserved capacity
  is **38.51 MiB**.
- There are **82 nominal physical PEBs outside its reservation and
  UBI's two layout PEBs**, before bad-block and wear-leveling reserves.
  That may support a separate `openwrt_data` UBIFS volume without
  shrinking or replacing vendor `rootfs_data`. Do **not** assume
  all 82 can be allocated; calculate actual available LEBs from
  `ubinfo` after a deliberately supervised UBI attachment.
- `nanddata` is actively populated with many mapped UBI volume-0
  blocks and is **not spare space**. Do not overwrite it.
- Explicit UBI attachment may update on-flash metadata; the work above
  did **not** attach, format, erase, create, resize or write any
  MTD/UBI partition.

## Preferred: conventional NAND SquashFS system

The stock U-Boot environment uses `bootcmd=bootipq`, and the
currently injected boot arguments include
`ubi.mtd=rootfs root=mtd:ubi_rootfs rootfstype=squashfs rootwait`.
The standard OpenWrt device recipe already produces a **normal
non-initramfs kernel FIT** and a **SquashFS root** in the
`squashfs-sysupgrade.bin` tar. The verified build's members:

- `sysupgrade-acer_wave7/kernel` — 4,937,520 bytes.
- `sysupgrade-acer_wave7/root` — 10,672,128 bytes, SHA256
  `571eea22e38f76978673012f21ae3c54fe5351604a9034f76a1cf542f7865b4f`,
  a 4KiB-padded version of `root.squashfs` (10,671,312 bytes).
- The wrapper's 230-LEB `ubi_rootfs` capacity comfortably holds
  the new root, and its minimum 50-LEB `kernel` reservation
  accommodates the normal FIT. The vendor alternate slot
  `rootfs_1` can remain untouched.

**The two production image changes are now implemented on branch
`wave7-nand-squashfs`, source revision `357d285920`:**

1. Built a **separate non-initramfs FIT DTB** without
   `root=/dev/ram0`, `rdinit=/init` and
   `ubi.no_autoattach=1`. Those flags are present in the
   original board DTS solely for the proven RAM-root trial;
   they would defeat the conventional squashfs-root boot.
   **Important:** built kernel has `CONFIG_MTD_UBI_BLOCK=y` but
   `CONFIG_MTD_UBI_GLUEBI=n`; vendor
   `root=mtd:ubi_rootfs` will not expose a SquashFS block device.
   Append `ubi.block=0,ubi_rootfs root=/dev/ubiblock0_2 rootwait=90`
   (Linux's last `root=` wins), while retaining the vendor
   `ubi.mtd=rootfs` and `rootwait`. Validate this in the
   final FIT DTB; root must remain on the selected UBI slot.
   Preserve console, QPIC/BCH-8, watchdog, Wi-Fi autoprobe and
   all validated LAN/MLO configuration. Use a separate
   production branch so the tested FIT stays immutable.
2. Added a source-controlled replacement for the existing vendor OTA wrapper
   `/home/jan/projects/acer-wave7-firmware/Acer_Predator_T7c/wrap-openwrt-initramfs.sh`
   as `scripts/wave7/host/pack-nand-ota.sh`. It accepts the
   normal OpenWrt sysupgrade tar, private vendor assets and an
   output directory. It extracts the paired OpenWrt FIT and SquashFS,
   keeps the exact known-good vendor `wifi_fw`, writes a dynamic
   `ubi_rootfs` volume containing **OpenWrt**, and wraps the whole
   UBI image using the proven vendor FIT/TLV format. The old wrapper
   hardcoded the vendor root and must not be used for NAND-root.
   The firstboot Wi-Fi deferral has also been moved after the
   writable overlay pivot on NAND SquashFS boots while preserving
   the proven initramfs path.

The kernel is built with `CONFIG_MTD_UBI=y`,
`CONFIG_SQUASHFS=y` and `CONFIG_UBIFS_FS=y`.
After building the production artifact, verify the embedded FIT DTB's
bootargs, rootfs SquashFS metadata and the entire UBI volume
payloads *offline* before any hardware transition. The next supervised
OTA may replace the **active** rootfs slot while retaining the
untouched alternate vendor slot, but stock bootloader selection and
power-cycle rollback require dedicated verification first.
The BCH-8 initramfs FIT remains the known-good recovery baseline.

## Built production candidate (not hardware-tested), 2026-11-09

- Experimental source branch `wave7-nand-squashfs`, functional commit
  `357d285920`. Six sccache-backed build stages **PASS**.
  OpenWrt release `r0+38211-357d285920`; normal sysupgrade TAR
  SHA256 `ad000b5ca657fb89c00fe4129ef7ec660d6d6906771889715b733898f9c7e3e5`.
- Non-initramfs kernel FIT **4,936,252 bytes**, SHA256
  `344c86d67b21bdda0cdcea66112e3c471c1a7590597f529c58bcb6f26466e419`.
  OpenWrt SquashFS **10,672,128 bytes**, SHA256
  `71a1afc8ce9ca9a0d56d4bfcdb4be51c77932ff932fa33751db970c68bb79385`.
- Output vendor OTA **22,547,328 bytes**, SHA256
  `89d05e6a4a30e75c613ee65c0eecf54b07ec188c28a87d5f2cb02679a28176fd`.
  Checksum-matched on Acer and Asus at
  `/home/jan/firmware/wave7/trials/production-357d285920-20261109/wave7-nand-squashfs-vendor-ota.bin`
  with `manifest.txt` and `audit.txt` alongside.
- Offline verification of the actual OTA: TLV MD5 and FIT payload
  boundaries valid, exactly **172 physical UBI eraseblocks**,
  all EC/VID headers and static data CRCs valid. Reassembled volumes
  byte-for-byte match their inputs: `wifi_fw` 46 LEB,
  `kernel` 39 LEB, `ubi_rootfs` 85 LEB (remaining dynamic
  padding 0xFF). The FIT-embedded 27,314-byte DTB has
  BCH-8/512 and `ubi.block=0,ubi_rootfs root=/dev/ubiblock0_2
  rootwait=90`, no ramdisk root override or
  `ubi.no_autoattach=1`. The SquashFS itself contains the correct
  release revision and NAND preinit post-overlay Wi-Fi deferral.
- **Still untested on hardware**. Current running 6.18.60
  BCH-8 `d72fd34a45` remains intact on initramfs, both MLO links
  and all three Q6 processors running, no ART ECC errors; known-good
  FIT on Asus SHA256
  `01c6a24ba77d05f0c032003bb6319bbdead918e864aa1ce86cb2de5e777e0d2e`.
  Do not claim persistent boot before a guarded trial. A success
  check must inspect the actual root mount (SquashFS
  `ubiblock0_2`), all 27 factory MTD partitions, LAN, Wi-Fi
  and preserved alternate vendor boot slot before keep-boot.
  The production preinit watchdog now enforces a matching
  mountinfo major:minor on `/rom` and rejects any mounted
  vendor UBIFS while deciding whether to set the keep-boot marker.
  The proven initramfs boot path is unaffected.

## First native NAND-root hardware boot — PASS, 2026-11-09

The production firmware was built from functional commit `98b9123f64`
(release `r0+38213-98b9123f64`) and successfully installed using
the original guarded vendor update harness. It was checked on real
Acer Wave 7 IPQ5332 hardware, **not merely offline**.

- **Firmware OTA:** 22,547,328 bytes, SHA256
  `aa0fd9245a6181306d99efdb3a59d2e6f68756637011b89829569a5105e6610a`.
  Staged and checksum-matched on Acer and Asus at
  `/home/jan/firmware/wave7/trials/production-98b9123f64-20261109/`.
  Offline audit verified all 172 UBI EC/VID headers and per-static-LEB
  CRCs; volume0 vendor wifi_fw (46 LEB), volume1 OpenWrt FIT
  (39 LEB), volume2 OpenWrt SquashFS (85 LEB) matched their inputs
  byte-for-byte. Embedded FIT DTB sets BCH8, UBI block volume2,
  rootwait=90, and the mount-gated fallback watchdog.
- Stock vendor Linux **5.4.213** reappeared after a normal OpenWrt
  `ubus call system reboot`. Its bootfail counter naturally
  cleared from 1 to 0; then the existing guarded updater accepted
  the production OTA, armed bootfail=4, staged and flashed it.
  Both independently supervised boot/recovery observers were active.
- On the production boot, `/rom` was **SquashFS, major:minor
  254:0**, exactly matching `/sys/class/block/ubiblock0_2/dev`.
  Root `/` is an OpenWrt disposable **RAM overlay**, with
  **no vendor UBIFS mounted**. `ubi0` shows volume IDs 0/1/2.
  Unlike the earlier working image, this is genuinely booted from
  the physical NAND UBI SquashFS root instead of an initramfs.
- The independent Asus-side `verify-nandroot-live.sh` accepted
  root, release, all 27 MTD partitions, BCH-8 ECC, wired peer,
  three Qualcomm Q6 processors, and **both MLO links** at uptime
  **98.64 seconds**. The keep-boot marker had been armed by the
  on-router root-validated watchdog before this acceptance;
  it was independently reasserted at 104.58s. Zero ART
  uncorrectable ECC failures.
- Independent standard observer confirmed
  `NAND_SMEMPART_READY=1`, `RADIO_MLO_READY=1`,
  `PEER_REACHABLE=1`, `KEEP_BOOT_ARMED=1`.
  Router remained online beyond **166 seconds**, past the
  120s failsafe.
- Complete trial evidence checksum-mirrored on Acer and Asus in
  `/home/jan/firmware/wave7/logs/nandroot-trial-20261109/`:
  `supervised-flash.log`, `nandroot-acceptance.log`,
  `openwrt-capture.txt`, both watcher logs and
  `trial-outcome.txt`.
- Source branch `wave7-nand-squashfs` is kept distinct from the
  established BCH-8 *initramfs* `wave7-current-openwrt`
  recovery branch until writable persistence is implemented.

**Remaining:** This proves *persistent read-only NAND root*
and Wi-Fi/LAN boot, **not persistent configuration writes**:
the current OpenWrt `/overlay` is temporary RAM. The vendor
`rootfs_data` UBIFS must remain intact. Next create a dedicated
`openwrt_data` volume after backing up current `rootfs_overlay`
and determining UBI available LEBs; integrate its mount into OpenWrt
native fstools and validate reboot/power-cycle behavior. Verify
the alternate vendor `rootfs_1` still matches its archived
baseline before attempting these operations.

## Dedicated persistent overlay — hardware-provisioned 2026-11-09

After checksum-verifying the complete live 52,690,944-byte
\`rootfs_overlay\` raw NAND partition, a **zstd-compressed recovery
snapshot** was saved on Acer at
\`/home/jan/projects/acer-wave7-firmware/device-backup-2026-11-09/rootfs_overlay-mtd23-bch8-20261109.raw.zst\`
and independently checksum-mirrored to Asus
\`/home/jan/firmware/wave7/backups/2026-11-09-rootfs-overlay/\`.
The exact raw backup SHA-256 is
\`22df4c4dce72aeb47eacee136d34fd8925a0f604b15dd70fd746dd59a888a8de\`;
zstd round-trip, live NAND re-read, and both copies were verified.

Attaching mtd23 \`rootfs_overlay\` with the default UBI bad-block
limit (20 per 1024 full-chip blocks) reserved **80 PEB**, leaving
**0 free LEB**. Linux 6.18 uses the full **4096-PEB flash chip**
for this calculation, *not* the 402-PEB MTD partition; it
over-reserves when applied independently to each partition.
Detached and reattached UBI1 with an explicit limit
\`ubiattach -d 1 -m 23 -b 4\`, reserving **16 PEB**
(equivalent to 4% of this particular MTD) and exposing
64 allocatable LEB. Existing vendor
\`rootfs_data\` (ubi1 volume0) remains **318 LEB**, intact.

Created **\`openwrt_data\`** as new dynamic
\`ubi1_1\` with **56 LEB = 7,110,656 bytes**
(6.78 MiB), leaving 8 free physical LEB beyond internal
and bad-block reserves. The kernel's UBIFS driver initialized the
empty volume when first mounted read/write. Created the standard
\`upper\` and \`work\` directories, wrote/verified/synced a
persistence marker, and unmounted cleanly. Zero bad NAND blocks
and zero uncorrectable ECC failures, both vendor and new volumes
verified by name and allocation. All prior vendor UBI data was
left in place.

**Pending the new boot build:** production board DTB appends
\`ubi.mtd=rootfs_overlay,0,4,1\` (explicit UBI1 attach) and
\`fstools_overlay_name=openwrt_data\` to make normal
\`mount_root\` find only OpenWrt UBIFS. The root-gated watchdog
requires \`/rom\` SquashFS from \`ubiblock0_2\` and
\`/overlay\` UBIFS specifically from \`ubi1:openwrt_data\`,
rejecting any other UBIFS mount. The rootfs overlay filesystem
must be confirmed persistent across reboot before retaining this
new firmware build.

## Persistence for mutable configuration

The conventional SquashFS root is immutable by design. Consider a
dedicated `openwrt_data` UBIFS volume within `rootfs_overlay`,
leaving the vendor `rootfs_data` volume intact. **Do not**
silently mount the vendor volume as OpenWrt upperdir.
OpenWrt `fstools mount_root` supports a named overlay
(`fstools_overlay_name` kernel argument), but the standard
`80_mount_root` preinit hook is skipped when
`INITRAMFS=1`. That is another reason to use a proper NAND
SquashFS root, and to test explicit attachment and volume discovery
before enabling the overlay.

Recommended progression: first boot a conventional OpenWrt
SquashFS root with disposable tmpfs overlay and retain watchdog
fallback; only after successful boot, verify backup of the existing
`rootfs_overlay` partition, attach its UBI device, calculate
available LEBs, create a separately named OpenWrt UBIFS volume,
and integrate it with the native early mount pipeline. A valid
raw UBI header **does not** prove attach/write safety.


## Trial boot and bounded root discovery

The production DTS explicitly uses `rootwait=90` to override the
factory's otherwise unbounded `rootwait`. Linux 6.18 accepts a
numeric rootwait timeout and proceeds to a kernel panic on missing
`/dev/ubiblock0_2` after at most 90 seconds of waiting. The
existing `panic=10` reboot and vendor bootfail recovery path should
then return to the stock slot without an infinite wait. This
covers mount-device absence, **not** a controller/MTD kernel hang;
the existing bootloader/watchdog and supervised recovery remain
required.

For the first production trial, do not arm keep-boot merely on LAN:
verify `/proc/mounts` shows a SquashFS root from the
`ubiblock0_2` device, the UBI device has the expected volume
contents, and the `rootfs_overlay`/vendor `rootfs_data` was not
reformatted or mounted as OpenWrt upperdir. Then verify normal LAN,
all three Q6 remoteprocs and both MLO links before retaining the
boot. Continue using temporary overlay until the separate
`openwrt_data` UBIFS strategy has been tested.
