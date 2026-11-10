#!/usr/bin/env bash
set -euo pipefail
umask 077
tag=$1
[[ "$tag" =~ ^[a-z0-9][a-z0-9.-]{0,60}$ ]] || exit 2
out="/home/jan/firmware/wave7/logs/q6-noc-20261110/$tag"
[[ ! -e "$out" ]] || { echo "Trial path exists: $out" >&2; exit 2; }
mkdir -p "$out"
log="$out/observations.tsv"
router() { ssh -o BatchMode=yes -o ConnectTimeout=4 -o ConnectionAttempts=1 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@192.168.76.1 "$@" 2>/dev/null; }
old_boot=$(router 'cat /proc/sys/kernel/random/boot_id')
router 'set -e
  test "$(uname -r)" = 6.18.60
  grep -q dfe24ead9d /etc/openwrt_release
  test "$(fw_printenv -n bootfail)" = 0
  test -e /tmp/wave7-keep-boot
  test "$(dmesg | grep -c "NOC ERROR DETECTED" || true)" = 0
  test "$(iw dev ap-mld0 station dump | grep -c "^Station " || true)" = 1
  ping -I br-lan -c 2 -W 1 192.168.76.2 >/dev/null
'
printf '# trial=%s start=%s previous_boot=%s\n' "$tag" "$(date -Is)" "$old_boot" | tee "$log"
printf '# time\tboot_id\tuptime_s\tbootfail\tstations\tq6_noc_count\twmi_eshutdown_count\tq6_root_state\ttxpower\n' >> "$log"
router 'ubus call system reboot' > "$out/reboot-response.txt" 2>&1 || :
found=0
for n in $(seq 1 110); do
  boot=$(router 'cat /proc/sys/kernel/random/boot_id' || :)
  if [[ -n "$boot" && "$boot" != "$old_boot" ]]; then
    found=1
    printf 'BOOT_RESTART_CONFIRMED %s %s\n' "$(date -Is)" "$boot" | tee -a "$log"
    break
  fi
  sleep 3
done
if [[ $found != 1 ]]; then echo 'FAILED_TO_OBSERVE_NEW_BOOT' | tee -a "$log"; exit 5; fi
for n in $(seq 1 115); do
  data=$(router '
    up=$(cut -d" " -f1 /proc/uptime)
    bf=$(fw_printenv -n bootfail 2>/dev/null || echo err)
    st=$(iw dev ap-mld0 station dump 2>/dev/null | grep -c "^Station " || true)
    noc=$(dmesg | grep -c "NOC ERROR DETECTED" || true)
    wmi=$(dmesg | grep -c "failed to submit beacon template command: -108" || true)
    rp=$(cat /sys/class/remoteproc/remoteproc0/state 2>/dev/null || echo missing)
    tx=$(iw dev 2>/dev/null | grep -A4 "link ID  1" | grep txpower | head -1 | tr -s " " | sed "s/^ *//")
    printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\n" "$up" "$bf" "$st" "$noc" "$wmi" "$rp" "$tx"
  ' || :)
  if [[ -z "$data" ]]; then
    printf '%s\tunreachable\n' "$(date -Is)" >> "$log"
    sleep 3
    continue
  fi
  printf '%s\t%s\t%s\n' "$(date -Is)" "$boot" "$data" >> "$log"
  IFS=$'\t' read -r uptime bf stations noc wmi rp tx <<< "$data"
  if [[ "$noc" =~ ^[1-9][0-9]*$ ]]; then
    printf 'NOC_REPRODUCED %s uptime=%s stations=%s bf=%s\n' "$(date -Is)" "$uptime" "$stations" "$bf" | tee -a "$log"
    WAVE7_CAPTURE_DIR="$out" "$(dirname "$0")/wave7-capture-devcoredump.sh" "$tag" > "$out/capture-output.log" 2>&1 || echo "CAPTURE_FAILED: see capture-output.log" | tee -a "$log"
    router 'logread' > "$out/logread.txt" || :
    printf 'END_WITH_NOC_FATAL\n' >> "$log"
    exit 3
  fi
  if [[ "$uptime" =~ ^[0-9]+([.][0-9]+)?$ ]] && awk -v u="$uptime" 'BEGIN {exit !(u >= 340)}'; then
    if [[ "$bf" == 0 && "$stations" == 1 && "$wmi" == 0 ]]; then
      echo "EARLY_ASSOC_NO_NOC_THROUGH_$uptime" | tee -a "$log"
      router 'dmesg' > "$out/dmesg-success.txt" || :
      exit 0
    fi
  fi
  sleep 3
done
echo 'TRIAL_TIMEOUT_WITHOUT_CONCLUSION' | tee -a "$log"
exit 6
