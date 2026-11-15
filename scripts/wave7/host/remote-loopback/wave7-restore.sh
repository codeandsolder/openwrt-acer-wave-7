#!/bin/ash
# shellcheck shell=dash
set -eu
expected=$1
original=$2
token=$3
arm=/tmp/wave7-remote-loopback.arm
sleep 8
test "$(cat /proc/sys/kernel/random/boot_id)" = "$expected" || exit 2
test -r "$arm" && test "$(cat "$arm")" = "$token" || exit 2
phytool write lan/0x18:3/0x805a "$original"
actual=$(phytool read lan/0x18:3/0x805a)
printf 'RESTORED boot=%s original=%s actual=%s\n' "$expected" "$original" "$actual" >/tmp/wave7-remote-loopback.restored
echo "<6>wave7-loopback: restored MMD3.805a $actual" > /dev/kmsg
[ "$actual" = "$original" ] || exit 3
sleep 20
test "$(cat /proc/sys/kernel/random/boot_id)" = "$expected" || exit 0
test -r "$arm" && test "$(cat "$arm")" = "$token" || exit 0
if ping -I br-lan -c 2 -W 1 192.168.76.2 >/dev/null 2>&1; then
  echo "HEALTHY boot=$expected" >> /tmp/wave7-remote-loopback.restored
  rm -f "$arm" /tmp/wave7-remote-loopback.pid
  exit 0
fi
if [ "$(cat /sys/class/net/lan/carrier 2>/dev/null)" != 1 ]; then
  echo "<4>wave7-loopback: cable physically down; no panic" >/dev/kmsg
  exit 4
fi
echo "<3>wave7-loopback: restore failed to restore peer; diagnostic panic" > /dev/kmsg
sync
echo c > /proc/sysrq-trigger
