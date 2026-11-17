# IPQ5332 UMACNOC QDSS diagnostics — experimental build

Scope: Acer Wave 7 IPQ5332 WBE1.3 UserPD1, UMACNOC at 0xe5140000,
fatal raw NoC route 0x3b / ERRLOG2 offset 0x2000. Trace capture only;
the actual route-to-hardware target remains unknown.

## Source and original firmware

- Original Acer IPQ5332 qdss_trace_config.bin has SHA256
  9b562386f2f1b48f946c405fbd22193dbac2f7cf9160c63221352471ed3502db.
- Original Acer WBE1.3 q6_fw1.b02 contains NoC trace configuration
  parser, filter0_path and filter0_path_mask, and QDSS QMI handlers.
- Qualcomm QSDK 2025 ath12k QDSS patch provides the QMI wire format,
  memory request/trace mode/save implementation:
  https://github.com/Telecominfraproject/wlan-ap/blob/4ebbb3a53afbc142802851a3a0e405bd671b5289/feeds/qca-wifi-7/mac80211/patches-qca/ath12k/0527-001-QSDK-PLATFORM-wifi-ath12k-Add-QDSS-support.patch
- Vendor Qualcomm IPQ5332 512 MiB DTS reserves 1 MiB Q6 ETR region
  at 0x4cd00000; on Acer this range was already inside the
  unreferenced Wi-Fi spare reservation.

## Implementation on diagnostic branch

- Patch 723 adds IPQ5332-only opt-in QDSS QMI to the existing native
  ath12k service. No automatic tracing at boot. The existing
  CNSS_QDSS_CFG_MISS feature negotiation is unchanged.
- At boot, QMI 0x44 uploads the profile but does not start tracing.
  Explicit start uses a firmware-requested 0x3f/host 0x40 MEM_INFO
  handshake when offered. Acer WBE1.3 instead proved successful with
  host-initiated 0x40 MEM_INFO for the dedicated 1MiB reserved ETR
  buffer, followed by QMI 0x45 MODE_ON after a one-second settle.
  Stop sends QMI 0x45 MODE_OFF. Firmware 0x41 SAVE indications, when
  received, still produce Linux devcoredumps from ETR/QMI data.
- QMI callbacks use the existing ordered worker; QDSS state and ETR
  mapping are mutex protected. Root-only IPQ5332 debugfs provides
  status, start, stop and a stopped-only raw_etr binary snapshot.
  The raw_etr snapshot is independent of optional firmware SAVE.
- Separate profile qdss_trace_umacnoc.bin enables the original
  commented-out UMACNOC trace and disables MAC/PHY event streams.
  Original zero path masks are preserved: IPQ5332 path mask width
  and probe mapping have NOT been verified.
- Diagnostic DTS splits Wi-Fi spare 0x4cb00000..0x4ce00000 into
  an unreferenced 2MiB span and named 1MiB ETR span at 0x4cd00000.
  This does not change the union of reserved physical memory.

## Offline reproducibility

From the OpenWrt checkout:

    uv run --no-project --no-managed-python python scripts/wave7/host/q6-noc-core/generate-qdss-profile.py files/lib/firmware/ath12k/IPQ5332/hw1.0/qdss_trace_config.bin files/lib/firmware/ath12k/IPQ5332/hw1.0/qdss_trace_umacnoc.bin
    uv run --no-project --no-managed-python python scripts/wave7/host/q6-noc-core/verify-qdss-layout.py --repo /home/jan/projects/acer-wave7-openwrt-current --baseline-rev b763b0fe85 --stock-fw-dir /home/jan/projects/acer-wave7-firmware/Acer_Predator_T7c/wifi-fw-067
    SCCACHE_SERVER_PORT=4228 make -j2 package/kernel/mac80211/compile

Memory checker verifies all direct-child DTS reservations are disjoint
and their coverage is unchanged vs accepted base, and none of the
physical PT_LOAD spans in the three OEM Q6 ELFs overlaps ETR.

## Exact accepted-kernel diagnostic image packaging

The independent native NAPI 5e3df9b898 image is the **accepted
rollback artifact**, not necessarily the currently running diagnostic boot. The dedicated builder at build-qdss-candidate.py takes that
original SHA-pinned image (18e285b7...), the final compiled kmod-ath12k
APK, and the generated trace-only profile.

It extracts the exact accepted compressed kernel from its FIT, patches
the *accepted* DTB in place with libfdt tooling (only one new ETR node,
Wi-Fi spare size adjustment, and its memory-region/region-names append),
regenerates the FIT CRC32/SHA1 hashes, and asserts the compressed kernel
bytes are identical to the accepted kernel. It compares the ENTIRE
canonical DTB and rejects any unapproved property change. The newly compiled companion ath12k_wifi7.ko is **always packaged
together with** its matching ath12k.ko. These two modules share the
C definition of ath12k_base and must have identical layout. During
the first diagnostic hardware trial we preserved the old companion,
causing a real null-pointer Oops at 43.5 seconds; that attempt
automatically fell back to the Acer vendor firmware. The builder
now compares complete DWARF layouts from both rebuilt modules and
requires both files to be present and replaced in the rootfs.

The SquashFS is rebuilt from the accepted root with the two matched
native ath12k modules, diagnostic QDSS firmware profile, four revision
strings and one trial marker changed. The builder checks the entire rootfs
manifest, module vermagic, special /dev/console node, rootfs reextract,
FIT hash data, sysupgrade tar members, target and fwtool metadata.
A generated .report.json records all changed files, artifact hashes,
and confirms hardware is untouched.

The corresponding Asus guard is flash-qdss.sh and qdss-watch.sh;
the independent raw QDSS devcoredump collector is
watch-qdss-devcore.sh. The already-running Q6 devcore collector
recognizes only ELF Q6 core dumps and must **not** be used to classify
the binary QDSS trace stream. Raw QDSS dumps are SHA-pinned on Asus,
with their router boot UUID, revision and device origin.

**Transport correction discovered during source review:** Qualcomm's
QMI TRACE_SAVE source field, *not the presence of total_size*,
distinguishes source=0 (ETR physical segment layout) from source=1
(segmented QMI TRACE_DATA). The experimental driver implements both
and validates the ETR offsets/sizes or streaming message sequence
without assuming a nonzero total_size means QMI. This correction
is required before any real capture.

## Early QDSS firmware negotiation (next diagnostic build)

Hardware test of the corrected 2026-11-17 `fc4cdcce47` image proved
`QDSS: uploaded qdss_trace_umacnoc.bin (3774 bytes, 1 segments)`
on original Acer WBE1.3 Q6, but ETR remains `configured=1 active=0`.
No firmware `QMI 0x003f` memory request or raw trace dump appeared.

The original IPQ5332 hardware parameters include
`CNSS_QDSS_CFG_MISS_V01` (bit 3) in QMI HOST_CAP. Qualcomm QSDK's
QDSS implementation has the expected CONFIG→MEM_REQ→MEM_INFO→MODE
sequence, but does not alter that feature bit. Independent ath12k
WCN7860 code in Armbian patches 0040/0041 demonstrates the early
initialization variant: when the missing-config flag is cleared, send
the QDSS profile at BDF load rather than after radio ready. This is
**related protocol evidence on different silicon**, not proof of
IPQ5332's behavior.

The next test source implements the equivalent IPQ5332-only handshake,
with an extra explicit opt-in: the active DTB must provide a named
exactly 1MiB `q6-etr-dump` reserved-memory region. Without that region
the original HOST_CAP bit and ordinary startup remain unchanged. With
it, the host clears only `CNSS_QDSS_CFG_MISS` in the QMI HOST_CAP
request and downloads the separate profile at the end of
`ath12k_qmi_event_load_bdf`. Any early configuration failure becomes
a real bring-up failure covered by vendor rollback.

The early memory-request worker provisions the exact ETR physical
reservation and sends MEM_INFO but **does not enable TRACE_MODE** until
an explicit debugfs `start`. If the ETR is ready when the command is
issued, it sends MODE_ON immediately; otherwise it defers the enable
until the validated FW MEM_REQ event. Debugfs status exposes
`start_requested` and `etr_ready` to distinguish upload,
memory allocation and actual tracing. An idle-session cancel sends
MODE_OFF and clears the host state only after a positive firmware
response.

Source:
- Qualcomm QSDK: `Telecominfraproject/wlan-ap` ath12k
  `0527-001-QSDK-PLATFORM-wifi-ath12k-Add-QDSS-support.patch`,
  commit `4ebbb3a53afbc142802851a3a0e405bd671b5289`
- Armbian ath12k protocol ordering: `armbian/build`
  `0040-wifi-ath12k-send-QDSS-config-when-CNSS_QDSS_CFG_MISS.patch`
  and `0041-wifi-ath12k-disable-CNSS_QDSS_CFG_MISS_V01-for-the-W.patch`,
  commit `90c251d5b9b15db625f51443216f173990c75f9f`
- Exact guarded `fc4cdcce47` trial evidence:
  `/home/jan/firmware/wave7/trials/20261117-umacnoc-qdss/runs/qdss-fc4cdcce47-20261117-060557/evidence`

This early-negotiation code requires a separate build and complete
revalidated image before hardware testing. Do not confuse the successful
config message with a successful trace capture.

## Fourth guarded hardware trial and early-MEM_REQ visibility (2026-11-17)

The fourth whole-image diagnostic, `r0+38249-qdss-f086787166`
(SHA256 `fb09dee95c351afd86c3598b24e739221e10fa43669d68a4d72bb29e3cffe203`),
booted as `5c61face-e0a3-4d4e-80d9-20e3d03c34b9` and passed the
independent Asus **900-second continuous-health soak** at 06:44:02 CET.
During the soak: three Q6 remoteprocs running, MLO2, wired Redmi reachable,
bootfail0 and firstboot keep marker. Asus observer evidence:
`/home/jan/firmware/wave7/trials/20261117-umacnoc-qdss/runs/qdss-f086787166-20261117-062642/observer.log`.
The three permanent passive NoC collectors remain active. The one-off vendor
observer expired at its 1800-second runtime limit *after* the successful soak;
the one-off raw QDSS collector remained active until its own runtime limit.
No raw UMACNOC QDSS capture has been produced.

The firmware accepted the exact 3774-byte profile at BDF load with
`CNSS_QDSS_CFG_MISS` cleared, but last hardware observation showed
`configured=1 active=0 start_requested=0 etr_ready=0`. The previous
interpretation that QMI 0x003f *was never sent by firmware* was too strong:
the native callback discarded this indication **without logging** whenever
`configured` was false. On a BDF-init transaction the indication could
race ahead of the host's local configuration state. No actual evidence of
such a race exists yet; it is a newly identified observability gap.

A subsequent **source-only, not flashed** patch now counts every decoded
0x003f indication delivered to the IPQ5332 QMI handler, including those
arriving before `configured` is set, and prints its segment metadata.
`umacnoc_qdss/status` includes persistent per-boot
`mem_req_seen`, `mem_req_before_config`, and `mem_req_invalid`
counters. This does not change firmware negotiation timing, tracing enable,
memory mappings, or production behavior.

Diagnostic interpretation for any later **independently guarded** boot:
- `mem_req_before_config>0`: the firmware requested trace memory before
  host configuration was complete. Preserve the exact early indication
  timestamp and compare to HOST_CAP and BDF configuration timestamps.
- `mem_req_seen>0` but `etr_ready=0`: use event logs and segment type,
  size and number to distinguish preconfiguration drops, validation and
  MEM_INFO errors.
- `mem_req_seen=0`: no *decoded* 0x003f reached this QMI callback. This
  does not prove the firmware never emitted anything (wire/TLV decode or
  another service instance could still account for missing visibility).

SCCACHE_SERVER_PORT=4228 OpenWrt regular mac80211 package compilation
passed. The patched seven-file series applies with `patch -p1 --fuzz=0`
to all original native sources and reproduces their expected bytes exactly.
Both freshly compiled native ath12k modules have byte-identical
`pahole --hex -C ath12k_base` layouts. Do not flash or call the new
counters hardware-validated on the basis of compilation alone.

### Fifth diagnostic image prepared offline (next guarded trial)

The source-only early MEM_REQ telemetry has now been packaged into a
**whitelist-verified but not flashed** whole-image diagnostic
`r0+38249-qdss-2f69a883f6`, 15,677,772 bytes, SHA256
`328469022e7b4e99759494f0520dc8f01d67fd66cefd3fa13f90d341f8423157`.
Offline report:
`/home/jan/firmware/wave7/trials/20261117-umacnoc-qdss/image-build/wave7-umacnoc-qdss-2f69a883f6-sysupgrade.report.json`.
The SHA-pinned accepted NAPI compressed kernel is byte-identical, ETR DTB
and original stock trace profile are identical to the prior fourth trial.
Its only approved rootfs changes versus accepted NAPI are the same eight
paths: four revision-identity entries, trial marker, profile and the
matched pair of native ath12k modules. No unrelated files change.
The packaged main module SHA256 is
`13ea03a3b2560d4f0473b8947a7eff04521f1d7da0bed200ce000d784851590a`;
companion Wi-Fi7 module SHA256 is
`ad018471227526232b07d072a1839e676f3fa692063534b968eef9d706dc420a`.

Guard scripts for this candidate require live predecessor
`r0+38249-qdss-f086787166`, rollback to exact accepted NAPI SHA256
`18e285b7dbfac4075a4f675b23c9b97cbf51c50aced6c16a82d1aab439dc0622`,
and independent Asus 900-second supervisor, vendor fallback and raw QDSS
collector before the flash command. Do not treat the presence of this
image or validation as a completed trial.

### Future observer checkpoint snapshots

For subsequent trials, the updated Asus-side `qdss-watch.sh` source
reads the single IPQ5332 `umacnoc_qdss/status` debugfs line with every
read-only health sample, and preserves it in `last-trial-state.txt`.
It records **QDSS_BOOT_STATUS**, **QDSS_REBOOT_STATUS**,
**QDSS_HEALTHY_STATUS** and **QDSS_SOAK_PASS_STATUS** markers at their
respective transitions. This avoids relying on manual SSH to reconstruct
preconfiguration indications. QDSS status is observational only:
missing debugfs produces `unavailable` and does not affect rollback
decisions. The fifth trial was armed using the previous observer script;
this additional instrumentation is source-tested for later trials and
must not be edited into a currently running guard.

### Explicit-start fixed-ETR provisioning experiment (source only)

The fifth hardware trial \`r0+38249-qdss-2f69a883f6\` passed its full
901-second continuous-health soak at 07:25:45 CET, but the early
\`mem_req_seen=0\` counter and missing ETR persist. This is *not* a
NoC-fatal fix or a captured QDSS trace.

Qualcomm QSDK normally receives QMI indication 0x003f before replying
with 0x0040 MEM_INFO, then waits one second before 0x0045 MODE_ON.
Acer's matching WBE1.3 firmware has a QDSS 0x0040 MEM_INFO request
handler. That suggests a useful experimental discriminator: would WCSS
accept the exact pre-reserved type6 ETR even without first issuing 0x3f?

Patch 723 now tests this **only after explicit debugfs start**. If a
firmware-driven 0x3f has already provisioned the ETR, it follows the
normal path. Otherwise the host maps only the dedicated original
\`q6-etr-dump\` reservation at 0x4cd00000 (1 MiB), sends an unsolicited
QMI 0x0040 with type6/base/size, checks firmware success, delays one
second, and sends 0x0045 MODE_ON. Successful firmware responses are
necessary but not sufficient: verify active status, stop SAVE indication,
and actual nonempty devcoredump before concluding it works.

A late firmware 0x3f always gets its own 0x40 response, including
after proactive provision; inconsistent extra requests no longer
discard an already-accepted trace session. The common explicit-start
path also handles starting from a freshly configured state after an
earlier stop (rather than uploading a profile and doing nothing).
Debugfs status adds \`etr_alloc_size\` and \`proactive_mem_info\`.
A rejected unsolicited 0x40 causes the explicit start to fail without
enabling trace mode. Normal boot remains upload-only, with no
unsolicited memory mapping or trace mode request.

This branch is a guarded diagnostic, not production. Source must be
built with both ABI-matched ath12k modules, exact original compressed
kernel/DTB/profile and whitelist-verification. Preserve independent
Asus NoC observer, vendor fallback, raw devcore collector and original
accepted NAPI rollback. Do not restart the 99-reboot corpus. The
discriminator is a single bounded explicit start/stop test after the
router passes firstboot health, followed by archive and decoding of
the raw trace if firmware actually emits it.

### Sixth fixed-ETR diagnostic candidate (2026-11-17)

Experimental \`r0+38249-qdss-48b2476bd6\` built and independently
whitelist-verified: SHA256
\`42b2dde4c2253a6168b6a423deff370122287ea69db34b7d5a7d55e82683db78\`,
15,677,772 bytes. Builder report on Acer at
\`/home/jan/firmware/wave7/trials/20261117-umacnoc-qdss/image-build/wave7-umacnoc-qdss-48b2476bd6-sysupgrade.report.json\`.
Accepted native NAPI compressed kernel and previously audited 1MiB
ETR DTB are byte-identical to the fifth diagnostic; unchanged Q6
firmware and stock QDSS profile. Exactly eight permitted rootfs paths
differ from original NAPI, no unrelated changes. Packaged native
\`ath12k.ko\` SHA256
\`6714a34ddf9d054717b0291a43ea2842b3121c2252fbafc89579a62415375a50\`,
paired Wi-Fi7 module SHA256
\`1e07b931cf2d4991734f982341d305169b452224c25026537ac181ab4381fa41\`.
The source unstripped modules have byte-identical \`ath12k_base\` DWARF
layouts and the native 6.18.60 mac80211 package built successfully
with the existing sccache. Patch 723 applies with zero fuzz to all
seven native files.

The new Asus guard requires predecessor
\`r0+38249-qdss-2f69a883f6\`, verified healthy boot, independent
NoC/Q6 passive collectors, vendor fallback, separate raw devcore
capture, and exact accepted NAPI rollback SHA256
\`18e285b7dbfac4075a4f675b23c9b97cbf51c50aced6c16a82d1aab439dc0622\`.
All runtime actions remain opt-in and separately guarded.

### Sixth first attempt safely aborted before NAND write

At 07:39:08 CET the new image and accepted rollback passed staging,
router SHA and \`sysupgrade -T\`, but the new Asus raw QDSS collector
exited \`QDSS_CAPTURE_LOCK_HELD\`: the fifth trial's successful collector
was still inside its 2100s capture window. The sixth launcher aborted
with \`PREFLIGHT_BLOCKED\` **before executing any sysupgrade**.
Evidence is archived in
\`runs/qdss-48b2476bd6-20261117-073903/\` (status
\`ABORTED_PRE_FLASH_NO_NAND_WRITES\`). The predecessor's live
\`qdss-watch.sh --check\` again confirmed its same healthy boot UUID,
Q6 3/3, MLO2, ping and bootfail0. The unfinished sixth native/vendor
observer units were stopped, and the fifth raw collector was stopped
only after verifying its recorded \`CANDIDATE_SOAK_PASS\`.
No router reboot or image change occurred.

The Asus launcher now checks active QDSS raw collectors BEFORE arming
any services. If a partial launch fails before invoking sysupgrade,
an EXIT trap stops all its own one-off collector/native/vendor guards
and records an explicit pre-flash abort. After the sysupgrade call
begins, the trap deliberately leaves those independent observers
running across the expected SSH disconnect. Bash syntax and
ShellCheck were run on the modified script. This resolves the aborted
trial's observer-leak without changing firmware.

### Sixth trial bounded QDSS probe operator script

\`scripts/wave7/host/q6-noc-core/probe-qdss.sh\` is the Asus-side
one-shot probe for the SHA-pinned \`48b2476bd6\` diagnostic. Use
\`probe-qdss.sh --check\` only after the sixth boot is accepted; this
validates exact image SHA, live revision and bootloader state, Q6 3/3,
MLO2, wired peer, no NoC fatal, passive collectors and QDSS configured
but idle.

\`probe-qdss.sh --run /home/jan/firmware/wave7/trials/20261117-umacnoc-qdss/runs/<exact sixth trial directory>\`
additionally requires three independent one-off Asus observer units
active and the matching candidate boot ID. It archives pre-start kernel
log and QDSS state, issues exactly one explicit debugfs start to test
QMI 0x40, and records its status/result. Only if trace actually becomes
active does it emit six low-rate wired packets, stop and request SAVE,
then inspect the independent raw devcoredump collector. All evidence
lands under that guarded run's \`evidence/proactive-etr-probe\`.
No reboot, repeated retry or PHY changes; the external guard retains
independent rollback responsibility. A QMI rejection is recorded
rather than silently treating the trace as active.

## Bounded guarded hardware test procedure (hardware tested)

This experimental variant changes the DTB, not only the kernel module.
It REQUIRES a separate sysupgrade built with the diagnostic kernel
and a SHA-pinned accepted whole-image rollback, independently controlled
by the Asus host watchdog. Verify the new boot and both radios first
with tracing inactive; check runtime Q6/WCSS memory allocations.

Once a guarded boot is healthy, locate the IPQ5332 AHB debugfs path
under /sys/kernel/debug/ath12k, typically ahb-c000000.wifi, then:

    cat /sys/kernel/debug/ath12k/<ipq5332>/umacnoc_qdss/status
    echo 1 > /sys/kernel/debug/ath12k/<ipq5332>/umacnoc_qdss/start
    cat /sys/kernel/debug/ath12k/<ipq5332>/umacnoc_qdss/status
    # Generate brief known traffic only. Do not repeat the reboot corpus.
    echo 1 > /sys/kernel/debug/ath12k/<ipq5332>/umacnoc_qdss/stop
    cat /sys/kernel/debug/ath12k/<ipq5332>/umacnoc_qdss/raw_etr > trace-etr.bin

Start provisions the fixed ETR mapping, then turns tracing on only
after successful QMI MEM_INFO. Stop requests MODE_OFF, not necessarily
a firmware SAVE; raw_etr is a bounded root-only 1MiB snapshot that
rejects reads while tracing is active. Persist binary and metadata
together on Asus. A separate QMI SAVE, if emitted, also produces
the normal devcoredump via the independent collector.
The normal production QDSS profile and unmodified accepted NAPI image
remain unchanged. The currently running *diagnostic* image is separate;
status and exact active boot should always be rechecked before a test.

## Remaining unknowns

The runtime firmware allocator has not been verified against ETR;
a static ELF/DTS nonoverlap test alone is insufficient. The captured
stream needs its NoC probe format determined from known traffic.
No verified IPQ5332 RouteId 0x3b path-mask semantics or target aperture
map has yet been recovered. A firmware crash may race with the
SAVE indication, so capture the raw QDSS/ETR trace early and with an
independent monitored rollback strategy.

Transient logs and build artifacts belong under the existing OpenWrt
build directory or /home/jan/research/wave7-qdss-20261117 only.
