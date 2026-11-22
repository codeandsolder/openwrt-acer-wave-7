#!/usr/bin/env bash
# Asus peer tap. Only capture the fixed echo IDs for the isolated lab.
set -Eeuo pipefail
umask 077
base=/home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8
[[ $(id -un) == jan && $# == 1 && $1 =~ ^0498-[0-9]{8}-[0-9]{6}$ ]] || exit 2
out="$base/client-validation/$1-peer"
[[ ! -e $out ]]
lock="$base/.lab-control.lock"
[[ -f $lock && ! -L $lock && -O $lock ]]
exec 8<>"$lock"
flock -n 8
export XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
test -z "$(systemctl --user --no-pager --no-legend list-units --state=active,activating 'wave7-*watch-*' 'wave7-*supervisor-*' 'wave7-autonomous-observer-*')"
systemctl is-active --quiet wave7-lab-upstream-guard8.service
direct=enp4s0f4u2u4
switch=enp4s0f4u2u2u4
[[ $(cat "/sys/class/net/$direct/address") == 00:e0:4c:68:00:6d ]]
[[ $(cat "/sys/class/net/$switch/address") == 00:e0:4c:68:01:45 ]]
for dev in "$direct" "$switch"; do
    [[ $(cat "/sys/class/net/$dev/carrier") == 1 && ! -e /sys/class/net/$dev/master ]]
    ! ip -4 route show default | rg -q "dev $dev( |$)"
    ! ip -6 route show default | rg -q "dev $dev( |$)"
done
[[ $(cat "/sys/class/net/$direct/speed") == 2500 && $(cat "/sys/class/net/$switch/speed") == 1000 ]]
ip -4 -o addr show dev "$direct" | rg -Fq 'inet 192.168.76.2/24 '
ip -6 -o addr show dev "$direct" | rg -Fq 'inet6 fd76:7::2/64 '
opts=(-nT -i /home/jan/.ssh/wave7-root-rsa -o BindInterface="$switch" -o BindAddress=192.168.76.250 -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$base/known_hosts" -o ConnectTimeout=4)
state() {
    ssh "${opts[@]}" root@192.168.76.1 'cat /proc/sys/kernel/random/boot_id /etc/openwrt_version /proc/uptime; cat /sys/class/net/lan/speed; fw_printenv -n bootfail; dmesg | grep -c "NOC ERROR DETECTED" || :'
}
mkdir -p "$base/client-validation"
mkdir -m 700 "$out"
state > "$out/router-before.txt"
[[ $(sed -n '1p' "$out/router-before.txt") == 195982f4-b227-4cd1-85e7-31f843cacd49 &&
   $(sed -n '2p' "$out/router-before.txt") == r0+38346-f9aa3e1fa3-ap-dhcp-guard8 &&
   $(sed -n '4,6p' "$out/router-before.txt") == $'2500\n0\n0' ]]
timedatectl show -p NTPSynchronized -p NTP > "$out/clock.txt"
filter='(icmp and host 192.168.76.2 and host 192.168.76.145 and (icmp[0] = 8 or icmp[0] = 0) and (icmp[4:2] = 47601 or icmp[4:2] = 47603)) or (ip6 and host fd76:7::2 and ip6[6] = 58 and (ip6[40] = 128 or ip6[40] = 129) and (ip6[44:2] = 47602 or ip6[44:2] = 47604))'
pids=()
cleanup() {
    local rc=$?
    trap - EXIT
    for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || :; wait "$pid" 2>/dev/null || :; done
    printf 'exit=%s\n' "$rc" > "$out/status"
    (cd "$out"; sha256sum ./*.txt ./*.pcapng status > SHA256SUMS; sha256sum -c SHA256SUMS) || rc=1
    echo "PEER_RUN_DIR=$out"
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
for name in direct switch; do
    dev=${!name}
    dumpcap -q -p -i "$dev" -f "$filter" -s 80 -a duration:180 -w "$out/$name.pcapng" > "$out/$name-capture.txt" 2>&1 &
    pids+=("$!")
done
for _ in {1..40}; do
    for pid in "${pids[@]}"; do kill -0 "$pid"; done
    if [[ -s $out/direct.pcapng && -s $out/switch.pcapng ]]; then break; fi
    sleep .1
done
[[ -s $out/direct.pcapng && -s $out/switch.pcapng ]]
date -Is > "$out/ready.txt"
echo PEER_CAPTURE_READY
for pid in "${pids[@]}"; do wait "$pid"; done
pids=()
state > "$out/router-after.txt"
[[ $(sed -n '1,2p;4,6p' "$out/router-after.txt") == "$(sed -n '1,2p;4,6p' "$out/router-before.txt")" ]]
for name in direct switch; do
    tshark -n -r "$out/$name.pcapng" -T fields -E separator=, -E occurrence=f \
        -e frame.time_epoch -e ip.src -e ip.dst -e ipv6.src -e ipv6.dst \
        -e icmp.type -e icmp.ident -e icmp.seq \
        -e icmpv6.type -e icmpv6.echo.identifier -e icmpv6.echo.sequence_number \
        > "$out/$name-echo.txt" 2> "$out/$name-tshark.txt"
done
echo PEER_CAPTURE_COMPLETE
