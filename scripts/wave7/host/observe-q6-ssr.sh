#!/usr/bin/env bash
# Read-only live Q6/ath12k health and event capture. Execute on Asus.
set -Eeuo pipefail
umask 077
mode=$1
case "$mode" in --check|--capture) ;; *) echo 'usage: observe-q6-ssr.sh --check|--capture' >&2; exit 2;; esac
root=/home/jan/firmware/wave7/trials/20261115-q6-phy-integration/q6-ssr
wave() {
  ssh -n -i /home/jan/.ssh/wave7-root-rsa -o BatchMode=yes -o IdentitiesOnly=yes \
    -o ConnectTimeout=4 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    root@192.168.76.1 "$@"
}
check='set -eu
. /etc/openwrt_release
test "$(uname -r)" = 6.18.60
test "$(fw_printenv -n bootfail)" = 0
test -f /tmp/wave7-keep-boot
test "$(cat /sys/class/net/lan/carrier)" = 1
test "$(iw dev | grep -Ec "link ID[[:space:]]+[01]")" = 2
for d in /sys/class/remoteproc/remoteproc0 /sys/class/remoteproc/remoteproc1 /sys/class/remoteproc/remoteproc2; do
  test "$(cat "$d/state")" = running
done
printf "revision=%s\n" "$DISTRIB_REVISION"
printf "boot=%s\n" "$(cat /proc/sys/kernel/random/boot_id)"
printf "stations=%s\n" "$(iw dev ap-mld0 station dump | grep -c ^Station || :)"
ping -I br-lan -c 2 -W 1 192.168.76.2 >/dev/null
'
state=$(wave "$check")
printf '%s\n' "$state"
if [[ $mode == --check ]]; then echo Q6_READONLY_CHECK_PASS; exit 0; fi
mkdir -p "$root"
tag="passive-$(date +%Y%m%d-%H%M%S)"
out="$root/$tag"
mkdir -p "$out"
printf '%s\n' "$state" > "$out/preflight.txt"
wave 'echo ====BOOT====; cat /proc/sys/kernel/random/boot_id; cat /etc/openwrt_release; echo ====RPROCS====; for d in /sys/class/remoteproc/remoteproc*; do echo "$(basename "$d"):$(cat "$d/name"):$(cat "$d/state"):$(cat "$d/recovery")"; done; echo ====RADIOS====; iw dev; iw dev ap-mld0 station dump; echo ====GMAC====; ethtool -S lan; echo ====KERNEL====; dmesg' > "$out/snapshot.txt"
sleep 5
wave 'echo ====AFTER_5S====; for d in /sys/class/remoteproc/remoteproc*; do echo "$(basename "$d"):$(cat "$d/state")"; done; echo ====MLO====; iw dev | grep -E "link ID|txpower"; echo ====PEER====; ping -I br-lan -c 3 -W 1 192.168.76.2; echo ====GMAC====; ethtool -S lan | grep -E "rx_frames:|tx_frames:|rx_crc_err:"' > "$out/followup.txt"
sha256sum "$out"/*.txt > "$out/evidence.sha256"
echo "PASSIVE_Q6_CAPTURE=$out"
