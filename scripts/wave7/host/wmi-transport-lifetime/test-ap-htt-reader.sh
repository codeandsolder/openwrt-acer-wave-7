#!/bin/bash
# Test the production request state machine against a local debugfs fixture.
set -Eeuo pipefail
h=$(dirname "$(realpath "$0")")
t=$(mktemp -d)
trap 'rm -rf "$t"' EXIT
source <(sed -e "s|/sys/kernel/debug/ath12k|$t/radio|g" \
             -e "s|/sys/class/remoteproc|$t/q6|g" \
             -e "s|/proc/uptime|$t/uptime|g" "$h/ap-htt-reader.sh")
for p in 0 1 2; do mkdir -p "$t/q6/remoteproc$p"; printf 'running\n' > "$t/q6/remoteproc$p/state"; done
for d in ahb-c000000.wifi ahb-soc@0:wifi; do
    mkdir -p "$t/radio/$d/mac0"
    touch "$t/radio/$d/mac0/htt_stats"
done
scenario=ok
dmesg(){ :; }
cat(){
    case "$1" in
        */htt_stats)
            local dir=${1%/*} kind
            read -r kind < "$dir/htt_stats_type"
            printf '%s %s\n' "${dir#"$t/radio/"}" "$kind" >> "$t/requests"
            if [[ "$scenario" == timeout ]]; then printf '103.00 0.00\n' > "$t/uptime"; fi
            if [[ "$scenario" == failure ]]; then echo 'fixture read failed' >&2; return 1; fi
            if [[ "$scenario" == late ]]; then printf '102.90 0.00\n' > "$t/uptime"; fi
            echo 'fixture firmware reply' ;;
        *) command cat "$@" ;;
    esac
}
reset(){
    : > "$t/requests"
    printf '100.00 0.00\n' > "$t/uptime"
    for d in "$t/radio"/*/mac0; do printf '%s\n' "$1" > "$d/htt_stats_type"; done
}
check_count(){ [[ $(wc -l < "$t/requests") == "$1" ]]; }
check_selectors(){
    for d in "$t/radio"/*/mac0; do [[ $(command cat "$d/htt_stats_type") == "$1" ]]; done
}
reset 0
capture_htt_tx > "$t/result"
check_count 2
check_selectors 1
rg -qx 'HTT_BEGIN ahb-c000000.wifi/mac0 100.00 selector=0' "$t/result"
rg -qx 'HTT_END ahb-soc@0:wifi/mac0 100.00 rc=0' "$t/result"
reset 1
capture_htt_rate > "$t/result"
check_count 2
check_selectors 1
rg -qx 'HTT_RATE_BEGIN ahb-c000000.wifi/mac0 9 100.00' "$t/result"
rg -qx 'HTT_RATE_END ahb-soc@0:wifi/mac0 9 100.00 rc=0' "$t/result"
reset 1
capture_htt_mlo > "$t/result"
check_count 4
check_selectors 1
[[ $(cut -d' ' -f2 "$t/requests" | paste -sd, -) == 63,64,63,64 ]]
for scenario in failure timeout late; do
    for profile in RATE MLO TX; do
        reset 1
        if capture_htt "$profile" > "$t/result"; then echo "accepted $scenario $profile" >&2; exit 1; fi
        check_count 1
        check_selectors 1
    done
done
scenario=ok
reset 9
if capture_htt_rate > "$t/result"; then exit 1; fi
check_count 0
check_selectors 9
reset 1
printf 'offline\n' > "$t/q6/remoteproc2/state"
if capture_htt_rate > "$t/result"; then exit 1; fi
check_count 0
printf 'running\n' > "$t/q6/remoteproc2/state"
rm "$t/radio/ahb-c000000.wifi/mac0/htt_stats"
if capture_htt_tx > "$t/result"; then exit 1; fi
check_count 0
echo AP_HTT_REQUEST_STATE_PASS
