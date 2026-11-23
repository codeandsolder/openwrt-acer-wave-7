#!/usr/bin/env bash
# Independent off-AP sampler; uses existing AP iw over one bounded wired SSH.
# No commands install, configure or modify firmware, AP interfaces or stations.
set -Eeuo pipefail
[[ $# == 3 &&
   $1 =~ ^0498-[0-9]{8}-[0-9]{6}$ &&
   $2 =~ ^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$ &&
   $3 =~ ^[0-9]{2,3}$ && $3 -ge 35 && $3 -le 120 &&
   $(id -un) == jan ]] || exit 2
tag=$1
boot=$2
seconds=$3
base=/home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8
out="$base/client-validation/$tag-ap-link-stats"
[[ ! -e $out &&
   $(systemctl is-active wave7-lab-upstream-guard8.service) == active &&
   $(ip -4 -o address show enp4s0f4u2u2u4) == *'192.168.76.250/24'* ]]
mkdir -m 700 "$out"
done_check() {
    local rc=$?
    trap - EXIT
    printf 'exit=%d\n' "$rc" > "$out/status"
    (
        cd "$out"
        sha256sum raw.txt ssh-stderr.txt status > SHA256SUMS
        sha256sum -c SHA256SUMS
    )
    exit "$rc"
}
trap done_check EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP
# Keep a SINGLE wired SSH process. Asus writes read-only AP commands
# at the required cadence; OpenWrt BusyBox sleep may be integer-only.
# Every AP response contains its own uptime plus Asus's request epoch.
{
    printf 'set -eu\n'
    # shellcheck disable=SC2016 # Remote shell expands command substitution.
    printf 'test "$(cat /proc/sys/kernel/random/boot_id)" = "%s"\n' "$boot"
    # shellcheck disable=SC2016 # Remote shell expands command substitution.
    printf 'test "$(cat /sys/class/remoteproc/remoteproc0/state)" = running\n'
    printf 'command -v iw >/dev/null\n'
    printf 'echo "AP_LINK_STATS_READY boot=%s samples=%s"\n' "$boot" "$((seconds*5))"
    for ((i=0; i<seconds*5; i++)); do
        epoch=$(date +%s.%N)
        printf 'echo "AP_LINK_SAMPLE_BEGIN index=%d asus_epoch=%s"; cat /proc/uptime; iw dev ap-mld0 station dump; echo "AP_LINK_SAMPLE_END index=%d"\n' "$i" "$epoch" "$i"
        sleep .2
    done
    printf 'echo "AP_LINK_STATS_END samples=%s"\n' "$((seconds*5))"
} | timeout --signal=TERM --kill-after=3s "$((seconds+30))s" \
ssh -T -i /home/jan/.ssh/wave7-root-rsa \
    -o BindInterface=enp4s0f4u2u2u4 -o BindAddress=192.168.76.250 \
    -o BatchMode=yes -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$base/known_hosts" \
    -o ServerAliveInterval=3 -o ServerAliveCountMax=2 -o ConnectTimeout=5 \
    root@192.168.76.1 sh > "$out/raw.txt" 2> "$out/ssh-stderr.txt"
test "$(rg -c '^AP_LINK_SAMPLE_BEGIN ' "$out/raw.txt")" == "$((seconds*5))"
rg -Fq "AP_LINK_STATS_END samples=$((seconds*5))" "$out/raw.txt"
