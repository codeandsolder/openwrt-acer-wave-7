#!/usr/bin/env bash
# Independently bounded dedicated direct-NIC speed/late-link experiment.
# All unrelated network settings and persistent connection profiles stay intact.
set -Eeuo pipefail
iface=enp4s0f4u2u4
sys=/sys/class/net/$iface
unit=wave7-peer-1g-window
self=$(realpath "$0")
phyctl="$(dirname "$self")/peer-phy-power.py"
phy() { uv run --no-project --offline --python /usr/bin/python3 python "$phyctl" "$@"; }
scope_ok() {
    [[ $(cat "$sys/address") == 00:e0:4c:68:00:6d && ! -e $sys/master ]] || return 1
    ! ip -4 route show default | rg -q "dev $iface([[:space:]]|$)" || return 1
    ! ip -6 route show default | rg -q "dev $iface([[:space:]]|$)" || return 1
}
peer_ready() {
    scope_ok &&
    ip -4 -o addr show dev "$iface" | rg -q 'inet 192\.168\.76\.2/24 .*valid_lft forever preferred_lft forever' &&
    [[ $(cat "$sys/carrier" 2>/dev/null || :) == 1 &&
       $(cat "$sys/speed" 2>/dev/null || :) == 1000 ]]
}
need_root() { [[ $EUID == 0 ]] || { echo 'run as root' >&2; exit 1; }; }
log() { printf '%s %s\n' "$(date -Is)" "$*"; }
restore() {
    # Never modify a renamed/replaced interface or a newly routed uplink.
    scope_ok || { log RESTORE_SCOPE_CHANGED; return 1; }
    ip link set dev "$iface" up
    phy up
    ethtool -s "$iface" autoneg on advertise 0x800000000000
    log PEER_RESTORED_ADVERTISE_2500
}
case "${1:-}" in
    --check)
        [[ $# == 1 ]] || exit 2
        peer_ready
        [[ $(systemctl show "$unit.service" -p ActiveState --value) == active &&
           $(systemctl show "$unit.service" -p Transient --value) == yes &&
           $(systemctl show "$unit.service" -p RuntimeMaxUSec --value) == 15min ]]
        started=$(systemctl show "$unit.service" -p ActiveEnterTimestamp --value)
        elapsed=$(( $(date +%s) - $(date -d "$started" +%s) ))
        (( elapsed >= 0 && elapsed <= 240 ))
        echo PEER_1G_WINDOW_READY
        ;;
    --start)
        need_root
        [[ $# == 2 && ( $2 == fast || $2 == delayed ) ]]
        scope_ok
        [[ $(phy status) == *"pdown=0"* ]]
        [[ $(cat "$sys/carrier") == 1 && $(cat "$sys/speed") == 2500 ]]
        ip -4 -o addr show dev "$iface" | rg -q 'inet 192\.168\.76\.2/24 .*valid_lft forever preferred_lft forever'
        [[ $(systemctl show "$unit.service" -p LoadState --value) == not-found ]]
        systemd-run --quiet --collect --unit="$unit" --property=RuntimeMaxSec=900 \
            --property=TimeoutStopSec=15 --property="ExecStopPost=$self --restore" \
            "$self" --serve "$2"
        ;;
    --restore)
        need_root
        [[ $# == 1 ]]
        restore
        ;;
    --stop)
        need_root
        [[ $# == 1 ]]
        systemctl stop "$unit.service"
        ;;
    --serve)
        need_root
        [[ $# == 2 && ( $2 == fast || $2 == delayed ) ]]
        scope_ok
        trap 'exit 0' TERM INT
        # The independently managed ExecStopPost restores on every exit.
        [[ -n ${INVOCATION_ID:-} ]] || exit 2
        ethtool -s "$iface" autoneg on advertise 0x20
        # Wait for a real healthy link before arming the first-loss trigger.
        good=0
        for ((i=0;i<120;i++)); do
            if peer_ready; then ((++good)); else good=0; fi
            (( good >= 10 )) && break
            sleep 0.25
        done
        (( good >= 10 )) || { log PEER_1G_NOT_ESTABLISHED; exit 1; }
        log "PEER_READY mode=$2"
        if [[ $2 == delayed ]]; then
            # A reboot drops carrier. Hold the dedicated NIC down from
            # that edge, not from guessed flash scheduling latency.
            for ((i=0;i<2400;i++)); do
                scope_ok
                [[ $(cat "$sys/carrier" 2>/dev/null || :) == 1 ]] || break
                sleep 0.1
            done
            (( i < 2400 )) || { log NO_CARRIER_LOSS; exit 1; }
            log PEER_CARRIER_FELL
            # Administrative down leaves the Realtek copper PHY
            # negotiating. Use BMCR power-down without closing the netdev.
            result=$(phy down)
            [[ $result == *"pdown=1"* ]] || exit 1
            log PEER_PHY_DOWN
            deadline=$((SECONDS+65))
            while (( SECONDS < deadline )); do
                scope_ok
                result=$(phy status)
                if [[ $result != *"pdown=1"* || $result != *"link=0" ]]; then
                    log PEER_PHY_HOLD_LOST
                    exit 1
                fi
                sleep 0.5
            done
            log PEER_PHY_HOLD_VERIFIED
            phy up
            ethtool -s "$iface" autoneg on advertise 0x20
            log PEER_PHY_RELEASED_1G
        fi
        # systemd enforces the independent deadline even if the caller is gone.
        while :; do scope_ok; sleep 2; done
        ;;
    --selftest)
        # Pure dry-run: check the policy and that the tested port is not routed.
        [[ $# == 1 ]]
        scope_ok
        echo PEER_SCOPE_PASS
        ;;
    *) echo 'usage: peer-1g-window.sh --start fast|delayed|--check|--stop|--selftest' >&2; exit 2 ;;
esac
