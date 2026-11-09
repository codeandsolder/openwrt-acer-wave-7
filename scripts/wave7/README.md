# Acer Wave 7 radio firmware

The Acer Wave 7 requires Qualcomm IPQ5332 and QCN6432 firmware,
calibration and BDF files used by the known-working two-link MLO image.
They are deliberately **not** included in this public source repository.

Use a private source tree containing IPQ5332/hw1.0 and
QCN6432/hw1.0. On Acer, the canonical copy is
~/firmware/wave7/vendor-radio/ath12k/; it was preserved from the
working Linux 6.18.55 build.

Before building the firmware image, run:

~~~sh
scripts/wave7/stage-firmware.sh stage
make -j5 package/compile
make -j5 package/install
make -j5 target/install
~~~

Optionally set WAVE7_FIRMWARE_SOURCE to a different private source tree.
The stage command checks **every** file against firmware.sha256, then
copies the verified complete tree into the standard, Git-ignored OpenWrt
files/lib/firmware/ath12k overlay. Image recipes verify the installed
rootfs against the same manifest and refuse to produce an incomplete image.
Never commit the binary overlay.

The sysupgrade bundle is not proof that NAND installation is safe. Until
partition handling and recovery are validated, use the initramfs FIT
artifact for subsequent controlled boot tests.

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
