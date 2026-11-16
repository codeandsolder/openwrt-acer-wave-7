#!/usr/bin/env bash
# Follow /dev/kmsg non-destructively; save each fatal event before context fetch.
set -Eeuo pipefail
umask 077
mode=${1:---check}
[[ $mode == --check || $mode == --run ]] || exit 2
dir=${WAVE7_NOC_EVENT_DIR:-/home/jan/firmware/wave7/captures/q6-noc-events}
key=${WAVE7_Q6_SSH_KEY:-/home/jan/.ssh/wave7-root-rsa}
host=${WAVE7_Q6_SSH_HOST:-root@192.168.76.1}
ssh_opts=(-n -T -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes
  -o ConnectTimeout=4 -o ConnectionAttempts=1
  -o ServerAliveInterval=10 -o ServerAliveCountMax=2
  -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
  -o LogLevel=ERROR)
log() { printf '%s %s\n' "$(date -Is)" "$*"; }
stream_command='
  printf "WAVE7_KMSG_BOOT=%s\n" "$(cat /proc/sys/kernel/random/boot_id)"
  printf "WAVE7_KMSG_REV=%s\n" "$(cat /etc/openwrt_version)"
  exec cat /dev/kmsg
'
context_command='
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
if [[ $mode == --check ]]; then
  response=$(ssh "${ssh_opts[@]}" "$host" 'test -r /dev/kmsg &&
    printf "BOOT_ID=%s\n" "$(cat /proc/sys/kernel/random/boot_id)" &&
    printf "REV=%s\n" "$(cat /etc/openwrt_version)"')
  [[ $response =~ BOOT_ID=([0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}) ]]
  found=${BASH_REMATCH[1]}
  [[ $response == *REV=r0+* ]]
  log "KMSG_STREAM_CHECK_PASS boot=$found"
  exit 0
fi
mkdir -p "$dir"
exec 9>"$dir/.kmsg-stream.lock"
flock -n 9 || { log 'KMSG stream collector already active'; exit 3; }
partial=''
cleanup() { [[ -z $partial ]] || rm -f -- "$partial"; }
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
log "KMSG_STREAM_STARTED dir=$dir"
while true; do
  boot='' revision=''
  # Explicit boot ID precedes the kmsg stream on every SSH reconnect.
  while IFS= read -r line; do
    if [[ $line =~ ^WAVE7_KMSG_BOOT=([0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12})$ ]]; then
      boot=${BASH_REMATCH[1]}
      revision=''
      continue
    fi
    if [[ $line == WAVE7_KMSG_REV=r0+* ]]; then
      revision=${line#WAVE7_KMSG_REV=}
      continue
    fi
    [[ -n $boot && -n $revision ]] || continue
    [[ $line == *'NOC ERROR DETECTED'* ]] || continue
    # /dev/kmsg: priority,monotonic_sequence,us_since_boot,flags;message
    kmsg_re="^[0-7],([0-9]+),[0-9]+,[^;]*;"; [[ $line =~ $kmsg_re ]] || continue
    seq=${BASH_REMATCH[1]}
    event="$dir/noc-kmsg-$boot-$seq.event.txt"
    if [[ ! -e $event ]]; then
      partial=$(mktemp "$dir/.noc-kmsg.partial.XXXXXXXX")
      printf 'CAPTURED_UTC=%s\nSTREAM_BOOT_ID=%s\nSTREAM_REV=%s\nKMSG_SEQUENCE=%s\nKMSG_RAW=%s\n' \
        "$(date -u -Is)" "$boot" "$revision" "$seq" "$line" > "$partial"
      mv -- "$partial" "$event"
      partial=''
      log "KMSG_EVENT_SAVED boot=$boot seq=$seq"
    fi
    sha256sum "$event" > "$event.sha256"
    target="$dir/noc-kmsg-$boot-$seq.kernel.txt"
    [[ ! -e $target ]] || continue
    partial=$(mktemp "$dir/.noc-kmsg.partial.XXXXXXXX")
    if timeout 15 ssh "${ssh_opts[@]}" "$host" "$context_command" > "$partial" 2>&1 &&
      rg -Fxq "BOOT_ID=$boot" "$partial" &&
      rg -Fq 'NOC ERROR DETECTED' "$partial"; then
      mv -- "$partial" "$target"
      partial=''
      sha256sum "$target" > "$target.sha256"
      log "KMSG_CONTEXT_ARCHIVED boot=$boot seq=$seq"
    else
      rm -f -- "$partial"
      partial=''
      log "KMSG_CONTEXT_UNAVAILABLE boot=$boot seq=$seq (event preserved)"
    fi
  done < <(ssh "${ssh_opts[@]}" "$host" "$stream_command" 2>/dev/null)
  log "KMSG_STREAM_RECONNECT"
  sleep 2
done
