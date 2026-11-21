# 0492 conditional same-tuple host preservation experiment

0491 is not a fix for the original failure. On the exact approved boot,
a transition from 2.5G to 1G passed a 58.08-second dual-path measurement
(116/116 each, both PHY directions and GMAC counters advancing).
A subsequent actual 1G→1G peer autonegotiation restart caused PHY
down/up edges 5/6 2.08s apart. Over 61.48s: direct 0/120, independent
switch 120/120, copper ingress +84, PHY external-MAC ingress 0, GMAC
RX 0 and TX +8, zero new errors. Both full SGMII reconfiguration and
adapter pulse executed. Restoring peer 2.5G restored DHCP and both
paths in the same boot. Nine seconds of host interface administrative
down did not drop router-side carrier; do not count that as a PHY test.

0492 preserves the stock replay's decision boundary, not all stock
operations. Opt-in requires the exact Wave7 port2 QCA8081 ID and MDIO
address, single-channel IPQ5332 PCS, and no system sleep support
(the target NAND config has suspend and hibernation disabled).
PCS callback defers outband SGMII to PPE's MAC callback, which has
resolved TX/RX pause. Cache is private to the PCS and becomes READY
only after successful PCS, MAC, flow-control and bridge programming.
Mode/reset/config/enable/disable/teardown and error paths invalidate;
ordinary successful media-down leaves the tuple valid. Preserve only
same interface, negotiation mode, speed, duplex and both pauses on
a valid warm reconnect. All cold/changed/invalidated paths retain
0479 and 0480 setup. 2.5G, other boards/ports and PHY0491 unchanged.

The actual patched C callbacks and real SGMII force/speed/adapter
register operations execute in the host fixture, with mocked mode
calibration, clock hardware, GMAC and bridge. 400 negotiated tuple
pairs, cold and warm errors at every configuration step, ordinary
link-down failures, mode changes, stop/start, explicit config, bad
deferred tuple, and board/topology/sleep scope checks pass.

## Build

Use an immutable accepted image and exact accepted kernel build
directory. The build compiles both in-tree module targets together
with original managed cross-GCC sccache, original NAND config and
all 9541 built-in exports. Existing prod-integrated kernel vmlinux.o
provides the exact matching exported-symbol set, which is compared
to the accepted 0491 kernel's saved exports. The original stripped
modules must match the approved image byte-for-byte before patching.
The only new exports are the four coordinated PCS/PPE operations.

```sh
r=/home/jan/projects/wave7-qca8081-conditional-relink
b=/home/jan/build/wave7
p=/home/jan/firmware/wave7/builds/secondary-ap-20261120/stock-poll-fifo-dhcp-guard8/wave7-stock-poll-fifo-dhcp-guard8-sysupgrade.bin
PYTHONDONTWRITEBYTECODE=1 uv run --no-project --offline --python /usr/bin/python3 python \
  "$r/scripts/wave7/host/qca8081-stock-poll-fifo/conditional-relink/build-modules.py" \
  "$p" "$b/qca8081-stock-poll-fifo" "$b/qca8081-conditional-relink/verified-modules" --experiment relink
```

No kernel/FIT changes are needed: both drivers are modules, their
module metadata and dependencies remain identical, and modversions
are disabled in the accepted kernel. Retain both together; do not
hot-unload or live-replace networking modules. Use the normal guarded
secondary AP sysupgrade with the exact approved predecessor as rollback.

The original failure is now reproducible using standard peer PHY
autonegotiation restart with both endpoints already healthy at 1G.
Only pass 0492 if a new actual PHY down/up and same-speed reconnect
are observed with the explicit preservation marker, no new reboot,
and the strict directional observer passes for at least 30 seconds.

To build 0493, use a new output directory and `--experiment stock-mac-order`. The builder reproduces both exact 0491 and 0492 module hashes before applying 0493; only PPE may change relative to 0492. The packer uses the approved 0491 image, with the same FIT and independently verified 46 radio firmware files, not the failed 0492 image. See ../stock-mac-order/README.md.
