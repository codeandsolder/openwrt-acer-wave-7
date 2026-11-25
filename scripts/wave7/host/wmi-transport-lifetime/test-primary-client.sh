#!/usr/bin/env bash
# Matched client-side reproduction of the secondary-activation NoC fault.
# Run only after the independently verified native primary-UMAC boot soak.
set -Eeuo pipefail
umask 077
base=/home/jan/firmware/wave7/trials/20261125-netgear-primary-dhcp-fixed
lab=/home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8
variant=upstream-prefix22-authorize-primary-mld-trace
client=/home/jan/scripts/wave7/client-validation
client_data=/home/jan/firmware/wave7/client-validation
fail(){ echo "PRIMARY_CLIENT_TEST_FAIL $*" >&2; exit 1; }
[[ $# == 1 && $1 == "$base"/runs/netgear-primary-* ]] || fail 'expected verified trial run'
run=$1
[[ $(cat "$run/status") == SOAK_PASS ]] || fail 'trial not soaked'
exec 8<>"$lab/.lab-control.lock"
flock -n 8 || fail 'lab already reserved'
[[ $(id -un) == jan && -s $run/known_hosts ]] || fail 'host identity'
boot=$(sed -n 's/^boot=//p' "$run/last-state.txt")
rev=$(jq -r .revision "$base/report.json")
[[ $boot =~ ^[0-9a-f-]{36}$ && $rev == r0+38346-77d7fa1171-ap-dhcp-guard8 ]] || fail 'trial identity'
out="$run/client-ab-$(date +%Y%m%d-%H%M%S)"
mkdir -m 700 "$out"
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
guard || fail 'router no longer healthy'
systemctl is-active --quiet wave7-lab-upstream-guard8.service || fail 'lab upstream'
wyse "sudo -n bash $client/client-module-stack.sh $variant --check-original" > "$out/client-original.txt"
remote 'cat /proc/sys/kernel/random/boot_id; dmesg; iw dev ap-mld0 info' > "$out/ap-before.txt"
active=0
trace_pid=''
sample_pid=''
cleanup(){
    local rc=$?
    trap - EXIT
    if [[ -n $trace_pid ]]; then wait "$trace_pid" || :; fi
    if [[ -n $sample_pid ]]; then wait "$sample_pid" || :; fi
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
# Per-case independent trace and passive Q6 samples. Only query station
# statistics before/after a healthy test, never during firmware teardown.
for band in 5 24; do
    guard || fail 'AP health before association'
    tag=0498-$(date +%Y%m%d-%H%M%S)
    prefix="$out/band-$band"
    printf '%s\n' "$tag" > "$prefix.tag"
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
    rc=0
    wyse "timeout 75 bash $client/client-sustained.sh $tag --early-only-$variant --bssid-$band" > "$prefix.client-run.txt" 2>&1 || rc=$?
    printf '%s\n' "$rc" > "$prefix.client-exit.txt"
    # Let the bounded independent observers complete even if a client fault
    # interrupts the association; keep the evidence before any restore.
    wait "$trace_pid" || :
    trace_pid=''
    wait "$sample_pid" || :
    sample_pid=''
    wyse "tar -C $client_data -cf - $tag" > "$prefix.client.tar" 2>"$prefix.client-archive-error.txt" || :
    remote 'cat /proc/sys/kernel/random/boot_id; dmesg' > "$prefix.ap-after.txt" 2>&1 || :
    if ! guard; then
        echo "AP_FAULT_AFTER_BAND_$band"
        exit 1
    fi
    printf 'CASE_COMPLETE band=%s client_rc=%s tag=%s\n' "$band" "$rc" "$tag"
done
echo PRIMARY_CLIENT_CASES_COMPLETE
