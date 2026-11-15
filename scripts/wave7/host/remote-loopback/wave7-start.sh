#!/bin/ash
# shellcheck shell=dash
set -eu
if [ "$1" = "--check" ]; then
  test "$(fw_printenv -n bootfail)" = 0
  test -f /tmp/wave7-keep-boot
  test "$(cat /sys/class/net/lan/carrier)" = 1
  test "$(phytool read lan/0x18:3/0x805a)" = 0x3002
  test ! -e /tmp/wave7-remote-loopback.arm
  test ! -e /tmp/wave7-postboot-trial.arm
  ping -I br-lan -c 2 -W 1 192.168.76.2 >/dev/null
  echo "REMOTE_LOOPBACK_CHECK_PASS $(cat /proc/sys/kernel/random/boot_id)"
  exit 0
fi
test "$1" = "--run"
boot=$(cat /proc/sys/kernel/random/boot_id)
original=$(phytool read lan/0x18:3/0x805a)
test "$original" = 0x3002
test ! -e /tmp/wave7-remote-loopback.arm
token=$(cat /proc/sys/kernel/random/uuid)
printf '%s\n' "$token" >/tmp/wave7-remote-loopback.arm
rm -f /tmp/wave7-remote-loopback.restored
start-stop-daemon -S -b -m -p /tmp/wave7-remote-loopback.pid \
  -x /bin/ash -- /tmp/wave7-remote-loopback-restore.sh "$boot" "$original" "$token"
sleep 1
test -s /tmp/wave7-remote-loopback.pid
kill -0 "$(cat /tmp/wave7-remote-loopback.pid)"
echo "<6>wave7-loopback: REMOTE_LOOPBACK_CONTROL_BEGIN boot=$boot original=$original" >/dev/kmsg
phytool write lan/0x18:3/0x805a 0x3003
val=$(phytool read lan/0x18:3/0x805a)
printf 'ENABLED boot=%s original=%s active=%s\n' "$boot" "$original" "$val" >/tmp/wave7-remote-loopback.enabled
echo "<6>wave7-loopback: REMOTE_LOOPBACK_ACTIVE value=$val" > /dev/kmsg
test "$val" = 0x3003
