# Wave 7 – guarded ath12k-only sysupgrade A/B

Accepted OpenWrt: r0+38249-3b1851eda6, sysupgrade SHA256:
a952779383ba6d6c0847951354af2d59a96e46b9422fba4fb0cda6e92a9877da.
Never use the checkout's ordinary full image for this test: its
SGMII/FIFO experiment source differs from the accepted kernel.

The build_module_candidate.py tool opens the exact accepted image and
replaces ONLY the stripped lib/modules/6.18.60/ath12k.ko from the
current prepared kmod-ath12k build. It does not replace ath12k_wifi7.ko:
that module is byte-for-byte identical to the accepted version. Exactly
four revision-identification files plus etc/wave7-napi-trial are also
changed. The builder checks every SquashFS file and symlink, device
inode, unchanged kernel FIT, fwtool metadata, module vermagic and the
complete changed-file allowlist. It pins all input image/module hashes
and uses uv for Python.

Candidate: r0+38249-napi-5e3df9b898 (code commit 5e3df9b898)
SHA256: 18e285b7dbfac4075a4f675b23c9b97cbf51c50aced6c16a82d1aab439dc0622.
Acer output:
/home/jan/firmware/wave7/trials/20261116-napi-irq-ab/image-build/

This is ONE changed module, not one changed code path. It comprises
three post-accepted ath12k correctness changes:
* 720: QCN6432 hybrid CMEM window/error propagation.
* 721: IPQ5332 AHB IRQ setup error checking/resource cleanup.
* 722: Qualcomm upstream IPQ5332 grouped-NAPI IRQ disable imbalance,
  extended to QCN6432 hybrid MSI/NAPI.
All compiled with the project SCCACHE_SERVER_PORT=4228.
The A/B tests the combined driver hardening, not individual NoC causality.

## Guarded hardware experiment

The exact-revision Asus controller and watchdog live at:
/home/jan/scripts/wave7/napi-ab/flash-napi.sh
/home/jan/scripts/wave7/napi-ab/napi-watch.sh

The controller validates current accepted revision, healthy Q6/MLO,
wired Redmi peer, independent Wyse wired management, accepted rollback
SHA256 and all three passive Asus NoC monitors. It stages and verifies
the candidate and rollback images with sysupgrade -T, then launches
independent native and vendor observers BEFORE flashing. The native
supervisor requires 900 seconds continuously healthy after firstboot
acceptance, with two MLO links, Q6 running, peer ping, bootfail0,
keepboot and no NoC fatal. A NoC fatal, or prolonged unhealthy
Q6/MLO/peer status after acceptance, triggers native rollback using
the original exact-sha accepted image. Before acceptance, the
bootloader bootfail/vendor fallback owns recovery; no blind upgrade.

The observer flow was proven on the WBE1.4 A/B of 2026-11-16 when a
NoC fatal caused an exact-SHA native accepted rollback. The revised
decision logic has an offline selftest. Unreachable targets leave
independent observers running, not a forced upgrade.

Use Wyse via ssh wyse-eth (ethernet management eno1 and MT7925 client
wlp2s0); preserve Asus irq-<boot>.tsv, /dev/kmsg and devcore collectors.

Passing 900 seconds does not prove that intermittent UMACNOC fatal is
fixed. Compare actual pre-fault IRQ records and retain uncertainty
until longer observed runtime.
