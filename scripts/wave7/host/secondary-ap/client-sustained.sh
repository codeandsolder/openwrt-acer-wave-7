#!/usr/bin/env bash
# Independent Wyse MT7925 client, temporary cloned profile only.
set -Eeuo pipefail
umask 077
iface=wlp2s0
profile=Wave7-MLO-Lab
base=/home/jan/firmware/wave7/client-validation

# A subscriber can attach during an already-running scan; its first event
# may be a completion. Determine current state from the last transition,
# never from equality of cumulative starts and completions. Read one
# snapshot to avoid comparing counts collected on opposite sides of an event.
scan_event_state() {
    awk -v iface="$iface" '
        index($0, ": " iface " (phy #") == 0 { next }
        /: scan started$/ { active = 1 }
        /: scan (finished|aborted)(:|$)/ { active = 0; completed++ }
        END { print active + 0, completed + 0 }
    ' "$1"
}

lab_ipv4_from_ip() {
    # Only the bounded, isolated lab prefix is eligible for probing.
    awk '$3=="inet" && $4 ~ /^192[.]168[.]76[.]/ {
        split($4, octets, "/")
        print octets[1]
        exit
    }'
}

if [[ $# == 1 && $1 == --selftest-early-ipv4 ]]; then
    [[ $(printf '%s\n' \
        '5: wlp2s0 inet 10.1.0.221/24 scope global wlp2s0' \
        '5: wlp2s0 inet 192.168.76.145/24 scope global dynamic wlp2s0' |
        lab_ipv4_from_ip) == 192.168.76.145 ]]
    [[ -z $(printf '%s\n' \
        '5: wlp2s0 inet 192.168.77.145/24 scope global dynamic wlp2s0' |
        lab_ipv4_from_ip) ]]
    echo EARLY_IPV4_SELFTEST_PASS
    exit 0
fi

if [[ $# == 1 && $1 == --selftest-scan-state ]]; then
    [[ $(scan_event_state - </dev/null) == "0 0" ]]
    [[ $(printf '%s\n' '1: wlp2s0 (phy #1): scan aborted: 2412' |
        scan_event_state -) == "0 1" ]]
    [[ $(printf '%s\n' '1: wlp2s0 (phy #1): scan aborted: 2412' \
        '2: wlp2s0 (phy #1): scan started' |
        scan_event_state -) == "1 1" ]]
    [[ $(printf '%s\n' '1: wlp2s0 (phy #1): scan aborted: 2412' \
        '2: wlp2s0 (phy #1): scan started' \
        '3: wlan9 (phy #0): scan finished: 5180' \
        '4: wlp2s0 (phy #1): scan finished: 2412' |
        scan_event_state -) == "0 2" ]]
    [[ $(printf '%s\n' '1: wlp2s0 (phy #1): scan started' \
        '2: wlp2s0 (phy #1): scan started' \
        '3: wlp2s0 (phy #1): scan finished: 2412' |
        scan_event_state -) == "0 1" ]]
    echo SCAN_EVENT_STATE_SELFTEST_PASS
    exit 0
fi

[[ $(id -un) == jan && ( $# == 1 || ( $# == 2 && -n $2 ) ||
   ( $# == 3 && ( $2 == --scan-timing-upstream-* || $2 == --early-only-upstream-* ) && ( $3 == --primary-24 || $3 == --bssid-24 || $3 == --bssid-5 ) ) ) &&
   $1 =~ ^0498-[0-9]{8}-[0-9]{6}$ ]] || exit 2
association_preference=${3:-}
stack_guard=/home/jan/scripts/wave7/client-validation/client-module-stack.sh
trace=0
scope_experiment=0
mode_experiment=0
timing_experiment=0
nosplit_experiment=0
trace_window=0
metadata_experiment=0
absence_experiment=0
binding_experiment=0
quota_experiment=0
rx_experiment=0
rocwire_experiment=0
roccontract_experiment=0
rocgeometry_experiment=0
upstream_stack_variant=''
early_only=0
pm_experiment=0
deep_expected=1
runtime_expected=1
case "${2:-}" in
    --trace) trace=1 ;;
    --scan-scope) scope_experiment=1; pm_experiment=1 ;;
    --scan-mode) scope_experiment=1; mode_experiment=1; pm_experiment=1 ;;
    --scan-timing) scope_experiment=1; mode_experiment=1; timing_experiment=1; pm_experiment=1 ;;
    --scan-timing-nosplit) scope_experiment=1; mode_experiment=1; timing_experiment=1; nosplit_experiment=1; pm_experiment=1 ;;
    --scan-timing-trace) scope_experiment=1; mode_experiment=1; timing_experiment=1; trace_window=1; pm_experiment=1 ;;
    --scan-timing-metadata) scope_experiment=1; mode_experiment=1; timing_experiment=1; trace_window=1; metadata_experiment=1; pm_experiment=1 ;;
    --scan-timing-absence) scope_experiment=1; mode_experiment=1; timing_experiment=1; trace_window=1; absence_experiment=1; pm_experiment=1 ;;
    --scan-timing-binding) scope_experiment=1; mode_experiment=1; timing_experiment=1; trace_window=1; binding_experiment=1; pm_experiment=1 ;;
    --scan-timing-quota) scope_experiment=1; mode_experiment=1; timing_experiment=1; trace_window=1; quota_experiment=1; pm_experiment=1 ;;
    --scan-timing-rx) scope_experiment=1; mode_experiment=1; timing_experiment=1; trace_window=1; rx_experiment=1; pm_experiment=1 ;;
    --scan-timing-rocwire) scope_experiment=1; mode_experiment=1; timing_experiment=1; trace_window=1; rocwire_experiment=1; pm_experiment=1 ;;
    --scan-timing-roccontract) scope_experiment=1; mode_experiment=1; timing_experiment=1; trace_window=1; roccontract_experiment=1; pm_experiment=1 ;;
    --scan-timing-rocgeometry) scope_experiment=1; mode_experiment=1; timing_experiment=1; trace_window=1; rocgeometry_experiment=1; pm_experiment=1 ;;
    --scan-timing-upstream-*|--early-only-upstream-*)
        if [[ $2 == --early-only-upstream-* ]]; then
            early_only=1
            upstream_stack_variant=${2#--early-only-}
        else
            upstream_stack_variant=${2#--scan-timing-}
        fi
        upstream_trace_profile=$(bash "$stack_guard" "$upstream_stack_variant" --trace-profile) || exit 2
        if [[ -n $association_preference ]]; then
            # Require firmware association evidence to identify the setup link.
            [[ $upstream_trace_profile == association* ]] || exit 2
        fi
        case "$upstream_trace_profile" in
            none) ;;
            admission|association|association-rx|association-rxtx|association-membership|association-dev-band|association-beacon-power)
                trace_window=1 ;;
            *) exit 2 ;;
        esac
        scope_experiment=1; mode_experiment=1; timing_experiment=1; pm_experiment=1
        if (( early_only )); then
            # Independent wired crash stream records this short diagnostic.
            # Avoid waiting for the full-duration internal trace/scan matrix.
            trace_window=0
            scope_experiment=0
        fi ;;
    --deep-sleep-on) pm_experiment=1 ;;
    --deep-sleep-off) pm_experiment=1; deep_expected=0 ;;
    --runtime-pm-off) pm_experiment=1; runtime_expected=0 ;;
    "") ;;
    *) exit 2 ;;
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
if nmcli -g NAME connection show | grep -Fxq "$tmp"; then exit 1; fi
mkdir -p "$base"
mkdir -m 700 "$out"
# Commands requiring root, preserving unprivileged ownership of evidence.
rootcmd() { sudo -n "$@"; }
phy=$(basename "$(readlink -f "/sys/class/net/$iface/phy80211")")
[[ $phy =~ ^phy[0-9]+$ ]]
pm_dir=/sys/kernel/debug/ieee80211/$phy/mt76
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
scope_pid=''
trace_pid=''
early_pid=''
neigh_pid=''
pings=()
ping_names=()
ping_counts=()

# Start before NetworkManager connects, so ARP and ICMP are sampled at the
# moment the first lab IPv4 address appears, not after nmcli has waited for
# the complete IPv6/DAD activation. This is additional evidence only:
# the existing all-packets-delivered gate is unchanged.
early_ipv4_probe() (
    local ipaddr='' i target label pid
    local -a children=()

    # The observer runs as a distinct subshell with its own traps. If
    # the parent is interrupted, forward TERM to every child and reap
    # them before the parent can checksum evidence files.
    # shellcheck disable=SC2329 # called indirectly from signal trap
    stop_children() {
        local pid
        trap - TERM INT HUP
        # GNU timeout creates a process group containing the actual
        # child. Signal the entire group and reap before checksumming.
        for pid in "${children[@]}"; do
            kill -TERM -- "-$pid" 2>/dev/null ||
                kill -TERM "$pid" 2>/dev/null || :
        done
        for pid in "${children[@]}"; do wait "$pid" 2>/dev/null || :; done
        exit 143
    }
    trap stop_children TERM INT HUP

    printf 'watch_started_epoch=%s\n' "$(date +%s.%N)"
    for ((i=0; i<820; i++)); do
        ipaddr=$(ip -4 -o addr show dev "$iface" | lab_ipv4_from_ip)
        if [[ -n $ipaddr ]]; then break; fi
        sleep .05
    done
    if [[ -z $ipaddr ]]; then
        echo EARLY_IPV4_NO_ADDRESS
        return 0
    fi

    printf 'address_seen_epoch=%s address=%s\n' "$(date +%s.%N)" "$ipaddr"
    # The lease can appear before NetworkManager installs its connected
    # route. Preserve this distinction rather than calling ENETUNREACH
    # a wireless datapath failure.
    ip -4 route get 192.168.76.1 from "$ipaddr" oif "$iface" ||
        echo EARLY_IPV4_ROUTE_NOT_READY
    ip -s neigh show dev "$iface" || :
    for label in ap asus; do
        case $label in
            ap) target=192.168.76.1 ;;
            asus) target=192.168.76.2 ;;
        esac
        printf 'probe_started_epoch=%s target=%s source=%s\n' \
            "$(date +%s.%N)" "$target" "$ipaddr" > "$out/early-$label-arp.txt"
        LC_ALL=C timeout --signal=TERM --kill-after=2s 4s \
            sudo -n arping -f -I "$iface" -s "$ipaddr" -c 2 -w 2 "$target" \
            >> "$out/early-$label-arp.txt" 2>&1 &
        children+=("$!")
        printf 'probe_started_epoch=%s target=%s source=%s\n' \
            "$(date +%s.%N)" "$target" "$ipaddr" > "$out/early-$label-icmp.txt"
        LC_ALL=C timeout --signal=TERM --kill-after=2s 8s \
            ping -4 -n -D -O -I "$iface" -I "$ipaddr" \
            -c 32 -i .05 -W 1 "$target" \
            >> "$out/early-$label-icmp.txt" 2>&1 &
        children+=("$!")
    done
    for pid in "${children[@]}"; do wait "$pid" || :; done
    trap - TERM INT HUP
    printf 'window_finished_epoch=%s\n' "$(date +%s.%N)"
    ip -s neigh show dev "$iface" || :
)
probe_start() {
    local name=$1 count=$2 ip=$3 target=$4 family=$5 interval=.25
    local interval_ms budget_s
    local -a id_args=()

    if (( timing_experiment )) &&
       [[ $name == steady-* || $name == short-hold-* ]]; then
        interval=.05
    fi
    if (( trace )); then
        case "$name" in
            immediate-v4) id_args=(-e 47601) ;;
            immediate-v6) id_args=(-e 47602) ;;
            steady-v4) id_args=(-e 47603) ;;
            steady-v6) id_args=(-e 47604) ;;
            *) return 2 ;;
        esac
    fi
    # Bound a lost-packet -O test to cadence + recovery margin.
    case $interval in
        .05) interval_ms=50 ;;
        .25) interval_ms=250 ;;
        *) return 2 ;;
    esac
    budget_s=$(((count * interval_ms + 999) / 1000 + 25))
    # Track timeout itself, not an outer subshell that can exit while
    # ping remains alive. GNU timeout establishes its own process group.
    LC_ALL=C timeout --signal=TERM --kill-after=2s "${budget_s}s" \
        ping "${id_args[@]}" "$family" -n -D -O -I "$iface" -I "$ip" \
        -c "$count" -i "$interval" -W 1 "$target" \
        > "$out/$name.txt" 2>&1 &
    pings+=("$!")
    ping_names+=("$name")
    ping_counts+=("$count")
}

probe_wait_one() {
    local index=$1
    local pid=${pings[$index]} name=${ping_names[$index]}
    local count=${ping_counts[$index]} rc=0

    wait "$pid" || rc=$?
    unset "pings[$index]" "ping_names[$index]" "ping_counts[$index]"
    [[ $rc == 0 ]] &&
        grep -Eq "^$count packets transmitted, $count received, (\\+0 duplicates, )?0% packet loss," "$out/$name.txt"
}

probe() {
    local index=${#pings[@]}

    probe_start "$@" || return
    probe_wait_one "$index"
}

cleanup() {
    local rc=$?
    trap - EXIT
    # Every active PID is GNU timeout's process-group leader.
    # Reap all group members before closing the checksum manifest.
    for pid in "${pings[@]}"; do
        kill -TERM -- "-$pid" 2>/dev/null ||
            kill -TERM "$pid" 2>/dev/null || :
    done
    for pid in "${pings[@]}"; do wait "$pid" 2>/dev/null || :; done
    pings=()
    ping_names=()
    ping_counts=()
    if [[ -n $early_pid ]]; then
        # In the failure path, bound the address watcher independently of
        # NetworkManager. Once IPv4 is seen, early probes run at most 8s.
        if [[ -f $out/early-probe-status.txt ]] &&
           grep -q '^address_seen_epoch=' "$out/early-probe-status.txt"; then
            # A detected IPv4 starts at most three seconds of probes.
            # Wait for all packet logs before checksumming the evidence.
            wait "$early_pid" 2>/dev/null || :
        else
            kill "$early_pid" 2>/dev/null || :
            wait "$early_pid" 2>/dev/null || :
        fi
        early_pid=''
    fi
    if [[ -n $neigh_pid ]]; then
        kill "$neigh_pid" 2>/dev/null || :
        wait "$neigh_pid" 2>/dev/null || :
        neigh_pid=''
    fi
    if [[ -n $scope_pid ]]; then kill "$scope_pid" 2>/dev/null || :; wait "$scope_pid" 2>/dev/null || :; fi
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
    if (( nosplit_experiment )) && [[ -f $out/nosplit-start-epoch.txt ]]; then
        journalctl -k -b --no-pager -o short-unix --since "@$(cat "$out/nosplit-start-epoch.txt")" |
          grep -F 'wave7-diag: no-split scan' > "$out/nosplit-markers.txt" || rc=1
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
    if [[ -n $trace_pid ]]; then
        wait "$trace_pid" || rc=1
        grep -Fxq 'TRACE_CLEANUP rc=0' "$out/client-kernel-trace.txt" || rc=1
    fi
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
    expected_srcversion=DB4C3E1671DC2EA009803A0
    if (( nosplit_experiment )); then
        expected_srcversion=1FB10711FECFBF21CC8F072
        [[ $(sha256sum "$(modinfo -n mt7925_common)" | cut -d' ' -f1) == bc4b790c90f196eb063b0d9605e3569d137069791fec9d192720962ffbf3c384 ]]
    fi
    if (( metadata_experiment )); then
        expected_srcversion=5505CE551C04266721B047A
        [[ $(sha256sum "$(modinfo -n mt7925_common)" | cut -d' ' -f1) == e423dd7b34d8e038b7b1a229ae1f9d7af08a27ce7370ea55ad09540175e274b0 ]]
    fi
    if [[ -n $upstream_stack_variant ]]; then
        [[ -f $stack_guard ]]
        bash "$stack_guard" "$upstream_stack_variant" --check-candidate > "$out/module-stack.txt"
        expected_srcversion=$(awk '/^mt7925_common srcversion=/ {sub(/srcversion=/,"",$2); print $2}' "$out/module-stack.txt")
        [[ $expected_srcversion =~ ^[0-9A-F]+$ ]]
    fi
    if (( quota_experiment )); then
        [[ -f $stack_guard ]]
        bash "$stack_guard" quota --check-candidate > "$out/module-stack.txt"
        expected_srcversion=E882C202FF34ABD6AFFEC2C
    fi
    if (( rocgeometry_experiment )); then
        expected_srcversion=C9E49C46E5D078C60790F76
        [[ $(sha256sum "$(modinfo -n mt7925_common)" | cut -d' ' -f1) == 3dc72a52e857e4eb6f103affd04b6df70a443ad532d36a71628c406b10956432 ]]
    fi
    if (( roccontract_experiment )); then
        expected_srcversion=4612169F0B6A0C2D484A758
        [[ $(sha256sum "$(modinfo -n mt7925_common)" | cut -d' ' -f1) == 1c50861dd4a5d390d942e45f78afc30a47bd616b9929e05f550c6a76c4c5d7f8 ]]
    fi
    if (( rocwire_experiment )); then
        expected_srcversion=9527AD69B79607CB0ABD540
        [[ $(sha256sum "$(modinfo -n mt7925_common)" | cut -d' ' -f1) == 50f1fd1cee84ceba1ba62abad2f04ed6d18803bc09fd395c266271297344d2f4 ]]
    fi
    if (( rx_experiment )); then
        expected_srcversion=C8590CC01B6D6AE3EAAC131
        [[ $(sha256sum "$(modinfo -n mt7925_common)" | cut -d' ' -f1) == fa786e5d0d56500d2042eb166a73130db97f1b542f5d0fbd174ff973ee382345 ]]
    fi
    if (( binding_experiment )); then
        expected_srcversion=CF0F5C99109529BD670B11A
        [[ $(sha256sum "$(modinfo -n mt7925_common)" | cut -d' ' -f1) == 0f2468ffc7aeb8ef76eaf63c20c5a405b80d0e61320bf1af28d931014b79f12b ]]
    fi
    if (( absence_experiment )); then
        expected_srcversion=5F394A90BE5C4D0D8C37C46
        [[ $(sha256sum "$(modinfo -n mt7925_common)" | cut -d' ' -f1) == 102037a9fdc2571c48426d70087eaa560a7bacb70ee6967a2aa0aa5f274e7f4f ]]
    fi
    [[ $(uname -r) == 7.4.0-rc1-2-cachyos-rc &&
       $(cat /sys/module/mt7925_common/srcversion) == "$expected_srcversion" &&
       $(cat "/sys/class/net/$iface/device/vendor") == 0x14c3 &&
       $(cat "/sys/class/net/$iface/device/device") == 0x7925 ]]
    iw dev "$iface" info | grep -Eq "^[[:space:]]*wiphy ${phy#phy}$"
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
{
    printf 'boot=%s\nkernel=%s\n' "$(cat /proc/sys/kernel/random/boot_id)" "$(uname -r)"
    printf 'mt7925_common=%s\nmt7925e=%s\n' "$(cat /sys/module/mt7925_common/srcversion)" "$(cat /sys/module/mt7925e/srcversion)"
    printf 'installed_common_file (not the live test override, if active): '
    sha256sum "$(modinfo -n mt7925_common)"
    journalctl -k -b --no-pager | grep -E 'mt7925e.*(HW/SW Version|WM Firmware Version)'
} > "$out/firmware.txt"
if (( nosplit_experiment )); then
    date +%s > "$out/nosplit-start-epoch.txt"
fi
if (( trace_window )); then
    helper=/home/jan/scripts/wave7/client-validation/client-trace-window.sh
    [[ -f $helper ]]
    trace_args=()
    if (( metadata_experiment )); then trace_args+=(--metadata); fi
    if (( absence_experiment )); then trace_args+=(--absence); fi
    if (( binding_experiment )); then trace_args+=(--binding); fi
    if (( quota_experiment )); then trace_args+=(--quota); fi
    if (( rx_experiment )); then trace_args+=(--rx); fi
    if (( rocwire_experiment )); then trace_args+=(--rocwire); fi
    if (( roccontract_experiment )); then trace_args+=(--roccontract); fi
    if (( rocgeometry_experiment )); then trace_args+=(--rocgeometry); fi
    if [[ -n $upstream_stack_variant ]]; then
        trace_args+=("--$upstream_stack_variant")
    fi
    rootcmd bash "$helper" "$tag" "${trace_args[@]}" > "$out/client-kernel-trace.txt" 2>&1 &
    trace_pid=$!
    ready=0
    for _ in {1..240}; do
        kill -0 "$trace_pid"
        if grep -Fxq TRACE_READY "$out/client-kernel-trace.txt"; then ready=1; break; fi
        sleep .25
    done
    (( ready ))
fi
stdbuf -oL iw event -t > "$out/events.txt" 2>&1 &
event_pid=$!
sleep .3
kill -0 "$event_pid"
rootcmd nmcli connection clone --temporary "$profile" "$tmp" > "$out/clone.txt"
clone=1
rootcmd nmcli connection modify --temporary "$tmp" connection.autoconnect no ipv4.never-default yes ipv4.ignore-auto-dns yes ipv6.never-default yes ipv6.ignore-auto-dns yes ipv4.may-fail no ipv6.may-fail no ipv4.method auto ipv6.method auto
if [[ $association_preference == --primary-24 ]]; then
    # Restrict only the disposable clone to the known lab channel. This
    # may affect background scan scope, so do not compare scan latency
    # directly with the unconstrained profile.
    rootcmd nmcli connection modify --temporary "$tmp" 802-11-wireless.band bg 802-11-wireless.channel 1
    nmcli -g 802-11-wireless.band,802-11-wireless.channel connection show "$tmp" > "$out/association-preference.txt"
elif [[ $association_preference == --bssid-24 ]]; then
    # Pin the observed laboratory link-0 BSSID without removing 5 GHz
    # from the candidate frequencies. Firmware trace determines the
    # actual association link; this setting is not proof of role reversal.
    rootcmd nmcli connection modify --temporary "$tmp" 802-11-wireless.bssid 70:5A:6F:5A:BB:16
    nmcli -g 802-11-wireless.bssid,802-11-wireless.band,802-11-wireless.channel connection show "$tmp" > "$out/association-preference.txt"
elif [[ $association_preference == --bssid-5 ]]; then
    # Dedicated 5GHz-primary, BSSID-locked discriminator for wpa_supplicant
    # bgscan; pin only the transient test clone and still require firmware
    # evidence of both negotiated/active MLO links. NetworkManager's
    # supplicant integration disables bgscan for a fixed BSSID.
    rootcmd nmcli connection modify --temporary "$tmp" 802-11-wireless.bssid 4E:5A:6F:5A:BB:16
    nmcli -g 802-11-wireless.bssid,802-11-wireless.band,802-11-wireless.channel connection show "$tmp" > "$out/association-preference.txt"
fi
# Preserve pre-association evidence even if the client hard-locks.
sync -f "$out"
if (( timing_experiment )); then
    # Kernel neighbour-state transitions, including ARP replies, are
    # captured continuously without querying AP station state.
    ip -ts monitor neigh dev "$iface" > "$out/early-neigh-events.txt" 2>&1 &
    neigh_pid=$!
    early_ipv4_probe > "$out/early-probe-status.txt" 2>&1 &
    early_pid=$!
fi
rootcmd nmcli --wait 40 connection up "$tmp" ifname "$iface" > "$out/association.txt" 2>&1
# Join the independent, bounded early sampling before changing interface or
# scan state. Its results are diagnostic, never a substitute for strict ICMP.
if [[ -n $early_pid ]]; then
    wait "$early_pid" || :
    early_pid=''
fi
ip -br addr show dev "$iface" > "$out/addresses-at-activation.txt"
v4=$(ip -4 -o addr show dev "$iface" | awk '$3=="inet" && $4 ~ /^192[.]168[.]76[.]/ {split($4,parts,"/"); print parts[1]; exit}')
v6=$(ip -6 -o addr show dev "$iface" | awk '$3=="inet6" && $4 ~ /^fd76:7:/ && $0 !~ /tentative|dadfailed/ {split($4,parts,"/"); print parts[1]; exit}')
if (( early_only )); then
    # Compare the first IPv4/ARP exchanges before a possible Q6 SSR.
    # Never label this shortened diagnostic as a production PASS.
    {
        printf 'snapshot_epoch=%s ipv4=%s ipv6=%s\n' "$(date +%s.%N)" "$v4" "$v6"
        ip -4 route get 192.168.76.1 from "$v4" oif "$iface" || :
        ip -s neigh show dev "$iface" || :
        iw dev "$iface" link || :
        path=/sys/kernel/debug/ieee80211/$phy/netdev:$iface
        for mask in active_links valid_links dormant_links; do
            printf 'mac80211_%s=' "$mask"
            rootcmd cat "$path/$mask" || :
        done
    } > "$out/early-only-snapshot.txt" 2>&1
    # Observe beyond the previously measured ~4.7s Q6 fatal window,
    # including both post-association and post-DHCP phases.
    # Do not count this abbreviated run as a production acceptance PASS.
    short_failed=0
    for target in 192.168.76.1 192.168.76.2; do
        probe_start "short-hold-${target##*.}" 440 "$v4" "$target" -4
    done
    for index in "${!pings[@]}"; do
        probe_wait_one "$index" || short_failed=1
    done
    printf 'short_hold_all_replies=%s\n' "$((1 - short_failed))" \
        > "$out/short-hold-result.txt"
    {
        printf 'snapshot_epoch=%s\n' "$(date +%s.%N)"
        ip -4 route get 192.168.76.1 from "$v4" oif "$iface" || :
        ip -s neigh show dev "$iface" || :
        iw dev "$iface" link || :
        path=/sys/kernel/debug/ieee80211/$phy/netdev:$iface
        for mask in active_links valid_links dormant_links; do
            printf 'mac80211_%s=' "$mask"
            rootcmd cat "$path/$mask" || :
        done
    } > "$out/early-only-final.txt" 2>&1
    echo EARLY_IPV4_ONLY_DIAGNOSTIC_COMPLETE
    exit 0
fi
[[ -n $v4 && -n $v6 ]]
routes() {
    if (( mode_experiment )); then
        ip -4 route get 192.168.76.1 from "$v4" oif "$iface"
    fi
    ip -4 route get 192.168.76.2 from "$v4" oif "$iface"
    ip -6 route get fd76:7::2 from "$v6" oif "$iface"
    ip -4 route get 10.1.0.2
    ip -4 route show default
    ip -6 route show default
}
validate_routes() {
    if (( mode_experiment )); then
        ip -4 route get 192.168.76.1 from "$v4" oif "$iface" | grep -Fq "dev $iface " || return 1
    fi
    ip -4 route get 192.168.76.2 from "$v4" oif "$iface" | grep -Fq "dev $iface " &&
    ip -6 route get fd76:7::2 from "$v6" oif "$iface" | grep -Fq "dev $iface " &&
    ip -4 route get 10.1.0.2 | grep -Fq 'dev eno1 ' &&
    ! ip -4 route show default | grep -Fq "dev $iface " &&
    ! ip -6 route show default | grep -Fq "dev $iface "
}
check_link() {
    local link active valid dormant
    local path=/sys/kernel/debug/ieee80211/$phy/netdev:$iface
    link=$(iw dev "$iface" link) || return 1
    printf '%s\n' "$link"
    active=$(rootcmd cat "$path/active_links") || return 1
    valid=$(rootcmd cat "$path/valid_links") || return 1
    dormant=$(rootcmd cat "$path/dormant_links") || return 1
    printf 'link_masks time=%s active=%s valid=%s dormant=%s\n' "$(date +%s.%N)" "$active" "$valid" "$dormant"
    [[ $active =~ ^0x[0-9a-fA-F]+$ && $valid =~ ^0x[0-9a-fA-F]+$ &&
       $dormant =~ ^0x[0-9a-fA-F]+$ ]] || return 1
    # MLSR can legitimately have only one active link. Both links must
    # remain negotiated and the active set must be nonempty and valid.
    (( (valid & 3) == 3 && active && !(active & ~valid) )) &&
      grep -Fq 'SSID: Wave7-MLO-Lab' <<< "$link" &&
      grep -Eq 'Link 0 BSSID ' <<< "$link" &&
      grep -Eq 'Link 1 BSSID ' <<< "$link"
}
# This is a diagnostic, not a relaxation of the zero-loss acceptance gate.
# Request only the dedicated lab SSID; never change the background scan policy.
# Logs contain just the requested frequencies/status and existing iw events.
scan_scope() {
    local label=$1 mode=$2; shift 2
    local -a scan_args
    case "$mode" in
        active) scan_args=(ssid "$profile") ;;
        passive) scan_args=(passive) ;;
        *) return 2 ;;
    esac
    local scanning finished before after rc deadline output attempt=0 returned
    deadline=$((SECONDS+18))
    while :; do
        if (( SECONDS >= deadline )); then
            printf '%s,%s,busy-timeout,%s\n' "$(date +%s.%N)" "$label" "$*"
            return 1
        fi
        read -r scanning finished < <(scan_event_state "$out/events.txt")
        if (( scanning )); then
            sleep .2
            continue
        fi
        # The kernel may start a background scan between the event check
        # and the trigger, or before iw has delivered its start event.
        # Retry EBUSY only, preserving every attempted request separately.
        (( attempt += 1 ))
        before=$(date +%s.%N)
        rc=0
        output=$(rootcmd iw dev "$iface" scan trigger freq "$@" "${scan_args[@]}" </dev/null 2>&1) || rc=$?
        returned=$(date +%s.%N)
        printf '%s,%s,%s,%s,%s,%s\n' "$before" "$returned" "$label" "$attempt" "$rc" "$*" >> "$out/scan-attempts.txt"
        if [[ -n $output ]]; then printf '%s\n' "$output" >&2; fi
        if (( rc != 0 )) && [[ $output == 'command failed: Device or resource busy (-16)' ]]; then
            sleep .2
            continue
        fi
        # The correlation log contains exactly one terminal request per label.
        printf '%s,%s,request,%s\n' "$before" "$label" "$*"
        printf '%s,%s,return=%s,%s\n' "$returned" "$label" "$rc" "$*"
        (( rc == 0 )) || return 1
        break
    done
    deadline=$((SECONDS+20))
    while (( SECONDS < deadline )); do
        read -r scanning after < <(scan_event_state "$out/events.txt")
        (( after > finished )) && break
        sleep .2
    done
    (( after > finished )) || return 1
    # Even after the reported completion, preserve a four-second observation window.
    sleep 4
}
scope_matrix() {
    local round failed=0
    # One collision with an automatic scan does not invalidate later requests.
    # Keep the strict trial failure while preserving the remaining evidence.
    sleep 2
    if (( mode_experiment )); then
        for round in 1 2; do
            scan_scope "active24-$round" active 2412 || failed=1
            scan_scope "passive24-$round" passive 2412 || failed=1
            scan_scope "active5-$round" active 5180 || failed=1
            scan_scope "passive5-$round" passive 5180 || failed=1
        done
        return "$failed"
    fi
    for round in 1 2; do
        scan_scope "home-$round" active 2412 5180 || failed=1
        scan_scope "off24-$round" active 2437 2462 || failed=1
        scan_scope "off5-$round" active 5200 5220 || failed=1
        scan_scope "off6-$round" active 5955 5975 || failed=1
        scan_scope "full-$round" active 2412 2417 2422 2427 2432 2437 2442 2447 2452 2457 2462 2467 2472 5180 5200 5220 5240 5260 5280 5300 5320 5500 5520 5540 5560 5580 5600 5620 5640 5660 5680 5700 5745 5765 5785 5805 5825 5955 5975 5995 6015 6035 6055 6075 6095 6115 6135 6155 6175 6195 6215 6235 6255 6275 6295 6315 6335 6355 6375 6395 6415 || failed=1
    done
    return "$failed"
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
printf 'immediate_interval_s=.25\nsteady_interval_s=%s\n' "$(if (( timing_experiment )); then echo .05; else echo .25; fi)" > "$out/probe-intervals.txt"
steady_count=300
sample_count=18
if (( scope_experiment )); then
    steady_count=600
    if (( timing_experiment )); then
        steady_count=3000
    fi
    sample_count=34
    scope_matrix > "$out/scan-requests.txt" 2> "$out/scan-request-errors.txt" &
    scope_pid=$!
fi
(
    for ((i=0;i<sample_count;i++)); do
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
probe_start steady-v4 "$steady_count" "$v4" 192.168.76.2 -4
probe_start steady-v6 "$steady_count" "$v6" fd76:7::2 -6
if (( mode_experiment )); then
    probe_start steady-ap-v4 "$steady_count" "$v4" 192.168.76.1 -4
fi
for index in "${!pings[@]}"; do probe_wait_one "$index" || failed=1; done
if [[ -n $scope_pid ]]; then
    # Do not let late scan requests outlive the packet test.
    if kill -0 "$scope_pid" 2>/dev/null; then
        kill "$scope_pid" 2>/dev/null || :
        failed=1
    fi
    wait "$scope_pid" || failed=1
    scope_pid=''
fi
kill "$sample_pid" 2>/dev/null || :
wait "$sample_pid" 2>/dev/null || :
sample_pid=''
routes > "$out/routes-after.txt"
validate_routes || failed=1
check_link > "$out/link-after.txt" || failed=1
rootcmd iw dev "$iface" station dump > "$out/stations-after.txt"
! grep -Eq 'MLO_LINK_LOST|PM_POLICY_CHANGED' "$out/stations-during.txt" || failed=1
# A fast disconnect/reconnect between station samples must not pass.
# This evaluates the event stream before our intentional cleanup.
kill -0 "$event_pid" || failed=1
connected=$(rg -c ': connected to ' "$out/events.txt" || :)
disconnected=$(rg -c ': disconnected' "$out/events.txt" || :)
printf 'connected_events=%s\ndisconnected_events=%s\n' "${connected:-0}" "${disconnected:-0}" > "$out/association-continuity.txt"
[[ $connected == 1 && -z $disconnected ]] || failed=1
if (( pm_experiment )); then
    pm_valid || failed=1
    pm_snapshot > "$out/pm-after.txt"
fi
names=(immediate-v4 immediate-v6 steady-v4 steady-v6)
if (( mode_experiment )); then names+=(steady-ap-v4); fi
for name in "${names[@]}"; do
    echo "$name"
    grep -E 'packets transmitted|rtt min/avg/max' "$out/$name.txt" || :
done
(( failed == 0 )) || { echo WAVE7_CLIENT_LOSS; exit 1; }
echo WAVE7_CLIENT_SUSTAINED_PASS
