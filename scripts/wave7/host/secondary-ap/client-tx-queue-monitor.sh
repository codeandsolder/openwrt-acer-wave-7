#!/usr/bin/env bash
# Read-only bounded observation of mt76 WFDMA0 queue against ICMP timestamps.
set -Eeuo pipefail
[[ $EUID == 0 && $# == 2 && $1 =~ ^phy[0-9]+$ &&
   $2 =~ ^[0-9]{2,3}$ && $2 -ge 10 && $2 -le 120 ]] || exit 2
phy=$1
seconds=$2
[[ $(basename "$(readlink -f /sys/class/net/wlp2s0/phy80211)") == "$phy" &&
   $(cat /sys/class/net/wlp2s0/device/device) == 0x7925 ]]
path="/sys/kernel/debug/ieee80211/$phy/mt76/xmit-queues"
[[ -r $path ]]
i=0
printf 'TX_QUEUE_READY epoch=%s path=%s seconds=%s\n' \
    "$(date +%s.%N)" "$path" "$seconds"
# Debugfs read does not change queue pointers or device PM state.
# The sample rate is capped at 20 Hz, and includes all available queues.
while (( i < seconds * 20 )); do
    time=$(date +%s.%N)
    printf 'TX_QUEUE_SAMPLE epoch=%s index=%d\n' "$time" "$i"
    cat "$path"
    ((i+=1))
    sleep .05
done
printf 'TX_QUEUE_DONE epoch=%s samples=%d\n' "$(date +%s.%N)" "$i"
