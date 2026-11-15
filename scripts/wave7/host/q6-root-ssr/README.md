# Root Q6 / ath12k MLO crash recovery trial — passed (2026-11-15)

A real, hardware-running acceptance test of the installed native OpenWrt
r0+38249-3b1851eda6 (no firmware changes). Direct Acer SSH into
Wyse's independent Ethernet management address 10.1.0.221 allowed
reassociation of Wi-Fi client 192.168.76.145 while Wave7 radio restarted,
without using any transient port relay or copying the cold-storage key.

## Procedure and result

The existing on-router SHA-pinned q6-recovery-guard.sh validated its
--check. Asus started independent Linux boot-ID and vendor fallback
observers and a boot-ID/UUID token-bound 240s on-router recovery guard
before invoking debugfs remoteproc0/crash with value 1 (kernel reports
type watchdog). This is a SYNTHETIC root-Q6 remoteproc crash, not a
physical firmware assert nor a full Linux kernel reboot.

Live test 2026-11-15 17:25:58 CET boot ID:
9e3660cf-ea28-43f7-8f58-dcb81f5696d3.
At kernel uptime2067.756s, root remoteproc0 crash #2 was reported.
At uptime2068.501, both ath12k UserPD consumers logged
"root Q6 restarted after crash; resetting UserPD".
All Q6 remoteproc0/1/2 were again running by uptime2069.655, and
ath12k QMI firmware ready / core-start by ~2071.607 (~4 seconds).

Root Q6 recovery and both AP MLO links were back on the SAME Linux
boot. Wyse STA was associated, but router->Wyse ping initially failed
while Wi-Fi reconnection settled; the controller manually requested
nmcli connection up from Acer over wired SSH at sample8 because Wyse
profile has connection.autoconnect=no. Sample9 (~34s) showed all three
remoteprocs running, MLO2, associated STA1, router->Wyse and
Wyse->router ICMP good, independent wired Redmi peer good. Recovery
guard token and process were canceled; Asus fallback observers stopped.
This validates Q6 SSR plus controlled STA reprovisioning, not fully
autonomous client association.

**Second important discovery:** the same boot had already spontaneously
recovered from an ACTUAL Q6 firmware fatal crash #1 at uptime184.766s:
WLAN.WBE.1.3-03279-QCAHKSWPL_SILICONZ-1 firmware, NOC_error.c:423
"NOC ERROR DETECTED", params (zero, 59, 8192),
wlan0/IST0 thread, SSR=0x01870127, PC=0xb032f004.
Root firmware reset and UserPD recovery completed; pdev1 reported
recovered by uptime194.967. We did not independently observe client
end-to-end connectivity across that earlier spontaneous event, so do
not claim it was fully client-transparent.

## Captured evidence

Asus host directory:
/home/jan/firmware/wave7/trials/20261115-q6-root-ssr/q6-root-ssr-20261115-172557

Contains preflight/armed, observer sequence for every recovery sample,
full after-dmesg, two watchdog observer logs, and SHA manifest. All
verified after the test. No router firmware flash or physical cable flap.

The source harness was subsequently corrected to compare the *new*
Q6 crash count to the pre-trigger count, because the boot already had
a crash #1 before injection; otherwise a non-injected run might pass
incorrectly. It also only forces manual Wyse Wi-Fi reconnection when
the current router-to-client probe fails and logs that action. These
post-test source-only correctness changes have NOT been rerun as
another hardware fault injection; do not repeat the full test for them.

The wired QCA8081/PCS1 SGMII post-carrier packet blackhole remains an
independent P0 bug. Proving Wi-Fi Q6 recovery does not address it.
