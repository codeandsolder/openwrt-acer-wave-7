#!/bin/sh
# One bounded isolated AP-side MLO trace, run over off-host SSH as root.
# No script installed on AP and no modifications to global tracefs instance.
set -eu

root=/sys/kernel/tracing
functions='ath12k_wmi_send_peer_create_cmd
ath12k_wmi_send_peer_delete_cmd
ath12k_wmi_send_peer_assoc_cmd
ath12k_wmi_send_mlo_link_set_active_cmd
ath12k_wmi_set_peer_param
ath12k_mac_op_sta_state
ath12k_mac_op_set_key
ath12k_mac_mlo_setup
ath12k_mac_mlo_ready
ath12k_wmi_mlo_setup
ath12k_wmi_mlo_ready'
events='mac80211/drv_sta_state
mac80211/drv_change_vif_links
mac80211/drv_change_sta_links
mac80211/drv_set_key
cfg80211/cfg80211_new_sta
cfg80211/cfg80211_del_sta'
instance=''
created=0

preflight() {
    test -r "$root/available_tracers"
    test -r "$root/available_filter_functions"
    test -r "$root/available_events"
    test -d "$root/instances"
    tr ' ' '\n' < "$root/available_tracers" |
        awk '$0=="function" {found=1} END {exit !found}'

    # One scan of the function catalogue; rescanning ~1 MB per function
    # needlessly stalls the observer and eats the trace readiness window.
    awk -v required="$functions" '
        BEGIN {
            n=split(required, names, "\n")
            for (i=1; i<=n; i++) if (names[i] != "") need[names[i]]=1
        }
        ($1 in need) { seen[$1]=1 }
        END {
            for (name in need) if (!(name in seen)) {
                print "AP_TRACE_MISSING_FUNCTION " name > "/dev/stderr"
                missing=1
            }
            exit missing
        }
    ' "$root/available_filter_functions"
    for event in $events; do
        test -r "$root/events/$event/format" || {
            printf 'AP_TRACE_MISSING_EVENT %s\n' "$event" >&2
            exit 1
        }
    done
    printf 'AP_TRACE_PREFLIGHT_PASS functions=%s events=%s\n' \
        "$(printf '%s\n' "$functions" | awk 'NF {n++} END {print n}')" \
        "$(printf '%s\n' "$events" | awk 'NF {n++} END {print n}')"
}

cleanup() {
    trap - EXIT HUP INT TERM
    if test "$created" -eq 1 && test -d "$instance"; then
        printf '0\n' > "$instance/tracing_on" || :
    fi
    if test "$created" -eq 1 && test -d "$instance"; then
        printf 'nop\n' > "$instance/current_tracer" || :
        for event in $events; do
            if test -e "$instance/events/$event/enable"; then
                printf '0\n' > "$instance/events/$event/enable" || :
            fi
        done
        if ! rmdir "$instance"; then
            printf 'AP_TRACE_CLEANUP_FAILED %s\n' "$instance" >&2
            exit 1
        fi
    fi
    printf 'AP_TRACE_CLEANUP_OK\n'
}

if test "${1:-}" = '--preflight'; then
    preflight
    exit 0
fi

test "$#" -eq 3 || {
    printf 'usage: sh -s -- TAG EXPECTED_BOOT SECONDS\n' >&2
    exit 2
}
tag=$1
expected_boot=$2
seconds=$3
case "$tag" in
    *[!a-zA-Z0-9_-]*|'') exit 2 ;;
esac
case "$seconds" in
    *[!0-9]*|'') exit 2 ;;
esac
test "$seconds" -ge 5 && test "$seconds" -le 180 || exit 2
actual_boot=$(cat /proc/sys/kernel/random/boot_id)
test "$actual_boot" = "$expected_boot" || {
    printf 'AP_TRACE_BOOT_MISMATCH expected=%s observed=%s\n' \
        "$expected_boot" "$actual_boot" >&2
    exit 1
}
preflight

instance="$root/instances/wave7_mlo_$tag"
test ! -e "$instance" || {
    printf 'AP_TRACE_INSTANCE_ALREADY_EXISTS %s\n' "$instance" >&2
    exit 1
}
trap cleanup EXIT
trap 'exit 143' HUP INT TERM
mkdir "$instance"
created=1
printf '0\n' > "$instance/tracing_on"
printf 'nop\n' > "$instance/current_tracer"
printf 'mono\n' > "$instance/trace_clock"
printf '1024\n' > "$instance/buffer_size_kb"
printf '%s\n' "$functions" > "$instance/set_ftrace_filter"
printf 'function\n' > "$instance/current_tracer"
for event in $events; do
    printf '1\n' > "$instance/events/$event/enable"
done
printf 'AP_TRACE_EVENTS_START\n'
for event in $events; do
    printf 'AP_TRACE_EVENT %s\n' "$event"
done
printf 'AP_TRACE_FUNCTIONS_START\n'
printf '%s\n' "$functions"
printf 'AP_TRACE_RUNNING boot=%s tag=%s seconds=%s\n' \
    "$actual_boot" "$tag" "$seconds"
printf '1\n' > "$instance/tracing_on"
printf 'AP_TRACE_READY\n'
sleep "$seconds"
# Bounded snapshot instead of a live trace_pipe consumer. The live
# consumer can outlive its parent and block a remote SSH channel; the
# isolated ring buffer survives WLAN remoteproc SSR on the same host boot.
printf '0\n' > "$instance/tracing_on"
printf 'AP_TRACE_SNAPSHOT_BEGIN boot=%s\n' \
    "$(cat /proc/sys/kernel/random/boot_id)"
cat "$instance/trace"
printf 'AP_TRACE_SNAPSHOT_END\n'
for statfile in "$instance"/per_cpu/cpu*/stats; do
    test -r "$statfile" || continue
    printf 'AP_TRACE_CPU_STATS %s\n' "$statfile"
    cat "$statfile"
done
printf 'AP_TRACE_END boot=%s\n' "$(cat /proc/sys/kernel/random/boot_id)"
