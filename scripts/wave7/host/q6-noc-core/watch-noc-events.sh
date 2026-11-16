#!/usr/bin/env bash
# Read-only independent kernel-log capture for spontaneously occurring NoC faults.
set -Eeuo pipefail
umask 077
mode=${1:---check}
[[ $mode == --check || $mode == --run ]] || exit 2
dir=${WAVE7_NOC_EVENT_DIR:-/home/jan/firmware/wave7/captures/q6-noc-events}
poll=${WAVE7_NOC_POLL_SECONDS:-8}
early_poll=${WAVE7_NOC_EARLY_POLL_SECONDS:-2}
early_window=${WAVE7_NOC_EARLY_WINDOW_SECONDS:-150}
[[ $poll =~ ^[0-9]+$ ]] && (( poll >= 2 && poll <= 300 )) || exit 2
[[ $early_poll =~ ^[0-9]+$ ]] && (( early_poll >= 2 && early_poll <= poll )) || exit 2
[[ $early_window =~ ^[0-9]+$ ]] && (( early_window >= 30 && early_window <= 600 )) || exit 2
key=${WAVE7_Q6_SSH_KEY:-/home/jan/.ssh/wave7-root-rsa}
host=${WAVE7_Q6_SSH_HOST:-root@192.168.76.1}
ssh_opts=(-n -T -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 -o ConnectionAttempts=1 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
remote() { ssh "${ssh_opts[@]}" "$host" "$@"; }
log() { printf '%s %s\n' "$(date -Is)" "$*"; }
probe() {
  remote 'echo "BOOT_ID=$(cat /proc/sys/kernel/random/boot_id)";
    echo "REV=$(cat /etc/openwrt_version)";
    dmesg | grep -F "NOC ERROR DETECTED" || :
    echo "====WAVE7_IRQS===="
    cat /proc/interrupts
    echo "====WAVE7_IRQS_END===="
    printf "WAVE7_UPTIME=%s\\n" "$(cut -d " " -f1 /proc/uptime)"
    printf "WAVE7_STATION_COUNT=%s\\n" "$(iw dev ap-mld0 station dump | grep -c "^Station " || :)"'
}
read_probe() {
  local response=$1
  boot=$(printf '%s\n' "$response" | sed -n 's/^BOOT_ID=//p' | head -1)
  revision=$(printf '%s\n' "$response" | sed -n 's/^REV=//p' | head -1)
  events=$(printf '%s\n' "$response" | rg -F 'NOC ERROR DETECTED' || :)
  uptime=$(printf '%s\n' "$response" | sed -n 's/^WAVE7_UPTIME=//p' | head -1)
  stations=$(printf '%s\n' "$response" | sed -n 's/^WAVE7_STATION_COUNT=//p' | head -1)
  [[ $boot =~ ^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$ &&
     $revision == r0+* &&
     $uptime =~ ^[0-9]+(\.[0-9]+)?$ &&
     $stations =~ ^[0-9]+$ &&
     $response == *'====WAVE7_IRQS===='* &&
     $response == *'====WAVE7_IRQS_END===='* ]]
}
irq_sample() {
  local response=$1 wallclock=$2 uptime=$3 stations=$4 revision=$5
  # Select by registered IRQ name, not by an assumed SoC IRQ number.
  # Numeric per-CPU columns are summed; preserve each IRQ's actual identity.
  printf '%s\n' "$response" | awk -v wall="$wallclock" -v up="$uptime" \
    -v sta="$stations" -v rev="$revision" '
    /^====WAVE7_IRQS====$/ { active = 1; next }
    /^====WAVE7_IRQS_END====$/ { active = 0; next }
    active && $1 ~ /^[0-9]+:$/ {
      id = substr($1, 1, length($1) - 1)
      total = 0
      for (i = 2; i <= NF && $i ~ /^[0-9]+$/; i++)
        total += $i
      if (i == 2)
        next
      name = $NF
      if (name ~ /^ce[0-9]+$/ ||
          name ~ /^pci[0-9]+_wlan_/ ||
          name ~ /^(rxdma|reo|wbm|host2)/ ||
          name ~ /^smp2p-/ ||
          $0 ~ /q6v5/) {
        printf "%s\t%s\t%s\t%s\t%.0f\t%s\t%s\n",
          wall, up, sta, id, total, name, rev
      }
    }
  '
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
  sleep_seconds=$poll
  if response=$(probe 2>/dev/null) && read_probe "$response"; then
    # The same read-only probe runs at 2s intervals only during early
    # Q6/UserPD startup. A previous NoC fatal occurred at uptime 99.9s;
    # the normal 8s cadence straddled its crucial IRQ transition.
    if (( 10#${uptime%%.*} <= early_window )); then
      sleep_seconds=$early_poll
    fi
    irq_file="$dir/irq-$boot.tsv"
    if [[ ! -s $irq_file ]]; then
      printf 'captured_utc\trouter_uptime_s\tassociated_stations\tirq_number\tcount\tirq_name\trevision\n' >> "$irq_file"
    fi
    irq_sample "$response" "$(date -u -Is)" "$uptime" "$stations" "$revision" >> "$irq_file"
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
  sleep "$sleep_seconds"
done
