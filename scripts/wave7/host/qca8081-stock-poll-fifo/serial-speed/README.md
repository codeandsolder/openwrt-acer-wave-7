# 0498 — stock serial speed resolution, PHY-managed link

This is **not** another DTS managed=in-band-status experiment.
Oct29–30 native managed mode and early adapter prime both failed
NO-CARRIER. MODE_CTRL bit0 alone (0475) also failed the frame-blackhole
test. Stock ARM replay 39be19afea6ea6e71311f33b4eaa424aa78c32e3
establishes that the actual wrapper15 non-forced port2 path configures
both 0x46c bit0 clear (non-ATH format) and 0x480 bit3 clear before
calibration, with no later force-speed/speed-field write in the stock
worker. It still obtains link/speed/duplex/pause via copper PHY polling.

Test that *coupled PCS negotiation policy*, with normal MLO_AN_PHY
and all other approved0491 behavior retained (including cold SGMII
deferral, media-up calibration, raw clocks, adapter pulse). Only exact
acer,wave7 MPPE memory resource 0x7a10000, index0, no other channels,
OUTBAND SGMII. No 0492–0497 code in this image; untouched PPE, kernel,
DTB and PHY. This tests two related bits together; it does not identify
either alone as causal. Avoid conflating a failed PCS carrier read with
lack of frame transport. The log records actual mode/ctrl/status after
the pulse on each real SGMII link-up (not fake carrier).

Build with the exact accepted kernel config/export inventory, managed
sccache and byte-identical rebuilt 0491 PCS as control. The C fixture
extracts actual 8 driver functions and register definitions, exercises
mode selection, configuration, VCO reset, callback sequencing and
failure propagation with mock hardware; actual silicon behavior requires
a live test. A valid intervention requires marker mode&1==0,
ctrl&8==0, ctrl&0x800!=0, speed field not rewritten, exact driver hash.
Check repeated 2500→1000 and genuine 1000→1000, and 2500 recovery
with both source+device-bound observations and switch isolation.
No persistent approval until cold soak and reconnect gates.

References: original stock ARM trace sealed on Acer
/home/jan/build/wave7/qca8081-stock-host-replay/uniphy-mode-feature-20261122.
Public header confirms UNIPHY_AUTONEG_MODE_ATH and UNIPHY_CH_FORCE_MODE:
https://github.com/openwrt/qca-uniphy/blob/main/qca_uniphy.h

## PCS0 fixed-speed register policy (independent of PCS1 0498)

Stock instruction replay f24a9e9260 verified wrapper12, forced port1
2500/full. Patch 0500 applies the stock register personality only to
Wave7 MPPE PCS0 (0x7a00000, exactly one MII). Program 0x21c=0xa882,
force-speed bit and full MISC2=0x50 before mode selection, then clear
MODE_CTRL mask0x1f01 using a physical write. Retain native reset,
calibration, raw clock and link-up adapter sequence; do not equate
this with full stock initialization parity. Preserve read-only
handoff markers and verify the effective register policy after
calibration. Exact parent is 0498, not any RTL-order experiment.
