#!/usr/bin/env bash
# Independent Asus native NAND trial/rollback for integrated Wave7 firmware.
set -Eeuo pipefail
umask 077
mode=--check
if (( $# )); then mode=$1; fi
base=/home/jan/firmware/wave7/trials/20261119-prod-integrated-0fbc2cc77b
candidate="$base/openwrt-qualcommbe-ipq53xx-acer_wave7-squashfs-sysupgrade.bin"
accepted=/home/jan/firmware/wave7/trials/20261118-asus-dualport/wave7-port0-16a784ae-sysupgrade.bin
# SHA manifest arrives only after final image QA and verified transport from
# Acer; no fallback SHA or force mode exists.
candidate_sha=$(awk '$2 == "openwrt-qualcommbe-ipq53xx-acer_wave7-squashfs-sysupgrade.bin" {print $1}' "$base/SHA256SUMS" 2>/dev/null || :)
accepted_sha=6098ac96a49f9d9384983e0d8f5534fefe6ad5cf743c217484f7a4b124cc9f3b
candidate_rev=r0+38346-0fbc2cc77b
accepted_rev=r0+38249-port0-16a784ae
key=/home/jan/.ssh/wave7-root-rsa
known=/home/jan/firmware/wave7/trials/20261118-asus-dualport/known_hosts
host=root@192.168.76.1
remote() {
  ssh -n -T -i "$key" -o BindInterface=enp4s0f4u2u2u4 -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 \
    -o ConnectionAttempts=1 -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$known" "$host" "$@"
}
remote_timed() {
  timeout 135 ssh -n -T -i "$key" -o BindInterface=enp4s0f4u2u2u4 -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 \
    -o ConnectionAttempts=1 -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$known" "$host" "$@"
}
upload() {
  scp -q -O -i "$key" -o BindInterface=enp4s0f4u2u2u4 -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=5 \
    -o ConnectionAttempts=1 -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$known" "$1" "$host:$2"
}
fatal() { printf 'PREFLIGHT_BLOCKED: %s\n' "$*" >&2; exit 3; }
value() { sed -n "s/^$2=//p" <<< "$1" | head -1; }
read_state() {
  remote 'echo "boot=$(cat /proc/sys/kernel/random/boot_id)";
    echo "rev=$(cat /etc/openwrt_version)";
    echo "kernel=$(uname -r)";
    echo "bootfail=$(fw_printenv -n bootfail 2>/dev/null || :)";
    echo "keep=$(test -e /tmp/wave7-keep-boot && echo 1 || echo 0)";
    echo "ap=$(iw dev ap-mld0 info 2>/dev/null | grep -Ec "link ID[[:space:]]+[01]" || :)";
    echo "q6=$(good=0; for p in /sys/class/remoteproc/remoteproc0 /sys/class/remoteproc/remoteproc1 /sys/class/remoteproc/remoteproc2; do [ "$(cat "$p/state" 2>/dev/null)" = running ] && good=$((good+1)); done; echo "$good")";
    echo "ping=$(ping -I br-lan -c 1 -W 1 192.168.76.2 >/dev/null 2>&1 && echo 1 || echo 0)";
    echo "noc=$(dmesg | grep -c "NOC ERROR DETECTED" || :)";
    echo "lan=$(cat /sys/class/net/lan/carrier 2>/dev/null || echo absent)";
    echo "lan_speed=$(cat /sys/class/net/lan/speed 2>/dev/null || echo absent)";
    echo "lan1=$(cat /sys/class/net/lan1/carrier 2>/dev/null || echo absent)";
    echo "bridge=$(readlink /sys/class/net/lan1/master 2>/dev/null | grep -q br-lan && echo 1 || echo 0)";
    echo "speed=$(cat /sys/class/net/lan1/speed 2>/dev/null || echo absent)";
    echo "uptime=$(cut -d. -f1 /proc/uptime)"'
}
healthy() {
  local s=$1
  for expect in "rev=$candidate_rev" kernel=6.18.60 bootfail=0 keep=1 ap=2 \
    q6=3 ping=1 noc=0 lan=1 lan_speed=2500 lan1=1 bridge=1 speed=1000; do
    grep -Fxq "$expect" <<< "$s" || return 1
  done
}
XDG_RUNTIME_DIR=/run/user/$(id -u)
export XDG_RUNTIME_DIR
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
if [[ $mode == --selftest ]]; then
  s=$'rev=r0+38346-0fbc2cc77b\nkernel=6.18.60\nbootfail=0\nkeep=1\nap=2\nq6=3\nping=1\nnoc=0\nlan=1\nlan_speed=2500\nlan1=1\nbridge=1\nspeed=1000'
  healthy "$s" || fatal 'good state rejected'
  for change in q6=2 ap=1 ping=0 noc=1 lan=0 lan_speed=1000 lan1=0 bridge=0 speed=2500 bootfail=4; do
    field=$(cut -d= -f1 <<< "$change")
    bad=$(sed "s/^$field=.*/$change/" <<< "$s")
    if healthy "$bad"; then fatal "bad state accepted: $change"; fi
  done
  echo INTEGRATED_GUARD_SELFTEST_PASS
  exit 0
fi
[[ $(id -un) == jan && -r $known && -r $key ]] || fatal 'Asus jan SSH identity absent'
if [[ $mode == --watch ]]; then
  [[ $# == 3 ]] || fatal 'watch requires old boot and directory'
  old_boot=$2
  out=$3
  [[ $old_boot =~ ^[0-9a-f-]{36}$ && $out == "$base"/runs/* ]] || fatal 'invalid watch parameters'
  mkdir -p "$out"
  exec 9>"$out/.watch.lock"
  flock -n 9 || fatal 'supervisor already running'
  log() { echo "$(date -Is) $*" | tee -a "$out/observer.log"; }
  log "ARMED predecessor=$old_boot"
  echo ARMED > "$out/status"
  trial_boot=''
  first_seen=0
  healthy_since=0
  rollback=0
  restore() {
    local cause=$1 state=$2 check
    (( rollback == 0 )) || return 0
    rollback=1
    log "ROLLBACK_REQUESTED cause=$cause"
    echo ROLLBACK_REQUESTED > "$out/status"
    remote 'echo ====BOOT====; cat /proc/sys/kernel/random/boot_id; echo ====DMESG====; dmesg; echo ====ETHERNET====; ethtool lan1' > "$out/pre-rollback.txt" 2>&1 || :
    [[ $(value "$state" rev) == "$candidate_rev" && $(value "$state" keep) == 1 &&
       $(value "$state" bootfail) == 0 ]] || { log ROLLBACK_DEFERRED_UNACCEPTED_BOOT; return 1; }
    upload "$accepted" /tmp/wave7-integrated-restore.bin || { log RESTORE_COPY_FAILED; return 1; }
    check=$(remote 'sha256sum /tmp/wave7-integrated-restore.bin; /sbin/sysupgrade -T -n /tmp/wave7-integrated-restore.bin') || { log RESTORE_PREFLIGHT_FAILED; return 1; }
    [[ $check == "$accepted_sha  /tmp/wave7-integrated-restore.bin"* ]] || { log RESTORE_SHA_FAILED; return 1; }
    log RESTORE_NATIVE_SYSUPGRADE
    remote_timed '/sbin/sysupgrade -n /tmp/wave7-integrated-restore.bin' > "$out/restore.log" 2>&1 || :
    echo RESTORE_ISSUED > "$out/status"
  }
  for ((i=0;i<410;i++)); do
    now=$(date +%s)
    if s=$(read_state 2>/dev/null); then
      boot=$(value "$s" boot)
      rev=$(value "$s" rev)
      [[ $boot =~ ^[0-9a-f-]{36}$ ]] || { sleep 3; continue; }
      if [[ $(value "$s" kernel) == 5.4.213 ]]; then
        log "VENDOR_FALLBACK boot=$boot"; echo VENDOR_FALLBACK > "$out/status"; exit 4
      elif [[ $boot == "$old_boot" ]]; then
        (( i % 10 )) || log STILL_ORIGINAL_BOOT
      elif [[ $rev == "$accepted_rev" ]]; then
        log "ACCEPTED_IMAGE_BOOT boot=$boot"; echo RESTORED > "$out/status"; exit 0
      elif [[ $rev == "$candidate_rev" ]]; then
        if [[ $trial_boot != "$boot" ]]; then
          trial_boot=$boot; first_seen=$now; healthy_since=0
          log "TRIAL_BOOT boot=$boot"
        fi
        printf '%s\n' "$s" > "$out/latest-state.txt"
        if (( rollback )); then
          (( i % 10 )) || log AWAITING_RESTORE
        elif healthy "$s"; then
          if (( healthy_since == 0 )); then
            healthy_since=$now; log FIRST_HEALTHY; echo SOAKING > "$out/status"
          fi
          if (( now-healthy_since >= 300 )); then
            log "SOAK_PASS seconds=$((now-healthy_since))"
            echo SOAK_PASS > "$out/status"
            exit 0
          fi
        else
          healthy_since=0
          if [[ $(value "$s" noc) =~ ^[1-9][0-9]*$ ]]; then
            restore NOC_FATAL "$s" || :
          elif (( now-first_seen > 165 )) && [[ $(value "$s" keep) == 1 && $(value "$s" bootfail) == 0 ]]; then
            restore UNHEALTHY_PORT_OR_RADIO "$s" || :
          elif (( i % 5 == 0 )); then
            log "WAIT q6=$(value "$s" q6) ap=$(value "$s" ap) lan1=$(value "$s" lan1) bridge=$(value "$s" bridge)"
          fi
        fi
      else
        log "UNKNOWN_REVISION rev=$rev boot=$boot"
        echo UNKNOWN_REVISION > "$out/status"
        exit 5
      fi
    else
      healthy_since=0
      (( i % 10 )) || log ROUTER_UNREACHABLE
    fi
    sleep 3
  done
  log WATCH_TIMEOUT
  echo TIMEOUT > "$out/status"
  exit 6
fi
[[ $mode == --check || $mode == --check-baseline || $mode == --run ]] || fatal "unknown mode $mode"
[[ -r $accepted ]] || fatal 'missing accepted rollback'
[[ $(sha256sum "$accepted" | cut -d' ' -f1) == "$accepted_sha" ]] || fatal 'accepted SHA mismatch'
[[ $(tar xOf "$accepted" sysupgrade-acer_wave7/CONTROL) == BOARD=acer_wave7 ]] || fatal 'wrong accepted board'
if [[ $mode != --check-baseline ]]; then
  [[ $candidate_sha =~ ^[a-f0-9]{64}$ ]] || fatal 'candidate digest not pinned by final QA'
  [[ -r $candidate ]] || fatal 'candidate image missing'
  [[ $(sha256sum "$candidate" | cut -d' ' -f1) == "$candidate_sha" ]] || fatal 'candidate SHA mismatch'
  [[ $(tar xOf "$candidate" sysupgrade-acer_wave7/CONTROL) == BOARD=acer_wave7 ]] || fatal 'wrong candidate board'
fi
ip -4 addr show dev enp4s0f4u2u4 | grep -q '192.168.76.2/24' || fatal 'Asus 2.5GbE .2 peer absent'
ip -4 addr show dev enp4s0f4u2u4 | grep -q '192.168.76.181/24' || fatal 'Asus 2.5GbE DHCP address absent'
ip -4 addr show dev enp4s0f4u2u2u4 | grep -q '192.168.76.190/24' || fatal 'independent 1GbE management absent'
[[ $(cat /sys/class/net/enp4s0f4u2u2u4/carrier) == 1 ]] || fatal 'management carrier down'
s=$(read_state) || fatal 'router inaccessible'
boot=$(value "$s" boot)
[[ $boot =~ ^[0-9a-f-]{36}$ ]] || fatal 'invalid boot ID'
for expect in "rev=$accepted_rev" kernel=6.18.60 bootfail=0 keep=1 ap=2 q6=3 ping=1 noc=0 lan=1 lan_speed=2500 lan1=1 bridge=1 speed=1000; do
  grep -Fxq "$expect" <<< "$s" || fatal "unhealthy source: $expect; $s"
done
for name in wave7-q6-devcoredump-capture wave7-q6-noc-kmsg wave7-q6-noc-events; do
  systemctl --user is-active --quiet "$name.service" || fatal "$name inactive"
done
test -z "$(systemctl --user --no-pager --no-legend list-units --state=active 'wave7-openwrt-watch-*' 'wave7-fallback-watch-*' 'wave7-napi-supervisor-*' 'wave7-qdss-supervisor-*' 'wave7-integrated-supervisor-*')" || fatal 'another supervisor active'
echo "PREFLIGHT_PASS predecessor=$boot candidate=$candidate_sha mode=$mode"
[[ $mode == --run ]] || exit 0
tag=integrated-$(date +%Y%m%d-%H%M%S)
out="$base/runs/$tag"
mkdir -p "$out"
printf '%s\n' "$s" > "$out/preflight.txt"
for pair in "$candidate|/tmp/wave7-integrated-trial.bin|$candidate_sha" "$accepted|/tmp/wave7-integrated-baseline.bin|$accepted_sha"; do
  IFS='|' read -r source dest digest <<< "$pair"
  upload "$source" "$dest"
  check=$(remote "sha256sum '$dest'; /sbin/sysupgrade -T -n '$dest'")
  [[ $check == "$digest  $dest"* ]] || fatal "remote sysupgrade check failed: $dest"
done
guard="wave7-integrated-supervisor-$tag"
fallback="wave7-fallback-watch-$tag"
flash_started=0
cleanup() {
  local rc=$?
  if (( rc != 0 && !flash_started )); then
    systemctl --user stop "$guard.service" "$fallback.service" >/dev/null 2>&1 || :
    echo ABORTED_PRE_FLASH > "$out/status"
  fi
}
trap cleanup EXIT
systemd-run --user --quiet --unit="$guard" --property=RuntimeMaxSec=1500 -- \
  /home/jan/scripts/wave7/prod-integrated/trial.sh --watch "$boot" "$out"
systemd-run --user --quiet --unit="$fallback" --property=RuntimeMaxSec=1500 -- \
  /home/jan/scripts/wave7/wave7-fallback-watch.sh "$tag"
sleep 2
systemctl --user is-active --quiet "$guard.service" || fatal 'supervisor failed to arm'
systemctl --user is-active --quiet "$fallback.service" || fatal 'fallback collector failed to arm'
[[ $(cat "$out/status") == ARMED ]] || fatal 'supervisor acknowledgement absent'
echo "GUARDS_ARMED $tag"
flash_started=1
set +e
remote_timed '/sbin/sysupgrade -n /tmp/wave7-integrated-trial.bin' > "$out/sysupgrade.log" 2>&1
rc=$?
set -e
echo "FLASH_SSH_RC=$rc" | tee -a "$out/sysupgrade.log"
if ! grep -q 'Commencing upgrade\. Closing all shell sessions\.' "$out/sysupgrade.log"; then
  # A refused upgrade must not be treated as an attempted flash.
  flash_started=0
  fatal "sysupgrade did not reach its actual upgrade stage"
fi
echo "RUN_DIR=$out"
