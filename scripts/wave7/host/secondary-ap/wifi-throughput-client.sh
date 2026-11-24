#!/bin/bash
# Bounded temporary Wi-Fi endpoint; independent Ethernet management.
set -euo pipefail
umask 077
[[ ( $# == 2 || ( $# == 3 && $3 == standalone ) || ( $# == 4 && $3 == standalone && ( $4 == 5180 || $4 == 5500 ) ) ) && $1 =~ ^[a-zA-Z0-9-]+$ && $2 =~ ^[0-9]+$ && $2 -ge 60 && $2 -le 900 ]]
tag=$1
seconds=$2
mode=${3:-mlo}
freq=${4:-5180}
out="/home/jan/firmware/wave7/client-validation/$tag"
mkdir -m 700 "$out"
tmp="w7-$tag"
iface=wlp2s0
addr=192.168.76.248
server=''
sampler=''
cloned=0
cleanup() {
    rc=$?
    trap - EXIT
    [[ -z $sampler ]] || { kill "$sampler" 2>/dev/null || :; wait "$sampler" 2>/dev/null || :; }
    [[ -z $server ]] || { kill "$server" 2>/dev/null || :; wait "$server" 2>/dev/null || :; }
    if (( cloned )); then
        sudo -n nmcli connection delete "$tmp" > "$out/delete.txt" 2>&1 || rc=1
    fi
    ip -br addr > "$out/after-cleanup.txt"
    printf '%s\n' "$rc" > "$out/status"
    (cd "$out"; find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS; sha256sum -c --status SHA256SUMS)
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP
[[ $(nmcli -t -f GENERAL.STATE device show "$iface") == *'30 (disconnected)' ]]
profile=Wave7-MLO-Lab
bssid=4e:5a:6f:5a:bb:16
if [[ $mode == standalone ]]; then
    profile=Wave7-5G-Lab
    bssid=''
fi
sudo -n nmcli connection clone "$profile" "$tmp" > "$out/clone.txt"
cloned=1
sudo -n nmcli connection modify "$tmp" connection.autoconnect no 802-11-wireless.bssid "$bssid" \
    ipv4.method manual ipv4.addresses "$addr/24" ipv4.never-default yes ipv4.ignore-auto-dns yes \
    ipv6.method link-local ipv6.never-default yes ipv6.ignore-auto-dns yes
sudo -n nmcli --wait 50 connection up "$tmp" ifname "$iface" > "$out/association.txt"
ip -br addr show "$iface" > "$out/address.txt"
ip -4 route get 192.168.76.2 from "$addr" > "$out/route.txt"
grep -Fq "dev $iface " "$out/route.txt"
! ip -4 route show default | grep -Fq "dev $iface "
! ip -6 route show default | grep -Fq "dev $iface "
iw dev "$iface" link > "$out/link-before.txt"
for f in active_links valid_links dormant_links; do
    sudo -n cat "/sys/kernel/debug/ieee80211/phy0/netdev:$iface/$f"
done > "$out/masks-before.txt"
iw dev "$iface" station dump > "$out/station-before.txt"
if [[ $mode == standalone ]]; then
    grep -Fq 'SSID: Wave7-5G-Lab' "$out/link-before.txt"
    grep -Eq "freq: ${freq}([.]0)?$" "$out/link-before.txt"
    ! grep -q 'MLD .* stats:' "$out/link-before.txt"
else
    grep -Eq 'Link 1 BSSID 4e:5a:6f:5a:bb:16' "$out/link-before.txt"
fi
ping -I "$addr" -c 5 -W 1 192.168.76.2 > "$out/ping.txt" || :
timeout "$seconds" iperf3 -s -B "$addr" -p 52229 > "$out/server.txt" 2>&1 &
server=$!
(
    while kill -0 "$server" 2>/dev/null; do
        date -Is
        iw dev "$iface" link
        iw dev "$iface" station dump
        sleep 1
    done
) > "$out/link-samples.txt" 2>&1 &
sampler=$!
for i in {1..20}; do
    if ss -ltnH 'sport = :52229' | grep -Fq "$addr:52229"; then
        printf '%s\n' "$addr" > "$out/ready.txt"
        break
    fi
    sleep .2
done
[[ -f $out/ready.txt ]]
rc=0
wait "$server" || rc=$?
server=''
[[ $rc == 0 || $rc == 124 ]]
