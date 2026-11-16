# Wave 7 reboot + MT7925 reassociation stress

Integration-stability gate for single-ath12k hardened OpenWrt candidate
r0+38249-napi-5e3df9b898. The same router image must be used for all
cycles; no experimental PHY/SGMII resets, NAND reflash, firmware swap,
or host kernel changes.

## Phase A: Wyse-only reconnects

Execute wyse-reassociate.sh 100 via Acer to Wyse wired SSH (wyse-eth).
The remote script touches only the Wyse NetworkManager profile
Wave7-MLO-Lab on wlp2s0, checks independent Ethernet eno1 management
before/after, and requires full disassociation + reactivation, MLO
link 0+1 BSSIDs, correct WLAN route, successful client→router ICMP.
On error it stops, tries to restore the saved profile, and reports
cycle/phase. Acer keeps timestamped results in
/home/jan/firmware/wave7/trials/20261116-cycle-stress/.

## Phase B: real router restarts

The Wyse profile must have NetworkManager connection.autoconnect=yes
before the first router restart. Original value was no on the lab Wyse;
a first controlled reboot correctly passed all router boot/Q6/AP checks
but failed the automatic Wyse reconnect because NetworkManager stopped
retrying after its SSID-not-found timeout. The original no setting is
saved on Acer in wyse-autoconnect-original.txt. For this test the profile
has been explicitly configured to yes and reconnected successfully.
The reboot harness now checks this prerequisite before issuing a reset.
Restore the original profile preference after test completion, if desired.


Run router-reboots.sh --check COUNT and then --run COUNT on Asus.
These are full router /sbin/reboot operations, not Wi-Fi reloads.
Each accepted restart requires:
- A different router boot ID.
- Exact trial revision, Linux 6.18.60, bootfail=0 and keepboot marker.
- All three Q6 domains running, MLO AP links 0 and 1.
- Wired Redmi connectivity and zero kernel NoC fatal lines.
- Wyse reachable independently via Ethernet and both MLO client links
  restored with two successful WLAN pings to Wave 7.
- All three independent Asus NoC/IRQ/core collectors active.
- A 12-second post-firstboot-acceptance stabilization window, followed
  by another explicit NoC/boot-ID/Q6/MLO health check **before** probing
  client reassociation; a 99.9-second Q6 fatal previously occurred after
  acceptance at 95s and was mistakenly classified as a Wyse-only error.
- Additional ten seconds after successful client reconnection to preserve
  a passive IRQ snapshot before attempting the next reboot.
- A second NoC check if Wyse fails, giving root-Q6 fatal priority over
  client symptom classification and preserving the original boot.

Stop on the first bad boot, mismatched revision, lost monitor, NoC fatal,
unreachable client, or 270-second timeout. Save failure diagnostics
from kernel and pstore if accessible, and leave the current boot for
diagnosis. Native bootfail/watchdog recovery stays enabled. Never
automatically force an additional firmware write on failure.

The 100 Wyse-only reconnects are distinct from automatic MT7925
reassociation after router restarts.

## Evidence

Pilot/full TSVs, stderr, source hashes, boot IDs, timings and failure
artifacts live under
/home/jan/firmware/wave7/trials/20261116-cycle-stress/ on the
respective controller (Acer phase A, Asus phase B).

100/100 successes rules out high-frequency restart/reassociation
failures. Under an independent-trial approximation, zero failures in
100 still leaves a one-sided 95% upper failure probability around 2.95%.
The intermittent UMACNOC fatal could remain dependent on continuous
traffic or uptime, so keep the passive kernel monitoring enabled.
