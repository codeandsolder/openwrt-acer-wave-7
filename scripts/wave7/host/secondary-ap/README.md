# Acer Wave 7 — secondary-AP firmware role

Guard8 static hardware acceptance, 301-second soak and client/wire validation passed.
Persistent approval and an unattested reboot are the remaining static-role gates.
The Guard8 DHCP image is built, native-preflight-verified and staged; a
separate isolated upstream DHCP/RA service has been validated through
the static AP.
## Verified current images

Both derive from accepted source sysupgrade SHA256:
8ac5e0ee1319e88c7e4f81d22dd0ba70128111edcc4e7d4b153203e067c837fd
and preserve the exact accepted kernel FIT (SHA256):
9258ee2d5c2b9d154552d000fc8deb647bc85a02efc9c1086700736473757be4

- Isolated static lab: r0+38346-0fbc2cc77b-ap-static-guard8
  SHA256: b3c5c96ed47fb8ea4c9ea6fd726b499fe52b1391b6591b7016a349f296c35ec8
- Upstream DHCP managed: r0+38346-0fbc2cc77b-ap-dhcp-guard8
  SHA256: 3a84923c5c18b1f1354985de975a775e3fbea464fc69dbf8e086267f0b917172

Build artifacts on Acer:
  /home/jan/firmware/wave7/builds/secondary-ap-20261120/
Staged copies on Asus:
  /home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8/

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
firstboot. The Guard8 trial-ap.sh static mode uses accepted Guard7 static rollback;
DHCP mode uses the persistently approved Guard8 static rollback.
Trunk mode uses the approved Guard8 DHCP rollback and the independent
2.5G management path; the second SSH session must traverse the actual
RTL8367D switch. Both flash and approved reboot observers log CPU-port
MIB counters and restart the 300-second soak on any FCS/fragment change.
After explicit lab approval, <profile> --arm-reboot supports all three
profiles and arms read-only observers before a separately issued reboot.
DHCP and trunk reboot tests require an active upstream lease; this does
not change the router's autonomous no-lease acceptance policy.

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

The external Asus trial-ap.sh static|dhcp adapts the tested native OTA
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
- trial-ap.sh: shared guarded static/DHCP-role trial on Asus.
- lab-upstream.sh and lab-upstream.conf: one-hour-bounded isolated upstream
  DHCP/RA test service; fixed lease by bridge MAC, no default route/DNS,
  scoped changes cleaned up on stop.
- build-image.sh: deterministic native sysupgrade/SquashFS repacker.
- test-stage.sh: valid/invalid role and boot acceptance tests.

All scripts ShellCheck clean. Image packager verifies allowed root
changes, special /dev/console inode, roundtrip extraction, 46 firmware
files, unchanged kernel and fwtool/board metadata. It never contacts
the router and refuses output overwrites. Previous -ap-*-auth, -ap-*-guard2, -ap-*-guard3 and
unattested -ap-* variants are obsolete, not deployment candidates.

## Hardware acceptance

1. Guard7 and Guard8 static native boot, soak, wire and client tests passed.
2. Guard8 DHCP image passed offline QA and native preflight.
3. The isolated upstream lab provided a real IPv4 lease and IPv6 SLAAC
   address to the Wyse MLO client through Guard8 static; IPv4 5/5 and
   IPv6 4/5 pings. Verify loss-free sustained IPv6 forwarding separately.
4. Explicitly approve the known-good Guard8 static boot, then prove an
   unattended reboot with no volatile attestation token.
5. Start the isolated upstream service and run trial-ap.sh dhcp --check
   before guarded DHCP-role testing. Preflight requires an approved static
   rollback, active upstream, no existing router lease, and exact image
   digests. During soak require the expected bridge address and matching
   unexpired lease in the independent server's lease file.

Current state: https://app.notion.com/p/41df74be90208166a3acf2b79a58e36e
Dated worklog: https://app.notion.com/p/41ef74be902081b0837ccec7c3218452

Intermittent Q6 UMACNOC and direct 1G QCA8081 SGMII RX blackhole
remain separate production reliability risks.

## RTL8367D candidate reboot evidence

On an isolated lab with a currently healthy approved trunk image, use
trial-ap.sh trunk --arm-reboot then separately issue the ordinary reboot
through the direct peer. Wait for SOAK_PASS, archive the exact boot with
archive-trunk-run.sh RUN_DIR, and verify the evidence.sha256 manifest.
report-trunk-run.py distinguishes sampled corruption from an actual
driver re-latch warning. CLEAN_BOOT_NO_CORRUPTION_OBSERVED means that
this boot was clean; it is NOT evidence of correction of a reproduced
corrupt-only episode. Review the sample gaps and counter reset flags.

Optional bench-trunk.sh RUN_DIR performs the four bounded TCP sweeps
during an accepted boot and requires unchanged switch CPU-port errors.
This uses the known hashed temporary ARM64 iperf runtime. No persistent
package install; per-boot router files are deleted on exit. Raw
throughput JSON and evidence SHA stay in the run directory.

The `native` trial profile is the stock-derived internal recovery pulse
escalation candidate. It uses the same independent direct management
path and counter observer as `trunk`, but its exact approved rollback
is the previously accepted external-module trunk-health image. The
baseline gate pins that module's SHA, O taint, manifest, and builder.
The per-boot report also records the native pulse attempt, completion
and failure/pending-release warnings separately. Clean-boot results
must never be interpreted as a demonstrated recovery.

Trial sequencing: initialize the shared Jan-owned mode-0600 file
`$guard8/.lab-control.lock` once. The trial arming and disruptive wire
policy commands take this lock; the wire test also refuses any active
or activating trial/fallback observer. Do wire policy only after
SOAK_PASS, archive that run, and stop its completed fallback watcher.
The lab server is part of the guard's DHCP-health predicate: stopping
it during a live flash soak requests rollback even while the router
lease and Ethernet are healthy. Lab service/lease failures now have
distinct rollback reasons and preserve the triggering state.

### Read-only trunk recovery observation

On Asus, as Jan, run the installed `probe-trunk-recovery.py capture OUT EXPECTED_REVISION --duration 60` via `uv run --no-project --offline --python /usr/bin/python3 python`. OUT must be a new directory under the Guard8 `native-recovery-dhcp-guard8/observations/` directory. This observer generates concurrent low-rate source-bound ICMP on both independent paths; checks both policy routes every interval; takes boot-consistent CPU-port MIB/carrier/driver-event snapshots over the direct path. It makes no configuration changes and can span an operator-initiated reboot. The report distinguishes complete directional corrupt-only loss, other switch loss, copper-down, direct-path loss, counter discontinuity and unobserved intervals. It deliberately never claims causal recovery on a pulse log alone. SHA256SUMS covers metadata, raw JSONL and report. `selftest` runs synthetic known-fault and missing-sample cases. This is additional evidence, not a replacement for the guarded acceptance soak.

The independent lab DHCP/RA service retains its one-hour hard runtime
bound. Start collects the new transient unit even after normal expiry,
and retires the exact old failed timeout unit if needed; it rejects
active units, foreign fragments, other failure causes and uncollected
units. Run test-lab-upstream-lifecycle.sh for the mocked lifecycle
regression. Inspect expired-service diagnostics in the system journal.
The service is not a persistent network configuration.

Observer schema 2 records each route lookup before and after probes,
including failures, instead of terminating when a route disappears.
Invalid paths are skipped; no traffic is sent using an unexpected
route. Loss of direct routing, switch routing, carrier and MIB
confirmation are separately classified. A clean interval requires
advancing valid CPU-port ingress, both paths fully responsive and no
error increments. Baselines after lost samples are re-established, not
bridged across outages. Capture duration remains bounded, and the
loop is paced even if both paths are unavailable. Historical raw
samples with the old schema can still be analyzed without modifying
their sealed evidence.

The pinned `phy` profile is the QCA8081 0491 stock-status-poll FIFO
experiment, built from the approved native-recovery parent. Its
management/attestation path is the switch NIC (.250), with a separate
authenticated direct NIC (.2) session. Both paths must pass the initial
2.5G/1G acceptance and the native switch module remains pinned. The
candidate additionally requires the exact PHY patch/FIT manifest and
a runtime stock_status_poll marker; the approved rollback must have
neither. Direct carrier loss is not a permitted initial soak state.
A later matched 1G direct-port test requires a separate accepted-boot
diagnostic harness, not running a cable flap during the acceptance soak.
DHCP remains on the isolated direct port, with a five-minute lease;
verify adequate remaining lease before that later diagnostic.
