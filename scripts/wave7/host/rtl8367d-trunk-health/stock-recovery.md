# RTL8367D (Acer stock 067) DW8051 observations

The exact firmware is 1545 bytes, SHA256
`ec5332a6bcc1a67a2202ffbf7b44a87c8fad412a907c9f65edf7602bab0bffd9`.
It is extracted from the 067 arm32 stock module
`rtl8367s_sw.ko`, SHA256
`e2efdabbbc2c852ee9bf6b50a40c0759fbc470b95da77a7f524816ddb3db6120`,
at the .data relocation +0x16d4 identified in the RTL8367D init routine.
Do not redistribute the vendor binary; supply the user's own extracted image.

Run `uv run --no-project python trace-stock-recovery.py DW8051_BIN`.
The exact instruction replay intercepts the ASIC read/write and delay
helpers. It validates dataflow at the register boundary, not bus timing,
analog behavior or the actual silicon response.

## SerDes routine (0x000e)

SDS13/15 only, disabled-mode guard (low 5 bits == 31), double link-down
test at SDS 0x003d bit4 with delay argument 500, diagnostic counter at
0x13a1 + lane, then SDS 0x003f bit5 assert, SDS 0x0400 bit2 assert/clear,
and SDS 0x003f bit5 clear. Each step reads the current 16-bit value and
preserves other bits. The native Linux candidate gates the same pulse
on persistent failure, not normal traffic. Real corrupt-only link-up
efficacy remains untested.

## Copper routine (0x02ad)

The main loop calls this routine before each SerDes lane. Five ports 0–4
only. For every port it reads ASIC 0x12d0 + port. The read wrapper
0x0372 stores R6 then R7, leaving the LOW byte in A; the bit tests are
A.6 and A.2, not bit14. Stock `dal_rtl8367d_port_macStatus_get` independently
identifies those positions as the MAC pause and duplex status fields
(the link bit is 4 and not used in this routine).

- Both clear: write 0x0060 to 0x12c0 + port (force data), then
  0x12c8 + port (force enable); force only the two pause bits.
- Both set: read 0x12c8 + port; if nonzero, write 0 to both registers.
- Mixed bits: no write.

The test covers all 4^5 status combinations with force-enable zero and
0x0060, plus mixed unrelated force values. Unrelated status bits are
nonzero in the exhaustive cases. This is a copper pause workaround,
not a CPU-port SerDes latch operation. Linux forces outside interfaces
only, and manages internal PHY ports through phylib. Do not transplant
the vendor copper override blindly into the healthy native driver. A
separate copper flow-control symptom and targeted local-port evidence
would be required.

The stock main loop increments 0x13a0; the lane recovery routine
increments 0x13a1 + lane. These are observed counter operations,
not production Linux writes. Their exact hardware register definitions
remain unknown.
