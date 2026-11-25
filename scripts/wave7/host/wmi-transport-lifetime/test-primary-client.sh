#!/usr/bin/env bash
# Matched client-side reproduction of the secondary-activation NoC fault.
# Run only after the independently verified native primary-UMAC boot soak.
set -Eeuo pipefail
umask 077
base=/home/jan/firmware/wave7/trials/20261125-netgear-primary-reo-lut
lab=/home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8
variant=upstream-prefix22-authorize-primary-mld-trace
client=/home/jan/scripts/wave7/client-validation
client_data=/home/jan/firmware/wave7/client-validation
fail(){ echo "PRIMARY_CLIENT_TEST_FAIL $*" >&2; exit 1; }
[[ $# -ge 1 && $# -le 5 && $1 == "$base"/runs/netgear-primary-* ]] || fail 'expected verified trial run'
run=$1
shift
bands=(5 24)
wired_capture=0
client_rx_arg=''
for arg in "$@"; do
    case "$arg" in
        --band=5) bands=(5) ;;
        --band=24) bands=(24) ;;
        --wired-capture) wired_capture=1 ;;
        --client-rx-trace) client_rx_arg=--rx-data ;;
        --client-single-link) variant=upstream-prefix22-authorize-single-link-trace ;;
        --client-delayed-links) variant=upstream-prefix22-authorize-delayed-links-trace ;;
        --client-delayed-links-fw20261016) variant=upstream-prefix22-authorize-delayed-links-fw20261016 ;;
        --client-header-trace) variant=upstream-prefix22-authorize-delayed-links-header-trace ;;
        --client-wtbl-trace) variant=upstream-prefix22-authorize-delayed-links-wtbl-trace ;;
        --client-mld-order-trace) variant=upstream-prefix22-authorize-delayed-links-mld-order-trace ;;
        --client-mld-rebind-trace) variant=upstream-prefix22-authorize-delayed-links-mld-rebind-trace ;;
        --client-mld-len-trace) variant=upstream-prefix22-authorize-delayed-links-mld-len-trace ;;
        --client-bss-presetup-trace) variant=upstream-prefix22-authorize-delayed-links-bss-presetup-trace ;;
        --client-roc-duration-trace) variant=upstream-prefix22-authorize-delayed-links-roc-duration-trace ;;
        --client-cnm-trace) variant=upstream-prefix22-authorize-delayed-links-cnm-trace ;;
        --client-omac-trace) variant=upstream-prefix22-authorize-delayed-links-omac-trace ;;
        --client-starec-split-trace) variant=upstream-prefix22-authorize-delayed-links-starec-split-trace ;;
        --client-eht-first-trace) variant=upstream-prefix22-authorize-delayed-links-eht-first-trace ;;
        --client-band-primary-trace) variant=upstream-prefix22-authorize-delayed-links-band-primary-trace ;;
        --client-band-primary-tx-trace) variant=upstream-prefix22-authorize-delayed-links-band-primary-tx-trace ;;
        --client-join-band1-trace) variant=upstream-prefix22-authorize-delayed-links-join-band1-trace ;;
        --client-band-primary-txd-trace) variant=upstream-prefix22-authorize-delayed-links-band-primary-txd-trace ;;
        *) fail 'invalid argument' ;;
    esac
done
if [[ $variant == upstream-prefix22-authorize-delayed-links-header-trace ]]; then
    client_rx_arg=--rx-header
elif [[ $variant == upstream-prefix22-authorize-delayed-links-wtbl-trace ||
        $variant == upstream-prefix22-authorize-delayed-links-mld-order-trace ||
        $variant == upstream-prefix22-authorize-delayed-links-mld-rebind-trace ||
        $variant == upstream-prefix22-authorize-delayed-links-mld-len-trace ||
        $variant == upstream-prefix22-authorize-delayed-links-bss-presetup-trace ||
        $variant == upstream-prefix22-authorize-delayed-links-roc-duration-trace ]]; then
    client_rx_arg=--rx-wtbl
elif [[ $variant == upstream-prefix22-authorize-delayed-links-cnm-trace ||
        $variant == upstream-prefix22-authorize-delayed-links-omac-trace ||
        $variant == upstream-prefix22-authorize-delayed-links-starec-split-trace ||
        $variant == upstream-prefix22-authorize-delayed-links-eht-first-trace ||
        $variant == upstream-prefix22-authorize-delayed-links-band-primary-trace ||
        $variant == upstream-prefix22-authorize-delayed-links-band-primary-tx-trace ||
        $variant == upstream-prefix22-authorize-delayed-links-join-band1-trace ]]; then
    client_rx_arg=--rx-cnm
elif [[ $variant == upstream-prefix22-authorize-delayed-links-band-primary-txd-trace ]]; then
    client_rx_arg=--rx-txd
fi
helper=$(dirname "$(realpath "$0")")/ap-control-trace.sh
delta_helper=$(dirname "$helper")/rx-counter-delta.py
[[ -r $helper && -r $delta_helper ]] || fail 'missing AP evidence helper'
[[ $(cat "$run/status") == SOAK_PASS ]] || fail 'trial not soaked'
exec 8<>"$lab/.lab-control.lock"
flock -n 8 || fail 'lab already reserved'
[[ $(id -un) == jan && -s $run/known_hosts ]] || fail 'host identity'
boot=$(sed -n 's/^boot=//p' "$run/last-state.txt")
rev=$(jq -r .revision "$base/report.json")
[[ $boot =~ ^[0-9a-f-]{36}$ && $rev == r0+38346-65f3c6bcfc-ap-dhcp-guard8 ]] || fail 'trial identity'
out="$run/client-ab-$(date +%Y%m%d-%H%M%S)"
mkdir -m 700 "$out"
printf "%s\n" "$variant" > "$out/client-variant.txt"
remote_stream(){
    ssh -T -i /home/jan/.ssh/wave7-root-rsa \
        -o BindInterface=enp4s0f4u2u4 -o BindAddress=192.168.76.2 \
        -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=3 \
        -o ServerAliveInterval=4 -o ServerAliveCountMax=2 \
        -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$run/known_hosts" root@192.168.76.1 "$@"
}
remote(){ remote_stream "$@" </dev/null; }
wyse(){
    ssh -nT -o BatchMode=yes -o ConnectTimeout=4 -o ServerAliveInterval=4 -o ServerAliveCountMax=2 acer \
        "ssh -nT -o BatchMode=yes -o ConnectTimeout=4 -o ServerAliveInterval=4 -o ServerAliveCountMax=2 wyse-eth $(printf '%q' "$1")"
}
guard(){
    local s
    s=$(remote 'cat /proc/sys/kernel/random/boot_id; cat /rom/etc/openwrt_version; fw_printenv -n bootfail; for p in 0 1 2; do cat /sys/class/remoteproc/remoteproc$p/state; done; dmesg | grep -c "NOC ERROR DETECTED" || :')
    [[ $s == "$(printf '%s\n%s\n0\nrunning\nrunning\nrunning\n0' "$boot" "$rev")" ]] || return 1
    ping -I 192.168.76.2 -c 1 -W 1 192.168.76.1 >/dev/null &&
    ping -I 192.168.76.250 -c 1 -W 1 192.168.76.1 >/dev/null
}
snapshot_rx(){
    remote 'set -eu
        cat /proc/sys/kernel/random/boot_id
        cat /proc/uptime
        for f in /sys/kernel/debug/ath12k/*/device_dp_stats; do
            echo "===$f"
            cat "$f"
        done'
}
snapshot_icmp(){
    remote 'cat /proc/sys/kernel/random/boot_id
        cat /proc/uptime
        cat /proc/net/snmp'
}
guard || fail 'router no longer healthy'
systemctl is-active --quiet wave7-lab-upstream-guard8.service || fail 'lab upstream'
wyse "sudo -n bash $client/client-module-stack.sh $variant --check-original" > "$out/client-original.txt"
remote 'cat /proc/sys/kernel/random/boot_id; dmesg; iw dev ap-mld0 info' > "$out/ap-before.txt"
active=0
trace_pid=''
sample_pid=''
ap_trace_pid=''
client_control_pid=''
wired_capture_pid=''
cleanup(){
    local rc=$?
    trap - EXIT
    if [[ -n $trace_pid ]]; then wait "$trace_pid" || :; fi
    if [[ -n $sample_pid ]]; then wait "$sample_pid" || :; fi
    if [[ -n $ap_trace_pid ]]; then wait "$ap_trace_pid" || :; fi
    if [[ -n $client_control_pid ]]; then wait "$client_control_pid" || :; fi
    if [[ -n $wired_capture_pid ]]; then wait "$wired_capture_pid" || :; fi
    if (( active )); then
        wyse "sudo -n bash $client/client-module-stack.sh $variant --restore" > "$out/client-restore.txt" 2>&1 || rc=1
    fi
    printf 'exit=%s\n' "$rc" > "$out/status"
    (cd "$out"; find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%P\0' | sort -z | xargs -0 sha256sum > SHA256SUMS)
    printf 'PRIMARY_CLIENT_TEST_DIR=%s\n' "$out"
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
active=1
wyse "sudo -n bash $client/client-module-stack.sh $variant --activate" > "$out/client-activate.txt" 2>&1
client_boot=$(wyse 'cat /proc/sys/kernel/random/boot_id')
[[ $client_boot =~ ^[0-9a-f-]{36}$ ]] || fail 'client boot'
if [[ $client_rx_arg == --rx-cnm || $client_rx_arg == --rx-txd ]]; then
    # Query once while disconnected. Do not associate on a failed query.
    wyse "sudo -n bash -c 'set -eu; mapfile -t paths < <(find /sys/kernel/debug/ieee80211 -name lab_cnm -type f); [[ \${#paths[@]} == 1 ]]; cat \"\${paths[0]}\"'" > "$out/client-cnm-preflight.txt" 2>&1 || fail 'CNM preflight query'
    grep -q '^CNM_GET_INFO count=' "$out/client-cnm-preflight.txt" || fail 'CNM preflight response'
    [[ $(wyse 'cat /proc/sys/kernel/random/boot_id') == "$client_boot" ]] || fail 'CNM preflight reboot'
fi
# Per-case independent trace and passive Q6 samples. Only query station
# statistics before/after a healthy test, never during firmware teardown.
cases_failed=0
for band in "${bands[@]}"; do
    guard || fail 'AP health before association'
    tag=0498-$(date +%Y%m%d-%H%M%S)
    prefix="$out/band-$band"
    printf '%s\n' "$tag" > "$prefix.tag"
    snapshot_rx > "$prefix.rx-before.txt"
    snapshot_icmp > "$prefix.icmp-before.txt"
    wyse "sudo -n bash $client/client-crash-stream.sh $tag $variant $client_boot 90" > "$prefix.client-trace.txt" 2>&1 &
    trace_pid=$!
    for _ in {1..80}; do
        kill -0 "$trace_pid" 2>/dev/null || fail 'client trace exited'
        grep -q '^CRASH_STREAM_READY ' "$prefix.client-trace.txt" && break
        sleep .25
    done
    grep -q '^CRASH_STREAM_READY ' "$prefix.client-trace.txt" || fail 'client trace not armed'
    (
        for seq in $(seq 1 360); do
            printf '%s\n' "$seq"
            sleep .25
        done
    ) | remote_stream 'while IFS= read -r seq; do
        printf "%s %s " "$seq" "$(cut -d" " -f1 /proc/uptime)"
        for p in 0 1 2; do printf "%s " "$(cat /sys/class/remoteproc/remoteproc$p/state)"; done
        printf "\n"
    done' > "$prefix.ap-passive.txt" 2>&1 &
    sample_pid=$!
    for _ in {1..20}; do
        [[ -s $prefix.ap-passive.txt ]] && break
        sleep .2
    done
    [[ -s $prefix.ap-passive.txt ]] || fail 'AP observer not armed'
    remote_stream "sh -s -- $boot $tag" < "$helper" > "$prefix.ap-control-trace.txt" 2>&1 &
    ap_trace_pid=$!
    for _ in {1..60}; do
        kill -0 "$ap_trace_pid" 2>/dev/null || fail 'AP trace exited'
        grep -q '^AP_CONTROL_TRACE_READY ' "$prefix.ap-control-trace.txt" && break
        sleep .25
    done
    grep -q '^AP_CONTROL_TRACE_READY ' "$prefix.ap-control-trace.txt" || fail 'AP trace not armed'
    wyse "sudo -n bash $client/client-control-trace.sh $tag $client_boot $client_rx_arg" > "$prefix.client-control-trace.txt" 2>&1 &
    client_control_pid=$!
    for _ in {1..60}; do
        kill -0 "$client_control_pid" 2>/dev/null || fail 'client control trace exited'
        grep -q '^CLIENT_CONTROL_TRACE_READY ' "$prefix.client-control-trace.txt" && break
        sleep .25
    done
    grep -q '^CLIENT_CONTROL_TRACE_READY ' "$prefix.client-control-trace.txt" || fail 'client control trace not armed'
    if (( wired_capture )); then
        # Only ICMP header summaries on the isolated wired lab interface.
        timeout -s INT 90 sudo -n /usr/bin/tcpdump -p -nn -l -tt -s 96         -i enp4s0f4u2u4 'icmp and host 192.168.76.2 and not host 192.168.76.1'         > "$prefix.wired-icmp.txt" 2> "$prefix.wired-icmp-status.txt" &
        wired_capture_pid=$!
        for _ in {1..40}; do
            kill -0 "$wired_capture_pid" 2>/dev/null || fail 'wired capture exited'
            grep -q 'listening on enp4s0f4u2u4' "$prefix.wired-icmp-status.txt" && break
            sleep .25
        done
        grep -q 'listening on enp4s0f4u2u4' "$prefix.wired-icmp-status.txt" || fail 'wired capture not armed'
    fi
    rc=0
    wyse "timeout 75 bash $client/client-sustained.sh $tag --early-only-$variant --bssid-$band" > "$prefix.client-run.txt" 2>&1 || rc=$?
    printf '%s\n' "$rc" > "$prefix.client-exit.txt"
    # Let the bounded independent observers complete even if a client fault
    # interrupts the association; keep the evidence before any restore.
    wait "$trace_pid" || :
    trace_pid=''
    wait "$sample_pid" || :
    sample_pid=''
    wait "$ap_trace_pid" || cases_failed=1
    ap_trace_pid=''
    wait "$client_control_pid" || cases_failed=1
    client_control_pid=''
    if (( wired_capture )); then
        capture_rc=0
        wait "$wired_capture_pid" || capture_rc=$?
        wired_capture_pid=''
        if [[ $capture_rc != 124 && $capture_rc != 0 ]] ||
           ! grep -Eq '^0 packets dropped by kernel$' "$prefix.wired-icmp-status.txt"; then
            cases_failed=1
        fi
    fi
    wyse "tar -C $client_data -cf - $tag" > "$prefix.client.tar" 2>"$prefix.client-archive-error.txt" || :
    remote 'cat /proc/sys/kernel/random/boot_id; dmesg' > "$prefix.ap-after.txt" 2>&1 || :
    if ! guard; then
        echo "AP_FAULT_AFTER_BAND_$band"
        exit 1
    fi
    snapshot_rx > "$prefix.rx-after.txt"
    snapshot_icmp > "$prefix.icmp-after.txt"
    uv run --no-project python -B "$delta_helper" "$prefix.rx-before.txt" "$prefix.rx-after.txt" > "$prefix.rx-delta.json" || cases_failed=1
    result=$(tar -xOf "$prefix.client.tar" "$tag/short-hold-result.txt" 2>/dev/null || :)
    if [[ $rc != 0 || $result != short_hold_all_replies=1 ]]; then
        cases_failed=1
    fi
    printf 'CASE_COMPLETE band=%s client_rc=%s hold=%s tag=%s\n' "$band" "$rc" "$result" "$tag"
done
echo PRIMARY_CLIENT_CASES_COMPLETE
exit "$cases_failed"
