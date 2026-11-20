# Acer Wave 7 — secondary-AP firmware role

Guard7 static hardware acceptance and client/wire validation passed.
Guard8 is the next role generation, adding explicit persistent approval
for autonomous subsequent boots. Do not flash until its separate guarded
trial and rollback harness are ready.
## Verified current images

Both derive from accepted source sysupgrade SHA256:
8ac5e0ee1319e88c7e4f81d22dd0ba70128111edcc4e7d4b153203e067c837fd
and preserve the exact accepted kernel FIT (SHA256):
9258ee2d5c2b9d154552d000fc8deb647bc85a02efc9c1086700736473757be4

- Isolated static lab: r0+38346-0fbc2cc77b-ap-static-guard7
  SHA256: see generated guard7 manifest
- Upstream DHCP managed: r0+38346-0fbc2cc77b-ap-dhcp-guard7
  SHA256: see generated guard7 manifest

Build artifacts on Acer:
  /home/jan/firmware/wave7/builds/secondary-ap-20261120/
Staged copies on Asus:
  /home/jan/firmware/wave7/trials/20261120-secondary-ap-guard7/

Both bridge four physical DSA ports, retain EHT MLO and all 46
SHA-pinned radio/diagnostic files, disable DNS, DHCPv4, DHCPv6, RA
and NDP proxy services, lock the root password, and allow only
existing key-based SSH access. Static mode uses 192.168.76.1/24
solely for isolated hardware testing; DHCP mode relies on an existing
upstream DHCP server and upstream IPv6 RA.

## Guard8 autonomous acceptance

A new image still requires the current-boot external SSH token. After
independent soak and client/wire acceptance, the operator explicitly runs
attest-management.sh --approve with router, revision, interface, source
IPv4, pinned known_hosts and verified boot UUID. The router requires
bootfail=0, keep marker, the original current-boot token and fresh local
health before atomically creating /overlay/wave7-ap-approved, root:root
0600. Its content binds the immutable manifest digest and revision,
including base image SHA and role builder commit. Different builds or
profiles cannot reuse approval. Subsequent approved boots still require
matching overlay policy, all five bridge members, all three Q6 domains,
both MLO links and no recorded NoC fatal, but do not require a cable or
an upstream DHCP lease. Static mode still requires its configured address.
Unapproved candidates remain fail-closed; no automatic promotion after
firstboot. The tested Guard7 trial-static.sh is historical and is not the
Guard8 trial harness.

## Boot gate

The accepted lab image is not modified. The current native OTA path
retains the independent ubi1:openwrt_data overlay EVEN with sysupgrade -n.
On the live original firmware, old standalone-router network, dhcp, system
configuration is present in /overlay/upper and shadows /rom defaults.
The AP role now mounts only the verified dedicated UBIFS volume in the
76 preinit_main hook after provisioning and before native mount_root.
It removes exactly role-owned upperdir overrides while OverlayFS is not
using that directory, unmounts the temporary UBIFS, then verifies the
merged files against /rom in the post-mount hook. Fresh volumes with no
upper directory are valid. Generated system configuration is not role-owned and survives migration.
Specific failed predicates and policy paths
are logged to the kernel console without recording secrets. Unrelated
UBIFS state and persistent SSH host identities are retained. The volatile
overlay-ready marker is created only after the merged check succeeds.
If anything fails, it BLOCKS service startup while the already-armed
hard firstboot watchdog enters recovery; never expose old DHCP/RA/SSH.
This profile is intentionally image-authoritative for its role-owned
network, Wi-Fi, service and SSH configuration on every boot. Persistent
UBIFS edits to those settings are discarded; change the source role
configuration and rebuild the image instead. Independent calibration,
boot environment state, UBI telemetry and SSH host identities survive.
The preinit policy is sourced strictly from /rom, never from inherited
upperdir files. The checks run before config generation and services.

The unapproved role's preinit acceptance function requires that overlay-ready
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

The independent Asus observer uses permanent 192.168.76.250/24 on
enp4s0f4u2u2u4, and the direct 2.5GbE peer uses permanent
192.168.76.2/24. Neither DHCP-assigned address is a prerequisite.
All supervisor SSH/SCP and the SSH attestor bind the management
interface and source IP; the router reports the actual authenticated
peer and both acceptance checks require it to match. This keeps the
management path independent of the AP's intentionally disabled DHCP
server. The existing vendor fallback collector remains observational.


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

1. Guard7 static passed native preflight, guarded trial, soak and wire/client tests.
2. Guard7 DHCP passed offline QA and on-router native preflight.
3. Guard8 source requires offline build QA and a new guarded trial.
4. Prepare a separate, upstream-DHCP-connected lab before deploying
   the DHCP-managed AP role.
   the DHCP-managed AP role.

Current state: https://app.notion.com/p/41df74be90208166a3acf2b79a58e36e
Dated worklog: https://app.notion.com/p/41ef74be902081b0837ccec7c3218452

Intermittent Q6 UMACNOC and direct 1G QCA8081 SGMII RX blackhole
remain separate production reliability risks.
