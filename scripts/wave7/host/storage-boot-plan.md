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

**Two production changes are required before a boot test:**

1. Build a **separate non-initramfs FIT DTB** without
   `root=/dev/ram0`, `rdinit=/init` and
   `ubi.no_autoattach=1`. Those flags are present in the
   original board DTS solely for the proven RAM-root trial;
   they would defeat the conventional squashfs-root boot.
   **Important:** built kernel has `CONFIG_MTD_UBI_BLOCK=y` but
   `CONFIG_MTD_UBI_GLUEBI=n`; vendor
   `root=mtd:ubi_rootfs` will not expose a SquashFS block device.
   Append `ubi.block=0,ubi_rootfs root=/dev/ubiblock0_2`
   (Linux's last `root=` wins), while retaining the vendor
   `ubi.mtd=rootfs` and `rootwait`. Validate this in the
   final FIT DTB; root must remain on the selected UBI slot.
   Preserve console, QPIC/BCH-8, watchdog, Wi-Fi autoprobe and
   all validated LAN/MLO configuration. Use a separate
   production branch so the tested FIT stays immutable.
2. Refactor the existing vendor OTA wrapper
   `/home/jan/projects/acer-wave7-firmware/Acer_Predator_T7c/wrap-openwrt-initramfs.sh`
   into a **proper image packager accepting both explicit
   kernel FIT and OpenWrt SquashFS root**. It currently hardcodes
   `ROOTFS=$BASE/extracted-ubi-067/...-ubi_rootfs.ubifs`,
   i.e. **the vendor root**, so reusing it unchanged would
   produce a mixed and non-bootable installation. Preserve
   `wifi_fw` unchanged, make the updated rootfs the UBI
   `ubi_rootfs` dynamic volume, and retain vendor FOTA format
   plus existing audit and rollback watchers.

The kernel is built with `CONFIG_MTD_UBI=y`,
`CONFIG_SQUASHFS=y` and `CONFIG_UBIFS_FS=y`.
After building the production artifact, verify the embedded FIT DTB's
bootargs, rootfs SquashFS metadata and the entire UBI volume
payloads *offline* before any hardware transition. The next supervised
OTA may replace the **active** rootfs slot while retaining the
untouched alternate vendor slot, but stock bootloader selection and
power-cycle rollback require dedicated verification first.
The BCH-8 initramfs FIT remains the known-good recovery baseline.

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
