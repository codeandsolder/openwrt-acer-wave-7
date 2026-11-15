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
