#!/usr/bin/env bash
# Read-only independent kernel-log capture for spontaneously occurring NoC faults.
set -Eeuo pipefail
umask 077
mode=${1:---check}
[[ $mode == --check || $mode == --run ]] || exit 2
dir=${WAVE7_NOC_EVENT_DIR:-/home/jan/firmware/wave7/captures/q6-noc-events}
poll=${WAVE7_NOC_POLL_SECONDS:-8}
[[ $poll =~ ^[0-9]+$ ]] && (( poll >= 2 && poll <= 300 )) || exit 2
key=${WAVE7_Q6_SSH_KEY:-/home/jan/.ssh/wave7-root-rsa}
host=${WAVE7_Q6_SSH_HOST:-root@192.168.76.1}
ssh_opts=(-n -T -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 -o ConnectionAttempts=1 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
remote() { ssh "${ssh_opts[@]}" "$host" "$@"; }
log() { printf '%s %s\n' "$(date -Is)" "$*"; }
probe() {
  remote 'echo "BOOT_ID=$(cat /proc/sys/kernel/random/boot_id)";
    echo "REV=$(cat /etc/openwrt_version)";
    dmesg | grep -F "NOC ERROR DETECTED" || :'
}
read_probe() {
  local response=$1
  boot=$(printf '%s\n' "$response" | sed -n 's/^BOOT_ID=//p' | head -1)
  revision=$(printf '%s\n' "$response" | sed -n 's/^REV=//p' | head -1)
  events=$(printf '%s\n' "$response" | rg -F 'NOC ERROR DETECTED' || :)
  [[ $boot =~ ^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$ && $revision == r0+* ]]
}
if [[ $mode == --check ]]; then
  response=$(probe)
  read_probe "$response"
  if [[ -n $events ]]; then count=$(printf '%s\n' "$events" | wc -l); else count=0; fi
  log "NOC_MONITOR_CHECK_PASS boot=$boot revision=$revision event_lines=$count"
  exit 0
fi
mkdir -p "$dir"
exec 9>"$dir/.monitor.lock"
flock -n 9 || { log 'NOC event collector already active'; exit 3; }
partial=''
cleanup() { [[ -z $partial ]] || rm -f -- "$partial"; }
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
log "NOC_MONITOR_STARTED poll=${poll}s dir=$dir"
while true; do
  if response=$(probe 2>/dev/null) && read_probe "$response"; then
    if [[ -n $events ]]; then
      fingerprint=$(printf '%s\n' "$events" | sha256sum | cut -d' ' -f1)
      target="$dir/noc-$boot-$fingerprint.kernel.txt"
      if [[ ! -e $target ]]; then
        partial=$(mktemp "$dir/.noc.partial.XXXXXXXX")
        if {
          printf 'CAPTURED_UTC=%s\nPROBE_BOOT_ID=%s\nPROBE_REV=%s\nEVENTS_SHA256=%s\n' \
            "$(date -u -Is)" "$boot" "$revision" "$fingerprint"
          timeout 15 ssh "${ssh_opts[@]}" "$host" '
            echo ====ROUTER_CONTEXT====
            echo "BOOT_ID=$(cat /proc/sys/kernel/random/boot_id)"
            echo "REV=$(cat /etc/openwrt_version)"
            echo ====REMOTEPROC====
            for p in /sys/class/remoteproc/remoteproc*; do
              printf "%s=" "$(basename "$p")"; cat "$p/state"
            done
            echo ====KERNEL_DMESG====
            dmesg
            echo ====DEVCOREDUMP_ENTRIES====
            ls /sys/class/devcoredump/ 2>/dev/null || :
          '
        } > "$partial" 2>&1 &&
          rg -Fxq "BOOT_ID=$boot" "$partial" &&
          rg -Fq "NOC ERROR DETECTED" "$partial"; then
          mv -- "$partial" "$target"
          partial=''
          sha256sum "$target" > "$target.sha256"
          log "NOC_EVENT_ARCHIVED boot=$boot rev=$revision events_sha256=$fingerprint file=$target"
        else
          rm -f -- "$partial"
          partial=''
          log "NOC_CAPTURE_INCOMPLETE boot=$boot (retry if boot persists)"
        fi
      fi
    fi
  else
    log 'NOC_PROBE_UNAVAILABLE retrying'
  fi
  sleep "$poll"
done
