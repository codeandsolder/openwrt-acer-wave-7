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
