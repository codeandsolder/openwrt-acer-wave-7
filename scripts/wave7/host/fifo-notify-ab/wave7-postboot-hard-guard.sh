#!/bin/ash
# shellcheck shell=dash
# One-shot independent management-health guard for an already accepted boot.
# The normal postboot monitor records root cause; this guard prevents a
# monitor crash or an unobserved carrier transition from stranding the router.
set -eu
# Read-only on-device runtime preflight: does not create an arm token or timer.
if [ "${1:-}" = "--check" ]; then
  test -r /proc/sys/kernel/random/boot_id
  test -w /proc/sysrq-trigger
  test -c /dev/kmsg
  command -v ping >/dev/null
  command -v start-stop-daemon >/dev/null
  ping -I br-lan -c 2 -W 1 192.168.76.2 >/dev/null
  echo "HARD_GUARD_CHECK_PASS boot=$(cat /proc/sys/kernel/random/boot_id)"
  exit 0
fi
expected=$1
trial=$2
peer=192.168.76.2
armfile=/tmp/wave7-postboot-trial.arm
test "$(cat /proc/sys/kernel/random/boot_id)" = "$expected" || exit 2
test -f "$armfile" || exit 2
test "$(cat "$armfile")" = "$trial" || exit 2
echo "<6>wave7-postboot-hard-guard: armed boot=$expected" > /dev/kmsg
sleep 145
test "$(cat /proc/sys/kernel/random/boot_id)" = "$expected" || exit 0
test -f "$armfile" || exit 0
test "$(cat "$armfile")" = "$trial" || exit 0
for _ in 1 2 3; do
  if ping -I br-lan -c 2 -W 1 "$peer" >/dev/null 2>&1; then
    echo "<6>wave7-postboot-hard-guard: peer restored; disarmed" > /dev/kmsg
    # A new same-boot trial may have replaced the token during the ping.
    # Never delete that newer trial's capability from an older guard.
    if test -f "$armfile" && test "$(cat "$armfile")" = "$trial"; then
      rm -f "$armfile"
    fi
    exit 0
  fi
  sleep 4
done
test -f "$armfile" || exit 0
test "$(cat "$armfile")" = "$trial" || exit 0
echo "<3>wave7-postboot-hard-guard: persistent unreachable peer after flap, guarded panic for recovery" > /dev/kmsg
sync
echo c > /proc/sysrq-trigger
exit 5
