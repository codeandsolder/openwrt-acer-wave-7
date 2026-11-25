#!/bin/bash
# Capture control-port and optional data-path metadata, never packet payloads.
set -Eeuo pipefail
[[ $EUID == 0 && $# == 4 &&
   $1 =~ ^0498-[0-9]{8}-[0-9]{6}$ &&
   $2 =~ ^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$ &&
   $4 =~ ^(90|150)$ ]]
case $3 in
    --none|--rx-data|--rx-header|--rx-wtbl|--rx-cnm|--rx-txd|--rx-cnm-group) ;;
    *) exit 2 ;;
esac
seconds=$4
group=0
profile=$3
if [[ $profile == --rx-cnm-group ]]; then
    group=1
    profile=--rx-cnm
fi
[[ $(cat /proc/sys/kernel/random/boot_id) == "$2" ]]
root=/sys/kernel/tracing
inst="$root/instances/wave7-control-$1"
events=(cfg80211/rdev_tx_control_port
        cfg80211/cfg80211_rx_control_port
        cfg80211/cfg80211_control_port_tx_status)
rx_data=0
rx_header=0
if [[ $profile == --rx-data || $profile == --rx-header || $profile == --rx-wtbl || $profile == --rx-cnm || $profile == --rx-txd ]]; then
    rx_data=1
    events+=(mt7925_lab/mt7925_lab_rxdesc
             mt7925_lab/mt7925_lab_rx_frame
             mt7925_lab/mt7925_lab_txs_peer_data)
fi
if [[ $profile == --rx-header || $profile == --rx-wtbl || $profile == --rx-cnm || $profile == --rx-txd ]]; then
    rx_header=1
    events+=(mt7925_lab/mt7925_lab_rx_header
             mt7925_lab/mt7925_lab_link_addr)
fi
if [[ $profile == --rx-wtbl || $profile == --rx-cnm || $profile == --rx-txd ]]; then
    events+=(mt7925_lab/mt7925_lab_wtbl_peer)
fi
if [[ $profile == --rx-cnm || $profile == --rx-txd ]]; then
    events+=(mt7925_lab/mt7925_lab_cnm_bss
             mt7925_lab/mt7925_lab_cnm_result)
fi
if (( group )); then
    events+=(mt7925_lab/mt7925_lab_decap_config)
fi
if [[ $profile == --rx-txd ]]; then
    events+=(mt7925_lab/mt7925_lab_tx_descriptor)
fi
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
if (( rx_data )); then
    echo 1024 > "$inst/buffer_size_kb"
    # Peer descriptors, accepted unicast data, and all peer TX statuses.
    # Capture errors and unresolved translated frames as well as valid peers.
    if (( group )); then
        # Include accepted multicast data and every RX descriptor; no
        # packet bodies. Needed to correlate RA delivery with RX metadata.
        echo 'data == 1' > "$inst/events/mt7925_lab/mt7925_lab_rx_frame/filter"
    else
        echo 'sta == 1 || result != 0 || encap == 1 || resolved_wcid == 65535' > "$inst/events/mt7925_lab/mt7925_lab_rxdesc/filter"
        echo 'data == 1 && u2m == 1' > "$inst/events/mt7925_lab/mt7925_lab_rx_frame/filter"
    fi
else
    echo 256 > "$inst/buffer_size_kb"
fi
for e in "${events[@]}"; do echo 1 > "$inst/events/$e/enable"; done
echo 1 > "$inst/tracing_on"
echo "CLIENT_CONTROL_TRACE_READY boot=$2 rx_data=$rx_data rx_header=$rx_header"
rc=0
timeout "${seconds}s" cat "$inst/trace_pipe" || rc=$?
[[ $rc == 124 ]]
echo 0 > "$inst/tracing_on"
for stats in "$inst"/per_cpu/cpu*/stats; do cat "$stats"; done
