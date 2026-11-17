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
- Explicit start sends QMI 0x44 segmented profile configuration.
  The FW asks for ETR memory via 0x3f, host uses named, dedicated
  no-map 1MiB ETR region to reply via 0x40, then QMI 0x45 enables
  the trace after FW configuration. Stop sends 0x45 mode-off.
  FW 0x41 save indication captures phys-memory or streamed QMI
  0x42 segments, exporting the binary as a Linux devcoredump.
- QMI callbacks enqueue the existing ordered worker; QDSS state and
  ETR mapping are mutex protected. Status, start, and stop_and_capture
  are available only through the IPQ5332 debugfs device.
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
    # Generate brief, known traffic only. Do not immediately do 100 reboots.
    echo 1 > /sys/kernel/debug/ath12k/<ipq5332>/umacnoc_qdss/stop_and_capture

Start uploads the separate profile; firmware memory and mode handshakes
must succeed before status shows active=1. Stop only requests a save;
only an actual firmware SAVE indication produces the binary
devcoredump. Persist the raw devcoredump on Asus together with
boot UUID, kernel/FW version, trace settings, and Q6 log events.
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
