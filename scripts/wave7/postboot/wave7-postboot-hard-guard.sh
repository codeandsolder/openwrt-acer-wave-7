#!/bin/ash
# One-shot independent management-health guard for an already accepted boot.
# The normal postboot monitor records root cause; this guard prevents a
# monitor crash or an unobserved carrier transition from stranding the router.
set -eu
expected=$1
peer=192.168.76.2
test "$(cat /proc/sys/kernel/random/boot_id)" = "$expected" || exit 2
echo "<6>wave7-postboot-hard-guard: armed boot=$expected" > /dev/kmsg
sleep 145
test "$(cat /proc/sys/kernel/random/boot_id)" = "$expected" || exit 0
for _ in 1 2 3; do
  if ping -I br-lan -c 2 -W 1 "$peer" >/dev/null 2>&1; then
    echo "<6>wave7-postboot-hard-guard: peer restored; disarmed" > /dev/kmsg
    exit 0
  fi
  sleep 4
done
echo "<3>wave7-postboot-hard-guard: persistent unreachable peer after flap, guarded panic for recovery" > /dev/kmsg
sync
echo c > /proc/sysrq-trigger
exit 5
