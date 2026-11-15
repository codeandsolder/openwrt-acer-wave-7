# Wave 7 QCA8081 FIFO-notify A/B — NEGATIVE (2026-11-15)

Source patch 0490, experimental native firmware r0+38257-0078d29fd0,
OTA SHA256 5e6a9277dc29117bd801e43da6b46d3f84b14d4e753b603df9913185e8cf7a86.

## Hypothesis and one-variable intervention

Stock Acer Linux5.4.213 qca-ssdk.ko symbol qca808x_link_change_notify
(0x69644) is bx lr, whereas upstream Linux6.18.60 changes QCA8081
pseudo-SerDes MMD1.0x9072 FIFO_RSTN on every copper link change.
Patch 0490 removes ONLY automatic FIFO transition writes; existing
hardware and PCS diagnostics remain. This differs from previous
additional FIFO reset/release trials and copper PHY BMCR reset.

Complete OpenWrt kernel compile, kmod/base-files/rootfs/FIT packing,
source marker checks and independent packed FIT/kernel/SquashFS/DTB/
ath12k verification passed. Forward native guarded OTA was accepted
on boot a06853ab-f319-45a9-973e-c7ddcc18e8b9, bootfail0/MLO2/
wired peer2/2, and running dmesg proved fifo_action=preserved.

## Actual matching physical result

One guarded nine-second Redmi lan2 link loss 16:43:40 CET,
autonomous port restore 16:43:47, with active independent traffic.
The unchanged normal copper PHY receive side accepted CRC-good frames
2020 -> 2051 (+31); the PHY external-MAC receive count stayed 1688
and host GMAC receive stayed 2016 after recovery of carrier.
No PHY FIFO transition writes occurred (kernel logged preserved at
both link-down and link-up). The on-router monitor classified
RX_STALLED_30S_AFTER_LINK_UP at uptime346.428.

The read-only failure-time clock-framework snapshot showed all twelve
expected host PCS1 / port2 NSSCC / UNIPHY clock branches prepared,
enabled, with expected 50/125/200 MHz programmed rates and HW=Y.
Host PCS MII link1 was forced mode and is not serial lock evidence.
No PHY+1 test-pattern lock indicator changed from healthy state.
The monitor then deliberately triggered SysRq panic for ramoops.
Original failed-boot pstore is SHA-preserved on Asus.

Autonomous recovery to same test firmware boot
2921e05f-dbe5-497e-a456-5802eb952c98 passed bootfail0, MLO2,
Q6 3/3, bidirectional wired peer and later Wi-Fi7 MT7925 client
reassociation. Observers and trial tokens were stopped/cleared.

**Outcome:** Automatic link-change FIFO hold/release is NOT the sole
root cause; do not repeat this negative A/B as a fix.

## Versioned orchestration / artifacts

The tested Asus scripts are preserved here:
- flash.sh: bounded native OTA, original accepted -> experimental
- controlled-flap.sh: one nine-second flap, traffic witness,
  independent guard, postfailure pstore and postpanic acceptance
- wave7-postboot-link-monitor.sh: RX classifier, PHY/PCS/MIB/CCF
  read-only diagnostics, deliberate panic on proven failure
- wave7-postboot-hard-guard.sh: independent timer
- restore-accepted.sh: native return to accepted 3b1851eda6 image

Raw data and SHA evidence manifest (on Asus):
/home/jan/firmware/wave7/trials/20261115-fifo-notify-ab/postboot/fifo-preserved-carrier-flap-20261115-164331/

Previous accepted firmware used for restoration:
r0+38249-3b1851eda6
SHA256 a952779383ba6d6c0847951354af2d59a96e46b9422fba4fb0cda6e92a9877da

Full build/OTA logs, images and captures remain in dedicated
/home/jan/firmware/wave7/trials/20261115-fifo-notify-ab on Acer/Asus,
not in the git source tree. Notion Wave7 current-state page points
to the detailed original failed-boot register/counter trace.

Future P0 needs an actual QCA8081 SerDes receiver / host symbol
alignment/lock/error signal or a validated directional test. Normal
CCF clock-gate state and forced PCS link status do not prove CDR lock.
