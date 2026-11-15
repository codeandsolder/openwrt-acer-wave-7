# Acer Wave 7 supervised boot-test harness

These scripts are the source-controlled canonical copies of the small
supervised vendor sysupgrade/observation harness deployed on Asus under
/home/jan/scripts/wave7/. The Asus copies have been updated to match.

- wave7-openwrt-watch.sh TRIAL_TAG EXPECT_KERNEL EXPECT_REV: read-only
  observer. Requires the exact Linux version and ten-character git revision;
  collects boot/driver/network logs and reports radio-ready only if all three
  remote processors are running, both MLO links are visible, the wired peer
  is reachable, and the router's current-boot keep marker exists.
  It also records the actual MTD/UBI inventory. The companion
  verify-factory-mtd.sh validates all 27 recorded factory NAND partitions
  by name, size and erase geometry against factory-mtd.tsv, extracted
  from the intact 2026-10-28 full NAND backup, ignoring additional
  kernel-created UBI-volume MTD entries. It prints NAND_SMEMPART_READY=1
  only when the complete physical NAND layout matches; discrepancies
  are included in the capture. NAND discovery remains independent of
  the separate radio-ready decision.
- wave7-fallback-watch.sh TRIAL_TAG: independently observes recovery to
  the stock vendor kernel and preserves pstore/raw ramoops evidence.
- wave7-trial-flash.sh TRIAL_TAG WRAPPED_IMAGE EXPECT_KERNEL EXPECT_REV:
  NAND-writing guarded updater. Refuses unless the router is running the
  original vendor kernel 5.4.213 with bootfail=0, verifies the local and
  on-router image SHA, validates the OTA wrapper, starts both managed watchers,
  arms bootfail=4, then invokes sysupgrade.

The flash entry point is NOT the RAM-only boot mechanism; it will write
the NAND rootfs UBI volume. Do not run it as a diagnostic/preflight and do
not reboot a known-working OpenWrt initramfs just to satisfy its vendor
precondition. It does not provide a working U-Boot serial/TFTP recovery route.

The **historical 2026-11-09 proven OpenWrt 6.18.60 RAM-boot lab image was d72fd34a45**
(BCH-8/512). Seven supervised vendor OTA trials culminated in a
successful NAND ECC-corrected initramfs router at 2026-11-09 16:35 CET:
all 27 factory SMEM MTD partitions and ART calibration pages 2/3/4/16
match the 2026-10-28 backup byte-for-byte, with 0 ECC failures and 5
corrected bits. Three Q6 processors and both MLO links were running,
LAN and the wired peer were reachable, and the live keep-boot marker
was set before the failsafe deadline. This validates NAND reads and
the AP, **not persistent rootfs or future power-cycle behavior**.

The tested **BCH-8 RAM-boot FIT** on Asus is
/home/jan/firmware/wave7/trials/wave7-d72fd34a45-bch8.itb
(SHA-256 01c6a24ba77d05f0c032003bb6319bbdead918e864aa1ce86cb2de5e777e0d2e).
The audited NAND-writing OTA, already used in successful trial seven, is
/home/jan/firmware/wave7/trials/wave7-current-61860-d72fd34a45-bch8.bin
(SHA-256 2581fc54b4c6b281dc02def9bfdad85d90a3201f2ee8861a879d08c550b220d8).

The previous working **BCH-4 image** cfb425bcad remains stored
separately on Asus at
/home/jan/firmware/wave7/trials/wave7-cfb425bcad-known-good.itb
(SHA-256 9b3a4a2b7fa5d7a59e7004eedca6ca89039ca1619c22fbb58c4dc016617a7353).
Its radio worked, but its NAND ECC setting demonstrably read factory
ART data incorrectly; preserve it as historical recovery only.

Successful seventh-trial observer snapshot, ART validator logs, update
log and recovery watcher are preserved on both Asus and Acer in
/home/jan/firmware/wave7/logs/bch8-trial-20261109/.

For the separate, read-only QPIC ECC investigation, see nand-ecc.md.
For the controlled UART/U-Boot RAM boot plan, see ram-boot.md.
For persistent NAND root and vendor-preserving overlay design, see storage-boot-plan.md.

The distinct experimental production `wave7-nand-squashfs` branch builds
a 22.55MB vendor OTA containing the **normal OpenWrt FIT and SquashFS**,
not the vendor SquashFS. It passed full offline UBI byte/CRC verification
and passed its first native NAND-root hardware boot on 2026-11-09. See storage-boot-plan.md for SHA256s
and staged hardware-verified artifact; the previous working `d72fd34a45` BCH-8 initramfs
remains the proven recovery baseline.

## Current native lab image (2026-11-15)

Installed and accepted NAND-native OpenWrt6.18.60 is
r0+38249-3b1851eda6, packed sysupgrade SHA256
a952779383ba6d6c0847951354af2d59a96e46b9422fba4fb0cda6e92a9877da.
After proving experimental FIFO link-change suppression ineffective, we
reinstalled this accepted image with guarded OTA; bootfail0, keepboot,
Q6 processors 3/3, MLO AP links 2/2 and wired peer all passed.
Primary source branch remains wave7-q6-phy-path-integration. The
authoritative evolving status is the Notion page:
https://app.notion.com/p/400f74be902081c0a3bef13c819b8320

## Q6 SSR validation (2026-11-15)

The native integrated firmware `r0+38244-b5e17c3979` was accepted on
real hardware; boot success alone does not prove in-place root-Q6 recovery.
`observe-q6-ssr.sh --check` and `--capture` run **on Asus** via the already
configured Wave 7 root SSH identity, without changing hardware state. Captures
are SHA-manifested in `/home/jan/firmware/wave7/trials/20261115-q6-phy-integration/q6-ssr`.

`q6-recovery-guard.sh --check` is the read-only on-device preflight of a
boot-ID-bound and per-trial-token guarded recovery timer. Its crash-recovery
branch is **not validated** and must not be armed until the control-plane
recovery experiment has independent observers and a genuinely associated MLO
station. The separate Nov 15 Notion implementation checkpoint records the
hardware status and acceptance gates; source-side instructions live here.

The MT7925 test station is Dell Wyse wifi7-lab.home. Its independent
Ethernet management interface eno1 is 10.1.0.221/16, and Wi-Fi interface
wlp2s0 is normally 192.168.76.145/24. As of 2026-11-15, Acer connects
to Wyse directly over Ethernet: use SSH host alias wyse-eth, configured
under /home/jan/.ssh/config on Acer, user jan, with the already-existing
Acer identity ~/.ssh/cold-storage-wrangler (Ed25519 public-key SHA256:
ZdGRoup5Sy7Jy37osT1wTMi66B8+XlUU5mjH93T3IMU). Its public key was
added idempotently to Wyse authorized_keys, preserving the existing key.
The separate cold-storage SentinelX key was not copied. The former
temporary Acer Tailscale TCP port 22221 SSH relay is no longer needed
and was stopped and verified inactive after enrollment.

The Wyse Wi-Fi profile Wave7-MLO-Lab intentionally has
connection.autoconnect=no; to re-associate without touching independent
wired management, run on Acer:

    ssh wyse-eth 'sudo -n nmcli connection up Wave7-MLO-Lab ifname wlp2s0'

After the Nov15 rollback, router-to-Wyse ICMP initially failed despite
association, but recovered without changes to the AP: 2/2 router-to-Wyse
and 5/5 Wyse-to-router ping succeeded later. Avoid treating just-associated
STA ARP/ping transients as persistent WLAN failure.

Wyse's clock had been stuck on 2026-10-20 (RTC near Jan 2012) with NTP
disabled. On Nov15, normal systemd-timesyncd was enabled via
sudo timedatectl set-ntp true. It is now enabled, active and
NTPSynchronized=yes (pool.ntp.org stratum 2), enabling correct alignment
of timestamps across Wave7, Redmi and Wyse.

The extra q6-ssr-observer.sh captures root/child state and AP/STA/peer
health at bounded intervals to an Asus trial directory; it does not
trigger any crash. Root-Q6 in-place SSR remains UNTESTED.

With an MLO STA active, the guard also accepts an optional fourth argument:
the station IPv4 address. At expiry it verifies that a station is associated
and the AP can ping that address, in addition to root/child `running`,
positive transmit power on two AP links, and wired peer reachability.
**This is still an unvalidated recovery primitive**, not an established
crash-recovery acceptance test. Never start it without an independent
management observer and a real client; always remove the matching arm token
when aborting an experiment.
