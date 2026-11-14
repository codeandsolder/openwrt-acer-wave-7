# Wave 7 guarded post-boot copper-link diagnostics

Research-only host-side helpers, not production firmware. These scripts
are not installed on the router by a build.

- controlled-postboot-link-flap.sh runs on Asus as jan, with the repo files
  copied to /home/jan/scripts/wave7/controlled-link first; it stages the
  two small read-only/guard scripts on Wave 7 via SSH.
- wave7-postboot-link-monitor.sh observes carrier DOWN/UP and classifies
  sustained peer failure separately for zero GMAC RX versus RX advancing.
  It records raw PHY+1 SerDes MMD1 diagnostics, PPE/PCS and MAC counters,
  then triggers the existing panic/bootloader recovery path on a proven
  persistent management failure after the flap.
- wave7-postboot-hard-guard.sh independently checks management reachability
  at 145 seconds even if the monitor exits or misses a carrier transition.
- watch-new-boot-id.sh is the Asus observer's boot-ID and revision gate.

The accepted baseline is ea66890908. This guard was statically validated
on 2026-11-14 (bash -n, ShellCheck warning threshold) but has NOT been
re-tested in hardware after these changes. Do not trigger another flap
until the router is reachable and the script's --check preflight passes.
Never count carrier1 alone as datapath recovery: test peer and RX counters.

Postboot link interruption 2026-11-14 at 21:49 CET *without* these guards
stranded wired management (no ARP replies despite Redmi carrier1). A physical
Wave 7 power-cycle was requested; see the Notion Wave 7 current-state hub.
