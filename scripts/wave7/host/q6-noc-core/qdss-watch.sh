#!/usr/bin/env bash
# Independent Asus-side UMACNOC QDSS whole-image candidate observer and rollback.
# Never issues a vendor firmware write. Does not disturb Q6 or PHY diagnostics.
set -Eeuo pipefail
umask 077
mode=${1:---check}
candidate_rev=r0+38249-qdss-f086787166
baseline_rev=r0+38249-qdss-fc4cdcce47
accepted_rev=r0+38249-napi-5e3df9b898
accepted_sha=18e285b7dbfac4075a4f675b23c9b97cbf51c50aced6c16a82d1aab439dc0622
accepted=/home/jan/firmware/wave7/trials/20261116-napi-irq-ab/image-build/wave7-napi-5e3df9b898-sysupgrade.bin
accepted_remote=/tmp/wave7-qdss-accepted-rollback.bin
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
    echo "q6=$(healthy=1; for p in /sys/class/remoteproc/remoteproc0 /sys/class/remoteproc/remoteproc1 /sys/class/remoteproc/remoteproc2; do test "$(cat "$p/state" 2>/dev/null)" = running || healthy=0; done; if [ "$healthy" = 1 ]; then echo 3; else echo 0; fi)";
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
  good=$'rev=r0+38249-qdss-f086787166\nkernel=6.18.60\nq6=3\nap=2\nping=1\nnoc=0\nkeep=1\nbootfail=0'
  trial_healthy "$good" || { echo 'good state failed' >&2; exit 1; }
  for bad in "${good/ap=2/ap=1}" "${good/noc=0/noc=1}" "${good/keep=1/keep=0}" "${good/r0+38249-qdss-f086787166/r0+38249-qdss-fc4cdcce47}"; do
    if trial_healthy "$bad"; then echo 'invalid state accepted' >&2; exit 1; fi
  done
  echo QDSS_OBSERVER_DECISION_TEST_PASS
  exit 0
fi
[[ -f $accepted && -r $key ]] || { echo "missing accepted image or SSH identity" >&2; exit 2; }
[[ $(sha256sum "$accepted" | cut -d' ' -f1) == "$accepted_sha" ]] || { echo "accepted image digest mismatch" >&2; exit 2; }
if [[ $mode == --check ]]; then
  state=$(state_read)
  [[ $(value "$state" rev) == "$baseline_rev" &&
     $(value "$state" bootfail) == 0 &&
     $(value "$state" keep) == 1 &&
     $(value "$state" q6) == 3 &&
     $(value "$state" ap) == 2 ]] || { echo "invalid baseline: $state" >&2; exit 3; }
  printf 'GUARD_PREFLIGHT_PASS\n%s\n' "$state"
  exit 0
fi
[[ $mode == --run && $# == 3 ]] || { echo 'usage: qdss-watch.sh --check|--selftest|--run OLD_BOOT OUTPUT_DIR' >&2; exit 2; }
old_boot=$2
output=$3
[[ $old_boot =~ ^[a-f0-9-]{36}$ && $output == /home/jan/firmware/wave7/trials/20261117-umacnoc-qdss/runs/* ]] || exit 2
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
  # Snapshot first, while the failing UserPD firmware is still running.
  # The previous WBE1.4 A/B caught a fresh NoC error but rebooted before the
  # full fatal line/params could be preserved. This passive bounded copy
  # prevents losing that most useful correlation on a future trial.
  if timeout 15 ssh "${ssh_opts[@]}" "$host" \
    'echo BOOT; cat /proc/sys/kernel/random/boot_id; echo FW; cat /etc/openwrt_version; echo Q6; for r in /sys/class/remoteproc/remoteproc*; do echo "$(basename "$r")=$(cat "$r/state")"; done; echo DMESG; dmesg' \
    > "$output/pre-rollback-dmesg.txt" 2>&1; then
    log 'FAULT_KERNEL_LOG_ARCHIVED'
  else
    log 'FAULT_KERNEL_LOG_UNAVAILABLE'
  fi
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
for ((i=0;i<1000;i++)); do
  now=$(date +%s)
  if state=$(state_read 2>/dev/null); then
    rev=$(value "$state" rev)
    kernel=$(value "$state" kernel)
    boot=$(value "$state" boot)
    # An invalid/missing boot ID cannot count toward continuous health.
    [[ $boot =~ ^[a-f0-9-]{36}$ ]] || {
      healthy_since=0
      sleep 2
      continue
    }
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
      elif [[ $boot != "$trial_boot" ]]; then
        # Restart the soak after a reboot, even if the revision matches.
        healthy_since=0
        trial_boot=$boot
        first_seen=$now
        log "CANDIDATE_REBOOT_SEEN boot=$boot"
      fi
      printf '%s\n' "$state" > "$output/last-trial-state.txt"
      if (( rollback_triggered )); then
        if (( i % 6 == 0 )); then log 'AWAITING_ACCEPTED_ROLLBACK_BOOT'; fi
      elif trial_healthy "$state"; then
        if (( healthy_since == 0 )); then healthy_since=$now; log 'CANDIDATE_HEALTHY_FIRST_SEEN'; fi
        if (( now - healthy_since >= 900 )); then
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
      healthy_since=0
      log "UNKNOWN_NEW_REVISION rev=$rev boot=$boot; no action"
    fi
  else
    # Require an uninterrupted sequence of affirmative health checks.
    # A missed SSH probe is not evidence of a failure, but it does
    # invalidate a continuous-observation claim.
    if (( healthy_since != 0 )); then
      healthy_since=0
      log 'SOAK_RESET_UNOBSERVED ssh_probe_unavailable'
    elif (( i % 12 == 0 )); then
      log 'SSH_UNREACHABLE awaiting_router_or_vendor_fallback'
    fi
  fi
  sleep 2
done
log 'GUARD_TIMEOUT_NO_FINAL_STATE'
printf 'TIMEOUT_NO_FINAL_STATE\n' > "$output/status"
exit 6
