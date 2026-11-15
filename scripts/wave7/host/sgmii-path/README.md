# IPQ5332/MPPE PCS1 ↔ QCA8081 SGMII path — passive evidence

The snapshot script has two read-only actions: --snapshot (for both
healthy and failed boot) and --check (requires 12 critical Linux
common-clock-framework branches enabled and at healthy rates).
It does not arm a trial, touch the PHY/PCS link, or consume clear-on-read
QCA8081 MMD7 counters. The existing Linux driver owns MMD7 accumulation.

## Evidentiary limits

In deployed Linux6.18.60, PCS1 debugfs reports MII control 0x084c,
force=1 and MII status 0x00e0, link=1. Source:
drivers/net/pcs/pcs-qcom-ipq9574.c ipq_pcs_config_sgmii()
sets PCS_MII_FORCE_MODE when negotiation is not in-band. Therefore the
PCS MII link bit is NOT independent evidence of SerDes CDR lock or
correct frame decode. The copper PHY carrier only reports copper link.

Linux clk_summary records enable/prepare counters and configured rates,
NOT sampled analog clock edges or actual recovered-clock lock.
A bad-only disabled clock would discriminate an NSSCC clock gate
fault. All enabled clocks do not prove working serial reception.

Healthy reference (~2026-11-15 16:00 CET): PCS1 PHY ref 50 MHz,
PCS1 RX/TX 125 MHz, NSS port2 RX/TX path 125 MHz and MAC clock
200 MHz, 12 total entries all enabled/prepared, hardware enabled Y.
These are runtime 1G SGMII expectations; do not reuse for 2.5G.

To use this capture for a *novel* guarded trial, execute after a
confirmed zero-RX fault and append the short output to /dev/kmsg before
any planned recovery crash. That integration is NOT deployed here;
don't repeat a known-negative link-flap/reset experiment solely to
capture the clocks. The QCA8081 pseudo-PHY normal mode values are
read-only; MMD1.0x006E PRBS BITSYNC=0 during healthy traffic and does
not prove CDR loss.
