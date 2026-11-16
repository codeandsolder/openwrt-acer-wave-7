#!/usr/bin/env bash
# Execute on Wyse over *wired* SSH, never over Wi-Fi.
set -Eeuo pipefail
count=$1
[[ $count =~ ^[1-9][0-9]*$ ]] && (( count <= 1000 )) || {
  echo 'usage: wyse-reassociate.sh COUNT (1..1000)' >&2; exit 2;
}
ssid=Wave7-MLO-Lab
iface=wlp2s0
router=192.168.76.1
eth=eno1
completed=0
phase=preflight
verify_wired_management() {
  local route
  route=$(ip -4 route get 10.1.0.2)
  [[ $route == *" dev $eth "* ]] || {
    printf 'ETHERNET_ROUTE_LOST route=%s\n' "$route" >&2; return 1;
  }
  [[ $(nmcli -g GENERAL.STATE dev show "$eth") == '100 (connected)' ]]
}
restore_on_error() {
  local rc=$?
  trap - ERR
  printf 'CYCLE_FAILURE\t%s\t%s\t%s\t%s\n' \
    "$(date -u +%FT%TZ)" "$((completed+1))" "$phase" "$rc"
  if verify_wired_management; then
    sudo -n nmcli --wait 30 connection up "$ssid" ifname "$iface" >&2 || :
  fi
  exit "$rc"
}
trap restore_on_error ERR
verify_wired_management
sudo -n true
nmcli -g GENERAL.CONNECTION dev show "$iface" | grep -Fx "$ssid" >/dev/null
iw dev "$iface" link | grep -Fq "Link 0 BSSID"
iw dev "$iface" link | grep -Fq "Link 1 BSSID"
printf 'CYCLE_START\t%s\t%s\t%s\t%s\n' "$(date -u +%FT%TZ)" "$count" "$eth" "$iface"
for ((i=1; i<=count; i++)); do
  phase=down
  begin=$(date +%s%3N)
  sudo -n nmcli --wait 15 connection down "$ssid" >/dev/null
  iw dev "$iface" link | grep -Fq "Not connected."
  # Leave the profile down long enough to verify a full disassociation.
  sleep 1
  verify_wired_management
  phase=up
  sudo -n nmcli --wait 35 connection up "$ssid" ifname "$iface" >/dev/null
  phase=verify
  for ((poll=0;poll<10;poll++)); do
    link=$(iw dev "$iface" link)
    if [[ $link == *"SSID: $ssid"* &&
          $link == *"Link 0 BSSID"* && $link == *"Link 1 BSSID"* ]]; then
      break
    fi
    sleep 1
  done
  [[ $link == *"SSID: $ssid"* &&
     $link == *"Link 0 BSSID"* && $link == *"Link 1 BSSID"* ]]
  route=$(ip -4 route get "$router" | head -1)
  [[ $route == *" dev $iface "* ]] || {
    echo "WLAN_ROUTE_MISMATCH $route" >&2; exit 5;
  }
  verify_wired_management
  ping -I "$iface" -c 2 -W 2 "$router" >/dev/null
  elapsed=$(( $(date +%s%3N)-begin ))
  completed=$i
  printf 'CYCLE_OK\t%s\t%d\t%d\t%s\t%s\n' \
    "$(date -u +%FT%TZ)" "$i" "$elapsed" \
    "$(printf '%s\n' "$link" | sed -n 's/^[[:space:]]*freq: //p' | paste -sd, -)" \
    "$route"
done
printf 'CYCLE_COMPLETE\t%s\t%d\t0\n' "$(date -u +%FT%TZ)" "$completed"
