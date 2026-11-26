#!/usr/bin/env bash
# Wyse MT7925 independent MLO client validation. Keep its wired SSH path
# and default routes untouched. The temporary cloned profile is removed.
set -euo pipefail
mode=${1:-dhcp}
test_variant=${2:-}
iface=wlp2s0
profile=Wave7-MLO-Lab
tmp="Wave7-lab-test-$$"
if [[ $mode != dhcp && $mode != static ]] ||
   [[ -n $test_variant && $test_variant != --settled && ( $mode != dhcp || $test_variant != --diagnose-ndp ) ]] ||
   (( $# > 2 )); then
  echo 'usage: client-lab.sh dhcp|static [--settled|--diagnose-ndp]' >&2
  exit 2
fi
sudo -n nmcli connection clone "$profile" "$tmp"
neighbor_added=0
cleanup() {
  if (( neighbor_added )); then
    sudo -n ip -6 neigh del fd76:7::2 dev "$iface" >/dev/null 2>&1 || :
  fi
  sudo -n nmcli connection delete "$tmp" >/dev/null 2>&1 || :
}
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
if [[ $test_variant == --settled ]]; then
  # Separate startup/roaming-scan behavior from steady-state forwarding.
  # The regular immediate run remains a distinct required test.
  echo CLIENT_SETTLE_SECONDS=15
  sleep 15
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
# With both -c and -w, iputils may send extra probes until it receives -c
# replies. Use a fixed send count, then check the actual summary instead.
check_ping() {
  local result rc=0
  result=$(LC_ALL=C ping -D -c 20 -i 0.25 -W 1 "$@") || rc=$?
  printf '%s\n' "$result"
  [[ $rc == 0 ]] && grep -Eq '^20 packets transmitted, 20 received, (\+0 duplicates, )?0% packet loss,' <<< "$result"
}
failed=0
check_ping -I "$v4" 192.168.76.2 || failed=1
if [[ $mode == dhcp ]]; then
  if ! check_ping -6 -I "$v6" fd76:7::2; then
    failed=1
    ip -6 neigh show dev "$iface"
    if [[ $test_variant == --diagnose-ndp ]]; then
      # Use only the known isolated upstream's NIC address. Do not
      # replace an existing permanent neighbor or alter another interface.
      # A passing later run is not proof of NDP causality when the first
      # run already has a REACHABLE neighbor; packet captures decide.
      if ip -6 neigh show to fd76:7::2 dev "$iface" | grep -Eq 'PERMANENT|NOARP'; then
        echo NDP_DIAGNOSTIC_REFUSED >&2
        exit 1
      fi
      sudo -n iw dev "$iface" station dump
      sudo -n ip -6 neigh replace fd76:7::2 lladdr 00:e0:4c:68:00:6d nud permanent dev "$iface"
      neighbor_added=1
      if check_ping -6 -I "$v6" fd76:7::2; then
        echo NDP_BYPASS_PASS
      else
        echo NDP_BYPASS_LOSS
      fi
      sudo -n iw dev "$iface" station dump
    fi
  fi
fi
if (( failed )); then
  echo "WAVE7_CLIENT_LOSS mode=$mode" >&2
  exit 1
fi
echo "WAVE7_CLIENT_PASS mode=$mode"
