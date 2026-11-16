#!/usr/bin/env bash
# Execute on Asus. Fail closed on first unexpected boot, fatal or Wyse failure.
set -Eeuo pipefail
umask 077
mode=$1
count=$2
[[ $mode == --check || $mode == --run ]] || exit 2
[[ $count =~ ^[1-9][0-9]*$ ]] && ((count <= 100)) || exit 2
export XDG_RUNTIME_DIR=/run/user/1000
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
[[ $(id -un) == jan ]] || exit 2
root=/home/jan/firmware/wave7/trials/20261116-cycle-stress
revision=r0+38249-napi-5e3df9b898
key=/home/jan/.ssh/wave7-root-rsa
target=root@192.168.76.1
remote() { ssh -n -T -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 -o ConnectionAttempts=1 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$target" "$@"; }
get() { sed -n "s/^$2=//p" <<< "$1" | head -1; }
message() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }
state() {
  remote '
    echo "boot=$(cat /proc/sys/kernel/random/boot_id)"
    echo "rev=$(cat /etc/openwrt_version)"
    echo "kernel=$(uname -r)"
    echo "bootfail=$(fw_printenv -n bootfail 2>/dev/null || :)"
    echo "keep=$(test -e /tmp/wave7-keep-boot && echo 1 || echo 0)"
    q6=0
    for r in /sys/class/remoteproc/remoteproc*; do
      if test "$(cat "$r/state" 2>/dev/null)" = running; then q6=$((q6+1)); fi
    done
    echo "q6=$q6"
    echo "mlo=$(iw dev ap-mld0 info 2>/dev/null | grep -Ec "link ID[[:space:]]+[01]" || :)"
    echo "peer=$(ping -I br-lan -c 1 -W 1 192.168.76.2 >/dev/null 2>&1 && echo 1 || echo 0)"
    echo "noc=$(dmesg | grep -c "NOC ERROR DETECTED" || :)"
  '
}
healthy() {
  local s=$1
  [[ $(get "$s" rev) == "$revision" &&
     $(get "$s" kernel) == 6.18.60 &&
     $(get "$s" bootfail) == 0 &&
     $(get "$s" keep) == 1 &&
     $(get "$s" q6) == 3 &&
     $(get "$s" mlo) == 2 &&
     $(get "$s" peer) == 1 &&
     $(get "$s" noc) == 0 ]]
}
valid_boot() { [[ $1 =~ ^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$ ]]; }
monitors() {
  [[ $(systemctl --user is-active wave7-q6-noc-events.service) == active &&
     $(systemctl --user is-active wave7-q6-noc-kmsg.service) == active &&
     $(systemctl --user is-active wave7-q6-devcoredump-capture.service) == active ]]
}
client() {
  local report
  report=$(timeout 20 ssh -n -T -o BatchMode=yes -o ConnectTimeout=5 acer \
    'ssh -n -T -o BatchMode=yes -o ConnectTimeout=5 wyse-eth "nmcli -g connection.autoconnect con show Wave7-MLO-Lab; iw dev wlp2s0 link; ip -4 route get 10.1.0.2; ping -I wlp2s0 -c 2 -W 2 192.168.76.1"' 2>/dev/null) || return 1
  [[ $report == yes$'\n'* &&
     $report == *'SSID: Wave7-MLO-Lab'* &&
     $report == *'Link 0 BSSID'* &&
     $report == *'Link 1 BSSID'* &&
     $report == *'dev eno1'* &&
     $report == *'2 received'* ]]
}
snapshot() {
  remote '
    echo ===BOOT===; cat /etc/openwrt_version; cat /proc/sys/kernel/random/boot_id
    echo ===BOOTFAIL===; fw_printenv -n bootfail 2>/dev/null || :
    echo ===Q6===; for r in /sys/class/remoteproc/remoteproc*; do echo "$r $(cat "$r/state")"; done
    echo ===MLO===; iw dev ap-mld0 info || :
    echo ===DMESG===; dmesg
    echo ===PSTORE===; ls -l /sys/fs/pstore 2>&1 || :
  ' > "$1" 2>&1 || :
}
[[ -r $key ]] && monitors || { echo GUARD_OR_KEY_UNAVAILABLE; exit 3; }
active=$(systemctl --user --no-pager --no-legend list-units --state=active 'wave7-napi-supervisor-*' 'wave7-fallback-watch-*' 'wave7-openwrt-watch-*' || :)
[[ -z $active ]] || { echo "CONCURRENT_TRIAL $active"; exit 3; }
before=$(state)
healthy "$before" || { echo "UNHEALTHY_BASELINE $before"; exit 3; }
previous=$(get "$before" boot)
valid_boot "$previous"
client || { echo WYSE_CLIENT_OR_OOB_FAILED; exit 3; }
message "PREFLIGHT_OK boot=$previous count=$count"
[[ $mode == --run ]] || exit 0

run=$root/reboots-$(date -u +%Y%m%dT%H%M%SZ)-$(cat /proc/sys/kernel/random/uuid)
mkdir -p "$run"
printf '%s\n' "$run" > "$root/active-reboot-run-path"
printf 'utc\tcycle\told_boot\tnew_boot\tready_s\twyse\tnoc\n' > "$run/reboots.tsv"
echo RUNNING > "$run/status"
completed=0
failed() {
  message "FAIL cycle=$((completed+1)) reason=$1" | tee -a "$run/events.log"
  echo "FAIL cycle=$((completed+1)) reason=$1" > "$run/status"
  snapshot "$run/failure-diagnostics.txt"
  exit 4
}
for ((i=1;i<=count;i++)); do
  monitors || failed MONITORS_UNAVAILABLE
  current=$(state) || failed ROUTER_UNREACHABLE_BEFORE_REBOOT
  healthy "$current" || failed UNHEALTHY_BEFORE_REBOOT
  [[ $(get "$current" boot) == "$previous" ]] || failed UNEXPECTED_REBOOT_BEFORE_CYCLE
  message "TRIGGER cycle=$i boot=$previous" | tee -a "$run/events.log"
  start=$(date +%s)
  timeout 14 ssh -n -T -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$target" /sbin/reboot > "$run/reboot-$i.log" 2>&1 || :
  ready=0
  sawnew=0
  while (( $(date +%s)-start < 270 )); do
    if current=$(state 2>/dev/null); then
      newboot=$(get "$current" boot)
      if valid_boot "$newboot" && [[ $newboot != "$previous" ]]; then
        sawnew=1
        [[ $(get "$current" rev) == "$revision" ]] || failed UNEXPECTED_FIRMWARE_REVISION
        [[ $(get "$current" noc) == 0 ]] || failed Q6_NOC_FATAL
        if healthy "$current"; then ready=1; break; fi
      fi
    fi
    sleep 4
  done
  ((sawnew)) || failed NO_NEW_BOOT_WITHIN_270S
  ((ready)) || failed NEW_BOOT_NOT_HEALTHY_WITHIN_270S
  elapsed=$(( $(date +%s)-start ))
  # Bootfail/keepboot acceptance happens around 95s. The original Q6
  # UMACNOC fatal has recurred at 99.9s: do not mistake this immediately
  # post-acceptance SSR for a subsequent Wyse association-only problem.
  sleep 12
  monitors || failed MONITOR_STOPPED_DURING_POSTBOOT_SOAK
  current=$(state) || failed ROUTER_LOST_DURING_POSTBOOT_SOAK
  [[ $(get "$current" boot) == "$newboot" ]] || failed SECOND_REBOOT_DURING_POSTBOOT_SOAK
  [[ $(get "$current" noc) == 0 ]] || failed Q6_NOC_FATAL_AFTER_BOOT_ACCEPTANCE
  healthy "$current" || failed UNHEALTHY_DURING_POSTBOOT_SOAK

  associated=0
  for ((k=0;k<12;k++)); do
    if client; then associated=1; break; fi
    sleep 3
  done
  if (( !associated )); then
    # The client failure may be a consequence of a newly recovered
    # remoteproc rather than an independent MLO association failure.
    if current=$(state 2>/dev/null); then
      [[ $(get "$current" noc) == 0 ]] ||
        failed Q6_NOC_FATAL_DURING_WYSE_RECONNECT
      [[ $(get "$current" boot) == "$newboot" ]] ||
        failed ROUTER_REBOOT_DURING_WYSE_RECONNECT
      healthy "$current" ||
        failed ROUTER_UNHEALTHY_DURING_WYSE_RECONNECT
    fi
    failed WYSE_NOT_DUAL_LINK_WITH_PING
  fi
  sleep 10
  monitors || failed MONITOR_STOPPED
  current=$(state) || failed ROUTER_LOST_AFTER_CLIENT
  [[ $(get "$current" noc) == 0 ]] || failed Q6_NOC_FATAL_AFTER_CLIENT
  healthy "$current" || failed UNHEALTHY_AFTER_CLIENT
  [[ $(get "$current" boot) == "$newboot" ]] || failed SECOND_REBOOT
  printf '%s\t%d\t%s\t%s\t%d\t1\t0\n' "$(date -u +%FT%TZ)" "$i" "$previous" "$newboot" "$elapsed" >> "$run/reboots.tsv"
  completed=$i
  previous=$newboot
  message "REBOOT_OK cycle=$i/$count boot=$newboot ready_seconds=$elapsed wyse_2links=1 noc=0" | tee -a "$run/events.log"
done
printf 'PASS %d/%d\n' "$completed" "$count" > "$run/status"
sha256sum "$run/reboots.tsv" > "$run/reboots.sha256"
message "REBOOTS_PASS count=$completed" | tee -a "$run/events.log"
