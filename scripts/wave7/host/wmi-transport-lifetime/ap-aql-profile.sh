#!/bin/sh
# Bounded AQL-only experiment, with occupancy samples and same-boot restore.
set -eu
[ "$#" -eq 3 ]
boot=$1
seconds=$2
requested=$3
[ "$seconds" = 335 ]
case "$requested" in 0|1) ;; *) exit 2 ;; esac
[ "$(id -u)" = 0 ]
check_boot(){
    read -r current </proc/sys/kernel/random/boot_id
    [ "$current" = "$boot" ]
}
check_boot
phy=/sys/kernel/debug/ieee80211/phy0
[ -r "$phy/aql_pending" ] && [ -w "$phy/aql_enable" ]
iw phy phy0 info | grep -Fq 'Airtime Queue Limits (AQL)'
[ -z "$(iw dev ap-mld0 station dump)" ]
for p in 0 1 2; do
    [ "$(cat /sys/class/remoteproc/remoteproc$p/state)" = running ]
done
read -r original < "$phy/aql_enable"
case "$original" in 0|1) ;; *) exit 2 ;; esac
# AQL pending is an independently sampled set of atomic counters. Do
# not demand their sum match mid-flight: the snapshot isn't atomic.
sample(){
    vo= vi= be= bk= bc= total=
    while read -r ac value unit rest; do
        [ "$ac" != AC ] || continue
        [ "$unit" = us ] && [ -z "$rest" ] || return 1
        case "$value" in ''|*[!0-9]*) return 1 ;; esac
        [ "$value" -le 2147483647 ] || return 1
        case "$ac" in
            VO) [ -z "$vo" ] || return 1; vo=$value ;;
            VI) [ -z "$vi" ] || return 1; vi=$value ;;
            BE) [ -z "$be" ] || return 1; be=$value ;;
            BK) [ -z "$bk" ] || return 1; bk=$value ;;
            BC/MC) [ -z "$bc" ] || return 1; bc=$value ;;
            total) [ -z "$total" ] || return 1; total=$value ;;
            *) return 1 ;;
        esac
    done < "$phy/aql_pending"
    [ -n "$vo" ] && [ -n "$vi" ] && [ -n "$be" ] && [ -n "$bk" ] &&
        [ -n "$bc" ] && [ -n "$total" ] || return 1
}
drained(){
    sample && [ "$vo:$vi:$be:$bk:$bc:$total" = 0:0:0:0:0:0 ]
}
wait_drain(){
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        if drained; then return 0; fi
        sleep .2
    done
    return 1
}
wait_drain
cleanup(){
    rc=$?
    trap - EXIT HUP INT TERM
    if check_boot; then
        if wait_drain; then
            printf 'AQL_PROFILE_DRAINED\n'
        else
            printf 'AQL_PROFILE_DRAIN_FAILED\n'
            rc=1
        fi
        if printf '%s\n' "$original" > "$phy/aql_enable" &&
           read -r restored < "$phy/aql_enable" &&
           [ "$restored" = "$original" ]; then
            printf 'AQL_PROFILE_RESTORE enabled=%s\n' "$restored"
        else
            rc=1
        fi
    else
        rc=1
    fi
    printf 'AQL_PROFILE_END rc=%s\n' "$rc"
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 143' HUP INT TERM
printf '%s\n' "$requested" > "$phy/aql_enable"
read -r enabled < "$phy/aql_enable"
[ "$enabled" = "$requested" ]
printf 'AQL_PROFILE_READY boot=%s enabled=%s original=%s seconds=%s\n' "$boot" "$enabled" "$original" "$seconds"
read -r now _ </proc/uptime
end=$(("${now%.*}" + seconds))
while :; do
    check_boot
    read -r enabled < "$phy/aql_enable"
    [ "$enabled" = "$requested" ]
    read -r now _ </proc/uptime
    sample
    printf 'AQL_PROFILE_SAMPLE %s %s %s %s %s %s %s\n' "$now" "$vo" "$vi" "$be" "$bk" "$bc" "$total"
    [ "${now%.*}" -lt "$end" ] || break
    sleep .25
done
