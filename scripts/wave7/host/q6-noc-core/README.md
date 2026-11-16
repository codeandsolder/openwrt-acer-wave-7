# IPQ5332/Wave7 UMAC NoC error: frozen DSP core decoder

Read-only, version-scoped, **successfully tested on both independent
November 10 2026 root-Q6 fatal cores**. Usage:

    uv run --no-project --offline --python 3.13 python decode.py \
      --firmware-mdt /path/to/fw067/q6_fw1.mdt \
      --core /path/to/core1.bin --core /path/to/core2.bin

The decoder reads ELF32 program headers from firmware MDT and root
Q6 physical devcoredump to translate DSP virtual pointers to captured
RAM, not live MMIO; requires the original matching firmware version.

## New evidence

The Qualcomm NoC error handler has two descriptors, both read from
the crash cores, not hardcoded by this decoder:
- UMACNOC: actual MMIO logger base 0xE5140000, ERRVALID = 1
- WCSS_CFGBUS: actual MMIO logger base 0xE5008000, ERRVALID = 0

Both independent crashes produced identical UMACNOC registers:
- ERRLOG0 low/high: 0x00012105 / 0x0000007F
- ERRLOG1 low/high: 0x0000003B / 0x0000841D
- ERRLOG2 low/high: 0x00002000 / 0x00000000
- ERRLOG3 low/high: 0 / 0

### Source-backed Qualcomm filter fields (2026-11-15 follow-up)

Qualcomm's 2026 first-party Trusted Firmware driver, rather than a
generic NVIDIA/NXP NoC implementation, extracts:
- errcode = (ERRLOG0_LOW >> 8) & 0x7 : **1**
- MID = ERRLOG1_HIGH & 0xff : **0x1d**
- EXTID = ERRLOG1_HIGH & 0xffffff00 : **0x00008400**

The driver uses the resulting EXTID and error code to filter certain
fault classes, but does not publish an IPQ5332 UMACNOC initiator,
target, route aperture, or human-readable error-code map.
Consequently MID=0x1d is a raw field, **not a mapped initiator**,
and errcode=1 is reported numerically rather than guessed to be
DECERR/SLVERR. We do not assert a CPU physical address for ERRLOG2.
The decoder outputs qti_source_backed_filter_fields only when its
firmware-verified QNoC4 layout matches and ERRVALID is set; other
NoC instances retain only the raw register values.

Primary source:
https://github.com/qualcomm-linux/trusted-firmware-a/blob/qcom-next/drivers/qti/icb/noc_error.c
(qti_noc_error_handle_filter, exact bit shifts and MID mask).

These are **64-bit register pairs** with offsets 0x20..0x3c matching
Qualcomm's published QNoC4 error logger definition, verified against
the *actual firmware descriptor table*. The NoC handler code at
0xB032A670 reads MMIO at the above offsets and saves it into
the 0x60-byte UMACNOC descriptor. At call site 0xB032A988 the handler
supplies the NoC index0 and captured ERRLOG1_LO=59,
ERRLOG2_LO=8192 to Qualcomm's general err_fatal routine. This
explains the log param0=zero, param1=59, param2=8192 and confirms
these are real fault register values, **not an absolute physical
address 0x2000 or the firmware faulting PC**.

The paired file/message/line metadata at UserPD virtual
0xB046D7DC is 10-byte little-endian line=423, string pointer for
"NOC ERROR DETECTED.", source filename "NOC_error.c". Nearby records
include line507 "NOC init error !". Source blob reference b02 offset
0x4707dc, no firmware changes. Firmware string pointers are
indirected by this catalogue, which explains why scanning the entire
firmware for direct code-to-string PC-relative references found none.

### Input and outputs

Firmware067 internal UserPD1 q6_fw1.mdt, same as accepted native image
r0+38249-3b1851eda6. Root Q6 cores on Asus:
- /home/jan/firmware/wave7/logs/ba1024-491e10892d-20261110/rollback-q6-noc-devcoredump.bin
  SHA256 9202a68a88f6034c1a5ca37cb4fd07870fff654898fc4e5988065d2a24ec0214
- /home/jan/firmware/wave7/logs/q6-noc-20261110/repro2-q6-core.bin
  SHA256 205b8f51a87102f6cf7c4b2062cafbe7d9deaa520b701616e181c7ef6a5dee60

Generated JSON, independent checks, legacy disassembly and catalogue
under Asus /home/jan/firmware/wave7/analysis/20261115-q6-noc
and Acer /home/jan/firmware/wave7/trials/20261115-q6-noc
(no core files or build artifacts copied into Git).

Qualcomm QNoC4 register offset source, 2026 public contribution:
https://chromium.googlesource.com/external/github.com/ARM-software/arm-trusted-firmware/+/9b28ff9f10c19d7852706e1f195d76ea5483c256%5E2..9b28ff9f10c19d7852706e1f195d76ea5483c256/

## Remaining boundary

Still missing **fabric-specific route-ID decoding**, initiator/target,
and physical address reconstruction for ERRLOG1/ERRLOG2. Do not guess
these or assume 0x2000 is an absolute CPU address. The third same-
signature NOC_error.c crash on November15 did not preserve a fresh
DSP devcoredump; the two prior dumps independently agree. Previous
Nov10 evidence and Nov15 follow-up are tracked in the detailed Notion
page https://app.notion.com/p/414f74be90208197b26df2c42bd0556a .

The existing coordinated Q6/UserPD/ath12k recovery patches were
already verified working; this is investigation of the origin, not
recovery. No new flash, reset, cable cut or live MMIO probe was done.

## Passive Q6 crash-core capture (2026-11-16)

The accepted Wave 7 router is monitored independently by Asus,
without any router filesystem or firmware change. Asus systemd user
unit: wave7-q6-devcoredump-capture.service. Source is in this folder:
watch-devcoredump.sh, test-watch-devcoredump.sh and
wave7-q6-devcoredump-capture.service. The installed Asus script is
/home/jan/scripts/wave7/q6-noc-core/watch-devcoredump.sh.

On Asus, inspect:

    systemctl --user status wave7-q6-devcoredump-capture.service
    journalctl --user -u wave7-q6-devcoredump-capture.service
    /home/jan/scripts/wave7/q6-noc-core/watch-devcoredump.sh --check

The unit is enabled and active, with jan Linger=yes; it should
survive logout and host reboot. Polls occur every 15 seconds over
independent Asus SSH to the router at 192.168.76.1, reading only
/sys/class/devcoredump/devcd*/data. The poller never writes to
router sysfs, injects a fault, touches Q6 recovery or uses Wi-Fi STA
connectivity. The accepted Q6 coredump mode is enabled, so the kernel
uses its buffered dev_coredumpv mechanism and recovery does not wait
for a userspace read. Kernel devcoredump entries expire normally.

The Asus output directory is
/home/jan/firmware/wave7/captures/q6-devcore/
with private permissions (umask 077). Dumps are named by SHA256 and
include per-dump .context.txt containing router boot ID, release,
remoteproc states, dmesg excerpt and ELF header. Byte-identical
captures deduplicate after a full cmp check, never overwriting an
existing core. Partial streams are removed and retried while the
entry is available; reused devcd names after disappearance can be
processed as new events. No binary cores are stored in Git.

At deployment 2026-11-16 14:42 CET the accepted router showed no
pending devcd entry, bootfail0, MLO2 and three running Q6 processors.
Only the prior natural crash #1 and test injection crash #2 existed
in that boot; no new spontaneous core was claimed or forced.

Preflight --check was verified on Asus over its real SSH identity;
Bash syntax and ShellCheck both passed. The fake SSH fixture test
test-watch-devcoredump.sh (run on Asus) verified initial ELF streaming,
SHA-based naming, context, restart dedup and cleanup, without talking
to the router or leaving any test fixtures. The mock is not a live
33MB dump validation; wait for a natural crash to test that path.

To remove the monitoring service intentionally:

    systemctl --user disable --now wave7-q6-devcoredump-capture.service

Configurable environment: WAVE7_Q6_SSH_HOST, WAVE7_Q6_SSH_KEY,
WAVE7_Q6_DUMP_DIR and WAVE7_Q6_POLL_SECONDS. The existing Nov15
guarded root-Q6 crash/recovery acceptance remains the proof of
in-place recovery; this service is only a passive evidence collector.

### 2026-11-16 capture integrity hardening

The monitor now validates the streamed ELF CORE before archiving: a
successful SSH command is not enough. It confirms a parseable ELF core,
at least one PT_LOAD segment, and sufficient file length to include
every program-header payload. The validation is generic for ELF32 or
ELF64 and does not impose a board-specific core length. On an incomplete
transfer it logs FAILED_INVALID_ELF, removes the partial file, and
retries while the devcd entry remains available. Termination also
removes any in-progress temporary file.

We replaced the earlier small synthetic fixture test with a test using
one genuine November10 Qualcomm DSP6 core, supplied with environment
WAVE7_TEST_CORE (default Asus archive path). It runs a fake SSH server
that returns first 4096 bytes with successful exit status, and checks
the truncated ELF is rejected. Then it returns the entire 34,603,092
byte archived core and checks the stored bytes and content SHA256
205b8f51a87102f6cf7c4b2062cafbe7d9deaa520b701616e181c7ef6a5dee60
against the original. It also checks the preserved metadata and
duplicate suppression after monitor restart. Asus validated:
ARCHIVED_Q6_CORE_TRUNCATION_REJECTION_DEDUP_METADATA_PASS.

The validated source was atomically installed on Asus and its user
systemd service restarted normally at 2026-11-16 15:22:47 CET,
active PID 3637016, NRestarts=0, no new live devcd or fault injection.
This establishes real-core transfer correctness in offline simulation,
not that a future naturally occurring live devcd has already been
captured. The collector still does not alter the router or recovery.

### 2026-11-16: Qualcomm legacy observer protocol interpretation

We identified a second, older Qualcomm first-party source for
encoded NoC packet fields: Android/Qualcomm kernel file
drivers/soc/qcom/gladiator_erp_v2.c (MSM/Gladiator observer, **not** the
IPQ5332 QNoC4 block):
https://android.googlesource.com/kernel/msm/+/a16b037ec055c8850000da3c283f207217cc966b/drivers/soc/qcom/gladiator_erp_v2.c

The driver defines OBS_ERROR_TYPE_MASK=0x700, shift8;
OBS_TRANS_OPCODE_MASK=0x1e, shift1; enum OBS_SLV=0, OBS_DEC=1,
OBS_UNS=2, OBS_DISC=3, OBS_SEC=4, OBS_HIDE=5, OBS_TMO=6;
enum OBS_RD=0, OBS_RDW=1, OBS_RDL=2, OBS_RDX=3, OBS_WR=4,
OBS_WRW=5, OBS_WRC=6, OBS_RESERVED=7, OBS_PRE=8, OBS_URG=9.

Applying that OLDER Qualcomm logger packet interpretation to the
observed QNoC4 ERRLOG0_LOW=0x00012105 gives error code1 (legacy
"address decode error"; source initiator NIU), opcode2 (legacy
"linked read"), lock-bit1, length1-field1. The numeric QNoC4 code1
is independently confirmed by first-party NEW Qualcomm 2026 TF-A,
but the symbolic meanings and opcode in IPQ5332 QNoC4 are still
UNCONFIRMED. The decoder therefore emits these as
legacy_observer_protocol_hypothesis with explicit provenance and a
not_verified_qnoc4 marker, separate from source-backed confirmed
numeric qti_source_backed_filter_fields.

This is NOT proof of which block issued the transaction, its full
address, nor that IPQ5332 actually emits linked reads. test_decode.py
tests the mapping including unknown opcode values and the exact
captured word. The revised decoder was run on BOTH independently
archived full Q6 DSP cores on Asus; output agrees completely:
BOTH_REAL_CORE_IDENTICAL;
VERIFIED_QNOC4_ERROR_CODE_1;
LEGACY_QCOM_OBSERVER_CANDIDATE_DEC_LINKED_READ;
NO_FABRIC_ROUTE_NAME.

New JSON is only in Asus
/home/jan/firmware/wave7/analysis/20261115-q6-noc/qnoc4-legacy-hypotheses.json,
SHA256 04d5095fb2c38a02be17af23f06bd168390a623610027d21545650c3fbab54f4.
No new crash, register read, or firmware image needed.

## Separate passive kernel NoC event recorder, 2026-11-16

The WBE1.4 hardware A/B produced a new NOC ERROR DETECTED at
uptime406s, but the existing passive devcd recorder saw no full ELF
core. The NoC event service captures kernel diagnostic text even
when Q6 SSR recovers without producing a core.

Independent Asus user service wave7-q6-noc-events.service runs
watch-noc-events.sh --run every 8 seconds, in parallel with the
existing passive devcoredump service. It uses read-only SSH to
inspect boot UUID, revision and filtered dmesg error lines. On a
new error it takes a bounded 15-second full kernel dmesg snapshot,
remoteproc states and devcd directory listing.
It rejects samples where the router rebooted between probe and
snapshot. Per-boot per-event hashes deduplicate across restarts;
files and SHA256 manifests are archived atomically.
No router-side file writes, reboots, module loads or MMIO.

Asus operational paths:
- /home/jan/scripts/wave7/q6-noc-core/watch-noc-events.sh
- /home/jan/.config/systemd/user/wave7-q6-noc-events.service
- /home/jan/firmware/wave7/captures/q6-noc-events/

At installation Nov16 18:17 CET both this service and the existing
devcore collector were enabled and active (jan user linger=yes).
Accepted boot 04dddd01-ac63-48a4-8f75-afbf491e03c2 showed no
new NOC ERROR DETECTED lines. Check with --check or systemctl.

The offline test-watch-noc-events.sh runs a bounded fake SSH fixture
to verify preflight, full log capture, different-boot rejection,
restart dedup and removal of incomplete temporary files. It does
not induce a hardware Q6 crash.

### Continuous kernel-message capture — 2026-11-16

The original eight-second poll has a blind spot: a fatal followed by
rapid reboot/rollback can erase the current boot's ring before the
second SSH request. A separate optional Asus user service
\`wave7-q6-noc-kmsg.service\` uses a **read-only** long-lived SSH
\`cat /dev/kmsg\` file descriptor instead of polling. \`/dev/kmsg\`
has a per-open reader cursor; unlike \`/proc/kmsg\`, reading does
not drain the system's global message queue. The accepted Wave7 BusyBox
\`dmesg\` does not support follow mode; live hardware successfully
returned records from \`/dev/kmsg\` without modifications.

Each SSH connection emits a boot UUID and revision before the stream.
An exact \`NOC ERROR DETECTED\` record is identified by its per-boot
kernel sequence number; it is saved atomically and SHA256-checked
**before** requesting a full dmesg/remoteproc/devcoredump snapshot.
The context snapshot is only accepted when its boot UUID matches the
stream and it still contains the fatal line. Even if that second SSH
fails because the router rebooted, the original event record persists.
Reconnecting to the same boot deduplicates by boot UUID and kmsg sequence.

Scripts: \`watch-noc-kmsg.sh\`, \`test-watch-noc-kmsg.sh\`, and
\`wave7-q6-noc-kmsg.service\`. The fake-SSH regression exercises a
router-reboot race, event persistence, later context recovery, SHA
verification, and reconnect deduplication. Run both the streaming
service and the independent eight-second poll to keep complementary
channels. Neither causes hardware tests or firmware changes.

## Pre-fatal IRQ and associated-station history (2026-11-16)

The existing Asus `wave7-q6-noc-events.service` now samples a small
selection of wireless and Q6 IRQ counters in the **same SSH/dmesg poll**
(every 8 seconds by default). No additional service, router package, or
router-side configuration is required. It records one tab-separated file per
router boot:

    /home/jan/firmware/wave7/captures/q6-noc-events/irq-<boot-uuid>.tsv

Columns are capture UTC, router monotonic uptime seconds, number of associated
MLO stations, Linux IRQ number, cumulative IRQ count summed across CPUs, IRQ
name, and OpenWrt revision. Selection is by the kernel's actual registered
IRQ name (CE, WLAN PCI MSI, REO/WBM/RXDMA, SMP2P, Q6), not an assumed IRQ
number. Interrupt rates are deltas of consecutive **cumulative** counters
on the same boot and same IRQ, divided by monotonic uptime deltas; counters
may reset on driver rebind. The existing per-event kernel archives still
capture full dmesg and independent `/dev/kmsg` streaming remains active.

A live 2026-11-16 connected-versus-disconnected MT7925 comparison saw
`rxdma2host-monitor-destination-mac1` at roughly 1.3k interrupts/s in both
conditions (no association dependency), but did not determine whether that
level is abnormal. The IRQ samples are intended to expose **changes
preceding** a future natural NoC fatal, not to claim this is the cause.

### Adaptive early-boot IRQ sampling

Default polling is now 2 seconds for the first 150 seconds of each
router boot, returning to the existing 8-second polling interval
for later uptime. This uses the same read-only SSH/dmesg/IRQ probe
and collector service, rather than creating another service or touching
the router filesystem. The faster startup cadence is motivated by the
new NoC fatal at uptime 99.899s: previous 8-second samples
straddled a large QCN6432 RX monitor ring IRQ-rate transition.
The IRQ rate is observational and does not establish causality; the
QCN6432 DP group 8 is a monitor ring, not the regular data ring.

Optional overrides: WAVE7_NOC_EARLY_POLL_SECONDS (2..base interval),
WAVE7_NOC_EARLY_WINDOW_SECONDS (30..600), and existing
WAVE7_NOC_POLL_SECONDS (2..300). Probe failures use normal intervals.
Boot-specific irq-<uuid>.tsv files retain the same schema.

### Firmware NoC ERRCLR operation (Acer stock 067)

The decoder now reads all 10 relevant firmware register-index table
entries (including the previously omitted ERRCLR at index offset
+0x08), rather than inferring the clear offset from another chip.
On both November 10 and November 16 WBE1.3-03279 Q6 fatal cores,
the tables assign ERRVALID=0x10, ERRCLR=0x18, ERRLOG0_LO=0x20.
UMACNOC clear MMIO = 0xe5140000 + 0x18 = 0xe5140018.
WCSS_CFGBUS clear MMIO = 0xe5008000 + 0x18 = 0xe5008018.

Direct Hexagon disassembly of the matching Acer 067 firmware ELF
at /home/jan/firmware/wave7/trials/20261115-q6-noc/q6_fw1-067-analysis.elf
establishes the handler's intended error-clear operation:

- 0xb032a6bc: initialize R24 = 1.
- 0xb032a6f4 onward: copy logger error registers into descriptor
  snapshots before clearing.
- 0xb032a844: R3 = memw(R27 + 0x08) (physical MMIO base).
- 0xb032a84c: R4 = memuh(memw(R27 + 0x04) + 0x08)
  (the descriptor's ERRCLR register offset).
- 0xb032a850: memw(R3 + R4) = R24 (write 1 to ERRCLR).

The handler then continues to report the saved error. This evidence
comes from static firmware instructions and the dynamic table decoded
from captured memory; it is not live-MMIO readback proving that the
fabric accepted the clear. The handler nevertheless explicitly
attempts to clear the logger after saving the syndrome. Repeated
byte-identical fatal syndromes therefore suggest the same failed
transaction/configuration recurring, rather than necessarily one
uncleared stale latch.

JSON now includes error_clear with the table-derived MMIO address and
null snapshot. Static handler write-value/instruction evidence is
attached only for the verified layout. Synthetic two-instance ELF
tests cover layout mapping, variant layout, and reserved index values.

### Q6-owned PCIe2 clock hardware state capture

Wave 7 intentionally leaves all Linux PCIe controller nodes disabled;
stock Acer 067 root-Q6 firmware contains its own register-level
clock-operation descriptors for all nine QCN6432-connected 2-lane PCIe
resources. The Linux common-clock framework shows enable_count=0
while the gate can still be physically on (hardware_enabled=Y).
The Q6 firmware descriptor CBCR aliases map to GCC physical
0x01828030/38/40/48/68/70/80 and 0x0182e048/7c.

The existing read-only Asus NoC/IRQ collector now records
clocks-<boot-id>.tsv alongside irq-<boot-id>.tsv. Every SSH probe
extracts just the 2-lane PCIe names matching gcc_pcie3x2_* or
gcc_snoc_pcie3_2lane_* from the kernel clock_summary debugfs.
Each row contains UTC, router uptime, clock name, CCF enable_count,
CCF prepare_count, rate_hz, hardware_enabled=Y/N, and firmware revision.
The same already-proven adaptive 2-second sampling applies during
the first 150 seconds, then the normal 8-second cadence applies.

These rows can demonstrate clock gate state transitions near an
occurring NoC fault; they are **not** a physical initiator/target
decoder, and sampled absence of transitions cannot exclude a very
brief clock glitch. Hardware_enabled is the driver's readback as
exposed by debugfs, not an independent bus scope. On a kernel without
the debugfs summary or with a missing clock, recording is optional
and cannot prevent the primary crash/core/IRQ collector from running.

The mock SSH test verifies Y and N hardware states, zero CCF users,
correct clocks selected, exclusion of unrelated PCIe0 clocks,
NoC archive deduplication, and adaptive sampling.
