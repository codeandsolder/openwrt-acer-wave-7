#!/bin/sh
# Bounded, private ftrace instance. Control-port tracepoints expose only
# metadata (protocol, length, link, acknowledgement), not payloads or keys.
set -eu
[ "$#" -eq 4 ]
boot=$1
tag=$2
seconds=$3
case "$seconds" in 90|150|300) ;; *) exit 2 ;; esac
case "$4" in full|control) ;; *) exit 2 ;; esac
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
mac80211/drv_change_sta_links'
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
echo 1024 > "$inst/buffer_size_kb"
if [ "$4" = full ]; then
    echo "$functions" > "$inst/set_ftrace_filter"
    echo function > "$inst/current_tracer"
fi
for ev in $events; do
    echo 1 > "$inst/events/$ev/enable"
done
echo 1 > "$inst/tracing_on"
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
