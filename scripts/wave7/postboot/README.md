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

## 2026-11-15 follow-up, no hardware flap

The hard guard requires a per-boot arming token
(/tmp/wave7-postboot-trial.arm) at startup, again after its timeout, and
immediately before recovery. Cancelling a trial invalidates that token;
the launcher also stops detached processes and removes readiness markers
on an aborted setup. The launcher marks the first started Asus observer
as armed so partially completed watcher setup can be cleaned up.

The monitor records a bounded raw SerDes+GMAC snapshot on SUCCESS as
well as the RX-stalled and RX-advancing peer-failure paths. Both on-router
scripts have read-only --check entry points.

Validation: Bash/Ash syntax and ShellCheck warning level PASS, Asus
controlled-postboot-link-flap.sh --check PASS. The staged monitor's
/bin/ash /tmp/wave7-postboot-link-monitor.sh --check PASS on Wave7
(0x001e=0x03d4, 0x007d=0x0008, management peer reachable).
Independent hard-guard runtime execution was blocked by platform
safeguards and is NOT validated. No arming process, hardware flap,
reboot or firmware flash occurred.

Do not treat this source change as validated autonomous recovery
until the complete guard launch/cancel/failure lifecycle is exercised.
