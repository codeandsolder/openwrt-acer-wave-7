#!/usr/bin/env bash
# Off-router, unprivileged packet headers on the Asus wired lab endpoint.
set -Eeuo pipefail
[[ $# == 2 && $1 =~ ^0498-[0-9]{8}-[0-9]{6}$ &&
   $2 =~ ^[0-9]{2,3}$ && $2 -ge 40 && $2 -le 180 &&
   $(id -un) == jan ]] || exit 2
tag=$1
seconds=$2
iface=enp4s0f4u2u4
base=/home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8/client-validation
out="$base/$tag-asus-wire"
[[ ! -e $out &&
   $(ip -4 -o addr show "$iface") == *"192.168.76.2/24"* &&
   $(systemctl is-active wave7-lab-upstream-guard8.service) == active ]]
mkdir -m 700 "$out"
capture_pid=''
cleanup() {
    local rc=$?
    trap - EXIT
    if [[ -n $capture_pid ]]; then
        # Catch premature parent termination without abandoning dumpcap.
        kill -TERM "$capture_pid" 2>/dev/null || :
        wait "$capture_pid" 2>/dev/null || :
    fi
    printf 'exit=%s\n' "$rc" > "$out/status"
    (
        cd "$out"
        : > SHA256SUMS
        for file in metadata.txt ready.txt dumpcap-stdout.txt \
                    dumpcap-stderr.txt icmp.pcapng packets.csv \
                    tshark-stderr.txt status; do
            if [[ -f $file ]]; then sha256sum "$file" >> SHA256SUMS; fi
        done
        sha256sum -c SHA256SUMS
    )
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP
printf 'capture_start_epoch=%s\niface=%s\nfilter=%s\n' \
    "$(date +%s.%N)" "$iface" \
    'icmp and host 192.168.76.145 and host 192.168.76.2' \
    > "$out/metadata.txt"
# The BPF is applied before packet bytes are copied. Snaplen includes
# only Ethernet/IP/ICMP headers; no unrelated lab traffic or payload.
dumpcap -q -i "$iface" \
    -f 'icmp and host 192.168.76.145 and host 192.168.76.2' \
    -s 96 -a "duration:$seconds" -w "$out/icmp.pcapng" \
    > "$out/dumpcap-stdout.txt" 2> "$out/dumpcap-stderr.txt" &
capture_pid=$!
ready=0
for ((i=0; i<100; i++)); do
    if [[ -f $out/icmp.pcapng && $(stat -c %s "$out/icmp.pcapng") -ge 24 ]] &&
       kill -0 "$capture_pid" 2>/dev/null; then
        ready=1
        break
    fi
    kill -0 "$capture_pid"
    sleep .1
done
(( ready ))
printf 'READY epoch=%s capture_pid=%d\n' "$(date +%s.%N)" "$capture_pid" \
    > "$out/ready.txt"
wait "$capture_pid"
capture_pid=''
printf 'capture_end_epoch=%s\n' "$(date +%s.%N)" >> "$out/metadata.txt"
# Decode only the timestamp, endpoint and echo tuple necessary to
# match independent client ping sequence numbers and reply direction.
tshark -n -r "$out/icmp.pcapng" -T fields -E separator=, \
    -e frame.time_epoch -e ip.src -e ip.dst -e icmp.type \
    -e icmp.ident -e icmp.seq -e frame.len \
    > "$out/packets.csv" 2> "$out/tshark-stderr.txt"
printf 'PACKETS=%s\n' "$(wc -l < "$out/packets.csv")"
