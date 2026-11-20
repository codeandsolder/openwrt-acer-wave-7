# Acer Wave 7 — secondary-AP firmware role

Current status (2026-11-20): both authenticated AP variants are verified
offline, and the static-role Asus trial controller has passed live
accepted-baseline preflight. The router still runs the accepted
r0+38346-0fbc2cc77b lab image. Physical AP-role trial remains gated
on target-side sysupgrade -T -n validation and recovery assessment.

## Verified current images

Both derive from accepted source sysupgrade SHA256:
8ac5e0ee1319e88c7e4f81d22dd0ba70128111edcc4e7d4b153203e067c837fd
and preserve the exact accepted kernel FIT (SHA256):
9258ee2d5c2b9d154552d000fc8deb647bc85a02efc9c1086700736473757be4

- Isolated static lab: r0+38346-0fbc2cc77b-ap-static-guard4
  SHA256: see SHA256SUMS in the generated guard4 directory
- Upstream DHCP managed: r0+38346-0fbc2cc77b-ap-dhcp-guard4
  SHA256: see SHA256SUMS in the generated guard4 directory

Build artifacts on Acer:
  /home/jan/firmware/wave7/builds/secondary-ap-20261120/
Staged copies on Asus:
  /home/jan/firmware/wave7/trials/20261120-secondary-ap-guard4/

Both bridge four physical DSA ports, retain EHT MLO and all 46
SHA-pinned radio/diagnostic files, disable DNS, DHCPv4, DHCPv6, RA
and NDP proxy services, lock the root password, and allow only
existing key-based SSH access. Static mode uses 192.168.76.1/24
solely for isolated hardware testing; DHCP mode relies on an existing
upstream DHCP server and upstream IPv6 RA.

## Boot gate

The accepted lab image is not modified. The current native OTA path
retains the independent ubi1:openwrt_data overlay EVEN with sysupgrade -n.
On the live original firmware, old standalone-router network, dhcp, system
configuration is present in /overlay/upper and shadows /rom defaults.
The AP role's early preinit_mount_root hook therefore clears just the
inherited /etc/config/{network,dhcp,dropbear,wireless,firewall,system},
/etc/shadow and /etc/dropbear/authorized_keys upper entries after the
UBIFS pivot, before UCI config generation and service startup. It keeps
fw_env.config, ubootenv, ubihealthd and SSH host keys. It rejects symlinked/opaque overlay parents,
uses only lowerdir helpers, and checks that
all resulting live files match the role image's /rom originals and sets
the ephemeral /tmp/wave7-ap-overlay-ready marker only after success.
If anything fails, it BLOCKS service startup while the already-armed
hard firstboot watchdog enters recovery; never expose old DHCP/RA/SSH.

The role's preinit acceptance function requires that overlay-ready
marker AND a volatile token of the current
boot UUID and exact role revision. The external Asus
attest-management.sh connects with publickey-only SSH and verifies
root shadow, Dropbear policy, overlay-ready marker, bridge address, service policy, Q6 3/3,
MLO2, both Ethernet links, NoC0 and return ping before writing the
token. Only the existing preinit watchdog can commit bootfail=0.

The separate late-init failsafe previously used the fixed lab ping
and could touch the keep-boot marker if preinit failed to arm. That
path is now fail-closed in both role images; it retains hard recovery
but can NEVER accept the role image. Full negative tests cover this.
No competing watchdog is installed.

Unaccepted image recovery can boot the vendor slot; the vendor
observer records fallback but is NOT by itself a proven automatic
reinstaller for the accepted OpenWrt slot. Do not flash until that
hardware recovery outcome is known.

The external Asus trial-static.sh adapts the tested native OTA
supervisor. It pins exact current accepted OpenWrt rollback,
checks both images, both live Ethernet links, Q6, MLO, peer and
current firstboot status, arms observers, drives authenticated
candidate firstboot, and requires 300s continuous post-acceptance
health. Read-only --selftest, --check-baseline, and --check run before
any --run flash attempt.

## Source files

- stage-root.sh: derives role policy and patches both boot paths.
- role-firstboot.sh: boot/token contract.
- overlay-reset.sh: selective role-aware UBIFS upperdir reset.
- preinit-overlay-reset.sh: pre-service mount_root hook and fail-closed gate.
- attest-management.sh: external publickey-only SSH attestation.
- trial-static.sh: guarded native static-role trial on Asus.
- build-image.sh: deterministic native sysupgrade/SquashFS repacker.
- test-stage.sh: valid/invalid role and boot acceptance tests.

All scripts ShellCheck clean. Image packager verifies allowed root
changes, special /dev/console inode, roundtrip extraction, 46 firmware
files, unchanged kernel and fwtool/board metadata. It never contacts
the router and refuses output overwrites. Previous -ap-*-auth, -ap-*-guard2, -ap-*-guard3 and
unattested -ap-* variants are obsolete, not deployment candidates.

## Hardware acceptance

1. Exact target-side read-only sysupgrade -T -n for candidate and
   rollback remains unverified; remote execution guard blocked it.
2. Confirm unattended fail-to-accept fallback handling.
3. Test static AP under supervisor, key-only SSH and MLO client
   traffic, with independent packet capture showing no DHCP/RA.
4. Prepare a separate, upstream-DHCP-connected lab before deploying
   the DHCP-managed AP role.

Current state: https://app.notion.com/p/41df74be90208166a3acf2b79a58e36e
Dated worklog: https://app.notion.com/p/41ef74be902081b0837ccec7c3218452

Intermittent Q6 UMACNOC and direct 1G QCA8081 SGMII RX blackhole
remain separate production reliability risks.
