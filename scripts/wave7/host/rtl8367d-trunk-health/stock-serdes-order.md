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
