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

## Bounded guarded hardware test procedure (not performed)

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
Normal production profile and accepted running router are unchanged.

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
