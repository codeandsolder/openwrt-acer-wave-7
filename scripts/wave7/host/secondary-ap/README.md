# Acer Wave 7 — dedicated secondary-AP firmware role

The accepted Acer Wave 7 hardware baseline is OpenWrt Linux 6.18.60,
r0+38346-0fbc2cc77b, verified on 2026-11-19 using native NAND
sysupgrade, firstboot watchdog and a 300-second Asus supervised soak.
That image intentionally operates as a standalone isolated lab AP:
it serves DHCPv4, DHCPv6, RA and DNS and accepts empty-password root SSH.
It must **not** be bridged into an ordinary production LAN unchanged.

This branch contains a different, explicit **image role** rather than
mutating the accepted lab source tree or overlay. Each variant repackages
the exact accepted kernel/FIT, preserves MLO, authorized keys, and all
private Q6/calibration blobs. A distinct release revision prevents
lab and secondary-AP images being confused by their supervisors.

## Role behavior

Both DHCP and static modes:
- Bridge all four verified ports (lan, lan1, lan2, game) and retain MLO.
- Disable dnsmasq and explicitly disable LAN DHCPv4, DHCPv6, RA and NDP.
  odhcpd may remain installed but has no advertising interface.
- Disable Dropbear password/root-password authentication; retain root
  public-key login on the management bridge. Lock the root shadow password
  with !, preserving all other account fields; disable SSH forwarding.
- Remove the ULA prefix and IPv6 prefix delegation for the bridge.
  No WAN/NAT or sole-router functionality is implied.

The 'dhcp' role uses an existing LAN DHCPv4 server for management, and
accepts upstream IPv6 RAs. This is the intended normal secondary-AP
mode; if the upstream DHCP server is absent, IPv4 management will not
be available. Arrange independent recovery and a role-aware guard
before deployment.

The 'static' role takes a caller-supplied management IPv4/CIDR and
does not add a gateway. 192.168.76.1/24 is only for the isolated Wave 7
lab, not ordinary LAN production where it may conflict.

## Offline build (from Acer)

Source image is never overwritten; all work is cleaned from a temporary
directory after execution. No root privileges, router access or NAND
writes occur.

~~~sh
r=/home/jan/projects/wave7-secondary-ap-profile
source=/home/jan/build/wave7/prod-integrated/bin/targets/qualcommbe/ipq53xx/openwrt-qualcommbe-ipq53xx-acer_wave7-squashfs-sysupgrade.bin
sha=8ac5e0ee1319e88c7e4f81d22dd0ba70128111edcc4e7d4b153203e067c837fd
out=/home/jan/firmware/wave7/builds/secondary-ap-20261119
export WAVE7_OPENWRT_BUILD_ROOT=/home/jan/projects/wave7-prod-integrated

"$r/scripts/wave7/host/secondary-ap/test-stage.sh"
"$r/scripts/wave7/host/secondary-ap/build-image.sh" "$source" "$sha" static "$out/static-lab" 192.168.76.1/24
"$r/scripts/wave7/host/secondary-ap/build-image.sh" "$source" "$sha" dhcp "$out/dhcp-managed"
~~~

The builder refuses existing output or wrong origin SHA, requires native
acer_wave7 board metadata, keeps the kernel byte-for-byte, verifies the
sole rootfs /dev/console device node, retains XZ/256KiB SquashFS settings,
enforces an allowlist of modified rootfs files, re-extracts the result
for byte-level comparison, and verifies all 46 firmware/diagnostic SHA
pins. Both variants include a distinct revision, source digest,
kernel digest, and human-readable report.

## Hardware acceptance for these variants

Do **not** use the ordinary lab-image trial supervisor unchanged. The
DHCP-managed variant requires an external DHCP server and an independent
management route. The static-lab variant requires static-IP clients for
tests because it intentionally has no DHCP/RA server.

Before flashing either variant: pass current router-side sysupgrade -T -n,
exact accepted rollback SHA, a new revision-aware Asus supervisor and
vendor observer, firstboot and client MLO traffic, and a separate wire
capture proving no DHCP/RA server is emitted.

The builder never flashes or reboots the accepted router.

- [Guarded integrated firmware hardware PASS](https://app.notion.com/p/41df74be902081368aa7f96ab6220581)
- [Production readiness gates](https://app.notion.com/p/41cf74be902081449f44f2150b08a3d0)

## Role-aware firstboot acceptance (2026-11-20)

The original firmware's preinit watchdog is not compatible with a DHCP-managed
secondary AP: it expects lab address 192.168.76.1 and pings fixed peer .2.
Worse, accepting mere carrier/reachability could lock in an inaccessible
key-only image. The authenticated variants address both failure modes.

- stage-root.sh patches only the role image's existing
  05_wave7_firstboot_watchdog function; it does not create another competing
  hard-recovery timer or modify the accepted lab source.
- Before the existing bootfail=0 acceptance function, the AP gate
  requires carrier, a management IPv4 address appropriate to static/DHCP
  mode, and an exact /tmp/wave7-ap-management-verified token holding
  the current boot UUID and current role image revision.
- The external Asus host must obtain actual successful SSH with publickey-only
  authentication; verify Dropbear policy, root password lock, all
  DHCPv4/DHCPv6/RA/DNS disable UCI settings, bridge state, Q6 3/3, MLO2,
  NoC0, and return-path ICMP; and only then write the volatile boot-specific
  token via attest-management.sh --run. It never commits bootfail directly.
- Missing/invalid/stale token cannot commit bootfail. At 90s the existing
  preinit watcher attempts acceptance; at 120s it rechecks, then follows
  its hard SysRq fallback path. A vendor fallback supervisor must be armed.
- The accepted lab image and its proven OTA supervisor remain unchanged.

Authenticated images have distinct revision suffix -ap-static-auth and
-ap-dhcp-auth. Previous ungated -ap-static and -ap-dhcp trial artifacts
are superseded and must never be flashed.

Authenticated static: Acer path
/home/jan/firmware/wave7/builds/secondary-ap-20261119/auth-static-lab
SHA256 01b04b06c6698e4bb0a53ce08026ca01922fb433a30bcfb8760d46d11da31c9c.

Authenticated DHCP: Acer path
/home/jan/firmware/wave7/builds/secondary-ap-20261119/auth-dhcp-managed
SHA256 b302e427d6178ccecc96a2337fdbf0e8d8b3c066402c0ac3d0b22fd80ad7e09c.

Both preserve the exact accepted kernel SHA
9258ee2d5c2b9d154552d000fc8deb647bc85a02efc9c1086700736473757be4.

Deployment gate: a revision-aware external Asus observer must perform
attestation early enough before the 120-second watchdog, with exact
SHA-pinned image validation, firstboot, real DHCP/RA wire capture,
recovery check and MLO client traffic. No automatic promotion.

## Guarded isolated-static AP trial controller

Source-only trial-static.sh adapts the hardware-proven Nov19 native sysupgrade
controller. This script is not a generic production-AP flasher. It pins both
the static-auth candidate SHA manifest and the *currently accepted*
r0+38346-0fbc2cc77b lab image SHA 8ac5e0ee..., and keeps Asus management
SSH/SCP on its independent 1GbE NIC. It requires stable baseline QCA8081 2.5G,
RTL8367D lan1 1G, MLO2, Q6 3/3, no current NoC, bootfail0 and the accepted
firstboot marker before allowing a trial.

The --watch mode continuously observes the new boot ID. During an unaccepted
static-auth candidate boot it periodically invokes attest-management.sh to
obtain key-only SSH access and verify the actual new image's UCI, shadow,
network and Q6/MLO state. On success the attestor writes a volatile token
bound to the new UUID/revision; the original preinit watchdog handles
bootfail acceptance. After acceptance the external observer requires 300
continuous seconds of health, and attempts native same-slot sysupgrade
rollback to the pinned original lab image if NoC/peer/radio/wired health fails.

If the role cannot get firstboot acceptance before the hard 120s deadline,
the existing kernel SysRq fallback may boot the vendor root, which the
separate passive vendor watcher records. This case is **vendor fallback,
not yet a demonstrated automatic reinstall of the accepted OpenWrt image**.
Do not treat the existing vendor observer as a restore service.

Commands after installing the tracked scripts to the Asus location
/home/jan/scripts/wave7/secondary-ap/:

  trial-static.sh --selftest
  attest-management.sh --selftest
  trial-static.sh --check-baseline   (read-only actual lab hardware)
  trial-static.sh --check            (read-only hash and baseline checks)
  trial-static.sh --run              (NAND writes; separately gated)

Do not use --run until actual router-side sysupgrade -T -n confirms
candidate and rollback, and a fail-to-accept vendor fallback recovery
procedure is ready. A static/lab peer is still required; DHCP-managed
role needs a separate upstream-DHCP-based supervisor.
