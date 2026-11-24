# RTL8367D exact stock SerDes initialization order

The exact Acer 067 ARM32 module is pinned by SHA in replay-stock-serdes.py.
Run: uv run replay-stock-serdes.py /path/to/rtl8367s_sw.ko

The stock init_sw at 0x1c calls rtk_port_macForceLinkExt_set at 0x19c
with logical port16, mode10 and ability words [1,4,1,1,0,1,1], then
rtk_port_sgmiiNway_set(port16,0) at 0x1a8. The family D logical port16
maps to physical MAC6/SDS13 (confirmed by prior portmap work).

Actual stock mode routine 0xd524, MAC force get/set 0xc854/0xc6cc,
NWAY 0xeff0 and original ASIC read-modify-write functions execute in
an offline ARM emulator. The mock boundary is the raw SMI bus, port
identity, initialized SDK state and libc memset; no device accesses.

80 combinations of SGMII/HSGMII, existing SDS_MISC fields and NWAY
values/enable tested. For HSGMII the stock sequence is:

1. Clear line-rate bypass bit1 in ASIC 0x03f7.
2. Select MAC6/SDS0 bit9 in 0x1d11, before the ten SDS13 tuning writes.
3. Write 0x13e8 bits7:6 = 1 (physical field value 0x40).
4. Set 0x1d11 bit10 (PA12), then bit11 (PA33), then low-five-bit mode
   0x12, using separate RMW writes even if values were already set.
5. MAC force: clear link bit4 in 0x12c6; write complete forced
   ability with link0; write 0xffff to 0x12ce; then write link1 ability.
   For the initial stock 2.5G ability the writes are 0,0x1065,
   0xffff,0x1075 given initial MAC ability0.
6. NWAY: temporarily disable DW8051 (0x130c bit5) if enabled,
   read SDS13 reg2, clear bit9/set bit8, then restore DW8051 state.

The stock setAsicRegBit and setAsicRegBits functions always issue an
SMI write even if the old value already matches, unlike Linux
regmap_update_bits. The stock init path does not write SDS13 registers
0x0003 or 0x0000 after the tuning table. Native Linux inherited explicit
reset/deassert and BMCR datapath-reset writes from the family C flow.

Independent potential experiment dimensions:
- Mode selection ordering/forced RMW: preserve native reset/NWAY and
  MAC force code. Change only the pre-tuning mux and post-tuning
  separate writes for the evidenced 0x6642 revision0x0020.
- MAC ability publication order: link down before enabling force,
  link up last. Keep all SerDes tuning and reset behavior unchanged.
- Family C extra reset writes: the stock direct mode routine omits them,
  but stock runs DW8051; absence alone is not proof they are unnecessary.
  Do not remove them until a separate controlled hypothesis is justified.

Equal final registers are not evidence of equal transition sequences.
No physical receiver lock, clock waveform or CRC outcome is modeled.

## Stock reset API dispatch (2026-11-24)

The stock module contains a generic `rtk_port_sds_reset` wrapper at
0x52f4, but the actual RTL8367D mapper getter at 0x8790 returns .data
offset 0xf5c. The wrapper's callback slot at +0x2ec (.data 0x1248)
is zero and has no relocation. The replay now executes the actual
getter and wrapper with the installed mapper, demonstrating return
18 for ports 0, 16, 17 and 0xffffffff without calling a reset routine.
There are no direct CALL/JUMP24 relocations to the reset wrapper.
This is additional evidence that explicit SDK SerDes resets are not
part of the RTL8367D stock host sequence, not evidence that its running
DW8051 performs no corresponding initialization. Keep this separate
from the lane-order and MAC force-order experiments.
