#!/usr/bin/env bash
# Wyse MT7925 independent MLO client validation. Keep its wired SSH path
# and default routes untouched. The temporary cloned profile is removed.
set -euo pipefail
mode=${1:-dhcp}
iface=wlp2s0
profile=Wave7-MLO-Lab
tmp="Wave7-lab-test-$$"
[[ $mode == dhcp || $mode == static ]] || { echo 'usage: client-lab.sh dhcp|static' >&2; exit 2; }
sudo -n nmcli connection clone "$profile" "$tmp"
cleanup() { sudo -n nmcli connection delete "$tmp" >/dev/null 2>&1 || :; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
sudo -n nmcli connection modify "$tmp" connection.autoconnect no ipv4.never-default yes ipv4.ignore-auto-dns yes ipv6.never-default yes ipv6.ignore-auto-dns yes ipv4.may-fail no ipv6.may-fail no
if [[ $mode == dhcp ]]; then
  sudo -n nmcli connection modify "$tmp" ipv4.method auto ipv6.method auto
else
  sudo -n nmcli connection modify "$tmp" ipv4.method manual ipv4.addresses 192.168.76.145/24 ipv6.method link-local
fi
sudo -n nmcli --wait 40 connection up "$tmp" ifname "$iface"
v4=$(ip -4 -o addr show dev "$iface" | awk '$3=="inet" && $4 ~ /^192[.]168[.]76[.]/ {sub(/\/.*/, "", $4); print $4; exit}')
[[ -n $v4 ]] || { echo 'WLAN_IPV4_MISSING' >&2; exit 1; }
ip -4 route get 192.168.76.2 from "$v4" | grep -Fq "dev $iface "
if [[ $mode == dhcp ]]; then
  v6=$(ip -6 -o addr show dev "$iface" | awk '$3=="inet6" && $4 ~ /^fd76:7:/ && $0 !~ /tentative|dadfailed/ {sub(/\/.*/, "", $4); print $4; exit}')
  [[ -n $v6 ]] || { echo 'WLAN_IPV6_MISSING' >&2; exit 1; }
  ip -6 route get fd76:7::2 from "$v6" | grep -Fq "dev $iface "
fi
# Verify no accidental default route was installed by either family.
if ip -4 route show default | grep -Fq "dev $iface " ||
   ip -6 route show default | grep -Fq "dev $iface "; then
  echo 'WLAN_DEFAULT_ROUTE' >&2
  exit 1
fi
date -Is
ip -br addr show dev "$iface"
ip -4 route show dev "$iface"
ip -6 route show dev "$iface"
link=$(sudo -n iw dev "$iface" link)
printf '%s\n' "$link"
for i in 0 1; do
  grep -Eq "Link $i BSSID " <<< "$link" || { echo "MLO_LINK_MISSING $i" >&2; exit 1; }
done
# Source binding matters on this dual-homed host; interface binding alone
# could select another interface's source before DHCP has completed.
ping -I "$v4" -c 20 -i 0.25 -W 1 -w 15 192.168.76.2
if [[ $mode == dhcp ]]; then
  ping -6 -I "$v6" -c 20 -i 0.25 -W 1 -w 15 fd76:7::2
fi
echo "WAVE7_CLIENT_PASS mode=$mode"
