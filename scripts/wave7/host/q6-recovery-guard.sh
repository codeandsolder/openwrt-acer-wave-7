#!/bin/ash
# shellcheck shell=dash
# Per-trial, boot-bound, independently timed recovery guard.
set -eu
arm=/tmp/wave7-q6-ssr-trial.arm
# Only link records from the named AP MLD; exclude unrelated radios.
check_mlo_info() {
  awk '
    $1 == "-" && $2 == "link" && $3 == "ID" {
      if ($4 == "0") { id = 0; n0++ }
      else if ($4 == "1") { id = 1; n1++ }
      else { id = -1 }
      next
    }
    $1 == "txpower" {
      if (id == 0) p0 = $2 + 0
      if (id == 1) p1 = $2 + 0
    }
    END { exit !(n0 == 1 && n1 == 1 && p0 > 0 && p1 > 0) }
  '
}
if [ "$1" = "--test-mlo-info" ]; then
  check_mlo_info
  exit
fi
if [ "$1" = "--check" ]; then
  test -r /proc/sys/kernel/random/boot_id
  test -r /sys/class/remoteproc/remoteproc0/state
  test -c /dev/kmsg
  command -v ping >/dev/null
  command -v iw >/dev/null
  iw dev ap-mld0 info | check_mlo_info
  echo Q6_GUARD_CHECK_PASS
  exit 0
fi
boot=$1
token=$2
delay=$3
client=${4:-}
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
iw dev ap-mld0 info 2>/dev/null | check_mlo_info || ok=0
ping -I br-lan -c 2 -W 1 192.168.76.2 >/dev/null 2>&1 || ok=0
if [ -n "$client" ]; then
  test "$(iw dev ap-mld0 station dump | grep -c "^Station " || :)" -gt 0 || ok=0
  ping -I br-lan -c 2 -W 1 "$client" >/dev/null 2>&1 || ok=0
fi
if [ "$ok" -eq 1 ]; then
  echo '<6>wave7-q6-guard: basic recovery healthy, no reboot' > /dev/kmsg
  if [ -r "$arm" ] && [ "$(cat "$arm")" = "$token" ]; then rm -f "$arm"; fi
  exit 0
fi
test -r "$arm" || exit 0
test "$(cat "$arm")" = "$token" || exit 0
echo '<3>wave7-q6-guard: recovery still broken at deadline, diagnostic panic' > /dev/kmsg
sync
echo c > /proc/sysrq-trigger
