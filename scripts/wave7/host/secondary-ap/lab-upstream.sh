#!/usr/bin/env bash
# Root-only explicitly bounded isolated test service. Run via root SSH.
# No changes to persistent NetworkManager profiles or unrelated interfaces.
set -euo pipefail
iface=enp4s0f4u2u4
expected_mac=00:e0:4c:68:00:6d
prefix=fd76:7::2/64
base=/home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8/upstream
unit=wave7-lab-upstream-guard8
config=$(dirname "$(realpath "$0")")/lab-upstream.conf
rule=(-i "$iface" -p udp --sport 68 --dport 67 -m comment --comment "$unit" -j ACCEPT)
preflight() {
  [[ $(cat "/sys/class/net/$iface/address") == "$expected_mac" ]] || return 1
  [[ ! -e /sys/class/net/$iface/master ]] || return 1
  ip -4 -o addr show dev "$iface" | grep -Fq 'inet 192.168.76.2/24 ' || return 1
  if ip -4 route show default | grep -Eq "dev $iface([[:space:]]|$)" ||
     ip -6 route show default | grep -Eq "dev $iface([[:space:]]|$)"; then
    echo 'test interface is a default route' >&2; return 1
  fi
  dnsmasq --test --conf-file="$config"
}
need_root() { [[ $(id -u) == 0 ]] || { echo 'run as root' >&2; exit 1; }; }
case "${1:---check}" in
  --check) preflight; echo LAB_UPSTREAM_PREFLIGHT_PASS ;;
  --start)
    need_root
    preflight
    if systemctl is-active --quiet "$unit.service"; then
      echo 'already running; refusing duplicate upstream' >&2; exit 1
    fi
    systemd-run --quiet --unit="$unit" --property=RuntimeMaxSec=3600 \
      --property=KillMode=mixed "$(realpath "$0")" --serve
    ;;
  --serve)
    need_root
    preflight
    # Require newly owned address and firewall rule. Only remove our own
    # changes on completion/failure. The transient unit bounds the lifetime.
    if ip -6 -o addr show dev "$iface" | grep -Fq "inet6 $prefix "; then
      echo 'test IPv6 address already exists' >&2; exit 1
    fi
    if iptables -C ufw-user-input "${rule[@]}" 2>/dev/null; then
      echo 'test firewall rule already exists' >&2; exit 1
    fi
    address_added=0
    rule_added=0
    child=
    cleanup() {
      if [[ -n $child ]]; then kill "$child" 2>/dev/null || :; wait "$child" 2>/dev/null || :; fi
      if (( rule_added )); then iptables -D ufw-user-input "${rule[@]}" || :; fi
      if (( address_added )); then ip -6 addr del "$prefix" dev "$iface" || :; fi
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
    wait "$child"
    ;;
  --stop)
    need_root
    systemctl stop "$unit.service"
    ;;
  *) echo 'usage: lab-upstream.sh --check|--start|--stop' >&2; exit 2 ;;
esac
