# IPQ5332 NSSCC input index correction (0494)

Discovery: November 21 2026, following the November 8 IPQ6018/IPQ8074
clock-parent series:
https://lists.openwall.net/linux-kernel/2026/11/08/288
and https://github.com/openwrt/openwrt/pull/26205 (different SoCs/driver,
clock output naming). The earlier port5 wrong-instance frequency table
problem (https://github.com/openwrt/openwrt/pull/24566) does NOT directly
apply: IPQ5332 port2's 25/125MHz choices already use UNIPHY1 exclusively.

Independently confirmed local bug: nsscc-ipq5332.c DT enum TX-first
for each pair, binding/DTS RX-first. The prepared source's PCS provider
uses PCS_RX_CLK=0, PCS_TX_CLK=1. Exact accepted 0491 FIT c2895986...
contains DTB SHA256
5eb62be61f9551eb44bb1b40622f2c77d515192da8fa3efe71430c61e90c6302.
Both pairs of actual DT phandle specifiers are RX0/TX1; input enum
causes port RX RCG logical parent = TX and vice versa. Patch changes
only four enum entries, not hardware SRC_SEL (RX3/TX4), divider or
frequency tables. All four mapping tests pass on actual FIT and source
after correction; before correction all four are swapped.

Run check-parent-order.py with uv, exact accepted FIT and prepared
kernel source directory. --expect swapped proves old bug; --expect
correct proves fix. Checks actual DT cell counts and phandle providers,
the PCS binding indices, NSSCC parent maps and positional parent_data.
No hardware access.

The clock graph error does not prove a physical mux error. The PCS RX
and TX recalc_rate both return the same configured-interface-derived
rate, so measured/wire-level effect is unknown. Test independently of
0492/0493 on approved 0491; no repeat of known-negative resets.

Next measurement: NSSCC port2 RX CMD/CFG/DIV offsets 468/46c/470,
TX 474/478/47c; PPE RX/TX branches 490/498; PCS RX/TX branches 4bc/4c0;
MAC branch 430 (all hexadecimal, NSSCC base 0x39b00000). Use exact
documented regmap offsets and read-only observation, not writes.
CMN/PCS rates are not physical frequency measurements. Avoid broad
register dumps across unknown fields.
