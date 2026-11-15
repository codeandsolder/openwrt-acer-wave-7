#!/bin/ash
# shellcheck shell=dash
# Per-trial, boot-bound, independently timed recovery guard.
set -eu
arm=/tmp/wave7-q6-ssr-trial.arm
if [ "$1" = "--check" ]; then
  test -r /proc/sys/kernel/random/boot_id
  test -r /sys/class/remoteproc/remoteproc0/state
  test -c /dev/kmsg
  command -v ping >/dev/null
  command -v iw >/dev/null
  echo Q6_GUARD_CHECK_PASS
  exit 0
fi
boot=$1
token=$2
delay=$3
test "$delay" -ge 90
test "$delay" -le 300
test "$(cat /proc/sys/kernel/random/boot_id)" = "$boot"
test -r "$arm"
test "$(cat "$arm")" = "$token"
echo "<6>wave7-q6-guard: armed boot=$boot duration=$delay" > /dev/kmsg
sleep "$delay"
test "$(cat /proc/sys/kernel/random/boot_id)" = "$boot" || exit 0
test -r "$arm" || exit 0
test "$(cat "$arm")" = "$token" || exit 0
ok=1
for d in /sys/class/remoteproc/remoteproc0 /sys/class/remoteproc/remoteproc1 /sys/class/remoteproc/remoteproc2; do
  test "$(cat "$d/state" 2>/dev/null)" = running || ok=0
done
test "$(iw dev 2>/dev/null | grep -Ec 'link ID[[:space:]]+[01]')" -eq 2 || ok=0
ping -I br-lan -c 2 -W 1 192.168.76.2 >/dev/null 2>&1 || ok=0
if [ "$ok" -eq 1 ]; then
  echo '<6>wave7-q6-guard: basic recovery healthy, no reboot' > /dev/kmsg
  exit 0
fi
test -r "$arm" || exit 0
test "$(cat "$arm")" = "$token" || exit 0
echo '<3>wave7-q6-guard: recovery still broken at deadline, diagnostic panic' > /dev/kmsg
sync
echo c > /proc/sysrq-trigger
