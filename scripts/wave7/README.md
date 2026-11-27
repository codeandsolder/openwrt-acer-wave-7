# Acer Wave 7 radio firmware

The Acer Wave 7 requires Qualcomm IPQ5332 and QCN6432 firmware,
calibration and BDF files used by the known-working two-link MLO image.
They are deliberately **not** included in this public source repository.

Use a private source tree containing IPQ5332/hw1.0 and
QCN6432/hw1.0. On Acer, the canonical copy is
~/firmware/wave7/vendor-radio/wbe1.4-01734/ath12k/. The current pin is
WLAN.WBE.1.4-01734-QCAHKSWPL_SILICONZ-1.162738.2.173996.1, preserving
Acer calibration and BDFs and the exact 46-file set in the hardware-validated
WBM image (SHA256 d30dc49c63ec5d3d803f2875b29a68ce6055f3f51ecf7e75a2bedf8346d5157a).

Before building the firmware image, run:

~~~sh
scripts/wave7/stage-firmware.sh stage
make -j5 package/compile
make -j5 package/install
make -j5 target/install
~~~

Optionally pass a different private source tree as the second argument to stage.
The stage command verifies the **45 private vendor files** against
firmware.sha256 and the separately versioned QDSS trace configuration
against diagnostic-firmware.sha256. It assembles the complete 46-file
tree into the Git-ignored OpenWrt files/lib/firmware/ath12k overlay.
Image recipes verify the installed rootfs against **both** manifests and
refuse incomplete, altered, or unexpected firmware files.

The QDSS diagnostic configuration is maintained as a tiny, non-vendor
source artifact in scripts/wave7/diagnostic-firmware/. Never commit the
assembled binary overlay or the private vendor blobs.

The image recipe builds and checks **two distinct DTBs** from one hardware
description: normal persistent NAND-root boot (root=/dev/ubiblock0_2)
and a RAM-only initramfs variant (root=/dev/ram0, rdinit=/init,
ubi.no_autoattach=1). A build fails if either DTB's bootargs-append
differs from its pinned mode. Never use a NAND-root DTB in a RAM boot FIT.

The sysupgrade bundle is not proof that NAND installation is safe.
The dedicated RAM-root FIT is for supervised UART/U-Boot RAM boot only;
see host/ram-boot.md for the independent recovery requirements. Neither
output is authorization for an unattended flash.

## Optional private two-link MLO lab configuration

The working OpenWrt 6.18.55 setup generated its LAN and WPA3-MLO UCI
configuration after boot. Those live settings are not part of the source
tree. Before an image intended to reproduce the working lab AP, run:

~~~sh
scripts/wave7/stage-lab-config.sh
make -j5 package/compile
make -j5 package/install
make -j5 target/install
~~~

The script copies network (static 192.168.76.1/24 wired LAN) and
wireless (2.4GHz EHT20 + 5GHz EHT80, Wave7-MLO-Lab, SAE MLO)
from a private snapshot at
~/firmware/wave7/configs/working-61855-a668b62dec/.
Set WAVE7_LAB_CONFIG_SOURCE to override the private source location.
This is an **opt-in lab overlay**, not a production configuration.
The config is only staged in Git-ignored files/etc/config and is
never committed with the public source. Keep this source snapshot for
regression tests following future kernel and driver updates.
