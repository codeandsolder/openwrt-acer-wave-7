#!/usr/bin/env bash
# Root-only bounded observation on the isolated Wyse, no global tracer changes.
set -Eeuo pipefail
[[ $EUID == 0 && $# == 1 && $1 =~ ^0498-[0-9]{8}-[0-9]{6}$ ]] || exit 2
[[ $(uname -r) == 7.4.0-rc1-2-cachyos-rc &&
   $(cat /sys/module/mt7925_common/srcversion) == DB4C3E1671DC2EA009803A0 &&
   $(cat /sys/class/net/wlp2s0/device/device) == 0x7925 &&
   $(cat /sys/class/net/wlp2s0/device/vendor) == 0x14c3 ]]
ip -4 route get 10.1.0.2 | grep -Fq 'dev eno1 '
root=/sys/kernel/tracing
inst="$root/instances/wave7-$1"
[[ ! -e $inst ]]
mkdir "$inst"
cleanup() {
    local rc=$?
    trap - EXIT
    printf '0\n' > "$inst/tracing_on" || rc=1
    printf 'nop\n' > "$inst/current_tracer" || rc=1
    rmdir "$inst" || rc=1
    echo "TRACE_CLEANUP rc=$rc"
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP
printf '0\n' > "$inst/tracing_on"
printf 'mono\n' > "$inst/trace_clock"
printf '8192\n' > "$inst/buffer_size_kb"
# Named functions only. The list is checked against the exact running kernel.
functions=(mt7925_mcu_rx_event mt7925_mcu_hw_scan mt7925_mcu_cancel_hw_scan
    mt7925_scan_work mt7925_roc_work mt7925_set_roc mt7925_abort_roc
    mt7925_mcu_set_roc mt7925_mcu_abort_roc mt7925_mcu_set_mlo_roc
    mt7925_mac_sta_event mt792x_mac_work mt792x_pm_wake_work
    mt792x_pm_power_save_work mt76_dma_tx_queue_skb mt76_dma_tx_cleanup
    mt76_tx_status_skb_done mt76_txq_schedule mt76_txq_schedule_all)
available=$(cat "$root/available_filter_functions")
for f in "${functions[@]}"; do
    grep -Eq "^$f( |$)" <<< "$available"
done
printf '%s\n' "${functions[@]}" > "$inst/set_ftrace_filter"
events=(mt76/mac_txdone mac80211/stop_queue mac80211/wake_queue
    mac80211/drv_hw_scan mac80211/api_scan_completed
    mac80211/drv_wake_tx_queue mac80211/drv_remain_on_channel
    mac80211/drv_cancel_remain_on_channel mac80211/api_ready_on_channel
    mac80211/api_remain_on_channel_expired mac80211/drv_change_vif_links
    mac80211/drv_change_sta_links mac80211/api_beacon_loss
    mac80211/api_connection_loss cfg80211/cfg80211_scan_done)
for e in "${events[@]}"; do
    [[ -f $inst/events/$e/enable ]]
    printf '1\n' > "$inst/events/$e/enable"
done
for e in net_dev_queue net_dev_start_xmit net_dev_xmit netif_receive_skb; do
    printf 'name == "wlp2s0"\n' > "$inst/events/net/$e/filter"
    printf '1\n' > "$inst/events/net/$e/enable"
done
printf 'function\n' > "$inst/current_tracer"
printf 'TRACE_BOOT %s\n' "$(cat /proc/sys/kernel/random/boot_id)"
printf 'TRACE_CLOCK %s\n' "$(cat "$inst/trace_clock")"
printf 'TRACE_FILTER\n'; cat "$inst/set_ftrace_filter"
printf 'TRACE_READY\n'
printf '1\n' > "$inst/tracing_on"
# Bracket the marker write with wall clock readings so the offline report
# can bound epoch conversion, rather than assuming monotonic == realtime.
end=$((SECONDS + 215))
n=0
while (( SECONDS < end )); do
    before=$(date +%s.%N)
    printf 'wave7_anchor=%d\n' "$n" > "$inst/trace_marker"
    after=$(date +%s.%N)
    printf 'ANCHOR %d %s %s\n' "$n" "$before" "$after"
    n=$((n+1))
    sleep 5
done
printf '0\n' > "$inst/tracing_on"
printf 'TRACE_STATS\n'
for stats in "$inst"/per_cpu/cpu*/stats; do
    echo "$stats"; cat "$stats"
done
printf 'TRACE_DATA\n'
cat "$inst/trace"
printf 'TRACE_END\n'
