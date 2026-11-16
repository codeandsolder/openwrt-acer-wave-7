# Wave 7 WBE1.3 to WBE1.4 offline firmware-family audit

Acer Wave7 accepted native WBE1.3-03279 versus public GL.iNet Slate7
WBE1.4-01734, 2026-11-16. No router firmware changes or flashes.

Candidate repository: https://github.com/fivefold3/openwrt-gl-be3600
branch gl-be3600, directory files/lib/firmware/ath12k.
All 22 IPQ5332 and 11 QCN6432 GitHub files were size/blob-SHA
verified and stored ONLY in:
 /home/jan/firmware/wave7/trials/20261116-wbe14-compat/gl-fw14/
The audit JSON is in that trial directory, not checked into Git.

Run from Acer primary OpenWrt repo:

    PYTHONDONTWRITEBYTECODE=1 uv run --no-project --offline --python 3.13 python scripts/wave7/host/q6-firmware-audit/audit.py --accepted files/lib/firmware/ath12k --candidate /home/jan/firmware/wave7/trials/20261116-wbe14-compat/gl-fw14 --report /home/jan/firmware/wave7/trials/20261116-wbe14-compat/structural-audit.json

STRUCTURAL_PASS: all five root/PD/IU split MDT images are internally
self-consistent, nonempty .bNN lengths match their indexed ELF32 PHDRs,
entries are contained in PT_LOADs, and the 14 physical PT_LOAD intervals
are disjoint inside Acer's DT WCSS reservation 0x4a900000..0x4ca00000.
The internal and external UserPD firmware report the SAME revision,
WLAN.WBE.1.4-01734-QCAHKSWPL_SILICONZ-1; accepted pair reports 1.3-03279.
This is only a *structural* pass, not a runtime or security acceptance.

CRITICAL Acer DTS path: external UserPD2 firmware-name refers to
ath12k/IPQ5332/hw1.0/q6_fw2.mdt, although canonical external firmware
is also in ath12k/QCN6432/hw1.0. The accepted overlays are byte-identical.
Any candidate image needs the new q6_fw2.mdt and all split .bNN files at
BOTH paths, plus complete q6_fw0, q6_fw1, and both IU sets. Existing
.mbn aliases also need coherent updates. Do not mix generations.

The QCN6432 GL board-2.bin database contains 13 named entries,
including board ID 83 (0x53, same as Acer DT) with length 100352 and
same first 12 BDF header bytes. But its board ID83 payload SHA256 is
7d4f02efdc2ad277991798c18a5a5f700417d4cbce590350b1273bdc488287d4;
the Acer QCN board.bin SHA256 is
f63bb6540a01b18dd342493f7cac32573ceb5888b048a92da6600a21633f42f7.
They are NOT identical. GL also lacks Acer IPQ board/caldata files.
Keep Acer board.bin, caldata*.bin, fw_ini_cfg.bin and regdb.bin; avoid
replacing them automatically with GL's radio calibration or regulatory
data. A matching BDF layout does not prove new firmware BDF acceptance.

The Qualcomm signed root Q6 hash blobs contain X.509 root CA6 and SubCA1
that are BYTE-IDENTICAL between old and new. Shared root SHA256 cert
fingerprint:
6D:8D:59:5F:C1:AD:2F:80:38:3F:26:64:53:F9:B4:8B:35:F4:8A:09:7C:C8:1B:1E:C2:82:16:1C:56:1D:47:F6
Shared intermediate fingerprint:
94:5D:44:CE:F4:35:81:75:01:A7:0B:DC:61:C1:56:C0:ED:55:05:04:A0:65:80:10:4E:E6:2F:FA:DB:6D:74:03
Leaf signing certificates differ. This is not proof that target secure
boot or antirollback accepts the newer signed image. Leaf wall-clock
certificate expiry dates are past for both accepted and candidate images;
the accepted image boots, so don't assume the host date alone is a gate.

Remaining hardware gates: secureboot authentication, QMI/WMI and MPD/
SMP2P recovery ABI, accepted Acer BDF with new firmware, MLO/WSI
behavior and actual recurrence of the NOC fault. The WBE1.4
NOC_error.c:423 fatal handler and logger initialization are almost
identical to accepted 1.3, so no proof this fixes the error.

OpenWrt rootfs currently uses a hardcoded $(TOPDIR)/files in both
package/Makefile and include/image.mk; simply specifying FILES=<path>
would be silently ignored. Do not stage via that invalid override.
Only attempt a complete separate native image with a real overlay,
verified SHA, independent Asus reboot/rollback guards and working Wyse
Ethernet management. Do not commit firmware blobs or leave modified
binary assets in the primary Git checkout.

## Isolated firmware-only native sysupgrade candidate — 2026-11-16

The actual on-device accepted 3b1851eda6 sysupgrade (not an older
local kernel build) was SHA-pinned to:
a952779383ba6d6c0847951354af2d59a96e46b9422fba4fb0cda6e92a9877da.
It is retained on Acer under
/home/jan/firmware/wave7/trials/20261116-wbe14-compat/image-build/
and on Asus under the earlier accepted trials directory.

From the Acer primary OpenWrt checkout, run:

    d=/home/jan/firmware/wave7/trials/20261116-wbe14-compat
    PYTHONDONTWRITEBYTECODE=1 uv run --no-project --offline --python 3.13 python scripts/wave7/host/q6-firmware-audit/build_candidate.py --accepted-image "$d/image-build/accepted-3b1851eda6-sysupgrade.bin" --candidate "$d/gl-fw14" --out "$d/image-build/wave7-wbe14-01734-kernel3b1851eda6-sysupgrade.bin"

Actually built and offline verified, 2026-11-16:
- Native Acer Wave7 sysupgrade length 15,790,406 bytes
- SHA256 8d80ca8123770aa7db1f934197f6ef513d5ce737cffa90154e00a8d185c0d2c7
- Kernel/DTB byte-identical to accepted image, SHA256
  869fb4c8a0459d7bea8bb11fe8645af35feb4e14e01e53125a9a4be4a1c95bf2
- Complete Qualcomm WBE1.4-01734 root Q6, two UserPD and both IU sets
- Signed QCN6432 UserPD2 duplicates coherent at both Acer DTS lookup paths
- All Acer board.bin, caldata, regulatory files, qdss and radio config retained
- 41 explicit changed rootfs entries: all complete split firmware pieces,
  release metadata, and /etc/wave7-firmware-trial marker; 0 unexpected
- Original /etc/os-release is a symlink to ../usr/lib/os-release;
  its target is updated without changing the symlink
- Distinct trial release r0+38249-wbe14-01734-test avoids accidental
  acceptance by watchers looking for original 3b1851eda6 revision
- The one device inode, /dev/console, is excluded for unprivileged
  extraction and recreated with OpenWrt's original mksquashfs pseudo
  definition; verified by listing resulting SquashFS
- Original OpenWrt XZ/256KiB SquashFS compression options reproduced,
  then the entire candidate is extracted and checked against staging
- Packaged with OpenWrt scripts/sysupgrade-tar.sh and fwtool -I metadata;
  repacked device/board/metadata/kernel and extracted contents verified
- One scoped temporary workdir automatically removed; only sysupgrade
  binary, SHA256, report JSON and accepted baseline image kept
- Builder refuses to overwrite an output that already exists; no
  repo rootfs overlay files are touched and no kernel is recompiled

Targeted source tests without re-running full firmware builds:

    PYTHONDONTWRITEBYTECODE=1 uv run --no-project --offline --python 3.13 python scripts/wave7/host/q6-firmware-audit/test_build_candidate.py

ON-ROUTER IMAGE ACCEPTANCE TEST PASSED:
Asus independent copy SHA matched; on running Acer Wave7 root@192.168.76.1
the exact SHA-matched candidate was staged to a temporary /tmp file and
/sbin/sysupgrade -T -n /tmp/wave7-wbe14-01734-sysupgrade-TEST-ONLY.bin
exited 0 on 2026-11-16 16:53 CET. Boot ID stayed
9e3660cf-ea28-43f7-8f58-dcb81f5696d3, bootfail0, MLO2, 3/3
remoteprocs running. The temporary file was deleted from router.
Asus retains candidate and router-sysupgrade-test.log in its own
/home/jan/firmware/wave7/trials/20261116-wbe14-compat directory.

This is a native installable-format candidate, NOT a successful
WBE1.4 boot. Separate guarded hardware A/B is still needed for
secureboot/PAS authentication, QMI/WMI/MPD ABI, Wi-Fi/MLO/WSI, and
whether UMACNOC root fault recurs. Use independent Asus rollback
observers, accepted SHA-pinned restore, separate Wyse Ethernet
management, and no false acceptance on old revision string.

## Guarded on-hardware WBE1.4 A/B (2026-11-16)

Asus-side `flash-wbe14.sh --check|--run` validates the exact trial
SHA256 `8d80ca8123770aa7db1f934197f6ef513d5ce737cffa90154e00a8d185c0d2c7`
and accepted rollback SHA256
`a952779383ba6d6c0847951354af2d59a96e46b9422fba4fb0cda6e92a9877da`.
It requires the accepted `r0+38249-3b1851eda6` 6.18.60 boot,
bootfail0, accepted firstboot marker, 3 running Q6, MLO2,
Redmi LAN peer, Asus Q6 core collector and independently reachable
Wyse Ethernet via Acer SSH. All are checked *before* image staging.

The `--run` action stages **both** exact SHA-verified images to
router `/tmp`, invokes `sysupgrade -T -n` on each (format verification,
not flash), arms and checks two autonomous Asus `systemd --user`
services, then calls the native `sysupgrade -n` for the trial.
One Asus observer (`wbe14-watch.sh`) watches for the new boot ID and
*exact* trial revision `r0+38249-wbe14-01734-test`, and waits for
three running Q6 processors, both AP MLO links, working Redmi LAN,
firstboot keep-boot marker and bootfail0. It monitors kernel logs for
new NOC ERROR DETECTED events, and demands 360 seconds of continuous
health before a trial can be considered temporarily stable. For
unhealthy **reachable and already firstboot-accepted** trial boots,
it can independently stage/verify/sysupgrade the exact prior accepted
image, then require a rebooted accepted revision. The second existing
Asus watcher independently observes/captures vendor slot fallback
and pstore. The 120-second firstboot SysRq watchdog and bootfail4
APPSBL fallback handle faults too early to permit native sysupgrade.

A vendor fallback is reported as `VENDOR_FALLBACK` for later native
restore, not falsely counted as success or silently flashed with an
OpenWrt-only uploader. If neither router nor vendor becomes reachable,
this protocol cannot magically power-cycle the router; preserve the
record and use separately available physical recovery. Don't replace
this with the old *vendor-only* `wave7-trial-flash.sh`, which rejects
native kernel 6.18.60.

Asus installed scripts are under `/home/jan/scripts/wave7/wbe14-ab/`,
trial evidence goes under
`/home/jan/firmware/wave7/trials/20261116-wbe14-compat/runs/`,
and journal logs belong to per-run `wave7-wbe14-supervisor-*` and
`wave7-fallback-watch-*` user services. User lingering must remain on.
Before flashing, run `wbe14-watch.sh --selftest` and both scripts with
`bash -n`/`shellcheck`, then `flash-wbe14.sh --check`. This probe was
actually run on Asus on the accepted router on Nov16 at 17:36 CET:
`PREFLIGHT_PASS`, accepted boot ID
`9e3660cf-ea28-43f7-8f58-dcb81f5696d3`.

## Real guarded WBE1.4 hardware A/B — FAILED NoC, rollback PASS

Executed 2026-11-16, Asus run
`/home/jan/firmware/wave7/trials/20261116-wbe14-compat/runs/wbe14-01734-20261116-173922/`.
Exact candidate SHA256 `8d80ca8123770aa7db1f934197f6ef513d5ce737cffa90154e00a8d185c0d2c7`.
The same accepted Linux 6.18.60 kernel and Acer board calibration
were used; only the coherent WBE1.4-01734 signed Qualcomm family
and explicit trial release strings changed.

- 17:39 CET: two local Asus independent observer services armed,
  exact candidate and rollback SHA verified on router, both passed
  `sysupgrade -T -n`; native sysupgrade stage2 started.
- 17:40:25 CET: first **real WBE1.4** NAND boot UUID
  `b7384820-ff98-4068-aee1-536de51ed623`, revision
  `r0+38249-wbe14-01734-test`, bootfail5.
- Uptime53s: 3/3 Q6 processors running, 2/2 MLO AP links and
  Redmi wired peer. At uptime95s native firstboot watchdog accepted
  root/radio/LAN and committed bootfail0, keep-boot marker.
- Via Acer's out-of-band SSH to Wyse Ethernet, manually activated the
  already-configured `Wave7-MLO-Lab` Wi-Fi station using `sudo nmcli`.
  Wyse MT7925 joined both MLO links (2412/5200 MHz), EHT 2x2, and
  client-to-router ICMP passed 5/5. This kept Ethernet management
  independent; original Wi-Fi profile remains autoconnect=no.
- 17:46:54 CET: at **trial uptime406s**, kernel dmesg's
  `NOC ERROR DETECTED` count changed from **0 to 1**. This is a
  genuine recurrent fatal string on the new WBE1.4 firmware after
  nearly five minutes of *continuous healthy service*. The 2026
  Qualcomm first-party QNoC4 code's exact MID/EXTID values were only
  captured from older WBE1.3 full crash cores; **the WBE1.4 fatal
  did not yield new preserved full DSP coredump**, so exact logger
  bytes/param values for this incident are not proven identical.
- 17:46:57 CET: autonomous Asus supervisor, seeing the new NoC event,
  uploaded and reverified exact accepted image, tested with native
  `sysupgrade -T -n`, and initiated native `sysupgrade -n` rollback.
  No physical power cycle, sysrq panic or vendor fallback required.
- 17:47:56 CET: accepted `r0+38249-3b1851eda6` came up on fresh boot
  `04dddd01-ac63-48a4-8f75-afbf491e03c2`, initially bootfail5;
  by 17:49:44 CET the production firstboot gate had committed
  **bootfail0**, keep-boot marker and 3/3 Q6, MLO2, Redmi 3/3
  ICMP and no fresh NoC messages. The one-shot Asus watchers were
  stopped; normal passive Q6 core collection remained enabled.

**Decision:** GL WBE1.4-01734 does not fix the intermittent IPQ5332
UMACNOC firmware fatal; keep accepted WBE1.3-03279 native baseline.
The tested native firstboot bootfail fallback and Asus independent
same-slot rollback both worked. This is an actual negative hardware
A/B, not a build or OTA-parser-only inference. Do not rerun the same
WBE1.4 trial without a new causal hypothesis. Next work: locate
actual UMACNOC initiator/target route map, or investigate complete
later Qualcomm WBE1.6/1.7 families with matching board-data ABI.

Captured evidence (on Asus, scoped): `preflight.txt`,
`sysupgrade.log`, `observer.log`, `restore.log`,
`last-trial-state.txt` (contains NoC count1, uptime406),
`accepted-after-rollback.txt`, `status=ROLLED_BACK`, and
`evidence.sha256` with all checks PASS. No test logs or signed
firmware blobs in Git. No separate pre-rollback full DSP core was
captured. A subsequent source-only improvement to `wbe14-watch.sh`
adds a bounded read-only `dmesg` snapshot immediately upon detecting
an error, before starting a native restore, to avoid this gap in
future guarded experiments. This **source improvement was not
hardware-retested**, and does not justify repeating the same A/B.
