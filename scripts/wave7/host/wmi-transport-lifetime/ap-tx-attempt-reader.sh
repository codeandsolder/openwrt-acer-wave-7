# Read-only software counters. Retry only core_lock contention.
capture_tx_attempts(){
    for d in /sys/kernel/debug/ath12k/ahb-c000000.wifi /sys/kernel/debug/ath12k/ahb-soc@0:wifi; do
        f="$d/tx_attempt_stats"
        [ -r "$f" ] || return 1
        attempt=0
        while :; do
            if result=$(cat "$f" 2>&1); then break; fi
            case "$result" in
                'cat: read error: Resource busy'|'cat: read error: Device or resource busy') ;;
                *) printf '%s\n' "$result" >&2; return 1 ;;
            esac
            attempt=$((attempt + 1))
            [ "$attempt" -lt 5 ] || return 1
            sleep .02
        done
        printf '==== TX_ATTEMPT %s\n%s\n' "${d##*/}" "$result"
    done
}
