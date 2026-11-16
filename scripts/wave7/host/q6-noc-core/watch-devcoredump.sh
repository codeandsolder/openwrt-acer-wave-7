#!/usr/bin/env bash
# Capture naturally occurring remoteproc devcoredumps over independent Asus SSH.
# No fault injection, router-side writes, or changes to remoteproc recovery.
set -Eeuo pipefail
umask 077
mode=${1:---check}
[[ $mode == --check || $mode == --run ]] || { echo 'usage: watch-devcoredump.sh --check|--run' >&2; exit 2; }
capture_dir=${WAVE7_Q6_DUMP_DIR:-/home/jan/firmware/wave7/captures/q6-devcore}
poll_seconds=${WAVE7_Q6_POLL_SECONDS:-15}
[[ $poll_seconds =~ ^[0-9]+$ ]] && (( poll_seconds >= 2 && poll_seconds <= 300 )) || { echo 'invalid poll seconds' >&2; exit 2; }
key=${WAVE7_Q6_SSH_KEY:-/home/jan/.ssh/wave7-root-rsa}
remote_host=${WAVE7_Q6_SSH_HOST:-root@192.168.76.1}
ssh_opts=(-n -T -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 -o ConnectionAttempts=1 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
log() { printf '%s %s\n' "$(date -Is)" "$*"; }
remote() { ssh "${ssh_opts[@]}" "$remote_host" "$@"; }
list_remote_dumps() {
  remote 'for p in /sys/class/devcoredump/devcd[0-9]*/data; do
    test -r "$p" || continue
    basename "$(dirname "$p")"
  done'
}
if [[ $mode == --check ]]; then
  dump_list=$(list_remote_dumps)
  log 'MONITOR_PREFLIGHT_PASS SSH_ACCESS=yes'
  if [[ -n $dump_list ]]; then
    printf '%s\n' "$dump_list" | sed 's/^/EXISTING_DUMP /'
  else
    log 'EXISTING_DUMP none'
  fi
  exit 0
fi
mkdir -p -- "$capture_dir"
exec 9>"$capture_dir/.monitor.lock"
flock -n 9 || { log 'Another devcoredump monitor is already running'; exit 1; }
declare -A seen=()
log "MONITOR_STARTED poll_seconds=$poll_seconds directory=$capture_dir"
capture_one() {
  local devcd=$1
  [[ $devcd =~ ^devcd[0-9]+$ ]] || { log "Invalid dump identifier: $devcd"; return 2; }
  local part hash dest context
  part=$(mktemp "$capture_dir/.capture.XXXXXXXX")
  # Reading this sysfs entry is safe. Writing to it discards the dump.
  if ! remote "cat /sys/class/devcoredump/$devcd/data" > "$part"; then
    rm -f -- "$part"
    log "FAILED_STREAM $devcd (retry)"
    return 1
  fi
  if [[ ! -s $part ]]; then
    rm -f -- "$part"
    log "FAILED_EMPTY $devcd (retry)"
    return 1
  fi
  read -r hash _ < <(sha256sum "$part")
  dest="$capture_dir/$hash.elf"
  context="$capture_dir/$hash.context.txt"
  if [[ -e $dest ]]; then
    if ! cmp -s "$part" "$dest"; then
      log "HASH_COLLISION $devcd $hash (refusing to overwrite)"
      mv -- "$part" "$capture_dir/$hash-$(date -u +%Y%m%dT%H%M%SZ).elf"
      return 1
    fi
    rm -f -- "$part"
    log "ALREADY_CAPTURED $devcd sha256=$hash"
  else
    mv -- "$part" "$dest"
    log "CAPTURED $devcd sha256=$hash bytes=$(stat -c %s "$dest")"
  fi
  if [[ ! -e $context ]]; then
    local tmpctx
    tmpctx=$(mktemp "$capture_dir/.context.XXXXXXXX")
    {
      printf 'Captured_UTC=%s\n' "$(date -u -Is)"
      printf 'Source=%s:%s\n' "$remote_host" "$devcd"
      printf 'SHA256=%s\n' "$hash"
      printf 'Local_ELF=%s\n' "$dest"
      printf 'ELF_HEADER\n'
      readelf -h "$dest" 2>&1 || true
      printf '\nROUTER_CONTEXT\n'
      remote 'echo BOOT_ID; cat /proc/sys/kernel/random/boot_id; echo OPENWRT_RELEASE; cat /etc/openwrt_release; echo Q6_STATES; for p in /sys/class/remoteproc/remoteproc*; do printf "%s " "$(basename "$p")"; cat "$p/state"; done; echo KERNEL_EVENTS; dmesg | tail -n 220' || true
    } > "$tmpctx"
    mv -- "$tmpctx" "$context"
  fi
}
while true; do
  if output=$(list_remote_dumps 2>/dev/null); then
    declare -A active=()
    while IFS= read -r devcd; do
      [[ -n $devcd ]] || continue
      [[ $devcd =~ ^devcd[0-9]+$ ]] || { log "INVALID_DEVCD $devcd"; continue; }
      active[$devcd]=1
      if [[ ! -v seen[$devcd] ]]; then
        if capture_one "$devcd"; then
          seen[$devcd]=1
        fi
      fi
    done <<< "$output"
    for old in "${!seen[@]}"; do
      if [[ ! -v active[$old] ]]; then
        unset 'seen[$old]'
      fi
    done
  else
    log 'SSH_UNREACHABLE retrying'
  fi
  sleep "$poll_seconds"
done
