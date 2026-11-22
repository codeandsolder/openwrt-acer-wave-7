#!/usr/bin/env bash
# Root-only bounded observation on the isolated Wyse, no global tracer changes.
set -Eeuo pipefail
[[ $EUID == 0 && ( $# == 1 || ( $# == 2 && ( $2 == --metadata || $2 == --absence || $2 == --binding || $2 == --quota || $2 == --rx || $2 == --rocwire || $2 == --roccontract || $2 == --rocgeometry || $2 == --upstream-prefix13 || $2 == --upstream-prefix14 || $2 == --upstream-prefix15 || $2 == --upstream-prefix17 || $2 == --upstream-prefix22-secondary-trace || $2 == --upstream-prefix22-assoc-eml-trace || $2 == --upstream-prefix22-primary-trace || $2 == --upstream-prefix22-bss-trace || $2 == --upstream-prefix22-assoc-rx-trace || $2 == --upstream-prefix22-assoc-trace || $2 == --upstream-prefix22-band-trace || $2 == --upstream-prefix22-trace || $2 == --upstream-prefix23-trace ) ) ) && $1 =~ ^0498-[0-9]{8}-[0-9]{6}$ ]] || exit 2
expected=DB4C3E1671DC2EA009803A0
if [[ ${2:-} == --metadata ]]; then
    expected=5505CE551C04266721B047A
    [[ $(sha256sum "$(modinfo -n mt7925_common)" | cut -d' ' -f1) == e423dd7b34d8e038b7b1a229ae1f9d7af08a27ce7370ea55ad09540175e274b0 ]]
elif [[ ${2:-} == --upstream-prefix13 || ${2:-} == --upstream-prefix14 || ${2:-} == --upstream-prefix15 || ${2:-} == --upstream-prefix17 || ${2:-} == --upstream-prefix22-secondary-trace || ${2:-} == --upstream-prefix22-assoc-eml-trace || ${2:-} == --upstream-prefix22-primary-trace || ${2:-} == --upstream-prefix22-bss-trace || ${2:-} == --upstream-prefix22-assoc-rx-trace || ${2:-} == --upstream-prefix22-assoc-trace || ${2:-} == --upstream-prefix22-band-trace || ${2:-} == --upstream-prefix22-trace || ${2:-} == --upstream-prefix23-trace ]]; then
    stack_check=$(bash /home/jan/scripts/wave7/client-validation/client-module-stack.sh "${2#--}" --check-candidate)
    printf '%s\n' "$stack_check"
    expected=$(awk '/^mt7925_common srcversion=/ {sub(/srcversion=/,"",$2); print $2}' <<< "$stack_check")
    [[ $expected =~ ^[0-9A-F]+$ ]]
elif [[ ${2:-} == --quota ]]; then
    expected=E882C202FF34ABD6AFFEC2C
    bash /home/jan/scripts/wave7/client-validation/client-module-stack.sh quota --check-candidate
elif [[ ${2:-} == --rocgeometry ]]; then
    expected=C9E49C46E5D078C60790F76
    [[ $(sha256sum "$(modinfo -n mt7925_common)" | cut -d' ' -f1) == 3dc72a52e857e4eb6f103affd04b6df70a443ad532d36a71628c406b10956432 ]]
elif [[ ${2:-} == --roccontract ]]; then
    expected=4612169F0B6A0C2D484A758
    [[ $(sha256sum "$(modinfo -n mt7925_common)" | cut -d' ' -f1) == 1c50861dd4a5d390d942e45f78afc30a47bd616b9929e05f550c6a76c4c5d7f8 ]]
elif [[ ${2:-} == --rocwire || ${2:-} == --roccontract ]]; then
    expected=9527AD69B79607CB0ABD540
    [[ $(sha256sum "$(modinfo -n mt7925_common)" | cut -d' ' -f1) == 50f1fd1cee84ceba1ba62abad2f04ed6d18803bc09fd395c266271297344d2f4 ]]
elif [[ ${2:-} == --rx || ${2:-} == --rocwire || ${2:-} == --roccontract ]]; then
    expected=C8590CC01B6D6AE3EAAC131
    [[ $(sha256sum "$(modinfo -n mt7925_common)" | cut -d' ' -f1) == fa786e5d0d56500d2042eb166a73130db97f1b542f5d0fbd174ff973ee382345 ]]
elif [[ ${2:-} == --binding ]]; then
    expected=CF0F5C99109529BD670B11A
    [[ $(sha256sum "$(modinfo -n mt7925_common)" | cut -d' ' -f1) == 0f2468ffc7aeb8ef76eaf63c20c5a405b80d0e61320bf1af28d931014b79f12b ]]
elif [[ ${2:-} == --absence ]]; then
    expected=5F394A90BE5C4D0D8C37C46
    [[ $(sha256sum "$(modinfo -n mt7925_common)" | cut -d' ' -f1) == 102037a9fdc2571c48426d70087eaa560a7bacb70ee6967a2aa0aa5f274e7f4f ]]
fi
[[ $(uname -r) == 7.4.0-rc1-2-cachyos-rc &&
   $(cat /sys/module/mt7925_common/srcversion) == "$expected" &&
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
if [[ ${2:-} == --upstream-prefix22-assoc-rx-trace || ${2:-} == --rx || ${2:-} == --rocwire || ${2:-} == --roccontract || ${2:-} == --rocgeometry ]]; then
    printf '16384\n' > "$inst/buffer_size_kb"
else
    printf '8192\n' > "$inst/buffer_size_kb"
fi
# Named functions only. The list is checked against the exact running kernel.
functions=(mt7925_mcu_rx_event mt7925_mcu_hw_scan mt7925_mcu_cancel_hw_scan
    mt7925_scan_work mt7925_roc_work mt7925_set_roc mt7925_abort_roc
    mt7925_mcu_set_roc mt7925_mcu_abort_roc mt7925_mcu_set_mlo_roc
    mt7925_mac_sta_event mt792x_mac_work mt792x_pm_wake_work
    mt792x_pm_power_save_work mt76_dma_tx_queue_skb mt76_dma_tx_cleanup
    mt76_tx_status_skb_done mt76_txq_schedule mt76_txq_schedule_all
    mt7925_mac_tx_free mt7925_mac_add_txs mt7925_txwi_free
    mt76_token_consume mt76_token_release __mt76_tx_complete_skb
    __mt76_set_tx_blocked mt792x_mcu_drv_pmctrl mt792x_mcu_fw_pmctrl
    mt76_connac_pm_queue_skb mt76_connac_pm_dequeue_skbs
    mt7925_mlo_pm_work mt7925_mcu_uni_bss_ps mt7925_mcu_set_dbdc)
if [[ ${2:-} == --upstream-prefix22-secondary-trace || ${2:-} == --upstream-prefix22-assoc-eml-trace || ${2:-} == --upstream-prefix22-primary-trace || ${2:-} == --upstream-prefix22-bss-trace || ${2:-} == --upstream-prefix22-assoc-rx-trace || ${2:-} == --upstream-prefix22-assoc-trace || ${2:-} == --upstream-prefix22-band-trace || ${2:-} == --upstream-prefix22-trace || ${2:-} == --upstream-prefix23-trace ]]; then
    # Low-volume control-plane trace: avoid relying on inlined static helpers.
    functions=(mt7925_mcu_rx_event mt7925_mcu_hw_scan mt7925_mcu_cancel_hw_scan
        mt7925_scan_work mt7925_roc_work mt7925_mcu_set_roc
        mt7925_mcu_abort_roc mt7925_mcu_set_mlo_roc mt7925_mac_sta_event)
fi
if [[ ${2:-} == --upstream-prefix13 || ${2:-} == --upstream-prefix14 || ${2:-} == --upstream-prefix15 || ${2:-} == --upstream-prefix17 ]]; then
    functions=(mt7925_mcu_hw_scan mt7925_scan_work mt7925_roc_work
        mt7925_mcu_set_roc mt7925_mcu_abort_roc mt7925_mcu_set_mlo_roc)
fi
# Preserve exact symbol checks while scanning the large list only once.
awk -v names="${functions[*]}" '
    BEGIN {
        n = split(names, wanted, " ")
        for (i = 1; i <= n; i++) missing[wanted[i]] = 1
    }
    { delete missing[$1] }
    END {
        for (name in missing) {
            print "TRACE_FUNCTION_MISSING " name > "/dev/stderr"
            failed = 1
        }
        exit failed
    }
' "$root/available_filter_functions"
printf '%s\n' "${functions[@]}" > "$inst/set_ftrace_filter"
events=(mac80211/stop_queue mac80211/wake_queue
    mac80211/drv_hw_scan mac80211/api_scan_completed
    mac80211/drv_wake_tx_queue mac80211/drv_remain_on_channel
    mac80211/drv_cancel_remain_on_channel mac80211/api_ready_on_channel
    mac80211/api_remain_on_channel_expired mac80211/drv_change_vif_links
    mac80211/drv_change_sta_links mac80211/api_beacon_loss
    mac80211/api_connection_loss cfg80211/cfg80211_scan_done)
if [[ ${2:-} == --metadata || ${2:-} == --absence || ${2:-} == --binding || ${2:-} == --quota || ${2:-} == --rx || ${2:-} == --rocwire || ${2:-} == --roccontract || ${2:-} == --rocgeometry ]]; then
    for e in mcu_rx roc mbmc scan_req scan_tlv txfree txs; do
        events+=("mt7925_lab/mt7925_lab_$e")
    done
fi
if [[ ${2:-} == --absence || ${2:-} == --binding || ${2:-} == --quota || ${2:-} == --rx || ${2:-} == --rocwire || ${2:-} == --roccontract || ${2:-} == --rocgeometry ]]; then
    events+=(mt7925_lab/mt7925_lab_absence)
fi
if [[ ${2:-} == --binding || ${2:-} == --quota || ${2:-} == --rx || ${2:-} == --rocwire || ${2:-} == --roccontract || ${2:-} == --rocgeometry ]]; then
    events+=(mt7925_lab/mt7925_lab_binding mt7925_lab/mt7925_lab_txdesc)
fi
if [[ ${2:-} == --quota ]]; then
    events+=(mt7925_lab/mt7925_lab_credit mt7925_lab/mt7925_lab_credit_refund)
fi
if [[ ${2:-} == --rx || ${2:-} == --rocwire || ${2:-} == --roccontract || ${2:-} == --rocgeometry ]]; then
    for e in rxdesc bss_basic bss_mld bss_rlm sta_mld sta_eht_mld sta_result bss_result mlo_roc_req mlo_roc_result; do
        events+=("mt7925_lab/mt7925_lab_$e")
    done
fi
if [[ ${2:-} == --rocwire || ${2:-} == --roccontract || ${2:-} == --rocgeometry ]]; then
    for e in roc_wire roc_abort txs_wire rx_frame; do
        events+=("mt7925_lab/mt7925_lab_$e")
    done
fi
if [[ ${2:-} == --roccontract ]]; then
    events+=(mt7925_lab/mt7925_lab_roc_geometry mt7925_lab/mt7925_lab_roc_band)
fi
if [[ ${2:-} == --rocgeometry ]]; then
    events+=(mt7925_lab/mt7925_lab_roc_geometry mt7925_lab/mt7925_lab_key_result mt7925_lab/mt7925_lab_decap_config)
fi
if [[ ${2:-} == --upstream-prefix22-secondary-trace || ${2:-} == --upstream-prefix22-assoc-eml-trace || ${2:-} == --upstream-prefix22-primary-trace || ${2:-} == --upstream-prefix22-bss-trace || ${2:-} == --upstream-prefix22-assoc-rx-trace || ${2:-} == --upstream-prefix22-assoc-trace || ${2:-} == --upstream-prefix22-band-trace || ${2:-} == --upstream-prefix22-trace || ${2:-} == --upstream-prefix23-trace ]]; then
    for e in mcu_rx roc_wire mlo_roc_req mlo_roc_result roc_geometry roc_abort \
        scan_req scan_tlv absence bss_basic bss_mld sta_result bss_result \
        key_result decap_config sta_eht_mld roc_band roc_sync beacon_loss sta_mld_slot; do
        events+=("mt7925_lab/mt7925_lab_$e")
    done
fi
if [[ ${2:-} == --upstream-prefix13 || ${2:-} == --upstream-prefix14 || ${2:-} == --upstream-prefix15 || ${2:-} == --upstream-prefix17 ]]; then
    # Admission trace only. Return tracepoints disambiguate rejection
    # before the driver callback versus a firmware/driver busy result.
    events=(cfg80211/rdev_scan cfg80211/rdev_return_int cfg80211/cfg80211_scan_done
        mac80211/drv_hw_scan mac80211/drv_return_int mac80211/api_scan_completed
        mac80211/drv_remain_on_channel mac80211/drv_cancel_remain_on_channel
        mac80211/api_ready_on_channel mac80211/api_remain_on_channel_expired
        mac80211/drv_change_vif_links mac80211/drv_change_sta_links
        mac80211/api_beacon_loss mac80211/api_connection_loss)
fi
if [[ ${2:-} == --upstream-prefix22-assoc-rx-trace ]]; then
    events+=(mt7925_lab/mt7925_lab_rxdesc mt7925_lab/mt7925_lab_rx_frame)
fi
for e in "${events[@]}"; do
    [[ -f $inst/events/$e/enable ]]
    printf '1\n' > "$inst/events/$e/enable"
done
if [[ ${2:-} != --upstream-prefix13 && ${2:-} != --upstream-prefix14 && ${2:-} != --upstream-prefix15 && ${2:-} != --upstream-prefix17 ]]; then
    for e in net_dev_queue net_dev_start_xmit net_dev_xmit netif_receive_skb; do
        printf 'name == "wlp2s0"\n' > "$inst/events/net/$e/filter"
        printf '1\n' > "$inst/events/net/$e/enable"
    done
fi
printf 'function\n' > "$inst/current_tracer"
printf 'TRACE_BOOT %s\n' "$(cat /proc/sys/kernel/random/boot_id)"
printf 'TRACE_CLOCK %s\n' "$(cat "$inst/trace_clock")"
printf 'TRACE_FILTER\n'; cat "$inst/set_ftrace_filter"
printf 'TRACE_EVENTS\n%s\n' "${events[@]}"
printf '1\n' > "$inst/tracing_on"
printf 'TRACE_READY\n'
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
