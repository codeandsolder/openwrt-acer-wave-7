#!/bin/sh
# Bounded, reversible affinity-only experiment on the QCN6432 lab AP.
# Resolve IRQs by the exact driver group names, not boot-specific numbers.
set -eu
[ "$#" -eq 2 ]
boot=$1
seconds=$2
[ "$seconds" = 335 ]
[ "$(id -u)" = 0 ]
[ "$(cat /proc/sys/kernel/random/boot_id)" = "$boot" ]
[ "$(cat /sys/devices/system/cpu/online)" = 0-3 ]
[ -z "$(pidof irqbalance || :)" ]
for p in 0 1 2; do
    [ "$(cat /sys/class/remoteproc/remoteproc$p/state)" = running ]
done
# Groups 3/4/5 service three data rings (3 also handles WBM/REO
# exception/status); group 8 handles monitor traffic. Leave group 6,
# Ethernet, CE and TX-completion affinity unchanged for this comparison.
plan=''
for pair in 3:1 4:2 5:3 8:2; do
    group=${pair%:*}
    cpu=${pair#*:}
    irq=$(awk -v name="pci2_wlan_dp_$group" '$NF == name {sub(/:$/, "", $1); print $1}' /proc/interrupts)
    case "$irq" in ''|*[!0-9]*) exit 2 ;; esac
    old=$(cat "/proc/irq/$irq/smp_affinity_list")
    effective=$(cat "/proc/irq/$irq/effective_affinity_list")
    [ "$old" = 0-3 ] && [ "$effective" = 0 ]
    plan="$plan $irq:$group:$cpu"
    printf 'IRQ_PROFILE_ORIGINAL irq=%s group=%s configured=%s effective=%s\n' "$irq" "$group" "$old" "$effective"
done
changed=''
cleanup(){
    rc=$?
    trap - EXIT HUP INT TERM
    # Check the boot before touching IRQs, since numbers can be reused
    # after a reboot. Restore both configured and effective affinity.
    if [ "$(cat /proc/sys/kernel/random/boot_id)" != "$boot" ]; then
        rc=1
    else
        for entry in $changed; do
            irq=${entry%%:*}
            if ! { printf '0\n' > "/proc/irq/$irq/smp_affinity_list" &&
                   printf '0-3\n' > "/proc/irq/$irq/smp_affinity_list" &&
                   [ "$(cat "/proc/irq/$irq/smp_affinity_list")" = 0-3 ] &&
                   [ "$(cat "/proc/irq/$irq/effective_affinity_list")" = 0 ]; }; then
                rc=1
            fi
            printf 'IRQ_PROFILE_RESTORE irq=%s configured=%s effective=%s\n' "$irq" \
                "$(cat "/proc/irq/$irq/smp_affinity_list")" "$(cat "/proc/irq/$irq/effective_affinity_list")"
        done
    fi
    printf 'IRQ_PROFILE_END rc=%s\n' "$rc"
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 143' HUP INT TERM
for entry in $plan; do
    irq=${entry%%:*}
    cpu=${entry##*:}
    changed="$entry $changed"
    printf '%s\n' "$cpu" > "/proc/irq/$irq/smp_affinity_list"
    [ "$(cat "/proc/irq/$irq/smp_affinity_list")" = "$cpu" ]
    [ "$(cat "/proc/irq/$irq/effective_affinity_list")" = "$cpu" ]
    printf 'IRQ_PROFILE_APPLIED irq=%s cpu=%s\n' "$irq" "$cpu"
done
printf 'IRQ_PROFILE_READY boot=%s seconds=%s\n' "$boot" "$seconds"
sleep "$seconds"
