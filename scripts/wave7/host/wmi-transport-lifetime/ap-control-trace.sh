#!/bin/sh
# Bounded, private ftrace instance. Control-port tracepoints expose only
# metadata (protocol, length, link, acknowledgement), not payloads or keys.
set -eu
[ "$#" -eq 4 ]
boot=$1
tag=$2
seconds=$3
case "$seconds" in 90|150|300) ;; *) exit 2 ;; esac
case "$4" in full|control|reconnect) ;; *) exit 2 ;; esac
case "$tag" in *[!a-zA-Z0-9_-]*|'') exit 2 ;; esac
[ "$(cat /proc/sys/kernel/random/boot_id)" = "$boot" ]
root=/sys/kernel/tracing
inst="$root/instances/wave7_primary_$tag"
[ ! -e "$inst" ]
functions='ath12k_dp_peer_setup
ath12k_wmi_send_peer_assoc_cmd
ath12k_mac_get_tx_link
ath12k_dp_rx_deliver_msdu
ath12k_wifi7_dp_rx_set_link_id_qcn9274
ieee80211_rx_napi'
events='cfg80211/rdev_tx_control_port
cfg80211/cfg80211_rx_control_port
cfg80211/cfg80211_control_port_tx_status
cfg80211/cfg80211_rx_mgmt
cfg80211/cfg80211_mgmt_tx_status
mac80211/drv_sta_state
mac80211/drv_ampdu_action
mac80211/drv_change_sta_links'
net_events='net/net_dev_start_xmit
net/netif_receive_skb_entry
net/netif_receive_skb_list_entry
net/napi_gro_receive_entry
net/netif_rx_entry'
driver_mgmt_events='ath12k_mgmt/ath12k_mgmt_lifetime
mac80211/ack_status_lifetime'
mgmt_trace=0
if [ "$4" = reconnect ]; then
    n=0
    for ev in $driver_mgmt_events; do
        if [ -r "$root/events/$ev/format" ]; then n=$((n + 1)); fi
    done
    case "$n" in
        0) ;;
        2) events="$events
$driver_mgmt_events"; mgmt_trace=1 ;;
        *) echo 'incomplete management lifetime tracepoint closure' >&2; exit 1 ;;
    esac
    events="$events
cfg80211/rdev_mgmt_tx
cfg80211/rdev_return_int_cookie
cfg80211/rdev_add_station
cfg80211/rdev_change_station
cfg80211/rdev_del_station
$net_events"
fi
if [ "$4" = full ]; then
for fn in $functions; do
    grep -Eq "^$fn([[:space:]]|$)" "$root/available_filter_functions"
done
fi
for ev in $events; do [ -r "$root/events/$ev/format" ]; done
mkdir "$inst"
cleanup(){
    rc=$?
    trap - EXIT HUP INT TERM
    echo 0 > "$inst/tracing_on" || rc=1
    echo nop > "$inst/current_tracer" || rc=1
    rmdir "$inst" || rc=1
    printf 'AP_CONTROL_TRACE_END rc=%s\n' "$rc"
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 143' HUP INT TERM
echo 0 > "$inst/tracing_on"
echo mono > "$inst/trace_clock"
if [ "$4" = reconnect ]; then
    echo 4096 > "$inst/buffer_size_kb"
    for ev in $net_events; do
        echo '(name == "ap-mld0" || name == "br-lan") && (protocol == 0x0800 || protocol == 0x0806 || protocol == 0x86dd)' > "$inst/events/$ev/filter"
    done
else
    echo 1024 > "$inst/buffer_size_kb"
fi
if [ "$4" = full ]; then
    echo "$functions" > "$inst/set_ftrace_filter"
    echo function > "$inst/current_tracer"
fi
for ev in $events; do
    echo 1 > "$inst/events/$ev/enable"
done
echo 1 > "$inst/tracing_on"
printf 'AP_MGMT_LIFETIME=%s\n' "$mgmt_trace"
printf 'AP_CONTROL_TRACE_READY boot=%s\n' "$boot"
# No fractional sleep on this BusyBox. Keep the interval bounded even if
# the observer connection is lost, and always remove this instance.
sleep "$seconds"
echo 0 > "$inst/tracing_on"
cat "$inst/trace"
for stats in "$inst"/per_cpu/cpu*/stats; do
    printf '%s\n' "$stats"
    cat "$stats"
done
