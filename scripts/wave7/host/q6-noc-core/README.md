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
