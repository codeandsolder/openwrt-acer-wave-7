#!/usr/bin/env bash
# Autonomous Asus-side WBE1.4 observer and rollback if native OpenWrt is healthy enough.
# Never issues a vendor firmware write. Does not disturb Q6 or PHY diagnostics.
set -Eeuo pipefail
umask 077
mode=${1:---check}
dir=/home/jan/firmware/wave7/trials/20261116-wbe14-compat
candidate_rev=r0+38249-wbe14-01734-test
accepted_rev=r0+38249-3b1851eda6
accepted_sha=a952779383ba6d6c0847951354af2d59a96e46b9422fba4fb0cda6e92a9877da
accepted="$dir/../20261115-pcs-analog-readback/pcs-analog-readback-3b1851eda6-sysupgrade.bin"
accepted_remote=/tmp/wave7-wbe14-accepted-rollback.bin
key=/home/jan/.ssh/wave7-root-rsa
host=root@192.168.76.1
ssh_opts=(-n -T -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=3 -o ConnectionAttempts=1 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
scp_opts=(-q -O -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 -o ConnectionAttempts=1 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
remote() { ssh "${ssh_opts[@]}" "$host" "$@"; }
log() { printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$output/observer.log"; }
state_read() {
  remote 'echo "boot=$(cat /proc/sys/kernel/random/boot_id)";
    echo "rev=$(cat /etc/openwrt_version)";
    echo "kernel=$(uname -r)";
    echo "bootfail=$(fw_printenv -n bootfail 2>/dev/null || :)";
    echo "keep=$(test -e /tmp/wave7-keep-boot && echo 1 || echo 0)";
    echo "ap=$(iw dev ap-mld0 info 2>/dev/null | grep -Ec "link ID[[:space:]]+[01]" || :)";
    echo "q6=$(for p in /sys/class/remoteproc/remoteproc0 /sys/class/remoteproc/remoteproc1 /sys/class/remoteproc/remoteproc2; do test "$(cat "$p/state" 2>/dev/null)" = running || exit 1; done && echo 3 || echo 0)";
    echo "ping=$(ping -I br-lan -c 1 -W 1 192.168.76.2 >/dev/null 2>&1 && echo 1 || echo 0)";
    echo "noc=$(dmesg | grep -c "NOC ERROR DETECTED" || :)";
    echo "uptime=$(cut -d. -f1 /proc/uptime)";
  '
}
value() { printf '%s\n' "$1" | sed -n "s/^$2=//p" | head -1; }
trial_healthy() {
  local state=$1
  [[ $(value "$state" rev) == "$candidate_rev" &&
     $(value "$state" kernel) == 6.18.60 &&
     $(value "$state" q6) == 3 &&
     $(value "$state" ap) == 2 &&
     $(value "$state" ping) == 1 &&
     $(value "$state" noc) == 0 &&
     $(value "$state" keep) == 1 &&
     $(value "$state" bootfail) == 0 ]]
}
if [[ $mode == --selftest ]]; then
  good=$'rev=r0+38249-wbe14-01734-test\nkernel=6.18.60\nq6=3\nap=2\nping=1\nnoc=0\nkeep=1\nbootfail=0'
  trial_healthy "$good" || { echo 'good state failed' >&2; exit 1; }
  for bad in "${good/ap=2/ap=1}" "${good/noc=0/noc=1}" "${good/keep=1/keep=0}" "${good/r0+38249-wbe14-01734-test/r0+38249-3b1851eda6}"; do
    if trial_healthy "$bad"; then echo 'invalid state accepted' >&2; exit 1; fi
  done
  echo OBSERVER_DECISION_TEST_PASS
  exit 0
fi
[[ -f $accepted && -r $key ]] || { echo "missing accepted image or SSH identity" >&2; exit 2; }
[[ $(sha256sum "$accepted" | cut -d' ' -f1) == "$accepted_sha" ]] || { echo "accepted image digest mismatch" >&2; exit 2; }
if [[ $mode == --check ]]; then
  state=$(state_read)
  [[ $(value "$state" rev) == "$accepted_rev" &&
     $(value "$state" bootfail) == 0 &&
     $(value "$state" keep) == 1 &&
     $(value "$state" q6) == 3 &&
     $(value "$state" ap) == 2 ]] || { echo "invalid baseline: $state" >&2; exit 3; }
  printf 'GUARD_PREFLIGHT_PASS\n%s\n' "$state"
  exit 0
fi
[[ $mode == --run && $# == 3 ]] || { echo 'usage: wbe14-watch.sh --check|--selftest|--run OLD_BOOT OUTPUT_DIR' >&2; exit 2; }
old_boot=$2
output=$3
[[ $old_boot =~ ^[a-f0-9-]{36}$ && $output == /home/jan/firmware/wave7/trials/20261116-wbe14-compat/runs/* ]] || exit 2
mkdir -p "$output"
exec 9>"$output/monitor.lock"
flock -n 9 || exit 3
log "GUARD_ARMED original_boot=$old_boot candidate_rev=$candidate_rev"
printf 'ARMED\n' > "$output/status"
seen_new=0
trial_boot=''
healthy_since=0
first_seen=0
rollback_triggered=0
restore_from_trial() {
  local reason=$1
  log "ROLLBACK_REQUESTED reason=$reason"
  printf 'ROLLBACK_TRIGGERED\n' > "$output/status"
  # Native upgrade requires accepted NAND root and bootfail0/keep marker.
  # Only execute while current new trial boot matches the expected revision
  # and is reachable. If firstboot guard has not accepted, let bootfail
  # APPSBL fallback and 120s watchdog handle it instead.
  local state
  state=$(state_read) || { log 'ROLLBACK_FAILED router_unreachable'; return 1; }
  [[ $(value "$state" boot) == "$trial_boot" &&
     $(value "$state" rev) == "$candidate_rev" &&
     $(value "$state" keep) == 1 &&
     $(value "$state" bootfail) == 0 ]] || {
    log "ROLLBACK_DEFERRED original_boot_not_accepted: $state"
    return 1
  }
  scp "${scp_opts[@]}" "$accepted" "$host:$accepted_remote" || {
    log 'ROLLBACK_FAILED upload'; return 1;
  }
  local verification
  verification=$(remote "sha256sum '$accepted_remote' && /sbin/sysupgrade -T -n '$accepted_remote'") || {
    log 'ROLLBACK_FAILED preflight'; return 1;
  }
  [[ $verification == "$accepted_sha  $accepted_remote"* ]] || {
    log 'ROLLBACK_FAILED digest_check'; return 1;
  }
  log 'ROLLBACK_NATIVE_SYSUPGRADE_START'
  timeout 90 ssh "${ssh_opts[@]}" "$host" "/sbin/sysupgrade -n '$accepted_remote'" >> "$output/restore.log" 2>&1 || :
  rollback_triggered=1
  return 0
}
for ((i=0;i<520;i++)); do
  now=$(date +%s)
  if state=$(state_read 2>/dev/null); then
    rev=$(value "$state" rev)
    kernel=$(value "$state" kernel)
    boot=$(value "$state" boot)
    [[ $boot =~ ^[a-f0-9-]{36}$ ]] || { sleep 2; continue; }
    if [[ $kernel == 5.4.213 ]]; then
      log "VENDOR_FALLBACK boot=$boot"
      printf 'VENDOR_FALLBACK\n' > "$output/status"
      exit 4
    fi
    if [[ $boot == "$old_boot" ]]; then
      if (( seen_new )); then log "ACCEPTED_OLD_BOOT_REAPPEARED boot=$boot"; printf 'ACCEPTED_RETURN\n' > "$output/status"; exit 0; fi
      if (( i % 12 == 0 )); then log 'STILL_ORIGINAL_BOOT'; fi
    elif [[ $rev == "$accepted_rev" ]]; then
      log "RESTORED_ACCEPTED_NEW_BOOT boot=$boot"
      printf 'ROLLED_BACK\n' > "$output/status"
      exit 0
    elif [[ $rev == "$candidate_rev" ]]; then
      if (( ! seen_new )); then
        seen_new=1
        trial_boot=$boot
        first_seen=$now
        log "CANDIDATE_BOOT_SEEN boot=$boot"
      fi
      printf '%s\n' "$state" > "$output/last-trial-state.txt"
      if (( rollback_triggered )); then
        if (( i % 6 == 0 )); then log 'AWAITING_ACCEPTED_ROLLBACK_BOOT'; fi
      elif trial_healthy "$state"; then
        if (( healthy_since == 0 )); then healthy_since=$now; log 'CANDIDATE_HEALTHY_FIRST_SEEN'; fi
        if (( now - healthy_since >= 360 )); then
          log "CANDIDATE_SOAK_PASS duration=$((now-healthy_since))s"
          printf 'CANDIDATE_SOAK_PASS\n' > "$output/status"
          exit 0
        fi
        if (( i % 6 == 0 )); then log "SOAKING duration=$((now-healthy_since))s"; fi
      else
        healthy_since=0
        if [[ $(value "$state" noc) =~ ^[1-9][0-9]*$ ]]; then
          restore_from_trial 'NOC_ERROR' || :
        elif (( now - first_seen >= 120 )) && [[ $(value "$state" keep) == 1 && $(value "$state" bootfail) == 0 ]]; then
          restore_from_trial 'UNHEALTHY_Q6_MLO_OR_PEER' || :
        elif (( i % 6 == 0 )); then
          log "TRIAL_NOT_YET_HEALTHY uptime=$(value "$state" uptime) q6=$(value "$state" q6) mlo=$(value "$state" ap) keep=$(value "$state" keep) bootfail=$(value "$state" bootfail)"
        fi
      fi
    else
      log "UNKNOWN_NEW_REVISION rev=$rev boot=$boot; no action"
    fi
  elif (( i % 12 == 0 )); then
    log 'SSH_UNREACHABLE awaiting_router_or_vendor_fallback'
  fi
  sleep 2
done
log 'GUARD_TIMEOUT_NO_FINAL_STATE'
printf 'TIMEOUT_NO_FINAL_STATE\n' > "$output/status"
exit 6
