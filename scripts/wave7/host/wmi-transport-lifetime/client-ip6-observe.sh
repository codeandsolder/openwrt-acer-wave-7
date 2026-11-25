#!/usr/bin/env bash
# Per-interface IPv6 stack evidence, independent of NetworkManager activation.
# No packet capture, addresses changed, or active network probes.
set -Eeuo pipefail
[[ $# == 3 && $1 =~ ^0498-[0-9]{8}-[0-9]{6}$ &&
   $2 =~ ^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$ &&
   $3 =~ ^([1-9][0-9]?|1[01][0-9]|120)$ ]]
iface=wlp2s0
stats=/proc/net/dev_snmp6/$iface
boot=/proc/sys/kernel/random/boot_id
expected_boot=$2
[[ $(cat "$boot") == "$expected_boot" && -r $stats ]]
# Verify the interface index on every sample: don't concatenate counters
# from an interface that was recreated after a driver reset.
read -r ifindex < "/sys/class/net/$iface/ifindex"
[[ $ifindex =~ ^[0-9]+$ ]]
snapshot(){
    local sample=$1
    [[ $(cat "$boot") == "$expected_boot" && $(cat "/sys/class/net/$iface/ifindex") == "$ifindex" ]]
    printf 'IP6_SAMPLE index=%s epoch=%s monotonic=%s\n' "$sample" "$(date +%s.%N)" "$(cut -d' ' -f1 /proc/uptime)"
    awk '$1 ~ /^(ifIndex|Ip6|Icmp6)/ {print "IP6_COUNTER", $1, $2}' "$stats"
    ip -6 -o addr show dev "$iface" | sed 's/^/IP6_ADDR /'
    ip -6 -o route show dev "$iface" | sed 's/^/IP6_ROUTE /'
    ip -6 -o neigh show dev "$iface" | sed 's/^/IP6_NEIGH /'
    printf 'IP6_SAMPLE_END index=%s\n' "$sample"
}
snapshot 0
echo "CLIENT_IP6_OBSERVER_READY tag=$1 boot=$2 ifindex=$ifindex"
for ((i=1; i<=$3; i++)); do
    sleep 1
    snapshot "$i"
done
echo "CLIENT_IP6_OBSERVER_END samples=$(( $3 + 1 ))"
