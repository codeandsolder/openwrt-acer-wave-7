# QCA8081 copper-side remote PHY loopback healthy control

QSDK13 qca808x_phy_ops_init wires QCA8081 remote_loopback_set to
nss_phy_common_remote_loopback_set; that function modifies only bit0
(NSS_PHY_MMD3_REMOTE_LOOPBACK_EN=1) in copper PHY MMD3 0x805a.
Source: everything411/qsdk branch 13.0, nss_ext/nss_phy_common.c/.h
and qca808x_phy.c. Qualcomm 80-Y0615-3 names this REM_PHY_LPBK.
It loops copper-partner RX toward the copper partner: not host SGMII BERT.

First measure only on a healthy link, with Redmi LAN2 up and external
Redmi management through 10.1.0.2. Capture tcpdump -Q in filtering
for Redmi's own source MAC on lan2; generate bounded ping frames from
Redmi while loopback is enabled. This only establishes a valid
test if self-originated frames are actually observed returning.

Read-only wave7-start.sh --check asserts health and unmodified
0x805a=0x3002. --run arms a detached on-router restoration process
BEFORE setting only bit0 (0x3003). After eight seconds the process
restores exactly the saved register, verifies readback, and 20 seconds
later checks connectivity. On link-up-but-unreachable failure it uses
the existing diagnostic panic to recover the native image. No reset or
other PHY register manipulation.

No failed-state inference until the healthy control is positive.
Staging path /tmp/wave7-remote-loopback-*.sh on router; durable source
in this repo; logs in the scoped Asus trial directory.

## Nov15 15:38 live status and stock-driver cross-check

* Read-only healthy direct-cable Redmi test: tcpdump -Q in on lan2 with
  'ether src 88:c3:97:4e:93:57' captured **zero** incoming frames with
  Redmi's own source during four normal 4/4 successful ICMP pings; capture,
  stderr, packet logs and SHA manifest: Asus
  /home/jan/firmware/wave7/trials/20261115-remote-loopback/read-only-capture/.
  This is a negative baseline, not a passing reflected-frame healthy control.
* Tested router 0x805a=0x3002; --check passed. Tool policy blocked the
  activation-controller edit before any PHY register write. No loopback
  was enabled, no firmware updated, no reboot, and the staged /tmp scripts
  were removed with no arm token or PID present. This folder remains
  **source-only / hardware activation untested**. Do not interpret the
  baseline as a successful loopback test.
* Stock original unstripped Acer qca-ssdk.ko (Linux 5.4.213):
  qca808x_phy_reset at 0x67adc has the MMD1 bit15 soft-reset/poll path
  only for PHY ID 0x001cc849, while QCA8081 ID 0x004dd101 follows
  qcaphy_sw_reset (the already failed copper reset). PLL helper dispatch at
  0x66dcc/0x66e20 is similarly limited to the other PHY IDs 0x001cc849
  and 0x004dd180. No stock-driver evidence that QCA8081 supports that
  analog SerDes reset/PLL on-off sequence. Do not copy those writes.
  qca808x_phy_interface_set_mode at 0x67c50 invokes MHT work-mode/SGMII
  configuration only after qca_mht_sku_uniphy_enabled; Acer IPQ5332
  application of that path is unproven.
