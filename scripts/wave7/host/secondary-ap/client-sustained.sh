#!/usr/bin/env bash
# Independent Wyse MT7925 client, temporary cloned profile only.
set -Eeuo pipefail
umask 077
iface=wlp2s0
profile=Wave7-MLO-Lab
base=/home/jan/firmware/wave7/client-validation
[[ $(id -un) == jan && ( $# == 1 || ( $# == 2 && ( $2 == --trace || $2 == --deep-sleep-on || $2 == --deep-sleep-off || $2 == --runtime-pm-off ) ) ) && $1 =~ ^0498-[0-9]{8}-[0-9]{6}$ ]] || exit 2
trace=0
pm_experiment=0
deep_expected=1
runtime_expected=1
case "${2:-}" in
    --trace) trace=1 ;;
    --deep-sleep-on) pm_experiment=1 ;;
    --deep-sleep-off) pm_experiment=1; deep_expected=0 ;;
    --runtime-pm-off) pm_experiment=1; runtime_expected=0 ;;
esac
tap=/home/jan/scripts/wave7/client-validation/icmp-probe-tap
if (( trace )); then
    [[ $(sha256sum "$tap" | cut -d' ' -f1) == d1fa6760fef57a219ba3df1255e7ab5a6f78e8038091b24bd7cc8ab5d9a56558 ]]
    "$tap" --selftest
fi
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
pm_dir=/sys/kernel/debug/ieee80211/phy0/mt76
pm_modified=0
runtime_modified=0
pm_snapshot() {
    local f
    printf 'time=%s\n' "$(date -Is)"
    for f in runtime-pm deep-sleep idle-timeout; do
        printf '%s=%s\n' "$f" "$(rootcmd cat "$pm_dir/$f")"
    done
    rootcmd cat "$pm_dir/runtime_pm_stats"
}
pm_valid() {
    [[ $(rootcmd cat "$pm_dir/runtime-pm") == "$runtime_expected" &&
       $(rootcmd cat "$pm_dir/deep-sleep") == "$deep_expected" &&
       $(rootcmd cat "$pm_dir/idle-timeout") == 83 ]] &&
       iw dev "$iface" get power_save | grep -Fxq 'Power save: off'
}
clone=0
event_pid=''
sample_pid=''
tap_pid=''
pings=()
cleanup() {
    local rc=$?
    trap - EXIT
    for pid in "${pings[@]}"; do kill "$pid" 2>/dev/null || :; wait "$pid" 2>/dev/null || :; done
    if [[ -n $sample_pid ]]; then kill "$sample_pid" 2>/dev/null || :; wait "$sample_pid" 2>/dev/null || :; fi
    if [[ -n $tap_pid ]]; then
        # The tap has its own 120-second deadline, even on a failed probe.
        wait "$tap_pid" || rc=1
        grep -Eq '^END parsed=[0-9]+ rejected=0 recv=[0-9]+ dropped=0 ifdrop=0$' "$out/client-tap.txt" || rc=1
    fi
    if (( clone )); then
        rootcmd nmcli connection delete "$tmp" > "$out/cleanup.txt" 2>&1 || rc=1
    fi
    if (( pm_modified )); then
        # Restore only the original requested firmware deep-sleep value.
        printf '1\n' | rootcmd tee "$pm_dir/deep-sleep" > "$out/restore-deep-sleep.txt" || rc=1
    fi
    if (( runtime_modified )); then
        printf '1\n' | rootcmd tee "$pm_dir/runtime-pm" > "$out/restore-runtime-pm.txt" || rc=1
    fi
    if (( pm_experiment )); then
        pm_snapshot > "$out/pm-restored.txt" || rc=1
        [[ $(rootcmd cat "$pm_dir/deep-sleep") == 1 &&
           $(rootcmd cat "$pm_dir/runtime-pm") == 1 ]] || rc=1
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
trap 'exit 129' HUP
if (( pm_experiment )); then
    # Exact test client/module and original controls; never alter active links.
    [[ $(uname -r) == 7.4.0-rc1-2-cachyos-rc &&
       $(cat /sys/module/mt7925_common/srcversion) == DB4C3E1671DC2EA009803A0 &&
       $(cat "/sys/class/net/$iface/device/vendor") == 0x14c3 &&
       $(cat "/sys/class/net/$iface/device/device") == 0x7925 ]]
    iw dev "$iface" info | grep -Eq '^[[:space:]]*wiphy 0$'
    pm_snapshot > "$out/pm-original.txt"
    [[ $(rootcmd cat "$pm_dir/runtime-pm") == 1 &&
       $(rootcmd cat "$pm_dir/deep-sleep") == 1 &&
       $(rootcmd cat "$pm_dir/idle-timeout") == 83 ]]
    if (( deep_expected == 0 )); then
        pm_modified=1
        printf '0\n' | rootcmd tee "$pm_dir/deep-sleep" > "$out/set-deep-sleep.txt"
    fi
    if (( runtime_expected == 0 )); then
        runtime_modified=1
        printf '0\n' | rootcmd tee "$pm_dir/runtime-pm" > "$out/set-runtime-pm.txt"
    fi
    pm_snapshot > "$out/pm-selected.txt"
    [[ $(rootcmd cat "$pm_dir/deep-sleep") == "$deep_expected" &&
       $(rootcmd cat "$pm_dir/runtime-pm") == "$runtime_expected" ]]
fi
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
    local -a id_args=()
    if (( trace )); then
        case "$name" in
            immediate-v4) id_args=(-e 47601) ;;
            immediate-v6) id_args=(-e 47602) ;;
            steady-v4) id_args=(-e 47603) ;;
            steady-v6) id_args=(-e 47604) ;;
            *) return 2 ;;
        esac
    fi
    LC_ALL=C ping "${id_args[@]}" "$family" -n -D -O -I "$iface" -I "$ip" -c "$count" -i .25 -W 1 "$target" > "$out/$name.txt" 2>&1 || rc=$?
    [[ $rc == 0 ]] && grep -Eq "^$count packets transmitted, $count received, (\\+0 duplicates, )?0% packet loss," "$out/$name.txt"
}
failed=0
routes > "$out/routes-before.txt"
validate_routes || exit 3
check_link > "$out/link-before.txt" || exit 3
if (( pm_experiment )); then
    pm_valid || exit 3
    pm_snapshot > "$out/pm-associated.txt"
fi
rootcmd iw dev "$iface" station dump > "$out/stations-before.txt"
if (( trace )); then
    [[ $v4 == 192.168.76.145 && $v6 == fd76:7:* ]]
    rootcmd "$tap" "$iface" 120 > "$out/client-tap.txt" 2> "$out/client-tap-stderr.txt" &
    tap_pid=$!
    for _ in {1..40}; do
        kill -0 "$tap_pid" || exit 3
        grep -q '^READY ' "$out/client-tap.txt" && break
        sleep .05
    done
    grep -q '^READY ' "$out/client-tap.txt"
fi
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
        if (( pm_experiment )); then
            pm_valid || echo PM_POLICY_CHANGED
            pm_snapshot
        fi
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
! grep -Eq 'MLO_LINK_LOST|PM_POLICY_CHANGED' "$out/stations-during.txt" || failed=1
if (( pm_experiment )); then
    pm_valid || failed=1
    pm_snapshot > "$out/pm-after.txt"
fi
for name in immediate-v4 immediate-v6 steady-v4 steady-v6; do
    echo "$name"
    grep -E 'packets transmitted|rtt min/avg/max' "$out/$name.txt" || :
done
(( failed == 0 )) || { echo WAVE7_CLIENT_LOSS; exit 1; }
echo WAVE7_CLIENT_SUSTAINED_PASS
