#!/usr/bin/env bash
# Independent Wyse MT7925 client, temporary cloned profile only.
set -Eeuo pipefail
umask 077
iface=wlp2s0
profile=Wave7-MLO-Lab
base=/home/jan/firmware/wave7/client-validation
[[ $(id -un) == jan && $# == 1 && $1 =~ ^0498-[0-9]{8}-[0-9]{6}$ ]] || exit 2
tag=$1
out="$base/$tag"
tmp=Wave7-test-$tag
[[ ! -e $out ]]
ip -4 route get 10.1.0.2 | grep -Fq 'dev eno1 '
[[ $(nmcli -g GENERAL.STATE device show "$iface") == '30 (disconnected)' ]]
[[ $(nmcli -g connection.autoconnect connection show "$profile") == no ]]
! nmcli -g NAME connection show | grep -Fxq "$tmp"
mkdir -p "$base"
mkdir -m 700 "$out"
# Commands requiring root, preserving unprivileged ownership of evidence.
rootcmd() { sudo -n "$@"; }
clone=0
event_pid=''
sample_pid=''
pings=()
cleanup() {
    local rc=$?
    trap - EXIT
    for pid in "${pings[@]}"; do kill "$pid" 2>/dev/null || :; wait "$pid" 2>/dev/null || :; done
    if [[ -n $sample_pid ]]; then kill "$sample_pid" 2>/dev/null || :; wait "$sample_pid" 2>/dev/null || :; fi
    if (( clone )); then
        rootcmd nmcli connection delete "$tmp" > "$out/cleanup.txt" 2>&1 || rc=1
    fi
    sleep 1
    if [[ -n $event_pid ]]; then kill "$event_pid" 2>/dev/null || :; wait "$event_pid" 2>/dev/null || :; fi
    {
        nmcli -g GENERAL.STATE device show "$iface"
        nmcli -g connection.autoconnect connection show "$profile"
        ip -4 route get 10.1.0.2
        ip -4 route show default
        ip -6 route show default
    } > "$out/after-cleanup.txt"
    if [[ $(nmcli -g connection.autoconnect connection show "$profile") != no ||
          $(nmcli -g GENERAL.STATE device show "$iface") != '30 (disconnected)' ]] ||
        nmcli -g NAME connection show | grep -Fxq "$tmp"; then rc=1; fi
    printf 'exit=%s\n' "$rc" > "$out/status"
    (cd "$out"; sha256sum ./*.txt status > SHA256SUMS; sha256sum -c SHA256SUMS)
    echo "CLIENT_RUN_DIR=$out"
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
stdbuf -oL iw event -t > "$out/events.txt" 2>&1 &
event_pid=$!
sleep .3
kill -0 "$event_pid"
rootcmd nmcli connection clone "$profile" "$tmp" > "$out/clone.txt"
clone=1
rootcmd nmcli connection modify "$tmp" connection.autoconnect no ipv4.never-default yes ipv4.ignore-auto-dns yes ipv6.never-default yes ipv6.ignore-auto-dns yes ipv4.may-fail no ipv6.may-fail no ipv4.method auto ipv6.method auto
rootcmd nmcli --wait 40 connection up "$tmp" ifname "$iface" > "$out/association.txt" 2>&1
ip -br addr show dev "$iface" > "$out/addresses-at-activation.txt"
v4=$(ip -4 -o addr show dev "$iface" | awk '$3=="inet" && $4 ~ /^192[.]168[.]76[.]/ {split($4,parts,"/"); print parts[1]; exit}')
v6=$(ip -6 -o addr show dev "$iface" | awk '$3=="inet6" && $4 ~ /^fd76:7:/ && $0 !~ /tentative|dadfailed/ {split($4,parts,"/"); print parts[1]; exit}')
[[ -n $v4 && -n $v6 ]]
routes() {
    ip -4 route get 192.168.76.2 from "$v4" oif "$iface"
    ip -6 route get fd76:7::2 from "$v6" oif "$iface"
    ip -4 route get 10.1.0.2
    ip -4 route show default
    ip -6 route show default
}
validate_routes() {
    ip -4 route get 192.168.76.2 from "$v4" oif "$iface" | grep -Fq "dev $iface " &&
    ip -6 route get fd76:7::2 from "$v6" oif "$iface" | grep -Fq "dev $iface " &&
    ip -4 route get 10.1.0.2 | grep -Fq 'dev eno1 ' &&
    ! ip -4 route show default | grep -Fq "dev $iface " &&
    ! ip -6 route show default | grep -Fq "dev $iface "
}
check_link() {
    local link
    link=$(iw dev "$iface" link)
    printf '%s\n' "$link"
    grep -Fq 'SSID: Wave7-MLO-Lab' <<< "$link" &&
      grep -Eq 'Link 0 BSSID ' <<< "$link" &&
      grep -Eq 'Link 1 BSSID ' <<< "$link"
}
probe() {
    local name=$1 count=$2 ip=$3 target=$4 family=$5 rc=0
    LC_ALL=C ping "$family" -n -D -O -I "$iface" -I "$ip" -c "$count" -i .25 -W 1 "$target" > "$out/$name.txt" 2>&1 || rc=$?
    [[ $rc == 0 ]] && grep -Eq "^$count packets transmitted, $count received, (\\+0 duplicates, )?0% packet loss," "$out/$name.txt"
}
failed=0
routes > "$out/routes-before.txt"
validate_routes || exit 3
check_link > "$out/link-before.txt" || exit 3
rootcmd iw dev "$iface" station dump > "$out/stations-before.txt"
date -Is > "$out/immediate-start.txt"
probe immediate-v4 20 "$v4" 192.168.76.2 -4 || failed=1
probe immediate-v6 20 "$v6" fd76:7::2 -6 || failed=1
sleep 15
validate_routes || exit 3
check_link > "$out/link-settled.txt" || exit 3
date -Is > "$out/steady-start.txt"
(
    for ((i=0;i<18;i++)); do
        date -Is
        check_link || echo MLO_LINK_LOST
        rootcmd iw dev "$iface" station dump
        sleep 5
    done
) > "$out/stations-during.txt" 2>&1 &
sample_pid=$!
probe steady-v4 300 "$v4" 192.168.76.2 -4 &
pings+=("$!")
probe steady-v6 300 "$v6" fd76:7::2 -6 &
pings+=("$!")
for pid in "${pings[@]}"; do wait "$pid" || failed=1; done
pings=()
kill "$sample_pid" 2>/dev/null || :
wait "$sample_pid" 2>/dev/null || :
sample_pid=''
routes > "$out/routes-after.txt"
validate_routes || failed=1
check_link > "$out/link-after.txt" || failed=1
rootcmd iw dev "$iface" station dump > "$out/stations-after.txt"
! grep -q MLO_LINK_LOST "$out/stations-during.txt" || failed=1
for name in immediate-v4 immediate-v6 steady-v4 steady-v6; do
    echo "$name"
    grep -E 'packets transmitted|rtt min/avg/max' "$out/$name.txt" || :
done
(( failed == 0 )) || { echo WAVE7_CLIENT_LOSS; exit 1; }
echo WAVE7_CLIENT_SUSTAINED_PASS
