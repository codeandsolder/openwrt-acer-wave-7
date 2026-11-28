#!/bin/sh
# Bounded, opt-in host-side datapath observation. No WMI queries, writes,
# station polling, or PCI window register access while traffic is running.
set -eu
[ "$#" = 1 ] || exit 2
boot=$1
healthy() {
    read -r actual </proc/sys/kernel/random/boot_id
    [ "$actual" = "$boot" ] || return 1
    for p in 0 1 2; do
        read -r state <"/sys/class/remoteproc/remoteproc$p/state"
        [ "$state" = running ] || return 1
    done
}
healthy
printf 'LOAD_SERIES_BEGIN boot=%s samples=120\n' "$boot"
i=0
while [ "$i" -lt 120 ]; do
    healthy
    read -r stamp rest </proc/uptime
    printf 'LOAD_SAMPLE %s %s\n' "$i" "$stamp"
    printf '==== CPU\n'
    cat /proc/stat
    for f in /sys/kernel/debug/ath12k/*/device_dp_stats; do
        printf '==== %s\n' "$f"
        cat "$f"
    done
    printf '==== SRNG\n'
    cat /sys/kernel/debug/ath12k/ahb-c000000.wifi/srng_state
    healthy
    read -r stamp rest </proc/uptime
    printf 'LOAD_SAMPLE_END %s %s\n' "$i" "$stamp"
    if [ "$i" = 0 ]; then printf 'LOAD_SERIES_READY\n'; fi
    i=$((i + 1))
    if [ "$i" -lt 120 ]; then sleep 1; fi
done
printf 'LOAD_SERIES_END boot=%s samples=%s\n' "$boot" "$i"
