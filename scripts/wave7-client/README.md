# MT7925 ROC test kernel module for the Wave 7 lab

The minimal Arch/CachyOS test client (Dell Wyse 5470, eMMC boot, MT7925 PCIe)
encountered a verified Linux NULL dereference at
`mt7925_mgd_prepare_tx+0x64` after mac80211 removed MLO link 1 and
wpa_supplicant subsequently deauthenticated. Previous-boot journal:
2026-11-10 09:29:34 removed=0x2; 09:35:34 RIP at `mt7925_mgd_prepare_tx`,
CR2=0, RAX=0. This is separate from the Wave 7 AP's ath12k reload panic.

## Upstream source

- Base: Linux `v7.4-rc1`, commit `6628e7d4c6b25c8d18f1345e3a20d21829aae7e4`.
- Patch: James-LY Huang, **2026-11-06 [PATCH v2 4/9]**,
  "wifi: mt76: mt7925: harden the ROC channel-grant handshake":
  https://lore-kernel.gnuweeb.org/linux-mediatek/20261106083004.3156085-5-james-ly.huang%40mediatek.com/T/
- The adjacent `was_assoc` early returns in **both** `mgd_prepare_tx` and
  `mgd_complete_tx` skip redundant ROC operations during associated
  deauthentication; the patch also fixes ROC token ownership and stale grants.
- `mt7925-roc-v2-20261106.patch` contains the two-file upstream changes.
  No unrelated driver or mac80211 modifications.

## Rebuild and install for this exact installed test kernel

On the client, install matching `linux-cachyos-rc-headers`, `make`, and
`clang` for `7.4.0-rc1-2-cachyos-rc`. Only build for the **exact** running
kernel/headers; do not reuse the resulting module across kernel upgrades.

1. Sparse-clone Linux `v7.4-rc1`, select
   `drivers/net/wireless/mediatek/mt76`, and apply the patch at repo root.
2. Build from the client (source can be copied from Acer) using:

   ```sh
   kver=$(uname -r)
   src="$HOME/projects/mt7925-roc-7.4/drivers/net/wireless/mediatek/mt76/mt7925"
   out="$HOME/build/wifi7-mt7925-7.4rc1"
   mkdir -p "$out"
   make -C "/usr/lib/modules/$kver/build" M="$src" MO="$out" LLVM=1 -j2 modules
   modinfo "$out/mt7925-common.ko"
   ```

3. Verify `vermagic` exactly matches running `uname -r`; verify signature
   enforcement is disabled. Install only the patched **core module** as a
   version-local override (do not overwrite distribution packages):

   ```sh
   sudo install -d "/usr/lib/modules/$kver/updates/mt7925"
   sudo install -m 0644 "$out/mt7925-common.ko" \
     "/usr/lib/modules/$kver/updates/mt7925/mt7925-common.ko"
   sudo depmod -a "$kver"
   modprobe --show-depends mt7925e
   ```

4. Reboot to load it without disconnecting a live MLO association. Confirm
   `/sys/module/mt7925_common/srcversion` equals the built module's
   `modinfo srcversion`. The first tested build was `DB4C3E1671DC2EA009803A0`.
   Ethernet management on `eno1` remains independent of Wi-Fi.

To revert, remove **only** the version-local
`/usr/lib/modules/$kver/updates/mt7925/mt7925-common.ko`, run
`sudo depmod -a "$kver"`, then reboot. The signed original
`kernel/drivers/net/wireless/mediatek/mt76/mt7925/mt7925-common.ko.zst`
remains intact.

Detailed test outcomes, MLO reconnect logs, radio widths and the AP's separate
reload panic are maintained in the project's Notion technical journal.
