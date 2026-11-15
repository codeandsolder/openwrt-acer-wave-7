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

## 2026-11-15 isolated behavioral tests (no live watchdog)

`test-hard-guard.sh` exercises the **production guard shell control flow**
using a disposable transformed copy, with boot-id, arming token, kernel-log
output and recovery request all redirected into a private temporary fixture.
Mocked ping/sleep commands make success, failure, cancellation and timing
deterministic; the test explicitly rejects any unredirected device path in
its runnable copy. It runs on Acer as a normal user with Bash, POSIX sh,
ShellCheck and ripgrep. No hardware reset and no kernel crash request occurs.

All **13** cases PASS: missing/wrong token, wrong boot, first and eventual
healthy responses, persistent three-probe failure (only a fixture recovery
request), token cancellation just after arming and just before recovery,
boot ID changing during the delay, a new same-boot trial replacing the old
token at two stages and during successful ping, and cancellation of a real
child process while it sleeps. The guard now accepts **boot ID and unique
trial UUID** separately; the controller obtains the UUID from the kernel
and pins the updated guard SHA. An old process cannot authorize recovery
using a newer same-boot trial's token.

This validates shell decisions in isolation, **not the OpenWrt
start-stop-daemon launch path nor kernel-panic/fallback behavior**. The
existing hard-guard runtime check on Wave 7 remains blocked; do not claim
that an automated recovery has been demonstrated, and do not schedule
another physical link flap on the basis of these tests alone.
