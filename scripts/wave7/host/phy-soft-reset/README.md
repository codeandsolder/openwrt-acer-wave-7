# QCA8081 live copper-PHY soft-reset recovery trial (2026-11-15)

This is a **one-shot hardware experiment**, not a released recovery fix. It
specifically tests whether a full QCA8081 *copper PHY* software reset repairs
the proven postboot PHY/host SGMII packet blackhole. This differs from failed
host-PCS reconfiguration, phylink recycle and PHY+1 SGMII FIFO hold/release.

Primary implementation evidence:
- Linux `drivers/net/phy/qcom/qca808x.c:qca808x_soft_reset()` calls
  `genphy_soft_reset()`, then restores QCA8081 master/slave seed config.
- `drivers/net/phy/phy.c:phy_mii_ioctl()` calls `phy_init_hw()` when a
  userspace Clause22 `BMCR_RESET` write is issued; the reset is *not merely*
  a disconnected raw MDIO write with abandoned driver state.
- Qualcomm QSDK13 `qca/src/qca-nss-phy/nss_ext/qca808x_phy.c`
  distinguishes `SOFT_RESET` (common PHY reset) from the QCA8081-specific
  `FIFO_RESET` at SerDes+1 MMD1.0x9072; QCA8081 does **not** support the
  QCA8084-only PLL on/off helper.

The controller performs only one **independently restored** nine-second
Redmi `lan2` flap. If and only if the on-router monitor verifies copper link
restored, peer unreachable *and* GMAC RX counter stalled for 30 seconds, it
logs PHY SerDes, PCS and MIB state, records copper PHY C22 interrupt status
(0x13) once, then writes `BMCR_RESET=0x8000` to copper PHY MDIO24 with
`phytool write lan/0x18/0x00 0x8000`. It accepts **same-boot** recovery only
when hardware GMAC RX increases **and** the peer exchanges ICMP afterward.
Otherwise the monitor triggers the existing firstboot-backed diagnostic
SysRq reboot. An independent boot-bound on-router hard-guard handles monitor
failure. External Asus new-boot and fallback watchers run for the trial.

Execution on Asus requires copy of these three files under
`/home/jan/scripts/wave7/phy-soft-reset/`. From Asus, invoke
`controlled-flap.sh --check`, then `controlled-flap.sh --run`. Evidence is
under `/home/jan/firmware/wave7/trials/20261115-qca8081-soft-reset/`;
retain the failed boot's pstore on automatic reboot. The controller's source
SHA checks must match the exact deployed scripts. Do not run it without
healthy native 3b1851eda6, bootfail0, the independent Redmi management path,
and no outstanding on-device trial tokens/timers. See Notion project's
linked experiment register for prior negatives and source revision.
