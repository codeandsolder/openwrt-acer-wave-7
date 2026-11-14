#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
action=${1:---check}
case "$action" in --help|-h) echo "usage: $0 [--check|--run]"; exit 0;; --check|--run) ;; *) exit 2;; esac

root=/home/jan/scripts/wave7/controlled-link
base=/home/jan/firmware/wave7/trials/20261113-link-flap
mkdir -p "$base"
ssh_wave() {
  ssh -n -i /home/jan/.ssh/wave7-root-rsa -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 \
   -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@192.168.76.1 "$@"
}
ssh_redmi() {
  ssh -n -o BatchMode=yes -o ConnectTimeout=4 -o StrictHostKeyChecking=accept-new root@10.1.0.2 "$@"
}
[[ "$(id -un)" == jan ]] || exit 2
exec 9>"$base/.controlled-flap.lock"
flock -n 9 || { echo 'Another controlled link-flap run is in progress' >&2; exit 2; }
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}
test -z "$(systemctl --user --no-pager --no-legend list-units --state=active 'wave7-openwrt-watch-*' 'wave7-fallback-watch-*')"
[[ $(ip route get 10.1.0.2) == *"dev wlan0"* ]] || { echo 'Asus local Redmi route is not direct' >&2; exit 2; }
expected=$(sha256sum "$root/wave7-postboot-link-monitor.sh" | cut -d' ' -f1)
[[ "$expected" == 43ff465573fec585cd3e91f09cba2861436b7c587c3639f187b9ae7c0dfe6cb1 ]]
old=$(ssh_wave '
 set -eu
 test "$(uname -r)" = 6.18.60
 grep -q ea66890908 /etc/openwrt_release
 test "$(fw_printenv -n bootfail)" = 0
 test -f /tmp/wave7-keep-boot
 test -f /tmp/wave7-autoprobe-success
 test "$(cat /sys/class/net/lan/carrier)" = 1
 test "$(iw dev | grep -Ec "link ID[[:space:]]+[01]")" = 2
 test ! -e /tmp/wave7-postboot-link-monitor.ready
 test ! -e /tmp/wave7-postboot-link-monitor.done
 ping -I br-lan -c 2 -W 1 192.168.76.2 >/dev/null
 echo "$(cat /proc/sys/kernel/random/boot_id)"
')
[[ $old =~ ^[a-f0-9-]{36}$ ]]
ssh_redmi '
  set -eu
  test "$(cat /sys/class/net/lan2/carrier)" = 1
  test "$(cat /sys/class/net/lan2/operstate)" = up
  ip addr show lan2 | grep -q "192.168.76.2/24"
  ip addr show br-lan | grep -q "10.1.0.2/16"
  test ! -e /tmp/wave7-postboot-port-restore.pid
  command -v start-stop-daemon >/dev/null
'
printf 'PREFLIGHT_PASS Wave7=%s Redmi=10.1.0.2 dedicated_port=lan2; read-only=%s\n' "$old" "$([[ $action == --check ]] && echo yes || echo no)"
if [[ $action == --check ]]; then exit 0; fi

tag="postboot-copper-flap-$(date +%Y%m%d-%H%M%S)"
out="$base/$tag"
mkdir -p "$out"
printf 'Wave7 boot_id=%s\nMonitor SHA256=%s\n' "$old" "$expected" > "$out/preflight.txt"
log() { echo "$(date -Is) $*" | tee -a "$out/orchestrator.log"; }
waveunit="wave7-openwrt-watch-$tag.service"
fallbackunit="wave7-fallback-watch-$tag.service"
armed=0
complete=0
cleanup() {
  code=$?
  trap - EXIT
  if (( armed )); then
    for suffix in openwrt-watch.log fallback-watch.log openwrt-capture.txt pstore.txt ramoops-raw.bin; do
      f=/tmp/wave7-$tag-$suffix
      [[ ! -s $f ]] || cp -p "$f" "$out/" || :
    done
    if (( complete )); then
      systemctl --user stop "$waveunit" "$fallbackunit" >/dev/null 2>&1 || :
    else
      log 'Not accepted or no complete result: independent recovery observers remain armed.'
    fi
  fi
  exit "$code"
}
trap cleanup EXIT

scp -q -O -i /home/jan/.ssh/wave7-root-rsa -o BatchMode=yes -o IdentitiesOnly=yes \
 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
 "$root/wave7-postboot-link-monitor.sh" root@192.168.76.1:/tmp/wave7-postboot-link-monitor.sh
actual=$(ssh_wave 'sha256sum /tmp/wave7-postboot-link-monitor.sh' | cut -d' ' -f1)
[[ "$actual" == "$expected" ]]
scp -q -O -i /home/jan/.ssh/wave7-root-rsa -o BatchMode=yes -o IdentitiesOnly=yes  -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null  "$root/wave7-postboot-hard-guard.sh" root@192.168.76.1:/tmp/wave7-postboot-hard-guard.sh
guard_hash=$(sha256sum "$root/wave7-postboot-hard-guard.sh" | cut -d' ' -f1)
[[ "$guard_hash" == fbd706840b83a1b4cd8654b0d767d8811615ab6452f6165c03f4672f281a9f80 ]]
remote_guard_hash=$(ssh_wave 'sha256sum /tmp/wave7-postboot-hard-guard.sh' | cut -d' ' -f1)
[[ "$remote_guard_hash" == "$guard_hash" ]]
ssh_wave 'chmod 700 /tmp/wave7-postboot-link-monitor.sh /tmp/wave7-postboot-hard-guard.sh; test -c /dev/kmsg; test -w /proc/sysrq-trigger; test "$(cat /proc/sys/kernel/panic)" -ge 1'
log "On-router recovery observer staged; original healthy boot=$old"
systemd-run --user --quiet --unit="wave7-openwrt-watch-$tag" \
 --property=RuntimeMaxSec=900 -- \
 /home/jan/scripts/wave7/controlled-link/watch-new-boot-id.sh "$tag" "$old" ea66890908
systemd-run --user --quiet --unit="wave7-fallback-watch-$tag" \
 --property=RuntimeMaxSec=900 -- /home/jan/scripts/wave7/wave7-fallback-watch.sh "$tag"
armed=1
systemctl --user is-active --quiet "$waveunit"
systemctl --user is-active --quiet "$fallbackunit"
ssh_wave 'set -eu
 test ! -e /tmp/wave7-postboot-hard-guard.pid
 start-stop-daemon -S -b -m -p /tmp/wave7-postboot-hard-guard.pid   -x /bin/ash -- /tmp/wave7-postboot-hard-guard.sh "$(cat /proc/sys/kernel/random/boot_id)"   </dev/null >/dev/null 2>&1 || :
 sleep 1
 test -s /tmp/wave7-postboot-hard-guard.pid
 kill -0 "$(cat /tmp/wave7-postboot-hard-guard.pid)"
 echo HARD_GUARD_ARMED
' > "$out/router-hard-guard.txt"
ssh_wave 'set -eu
 start-stop-daemon -S -b -m -p /tmp/wave7-postboot-monitor.pid   -x /bin/ash -- /tmp/wave7-postboot-link-monitor.sh   </dev/null >/dev/null 2>&1 || :
'
for i in 1 2 3 4 5; do
  ssh_wave 'test -f /tmp/wave7-postboot-link-monitor.ready' && break || sleep 1
done
ssh_wave 'test -f /tmp/wave7-postboot-link-monitor.ready; test ! -f /tmp/wave7-postboot-link-monitor.done'
log 'Local monitor and independent timed hard recovery guard both armed.'
log 'Monitor ready, both recovery observers active. Triggering ONE 9-second copper link drop on Redmi lan2.'
ssh_redmi 'set -eu
 test ! -e /tmp/wave7-postboot-port-restore.pid
 start-stop-daemon -S -b -m -p /tmp/wave7-postboot-port-restore.pid   -x /bin/sh -- -c "exec >/dev/null 2>&1; sleep 9; ip link set lan2 up; logger -t wave7-postboot restored-lan2; rm -f /tmp/wave7-postboot-port-restore.pid" || :
 sleep 1
 test -s /tmp/wave7-postboot-port-restore.pid
 kill -0 "$(cat /tmp/wave7-postboot-port-restore.pid)"
 echo REDMI_RESTORE_TIMER_ARMED
' > "$out/redmi-control.txt" 2>&1
# The link cut can interrupt SSH. Restore is already independently armed.
ssh_redmi 'ip link set lan2 down' >> "$out/redmi-control.txt" 2>&1 || :
log 'Redmi lan2 cut with independent nine-second restore armed.'
sleep 13
ssh_redmi 'echo DATE=$(date -Is); echo OPERSTATE=$(cat /sys/class/net/lan2/operstate); echo CARRIER=$(cat /sys/class/net/lan2/carrier); logread | grep -F wave7-postboot | tail -4' \
 > "$out/redmi-restored.txt" 2>&1 || :
if ! ssh_redmi 'test "$(cat /sys/class/net/lan2/operstate)" = up; test "$(cat /sys/class/net/lan2/carrier)" = 1'; then
  log 'Redmi auto-restoration not yet verified; forcing dedicated port UP.'
  ssh_redmi 'ip link set lan2 up' || :
fi
log 'Redmi physical interface restored; checking Wave7 on-router result.'
for ((i=1; i<=100; i++)); do
  result=$(ssh_wave 'cat /tmp/wave7-postboot-link-monitor.done 2>/dev/null' 2>/dev/null || :)
  if [[ $result == SUCCESS* ]]; then
    log "WAVE7_MONITOR_$result"
    ssh_wave 'cat /tmp/wave7-postboot-link-monitor.log' > "$out/wave7-monitor.log"
    ssh_wave 'dmesg; echo ===GMAC===; ethtool -S lan; echo ===PPE===; cat /sys/kernel/debug/ppe/port_rx' \
     > "$out/wave7-posttest-dmesg-and-mib.txt"
    test "$(ssh_wave 'fw_printenv -n bootfail')" = 0
    test "$(ssh_wave 'cat /proc/sys/kernel/random/boot_id')" = "$old"
    a=$(ssh_wave 'cat /sys/class/net/lan/statistics/rx_packets')
    ssh_wave 'ping -I br-lan -c 3 -W 1 192.168.76.2' > "$out/peer-check.txt"
    b=$(ssh_wave 'cat /sys/class/net/lan/statistics/rx_packets')
    [[ "$b" =~ ^[0-9]+$ && "$a" =~ ^[0-9]+$ && b -gt a ]]
    log "ACCEPTED: Same boot; copper link recovered; received packets $a->$b."
    complete=1
    break
  fi
  if [[ $result == INCONCLUSIVE* ]]; then
    log "INCONCLUSIVE: $result"
    complete=1
    break
  fi
  # In failed receive path the on-router observer preserves its own
  # kernel trace with SysRq, and boot/fallback observers stay active.
  sleep 2
done
if (( ! complete )); then
  log 'No accepted post-test result within deadline; recovery observers stay active.'
  exit 4
fi
ssh_wave 'if test -s /tmp/wave7-postboot-hard-guard.pid; then kill "$(cat /tmp/wave7-postboot-hard-guard.pid)" 2>/dev/null || :; fi; rm -f /tmp/wave7-postboot-link-monitor.sh /tmp/wave7-postboot-link-monitor.log /tmp/wave7-postboot-link-monitor.ready /tmp/wave7-postboot-link-monitor.done /tmp/wave7-postboot-monitor.pid /tmp/wave7-postboot-hard-guard.sh /tmp/wave7-postboot-hard-guard.pid' >/dev/null 2>&1 || :
(cd "$out"; find . -maxdepth 1 -type f ! -name evidence.sha256 -print0 | sort -z | xargs -0 sha256sum > evidence.sha256; sha256sum -c evidence.sha256 | tail -8)
echo "EVIDENCE=$out"
