# Read-only software counters. Retry only core_lock contention.
capture_tx_attempts(){
    for d in /sys/kernel/debug/ath12k/ahb-c000000.wifi /sys/kernel/debug/ath12k/ahb-soc@0:wifi; do
        f="$d/tx_attempt_stats"
        [ -r "$f" ] || return 1
        result=$(read_debugfs "$f") || return 1
        printf '==== TX_ATTEMPT %s\n%s\n' "${d##*/}" "$result"
    done
}
