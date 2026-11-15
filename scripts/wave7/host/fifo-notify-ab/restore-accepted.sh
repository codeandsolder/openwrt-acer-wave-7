#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
action=$1
[[ $action == --check || $action == --run ]] || exit 2
base=/home/jan/firmware/wave7/trials/20261115-fifo-notify-ab/rollback
image="/home/jan/firmware/wave7/trials/20261115-pcs-analog-readback/pcs-analog-readback-3b1851eda6-sysupgrade.bin"
manifest="/home/jan/firmware/wave7/trials/20261115-pcs-analog-readback/firmware.sha256"
rollback=/home/jan/firmware/wave7/trials/20261115-fifo-notify-ab/fifo-notify-preserved-0078d29fd0-sysupgrade.bin
ssh_opts=(-n -i /home/jan/.ssh/wave7-root-rsa -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=3 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
ssh_wave() { ssh "${ssh_opts[@]}" root@192.168.76.1 "$@"; }
[[ "$(id -un)" == jan ]]
[[ -s $image && -s $manifest && -s $rollback ]]
[[ "$(sha256sum "$rollback" | cut -d' ' -f1)" == 5e6a9277dc29117bd801e43da6b46d3f84b14d4e753b603df9913185e8cf7a86 ]]
want=$(cut -d' ' -f1 "$manifest")
[[ $want =~ ^[a-f0-9]{64}$ && "$(sha256sum "$image" | cut -d' ' -f1)" == "$want" ]]
[[ "$(tar xOf "$image" sysupgrade-acer_wave7/CONTROL)" == BOARD=acer_wave7 ]]
old=$(ssh_wave 'set -e
test "$(uname -r)" = 6.18.60
grep -q 0078d29fd0 /etc/openwrt_release
test "$(fw_printenv -n bootfail)" = 0
test -e /tmp/wave7-keep-boot
test -e /tmp/wave7-autoprobe-success
test "$(cat /sys/class/net/lan/carrier)" = 1
test "$(cat /sys/class/net/lan/statistics/rx_packets)" -gt 0
iw dev | grep -Eq "link ID[[:space:]]+0"
iw dev | grep -Eq "link ID[[:space:]]+1"
ping -I br-lan -c 2 -W 1 192.168.76.2 >/dev/null
cat /proc/sys/kernel/random/boot_id
')
[[ $old =~ ^[a-f0-9-]{36}$ ]]
XDG_RUNTIME_DIR=/run/user/$(id -u); export XDG_RUNTIME_DIR
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
test -z "$(systemctl --user --no-pager --no-legend list-units --state=active 'wave7-openwrt-watch-*' 'wave7-fallback-watch-*')"
echo "CHECK PASS accepted_boot=$old image_sha256=$want rollback=verified"
[[ $action == --run ]] || exit 0
tag=fifo-ab-rollback-flash-$(date +%Y%m%d-%H%M%S)
out="$base/$tag"
mkdir -p "$out"
printf 'old=%s\nimage_sha256=%s\n' "$old" "$want" > "$out/preflight.txt"
pristine="/tmp/wave7-fifo-ab-rollback-3b1851eda6.bin"
scp -q -O -i /home/jan/.ssh/wave7-root-rsa -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$image" root@192.168.76.1:"$pristine"
ssh_wave "set -e; test \"\$(sha256sum '$pristine' | cut -d' ' -f1)\" = '$want'; /sbin/sysupgrade -T -n '$pristine'" > "$out/router-sysupgrade-test.log" 2>&1
openunit=wave7-openwrt-watch-$tag.service
fallbackunit=wave7-fallback-watch-$tag.service
armed=0
flashing=0
accepted=0
cleanup() {
  rc=$?
  trap - EXIT
  if (( armed )); then
    for suffix in bootid-gate.log openwrt-watch.log fallback-watch.log openwrt-capture.txt pstore.txt ramoops-raw.bin; do
      f=/tmp/wave7-$tag-$suffix
      [[ ! -s $f ]] || cp -p "$f" "$out/"
    done
    if (( ! flashing || accepted )); then
      systemctl --user stop "$openunit" "$fallbackunit" >/dev/null 2>&1 || :
    else
      echo "Not accepted: recovery observers remain armed, tag=$tag" >&2
    fi
  fi
  exit "$rc"
}
trap cleanup EXIT
systemd-run --user --quiet --unit="wave7-openwrt-watch-$tag" --property=RuntimeMaxSec=1200 -- /home/jan/scripts/wave7/controlled-link/watch-new-boot-id.sh "$tag" "$old" 3b1851eda6
armed=1
systemd-run --user --quiet --unit="wave7-fallback-watch-$tag" --property=RuntimeMaxSec=1200 -- /home/jan/scripts/wave7/wave7-fallback-watch.sh "$tag"
sleep 2
systemctl --user is-active --quiet "$openunit"
systemctl --user is-active --quiet "$fallbackunit"
echo "WATCHERS_ACTIVE tag=$tag"
flashing=1
set +e
ssh_wave "/sbin/sysupgrade -n '$pristine'" > "$out/sysupgrade.log" 2>&1
flash_rc=$?
set -e
echo "SYSUPGRADE_SSH_RC=$flash_rc" | tee -a "$out/sysupgrade.log"
deadline=$(( $(date +%s) + 490 ))
while (( $(date +%s) < deadline )); do
  state=$(ssh_wave 'echo BOOT="$(cat /proc/sys/kernel/random/boot_id)"; echo REV="$(sed -n "s/^DISTRIB_REVISION=//p" /etc/openwrt_release)"; echo BOOTFAIL="$(fw_printenv -n bootfail 2>/dev/null || :)"; echo KEEP="$(test -e /tmp/wave7-keep-boot && echo YES || echo NO)"; echo RX="$(cat /sys/class/net/lan/statistics/rx_packets 2>/dev/null || :)"; echo MLO="$(iw dev 2>/dev/null | grep -Ec "link ID[[:space:]]+[01]" || :)"; echo PEER="$(ping -I br-lan -c 2 -W 1 192.168.76.2 >/dev/null 2>&1 && echo YES || echo NO)"; echo PCS="$(for key in pll_reset clkout_50m_ctrl link_detect; do grep -q "^$key=" /sys/kernel/debug/ipq-pcs-7a10000.ethernet-pcs/link_state || break; echo "$key"; done | wc -l)"; dmesg | grep -F "wave7-diag: first-media SGMII mode ready" | tail -1; dmesg | grep -F "fifo_ret=" | head -1' 2>/dev/null || :)
  if [[ $state == *3b1851eda6* && $state == *"BOOTFAIL=0"* && $state == *"KEEP=YES"* && $state == *"MLO=2"* && $state == *"PEER=YES"* && $state == *"PCS=3"* && $state == *"first-media SGMII mode ready"* && $state == *"fifo_ret="* && $state != *"BOOT=$old"* ]]; then
    printf '%s\n' "$state" > "$out/accepted.txt"
    ssh_wave 'dmesg; echo ====GMAC====; ethtool -S lan; echo ====PPE====; cat /sys/kernel/debug/ppe/port_rx; echo ====MLO====; iw dev' > "$out/live-diagnostics.txt"
    ssh_wave 'echo ====PCS1====; cat /sys/kernel/debug/ipq-pcs-7a10000.ethernet-pcs/link_state; echo ====Q6====; for d in /sys/class/remoteproc/remoteproc*; do echo "$(basename "$d")=$(cat "$d/state")"; done' > "$out/pcs-readbacks.txt"
    for marker in pll_reset clkout_50m_ctrl link_detect; do rg -q "^$marker=" "$out/pcs-readbacks.txt"; done
    accepted=1
    echo "FAST_BOOT_ACCEPTED tag=$tag"
    break
  fi
  if [[ $state == *"REV="* ]]; then
    printf '%s\n' "$state" > "$out/latest-state.txt"
  fi
  sleep 4
done
(( accepted )) || { echo "NOT_ACCEPTED tag=$tag"; exit 4; }
echo "IMAGE=$image"
