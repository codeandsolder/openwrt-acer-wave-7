# RTL8367D MIB row freshness

Exact Acer 067 module SHA256: e2efdabbbc2c852ee9bf6b50a40c0759fbc470b95da77a7f524816ddb3db6120.
Inspect with llvm-objdump -dr --start-address=0x9efc --stop-address=0xa1d8 MODULE.
The internal reader at 0x9f7c uses the 59 u16 counter lengths at .rodata+0xa88,
matching the Linux per-port counter widths and offsets. Port stride is 124
words for ports 0–7; stock adds 68 words for ports above 7.

At 0xa00c stock reads 0x1004, the selected SRAM row. If equal to target,
it selects target+1, verifies readback and waits for 0x1005 busy bit 0
to clear, rejecting reset bit 1. Then it selects and verifies the target.
Data words are read high-first from 0x1000–0x1003, matching Linux.

The patch applies this refresh only to 0x6642 revision 0x0020, bounds
write retries, and uses an alternate row within the same port. Both
transactions remain inside the existing MIB lock.

The earlier stationary CPU6 counters motivate the audit but do not
prove a stale latch; that capture included several distinct SRAM rows.
Same-address-only staleness cannot explain all flat counters. Physical
corruption evidence remains separate. Next hardware A/B: repeated
counter reads correlated with device-bound physical packet captures,
including ordinary all-counter ethtool reads. No switch reset needed.

Offline test extracts actual driver functions: 496 repeated-row cases
plus 9 targeted cases covering 64-bit reads, ignored writes, reset,
timeout, transport errors and unchanged behavior for other chips.
