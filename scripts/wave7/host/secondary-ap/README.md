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
- lab-upstream.sh and lab-upstream.conf: explicitly stopped isolated upstream
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

The independent lab DHCP/RA service has no runtime expiry. It remains
active until stopped explicitly, the interface scope changes, the child
exits, or the host shuts down. The service still binds to the isolated
lab interface and removes its owned address and firewall rule on exit.
Start collects the transient unit and retires the exact old failed timeout
unit if needed; it rejects active units, foreign fragments, other failure
causes and uncollected units. Run test-lab-upstream-lifecycle.sh for the
mocked lifecycle regression. The service is not enabled at host boot and
does not change persistent network configuration.

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

The `probe-phy-reconnect.py` observer targets either approved
0491 or 0492 candidate after initial soak (`capture --profile 0491`
or `--profile 0492`). It captures switch-bound SSH GMAC
MIBs, kernel-owned PHY edge-window logs, switch error counters, peer
NIC counters and separately route-verified probe bursts. It neither
changes links nor consumes PHY clear-on-read registers. A valid
classification needs observed carrier down/up, fresh same-edge PHY
samples and 30 seconds of contiguous post-up 1G evidence. It
distinguishes a 2.5-to-1G transition from a true 1G reconnect; an
expired log window does not erase earlier measured episodes.
Live 0491 evidence confirmed a successful 2.5G-to-1G transition and a
bidirectional datapath stall after genuine same-speed autoneg restart.
The 0492 observer additionally requires same-edge stock-relink policy
and commit log markers, host speed, and healthy pre-edge traffic.
A full-prepare reconnect is classified separately, not a preservation pass.
The pinned `relink` image changes only PCS/PPE modules and identity
files over 0491. Its rollback retains the exact 0491 PHY manifest and
marker; the guard validates both candidate module identities before
attestation.
The existing initial acceptance supervisor is independent of this
experimental read-only observer.

Offline `report-client-scans.py PING_LOG IW_EVENT_LOG` reports complete
association and scan intervals, estimated per-reply send/receive
overlap, and missing sequence numbers with nominal cadence estimates
(not measured send timestamps). It is a separate diagnostic, not a
replacement for the loss-free client gate. The Nov20 instrumented
capture spent 13.253810 of 28.758080 associated seconds scanning;
IPv4 observed-overlap RTT avg31.564ms vs8.71ms outside, but the missing
seq20 nominally started after scan end, and all IPv6 exchanges occurred
after the scan (including the 1037ms burst). Scan overlap is not proof
of a cause or evidence of continuous radio off-channel dwell.

The reconnect classifier records a second directional signature only
when host GMAC TX frames advance but PHY external-MAC ingress and its
error counters do not. PHY TX statistics are external-MAC ingress,
not proof of copper transmission; neither a flat counter nor a
successful forced carrier flag proves SerDes synchronization.

### Deliberately delayed first copper link — 0498

On Asus the dedicated RTL8156B direct peer is `enp4s0f4u2u4`
(MAC 00:e0:4c:68:00:6d, USB 6-2.4:1.0). An administratively down
netdev is not a powered-down PHY: the 09:04 trial observed early
router carrier and later relink despite a 69-second admin-down hold.
The root-only `peer-phy-power.py` uses the driver's Clause 22
MII ioctl, BMCR.PDOWN, and readback, leaving the USB device and
netdev present. An independent short warm test confirmed actual
router carrier-down/up. Do not use the USB hub port controls.

Renew the scoped lab DHCP service before a long trial if needed.
From cold-storage as the ordinary user, use the configured root
SSH alias, with no local sudo:

```sh
ssh -o BatchMode=yes -o ConnectTimeout=5 root@asus '/home/jan/scripts/wave7/secondary-ap-guard8/peer-1g-window.sh --start delayed'
```

Then on Asus as jan run the normal 1G guard:
`trial-ap.sh serial-speed --reboot-1g`, after
`peer-1g-window.sh --check` passes. The transient peer unit verifies
a healthy initial 1G link, waits for reboot carrier loss, powers
down the PHY and checks BMCR and BMSR repeatedly for 65 seconds,
then powers up and returns the advertisement to 1G. Its independent
15-minute deadline and ExecStopPost restore the original 2500
advertisement, including on failure.

After SOAK_PASS, archive the run and capture at least 35 seconds
of both independently route-bound probe paths with
`probe-phy-reconnect.py capture OUT BOOT --duration 40 --profile 0498`.
Save only the matching invocation's PEER journal records, then run
`report-cold-1g.py qualify RUN CAPTURE PEER_LOG --expect delayed`.
The qualifier requires the first router PHY observation to be
down during the verified power hold, a first 1G SGMII up at least
35 seconds after boot and at least 20 seconds after the first poll,
exactly one up edge and one serial-speed marker, valid clock
alignment, advancing PHY/GMAC counters, clean two-path traffic and
a minimum 300-second healthy soak. The old admin-down logs are
not sufficient evidence for this qualification. Stop the completed
fallback observer and peer service only after sealing the evidence.

### MT7925 delayed scan interruption experiment (client-only)

The 50 ms timing probe is a diagnostic, not a relaxation of the existing
wireless acceptance criteria. The isolated Wyse keeps its Ethernet SSH
management and original August 2026 firmware. `client-sustained.sh
0498-YYYYMMDD-HHMMSS --scan-timing` retains both MLO links, the normal
NetworkManager background-scan policy, and the 250 ms immediate gate. It
requests active/passive single-channel scans on 2412/5180 MHz and sends
3000 probes at 50 ms on each of IPv4/IPv6 wired-peer and AP-local IPv4.

The experimental `mt7925-single-channel-nosplit-test.patch` is **not a
general fix**. It omits Connac `SCAN_FUNC_SPLIT_SCAN` (bit 5) only on the
MT7925, station-mode, associated, at least two valid MLO links, exactly
one requested channel. Otherwise the request remains unchanged. It logs
the actual branch's frequency, scan mode, BSS and valid/active link masks.
The automatic multi-channel background scans remain internal controls.

Exact baseline: Linux v7.4-rc1
`6628e7d4c6b25c8d18f1345e3a20d21829aae7e4`, plus the November 6 ROC repair
tracked in commit `79c2e660a8`. The client headers/config/vmlinux/
Module.symvers are copied from its installed 7.4.0-rc1-2-cachyos-rc
header package; Acer's managed clang/sccache then builds baseline and
candidate from the same tree and compiler (clang23.1.5; original module
built on clang23.1.4). The baseline source version matches the installed
one exactly; the binary hashes differ. Compare the rebuilt baseline
live before the candidate to control for compiler/build environment.

Scoped build workspace on Acer:
`/home/jan/build/wave7/mt7925-single-channel-split`. Retrieve the exact
mt76 directory from the official Linux commit, apply the tracked ROC
repair, and build the common module:

```sh
make -C "$root/headers" \
  M="$root/source/drivers/net/wireless/mediatek/mt76/mt7925" \
  MO="$root/baseline" LLVM=1 CONFIG_MT7925E=n CONFIG_MT7925U=n -j2 modules
```

Preserve the rebuilt baseline module, apply only the no-split patch and
rebuild incrementally with the same command. Verify BTF, vermagic,
imports/exports, modinfo and Module.symvers. Do not override managed
compiler wrappers or introduce a new sccache instance. The original,
rebuilt baseline and candidate artifacts are pinned by SHA256 inside
`client-module-ab.sh` and kept in the explicitly scoped test bundle.
The script checks the running kernel/module, device, disconnected
lab profile and wired management. It atomically replaces only the
existing version-local **already ROC-repaired** common module, not the
distribution package; it has stage-baseline, stage-nosplit, check and
restore modes. Each stage needs a normal test-client reboot and
independent boot/version verification. Restore to the exact original
module after the A/B; preserve the November ROC crash repair.

Offline reports:
```sh
uv run --offline --no-project --python /usr/bin/python3 python report-client-scans.py \
  steady-v4.txt events.txt --additional-ping steady-v6.txt \
  --additional-ping steady-ap-v4.txt --interval .05 \
  --requests scan-requests.txt > shared-scope-report.json
uv run --offline --no-project --python /usr/bin/python3 python report-postscan-timing.py \
  shared-scope-report.json > postscan-arrival-timing.json
# Candidate only: match unique driver diagnostic markers to the actual scans.
uv run --offline --no-project --python /usr/bin/python3 python report-nosplit.py \
  shared-scope-report.json postscan-arrival-timing.json nosplit-markers.txt
```

The immediate streams still use `--interval .25`. The timing report
merges actual reply epochs, so late/out-of-order replies cannot inflate
a shared silence. It separates isolated unattributed multi-channel scans.
Outstanding notices are not packet transmission timestamps. Repeated
notices are preserved while packet loss is determined by actual final
reply sequences. A candidate marker attests branch selection before the
MCU request, not firmware acceptance or internal state.

### MT7925 MLD-wide absence credits (experimental full-stack ABI)

The vendor absence event 0x29 declares BSS availability and a quota.
MediaTek gen4m `isNetAbsent()` tests the complete active MLD's BSS
bitmap, not just the primary WCID's BSS. Keep ordinary MLD data
admission unrestricted while another active member is present. This
policy does not claim that the other member can actually deliver RF
traffic; the long scan-related outage is a separate failure to test.

Apply `mt7925-client-mld-absence-quota.patch` on top of the ROC repair,
event, absence, and binding trace patches (the `trace-source` tree).
The new hooks change common mt76 data structures and the shared ABI:
**never install just the candidate common module**. Make a separate
source copy `quota-source` and build the complete dependency closure
from the original Wyse headers, using the existing managed LLVM and
sccache configuration:

```sh
make -C "$root/headers" \
  M="$root/quota-source/drivers/net/wireless/mediatek/mt76" \
  MO="$root/quota-build" LLVM=1 CONFIG_MT76_CORE=m CONFIG_MT76_USB=m \
  CONFIG_MT76_SDIO=n CONFIG_MT76x02_LIB=n CONFIG_MT76x02_USB=n \
  CONFIG_MT76x0_COMMON=n CONFIG_MT76x2_COMMON=n CONFIG_MT7603E=n \
  CONFIG_MT7615_COMMON=n CONFIG_MT7915E=n CONFIG_MT7921_COMMON=n \
  CONFIG_MT7996E=n CONFIG_MT76_CONNAC_LIB=m CONFIG_MT792x_LIB=m \
  CONFIG_MT792x_USB=m CONFIG_MT7925_COMMON=m CONFIG_MT7925E=m \
  CONFIG_MT7925U=m -j2 modules
```

`test-mld-absence.c` compiles against the actual new inline policy
with the managed C compiler, `-Wall -Wextra -Werror`, and include path
`$root/quota-source/drivers/net/wireless/mediatek/mt76` (see source for
required standard C headers). Preserve the executable in quota-build.
`replay-mld-absence.py` independently reconstructs uncapped descriptor
admissions from a sealed baseline trace and exercises the same C code;
this is fixed-arrival replay, not a queue latency simulator.

Use `client-module-stack.sh quota --check-original`, then root `client-module-stack.sh quota --activate`
on Wyse. Pin the entire PCI dependency closure (mt76, mt76-connac-lib,
mt792x-lib, mt7925-common, mt7925e) including file hash, GNU build ID,
srcversion and module holder sets. There must be no active Wi-Fi or
trace and wired management must be intact. The guard stages in `/run`,
arms a 15-minute independent reboot timer before unloading anything,
and loads exactly the matched modules. No installed kernel module or
initramfs is replaced. Root `client-module-stack.sh quota --restore` reboots; verify the original
stack with `client-module-stack.sh quota --check-original` afterward. A failed activation also
reboots if any module has been changed.

Use the same bounded AP observer and client trial as the binding
experiment, but with `client-sustained.sh TAG --scan-timing-quota`.
The wiphy index is discovered afresh after the live reload. Seal both
manifests and run the usual scan, timing, absence, binding and kernel
trace reports, plus `report-client-credit.py TRACE TIMING`. The latter
checks the per-epoch ledger and bounds timestamp ties. The raw absence
tracepoint precedes the handler lock, so quota accounting may only use
a uniform observed budget, not an assumed cross-CPU event ordering.
Denied admission attempts and refunds are not unique packet counts.

### Exact upstream MediaTek MLO series / prefix regression isolation

Use the exact advertised base commit
`8739e5b44b23bbf6dc6568c3fefcbd22413dc117` (mt76 tree
`495cf61b68e8e7f03daf896c21464e609f5f2e6f`), not the installed
CachyOS mt76 snapshot. The verified 239-blob base is retained in
`$root/exact-upstream-base`; the 2026-11-10 28-patch Emery Hsin series
is archived under `/home/jan/build/wave7/mt7925-scan-source/upstream-20261110`
with the original mail Message-IDs, SHA256 manifest and base-tree blob
verification. Mail 1 is the cover, mails 2–29 are patches 1–28.
For a prefix, copy the original base into a fresh scoped source directory,
verify the archived mail manifest, then apply mails 2 through N+1 in
numeric order using `git apply --check` followed by `git apply`.
Build the full eight-module closure using the Kbuild configuration above
and its own `MO` directory. Never mix common/core/PCI modules across
prefixes. Pin all five PCI files, srcversions and live build IDs in
`client-module-stack.sh` before running, and use the same guarded
activation, independent reboot timer and original-stack verification.

The exact-base control is `upstream-base` and the complete series is
`upstream-mlo`. Use `client-sustained.sh TAG --scan-timing-upstream-base`
or `--scan-timing-upstream-mlo`, respectively, with the unchanged AP
observer. The continuity gate records valid/active/dormant masks and
rejects unexpected disconnect/reassociation; both negotiated links must
remain valid. It does not confuse legitimate single-active-link MLSR
with deletion of a negotiated link.

2026-11-22 direct comparison: exact base (tag 123420) maintained both
links, with eight 661–747ms post-scan all-path gaps and stationary AP
RX/TX counters. Full series (tag 121900) had a 26.641s first associated
full scan, disconnected ~0.97s after completion, re-associated on
5GHz alone, and emitted mac80211 `!rx->link` warning after reconnect.
The full-series steady packet count is not a valid dual-link result.
A single matched comparison narrows the regression to the series but
is not sufficient to attribute it to a particular patch. Prefix12
ends before multi-link ROC changes; later boundaries 22/24 precede
authorization-driven link activation and FW-driven link-state handling,
respectively. Preserve the raw/derived manifests and AP observer; do
not infer missing keys solely from RX silence or assume the second
link carried data merely because its firmware STA_REC was accepted.
