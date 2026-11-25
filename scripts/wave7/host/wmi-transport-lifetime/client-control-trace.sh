#!/bin/bash
# Capture only control-port metadata at the client, independently of the AP.
set -Eeuo pipefail
[[ $EUID == 0 && $# == 2 &&
   $1 =~ ^0498-[0-9]{8}-[0-9]{6}$ &&
   $2 =~ ^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$ ]]
[[ $(cat /proc/sys/kernel/random/boot_id) == "$2" ]]
root=/sys/kernel/tracing
inst="$root/instances/wave7-control-$1"
events=(cfg80211/rdev_tx_control_port
        cfg80211/cfg80211_rx_control_port
        cfg80211/cfg80211_control_port_tx_status)
for e in "${events[@]}"; do [[ -r $root/events/$e/format ]]; done
[[ ! -e $inst ]]
mkdir "$inst"
cleanup(){
    local rc=$?
    trap - EXIT
    echo 0 > "$inst/tracing_on" || rc=1
    rmdir "$inst" || rc=1
    echo "CLIENT_CONTROL_TRACE_END rc=$rc"
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 143' TERM HUP
trap 'exit 130' INT
echo 0 > "$inst/tracing_on"
echo mono > "$inst/trace_clock"
echo nop > "$inst/current_tracer"
echo 256 > "$inst/buffer_size_kb"
for e in "${events[@]}"; do echo 1 > "$inst/events/$e/enable"; done
echo 1 > "$inst/tracing_on"
echo "CLIENT_CONTROL_TRACE_READY boot=$2"
rc=0
timeout 90s cat "$inst/trace_pipe" || rc=$?
[[ $rc == 124 ]]
echo 0 > "$inst/tracing_on"
for stats in "$inst"/per_cpu/cpu*/stats; do cat "$stats"; done
