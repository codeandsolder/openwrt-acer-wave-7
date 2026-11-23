#!/usr/bin/env bash
# Isolated finite-snapshot scan/PM trace during a guarded MT7925 client test.
set -Eeuo pipefail
[[ $EUID == 0 && $# == 4 &&
   $1 =~ ^0498-[0-9]{8}-[0-9]{6}$ &&
   $2 == upstream-prefix22-authorize-primary-mld-trace &&
   $3 =~ ^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$ &&
   $4 =~ ^[0-9]{2,3}$ && $4 -ge 40 && $4 -le 180 ]] || exit 2
tag=$1 variant=$2 boot=$3 duration=$4
guard=/home/jan/scripts/wave7/client-validation/client-module-stack.sh
root=/sys/kernel/tracing
[[ $(cat /proc/sys/kernel/random/boot_id) == "$boot" &&
   $(uname -r) == 7.4.0-rc1-2-cachyos-rc ]]
bash "$guard" "$variant" --check-candidate
ip -4 route get 10.1.0.2 | rg -Fq 'dev eno1 '
functions=(
    mt7925_mcu_hw_scan mt7925_mcu_cancel_hw_scan
    mt7925_scan_work mt7925_roc_work
    mt7925_mcu_set_roc mt7925_mcu_set_mlo_roc
    mt792x_pm_power_save_work mt792x_pm_wake_work
    mt792x_mcu_drv_pmctrl mt792x_mcu_fw_pmctrl
    mt7925_mlo_pm_work mt7925_mac_sta_event
)
events=(
    mac80211/drv_hw_scan mac80211/drv_cancel_hw_scan
    mac80211/drv_return_int mac80211/api_scan_completed
    mac80211/drv_change_vif_links mac80211/drv_change_sta_links
    mac80211/api_beacon_loss mac80211/api_connection_loss
    mac80211/stop_queue mac80211/wake_queue
    cfg80211/cfg80211_scan_done
    mt7925_lab/mt7925_lab_scan_req
    mt7925_lab/mt7925_lab_scan_tlv
    mt7925_lab/mt7925_lab_txs_peer_data
    mt7925_lab/mt7925_lab_beacon_loss
)
awk -v functions="${functions[*]}" '
  BEGIN {
    n=split(functions, names, " ")
    for (i=1; i<=n; i++) need[names[i]]=1
  }
  ($1 in need) {seen[$1]=1}
  END {
    for (name in need) if (!(name in seen)) {
      print "SCAN_PM_FUNCTION_MISSING " name > "/dev/stderr"
      fail=1
    }
    exit fail
  }
' "$root/available_filter_functions"
for e in "${events[@]}"; do
    [[ -r $root/events/$e/format ]] || {
        echo "SCAN_PM_EVENT_MISSING $e" >&2
        exit 1
    }
done
grep -Fxq function < <(tr ' ' '\n' < "$root/available_tracers")
inst="$root/instances/wave7-scanpm-$tag"
[[ ! -e $inst ]]
created=0
cleanup() {
    local rc=$?
    trap - EXIT HUP INT TERM
    if (( created )) && [[ -d $inst ]]; then
        printf '0\n' > "$inst/tracing_on" || rc=1
        printf 'nop\n' > "$inst/current_tracer" || rc=1
        for e in "${events[@]}"; do
            printf '0\n' > "$inst/events/$e/enable" || rc=1
        done
        rmdir "$inst" || rc=1
    fi
    printf 'SCAN_PM_CLEANUP rc=%d\n' "$rc"
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP
mkdir "$inst"
created=1
printf '0\n' > "$inst/tracing_on"
printf 'nop\n' > "$inst/current_tracer"
printf 'mono\n' > "$inst/trace_clock"
printf '4096\n' > "$inst/buffer_size_kb"
printf '%s\n' "${functions[@]}" > "$inst/set_ftrace_filter"
printf 'function\n' > "$inst/current_tracer"
for e in "${events[@]}"; do
    printf '1\n' > "$inst/events/$e/enable"
done
printf 'SCAN_PM_TRACE_BOOT %s\n' "$boot"
printf 'SCAN_PM_TRACE_FUNCTIONS\n%s\n' "${functions[@]}"
printf 'SCAN_PM_TRACE_EVENTS\n%s\n' "${events[@]}"
printf '1\n' > "$inst/tracing_on"
printf 'SCAN_PM_READY epoch=%s\n' "$(date +%s.%N)"
for ((i=0; i<duration; i+=5)); do
    before=$(date +%s.%N)
    printf 'wave7_scanpm_anchor=%d\n' "$i" > "$inst/trace_marker"
    after=$(date +%s.%N)
    printf 'SCAN_PM_ANCHOR %d %s %s\n' "$i" "$before" "$after"
    sleep 5
done
printf '0\n' > "$inst/tracing_on"
printf 'SCAN_PM_TRACE_STATS\n'
for stats in "$inst"/per_cpu/cpu*/stats; do
    printf '%s\n' "$stats"
    cat "$stats"
done
printf 'SCAN_PM_TRACE_DATA\n'
cat "$inst/trace"
printf 'SCAN_PM_TRACE_END boot=%s\n' "$(cat /proc/sys/kernel/random/boot_id)"
