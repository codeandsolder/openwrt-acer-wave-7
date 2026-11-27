#!/usr/bin/env bash
# Root-only isolated test service. Run via root SSH; stop explicitly.
# No changes to persistent NetworkManager profiles or unrelated interfaces.
set -euo pipefail
iface=enp4s0f4u2u4
expected_mac=00:e0:4c:68:00:6d
prefix=fd76:7::2/64
network=fd76:7::/64
lab_ifaces=(enp4s0f4u2u4 enp4s0f4u2u2u4)
base=/home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8/upstream
unit=wave7-lab-upstream-guard8
config=$(dirname "$(realpath "$0")")/lab-upstream.conf
rule=(-i "$iface" -p udp --sport 68 --dport 67 -m comment --comment "$unit" -j ACCEPT)
scope_ok() {
  [[ $(cat "/sys/class/net/$iface/address") == "$expected_mac" ]] || return 1
  [[ ! -e /sys/class/net/$iface/master ]] || return 1
  if ip -4 route show default | grep -Eq "dev $iface([[:space:]]|$)" ||
     ip -6 route show default | grep -Eq "dev $iface([[:space:]]|$)"; then
    echo 'test interface is a default route' >&2; return 1
  fi
}
preflight() {
  scope_ok || return 1
  ip -4 -o addr show dev "$iface" | grep -Fq 'inet 192.168.76.2/24 ' || return 1
  dnsmasq --test --conf-file="$config"
}
need_root() { [[ $(id -u) == 0 ]] || { echo 'run as root' >&2; exit 1; }; }
prepare_upstream_unit() {
  local service="$unit.service" state
  state=$(systemctl show "$service" -p LoadState --value)
  if [[ $state == not-found ]]; then
    return 0
  fi
  if [[ $state != loaded ||
        $(systemctl show "$service" -p ActiveState --value) != failed ||
        $(systemctl show "$service" -p Transient --value) != yes ||
        $(systemctl show "$service" -p Result --value) != timeout ||
        $(systemctl show "$service" -p MainPID --value) != 0 ||
        $(systemctl show "$service" -p FragmentPath --value) != "/run/systemd/transient/$service" ]]; then
    echo "refusing existing unit $service (not a retired lab timeout)" >&2
    return 1
  fi
  systemctl reset-failed "$service"
  # Unit GC is asynchronous; do not blindly launch on a stale name.
  for _ in {1..20}; do
    [[ $(systemctl show "$service" -p LoadState --value) != not-found ]] || return 0
    sleep 0.1
  done
  echo "expired lab unit was not collected: $service" >&2
  return 1
}
case "${1:---check}" in
  --check) preflight; echo LAB_UPSTREAM_PREFLIGHT_PASS ;;
  --start)
    need_root
    preflight
    # Retire only the exact timeout from older deployments. Keep
    # the service active until explicit stop or scope/child failure.
    prepare_upstream_unit
    systemd-run --quiet --collect --unit="$unit" --property=RuntimeMaxSec=infinity \
      --property=KillMode=mixed "$(realpath "$0")" --serve
    ;;
  --serve)
    need_root
    preflight
    # Require newly owned address and firewall rule. Only remove our own
    # changes on explicit stop or failure. The interface guard remains active.
    for lab in "${lab_ifaces[@]}"; do
      if [[ -n $(ip -6 -o addr show dev "$lab" to "$network") ||
            -n $(ip -6 route show dev "$lab" to "$network") ]]; then
        echo "test IPv6 prefix already exists on $lab" >&2; exit 1
      fi
    done
    if iptables -C ufw-user-input "${rule[@]}" 2>/dev/null; then
      echo 'test firewall rule already exists' >&2; exit 1
    fi
    address_added=0
    rule_added=0
    child=
    cleanup() {
      if [[ -n $child ]]; then kill "$child" 2>/dev/null || :; wait "$child" 2>/dev/null || :; fi
      if (( rule_added )); then iptables -D ufw-user-input "${rule[@]}" || :; fi
      if (( address_added )); then
        # Our RA may have traversed the bridge and configured an additional
        # SLAAC address on either lab NIC. The start gate proved no existing
        # addresses/routes for this dedicated prefix; remove only that scope.
        for lab in "${lab_ifaces[@]}"; do
          ip -6 addr flush dev "$lab" to "$network" || :
          ip -6 route flush dev "$lab" to "$network" || :
        done
      fi
    }
    trap cleanup EXIT
    trap 'exit 0' TERM INT
    install -d -m 0700 -o jan -g "$(id -gn jan)" "$base"
    ip -6 addr add "$prefix" dev "$iface"
    address_added=1
    iptables -I ufw-user-input 1 "${rule[@]}"
    rule_added=1
    /usr/bin/dnsmasq --keep-in-foreground --conf-file="$config" \
      --user=jan --group="$(id -gn jan)" \
      --dhcp-leasefile="$base/dnsmasq.leases" --pid-file= &
    child=$!
    # NetworkManager can remove manually added IPv6 addresses when the
    # router's native upgrade temporarily drops both Ethernet links.
    # Dnsmasq uses Linux dynamic binding; restore only our owned prefix
    # after the isolated interface's permanent IPv4 and carrier return.
    while kill -0 "$child" 2>/dev/null; do
      scope_ok || { echo 'test interface scope changed' >&2; exit 1; }
      if [[ $(cat "/sys/class/net/$iface/carrier" 2>/dev/null || :) == 1 ]] &&
         ip -4 -o addr show dev "$iface" | grep -Fq 'inet 192.168.76.2/24 ' &&
         ! ip -6 -o addr show dev "$iface" | grep -Fq "inet6 $prefix "; then
        ip -6 addr add "$prefix" dev "$iface"
        echo "restored scoped test IPv6 prefix on $iface"
      fi
      sleep 3
    done
    wait "$child"
    ;;
  --stop)
    need_root
    systemctl stop "$unit.service"
    ;;
  *) echo 'usage: lab-upstream.sh --check|--start|--stop' >&2; exit 2 ;;
esac
