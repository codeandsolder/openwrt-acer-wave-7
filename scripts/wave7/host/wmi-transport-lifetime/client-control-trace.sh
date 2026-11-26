#!/bin/bash
# Capture control-port and optional data-path metadata, never packet payloads.
set -Eeuo pipefail
[[ $EUID == 0 && $# == 4 &&
   $1 =~ ^0498-[0-9]{8}-[0-9]{6}$ &&
   $2 =~ ^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$ &&
   $4 =~ ^(90|150|300)$ ]]
case $3 in
    --none|--rx-data|--rx-header|--rx-wtbl|--rx-cnm|--rx-txd|--rx-cnm-group|--mgmt-tx|--reconnect-datapath|--reconnect-data-tokens|--reconnect-mld-record) ;;
    *) exit 2 ;;
esac
seconds=$4
group=0
reconnect=0
profile=$3
tokens=0
mld_record=0
if [[ $profile == --reconnect-mld-record ]]; then
    mld_record=1
    profile=--reconnect-data-tokens
fi
if [[ $profile == --reconnect-data-tokens ]]; then
    tokens=1
    profile=--reconnect-datapath
fi
if [[ $profile == --reconnect-datapath ]]; then
    reconnect=1
    group=1
    profile=--rx-cnm
fi
if [[ $profile == --rx-cnm-group ]]; then
    group=1
    profile=--rx-cnm
fi
[[ $(cat /proc/sys/kernel/random/boot_id) == "$2" ]]
root=/sys/kernel/tracing
inst="$root/instances/wave7-control-$1"
events=(cfg80211/rdev_tx_control_port
        cfg80211/cfg80211_rx_control_port
        cfg80211/cfg80211_control_port_tx_status
        cfg80211/cfg80211_mgmt_tx_status
        mac80211/drv_mgd_prepare_tx
        mac80211/drv_mgd_complete_tx
        mac80211/drv_flush
        mac80211/drv_flush_sta
        mac80211/drv_sta_state
        mac80211/drv_ampdu_action)
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
if [[ $profile == --mgmt-tx ]] || (( reconnect )); then
    events+=(mt7925_lab/mt7925_lab_mgmt_txd
             mt7925_lab/mt7925_lab_mgmt_tx_free
             mt7925_lab/mt7925_lab_mgmt_txs
             mt7925_lab/mt7925_lab_absence)
fi
net_events=(net/net_dev_start_xmit net/netif_receive_skb_entry
            net/netif_receive_skb_list_entry net/napi_gro_receive_entry
            net/netif_rx_entry)
if (( reconnect )); then
    events+=("${net_events[@]}")
fi
if (( tokens )); then
    events+=(mt7925_lab/mt7925_lab_data_txd mt7925_lab/mt7925_lab_data_tx_free)
fi
if (( mld_record )); then
    events+=(mt7925_lab/mt7925_lab_mld_record_result
             mt7925_lab/mt7925_lab_mld_record
             mt7925_lab/mt7925_lab_mld_record_link)
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
if (( reconnect )); then
    # Ethernet protocol and skb length only; restrict to the isolated
    # Wi-Fi interface and the address-configuration/data protocols.
    for e in "${net_events[@]}"; do
        echo 'name == "wlp2s0" && (protocol == 0x0800 || protocol == 0x0806 || protocol == 0x86dd)' > "$inst/events/$e/filter"
    done
fi
for e in "${events[@]}"; do echo 1 > "$inst/events/$e/enable"; done
echo 1 > "$inst/tracing_on"
echo "CLIENT_CONTROL_TRACE_READY boot=$2 rx_data=$rx_data rx_header=$rx_header"
rc=0
timeout "${seconds}s" cat "$inst/trace_pipe" || rc=$?
[[ $rc == 124 ]]
echo 0 > "$inst/tracing_on"
for stats in "$inst"/per_cpu/cpu*/stats; do cat "$stats"; done
