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
[[ $# -ge 1 && $1 == "$base"/runs/netgear-primary-* ]] || fail 'expected verified trial run'
run=$1
shift
bands=(5 24)
wired_capture=none
ip6_observe=0
dual_hold=0
dual_soak=0
dual_load=0
dual_reconnect=0
reconnect_datapath=0
ap_irq_spread=0
ap_link_stats=0
ap_link_tool=""
client_rx_arg=--none
for arg in "$@"; do
    case "$arg" in
        --band=5) bands=(5) ;;
        --band=24) bands=(24) ;;
        --wired-capture)
            [[ $wired_capture == none ]] || fail 'one wired capture profile'
            wired_capture=icmp ;;
        --wired-ndp)
            [[ $wired_capture == none ]] || fail 'one wired capture profile'
            wired_capture=ndp ;;
        --client-ip6-observe) ip6_observe=1 ;;
        --client-dual-hold) dual_hold=1 ;;
        --client-dual-soak) dual_hold=1; dual_soak=1 ;;
        --client-load) dual_hold=1; dual_load=1 ;;
        --client-reconnect) dual_hold=1; dual_reconnect=1 ;;
        --reconnect-datapath) reconnect_datapath=1 ;;
        --ap-irq-spread) ap_irq_spread=1 ;;
        --ap-link-stats) ap_link_stats=1 ;;
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
        --client-band-primary-immediate-trace) variant=upstream-prefix22-authorize-delayed-links-band-primary-immediate-trace ;;
        --client-group-raw-trace) variant=upstream-prefix22-authorize-delayed-links-group-raw-trace ;;
        --client-mgmt-tx-trace) variant=upstream-prefix22-authorize-delayed-links-mgmt-tx-trace ;;
        --client-mgmt-fixed-link-trace) variant=upstream-prefix22-authorize-delayed-links-mgmt-fixed-link-trace ;;
        --client-mgmt-wmm-trace) variant=upstream-prefix22-authorize-delayed-links-mgmt-wmm-trace ;;
        --client-mgmt-mat-trace) variant=upstream-prefix22-authorize-delayed-links-mgmt-mat-trace ;;
        --client-host-flush-trace) variant=upstream-prefix22-authorize-delayed-links-host-flush-trace ;;
        --client-data-txs-trace) variant=upstream-prefix22-authorize-delayed-links-data-txs-trace ;;
        --client-mgmt-privilege-trace) variant=upstream-prefix22-authorize-delayed-links-mgmt-privilege-trace ;;
        --client-mgmt-privilege-flush-trace) variant=upstream-prefix22-authorize-delayed-links-mgmt-privilege-flush-trace ;;
        *) fail 'invalid argument' ;;
    esac
done
if (( (dual_soak || dual_load || dual_reconnect) && ${#bands[@]} != 1 )); then fail "select one band per extended trial"; fi
if (( dual_soak + dual_load + dual_reconnect > 1 )); then fail "select one extended trial mode"; fi
if (( reconnect_datapath )) && { (( !dual_reconnect )) ||
    [[ $variant != upstream-prefix22-authorize-delayed-links-mgmt-privilege-flush-trace ]]; }; then
    fail "reconnect datapath capture requires the combined privilege/flush reconnect variant"
fi
if (( ap_irq_spread && !dual_load )); then fail "IRQ profile requires isolated TCP load trial"; fi
if (( ap_link_stats && !dual_load )); then fail "link stats require isolated TCP load trial"; fi
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
        $variant == upstream-prefix22-authorize-delayed-links-join-band1-trace ||
        $variant == upstream-prefix22-authorize-delayed-links-band-primary-immediate-trace ||
        $variant == upstream-prefix22-authorize-delayed-links-group-raw-trace ]]; then
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
# Keep a single authenticated Asus->Acer transport for the duration of
# the trial. Each command still uses its own SSH channel and exit status.
# A busy Acer must not require a new TCP handshake for every observer.
ssh_dir=''
ssh_socket=''
open_wyse_transport(){
    local runtime
    runtime="/run/user/$(id -u)"
    [[ -d $runtime && -O $runtime ]] || fail 'missing user runtime directory'
    ssh_dir=$(mktemp -d "$runtime/wave7-ssh.XXXXXXXX")
    ssh_socket="$ssh_dir/control"
    ssh -MNf -S "$ssh_socket" -o ControlPersist=no \
        -o BatchMode=yes -o ConnectTimeout=20 \
        -o ServerAliveInterval=10 -o ServerAliveCountMax=3 acer
    ssh -S "$ssh_socket" -O check acer
}
wyse(){
    ssh -nT -S "$ssh_socket" -o ControlMaster=no \
        -o BatchMode=yes -o ConnectTimeout=20 \
        -o ServerAliveInterval=10 -o ServerAliveCountMax=3 acer \
        "ssh -nT -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=10 -o ServerAliveCountMax=3 wyse-eth $(printf '%q' "$1")"
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
snapshot_load(){
    # Never query station firmware after an SSR. This executes at the
    # edges of each TCP case, not in the saturated packet path.
    remote "set -eu
        [ \"\$(cat /proc/sys/kernel/random/boot_id)\" = '$boot' ]
        for p in 0 1 2; do
            [ \"\$(cat /sys/class/remoteproc/remoteproc\$p/state)\" = running ]
        done
        [ \"\$(dmesg | grep -c 'NOC ERROR DETECTED' || :)\" = 0 ]
        cat /proc/sys/kernel/random/boot_id
        cat /proc/uptime
        echo ==== CPU
        cat /proc/stat
        echo ==== SOFTIRQ
        cat /proc/softirqs
        echo ==== IRQ
        cat /proc/interrupts
        echo ==== STATION
        iw dev ap-mld0 station dump
        if [ '$ap_link_stats' = 1 ]; then
            echo ==== LINK_STATION
            '$ap_link_tool/iw' dev ap-mld0 station dump --links
            echo ==== LINK_DATAPATH
            cat /sys/kernel/debug/ieee80211/phy0/netdev:ap-mld0/link_stats
        fi
        echo ==== AGGREGATION
        for sta in /sys/kernel/debug/ieee80211/phy0/netdev:ap-mld0/stations/*; do
            [ -d \"\$sta\" ] || exit 1
            printf '%s\\n' \"\$sta\"
            cat \"\$sta/agg_status\"
            for link in \"\$sta\"/link-*; do
                [ -d \"\$link\" ] || continue
                echo \"\$link\"
                for f in addr rx_duplicates rx_fragments; do
                    printf '%s=' \"\$f\"
                    cat \"\$link/\$f\"
                done
            done
        done
        echo ==== AFFINITY
        for irq in \$(sed -n 's/^[[:space:]]*\\([0-9][0-9]*\\):.* pci2_wlan_dp_[0-9][0-9]*$/\\1/p' /proc/interrupts); do
            printf '%s ' \"\$irq\"
            cat \"/proc/irq/\$irq/effective_affinity_list\"
        done
        echo ==== CPUFREQ
        for f in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq; do
            printf '%s ' \"\$f\"
            cat \"\$f\"
        done
        echo ==== AQL
        cat /sys/kernel/debug/ieee80211/phy0/aql_pending
        for f in /sys/kernel/debug/ath12k/*/device_dp_stats; do
            echo ==== \"\$f\"
            cat \"\$f\"
        done
        echo ==== END
        cat /proc/sys/kernel/random/boot_id"
}
guard || fail 'router no longer healthy'
systemctl is-active --quiet wave7-lab-upstream-guard8.service || fail 'lab upstream'
active=0
trace_pid=''
sample_pid=''
ap_trace_pid=''
client_control_pid=''
wired_capture_pid=''
ip6_pid=''
load_client_pid=''
ap_irq_pid=''
cleanup(){
    local rc=$?
    trap - EXIT
    if [[ -n $load_client_pid ]]; then
        # The remote session owns bounded listeners and the temporary
        # association; join it before restoring the module closure.
        wait "$load_client_pid" || :
    fi
    if [[ -n $trace_pid ]]; then wait "$trace_pid" || :; fi
    if [[ -n $sample_pid ]]; then wait "$sample_pid" || :; fi
    if [[ -n $ap_trace_pid ]]; then wait "$ap_trace_pid" || :; fi
    if [[ -n $client_control_pid ]]; then wait "$client_control_pid" || :; fi
    if [[ -n $wired_capture_pid ]]; then wait "$wired_capture_pid" || :; fi
    if [[ -n $ip6_pid ]]; then wait "$ip6_pid" || :; fi
    if [[ -n $ap_irq_pid ]]; then wait "$ap_irq_pid" || rc=1; fi
    if [[ -n $ap_link_tool ]]; then
        remote "set -eu; [ \"\$(cat /proc/sys/kernel/random/boot_id)\" = '$boot' ]; rm -f '$ap_link_tool/iw'; rmdir '$ap_link_tool'" || rc=1
    fi
    if (( active )); then
        wyse "sudo -n bash $client/client-module-stack.sh $variant --restore" > "$out/client-restore.txt" 2>&1 || rc=1
    fi
    if [[ -n $ssh_socket ]]; then
        ssh -S "$ssh_socket" -O exit acer > "$out/ssh-control-close.txt" 2>&1 || :
    fi
    if [[ -n $ssh_dir ]]; then
        rmdir "$ssh_dir" || rc=1
    fi
    printf 'exit=%s\n' "$rc" > "$out/status"
    (cd "$out"; find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%P\0' | sort -z | xargs -0 sha256sum > SHA256SUMS)
    printf 'PRIMARY_CLIENT_TEST_DIR=%s\n' "$out"
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
open_wyse_transport > "$out/ssh-control-open.txt" 2>&1
wyse "sudo -n bash $client/client-module-stack.sh $variant --check-original" > "$out/client-original.txt"
remote 'cat /proc/sys/kernel/random/boot_id; dmesg; iw dev ap-mld0 info' > "$out/ap-before.txt"
# A stale authorized MFP station may trigger SA Query on reassociation.
# Record the old station state rather than forcibly deleting it.
remote 'iw dev ap-mld0 station dump' > "$out/ap-stations-before.txt"
if (( dual_soak || dual_load || dual_reconnect )); then
    [[ ! -s $out/ap-stations-before.txt ]] || fail 'extended hold requires an empty AP station table'
fi
if (( ap_link_stats )); then
    tool="$base/analysis/mt7925-mlo-data-20261125/iw-link-stats/iw"
    digest=36d53ae834363dd824975a66d9f3efea53345c040568fc8e381b14b6f2c4a7ca
    [[ $(sha256sum "$tool" | cut -d' ' -f1) == "$digest" ]] || fail 'link stats tool identity'
    ap_link_tool=$(remote 'mktemp -d /tmp/wave7-iw.XXXXXX')
    [[ $ap_link_tool =~ ^/tmp/wave7-iw[.][a-zA-Z0-9]{6}$ ]] || fail 'link stats temporary path'
    remote_stream "set -eu; cat > '$ap_link_tool/iw'; [ \"\$(sha256sum '$ap_link_tool/iw' | cut -d' ' -f1)\" = '$digest' ]; chmod 700 '$ap_link_tool/iw'" < "$tool"
fi
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
observe_seconds=150
client_seconds=75
if (( dual_soak || dual_load || dual_reconnect )); then observe_seconds=300; client_seconds=225; fi
for band in "${bands[@]}"; do
    guard || fail 'AP health before association'
    tag=0498-$(date +%Y%m%d-%H%M%S)
    prefix="$out/band-$band"
    printf '%s\n' "$tag" > "$prefix.tag"
    if (( ap_irq_spread )); then
        remote_stream "sh -s -- $boot 335" < "$(dirname "$helper")/ap-irq-profile.sh" \
            > "$prefix.ap-irq-profile.txt" 2>&1 &
        ap_irq_pid=$!
        deadline=$((SECONDS + 15))
        until [[ -s $prefix.ap-irq-profile.txt ]] && rg -q '^IRQ_PROFILE_READY ' "$prefix.ap-irq-profile.txt"; do
            kill -0 "$ap_irq_pid" 2>/dev/null || fail 'IRQ profile failed'
            (( SECONDS < deadline )) || fail 'IRQ profile readiness timeout'
            sleep .25
        done
    fi
    snapshot_rx > "$prefix.rx-before.txt"
    snapshot_icmp > "$prefix.icmp-before.txt"
    wyse "sudo -n bash $client/client-crash-stream.sh $tag $variant $client_boot $observe_seconds" > "$prefix.client-trace.txt" 2>&1 &
    trace_pid=$!
    (
        for seq in $(seq 1 "$((observe_seconds * 4))"); do
            printf '%s\n' "$seq"
            sleep .25
        done
    ) | remote_stream 'while IFS= read -r seq; do
        printf "%s %s " "$seq" "$(cut -d" " -f1 /proc/uptime)"
        for p in 0 1 2; do printf "%s " "$(cat /sys/class/remoteproc/remoteproc$p/state)"; done
        printf "\n"
    done' > "$prefix.ap-passive.txt" 2>&1 &
    sample_pid=$!
    ap_profile=full
    if (( dual_load || dual_reconnect )); then ap_profile=control; fi
    if (( reconnect_datapath )); then ap_profile=reconnect; fi
    remote_stream "sh -s -- $boot $tag $observe_seconds $ap_profile" < "$helper" > "$prefix.ap-control-trace.txt" 2>&1 &
    ap_trace_pid=$!
    control_profile=$client_rx_arg
    if (( dual_load )); then control_profile=--none; fi
    if [[ $variant == upstream-prefix22-authorize-delayed-links-mgmt-tx-trace ||
          $variant == upstream-prefix22-authorize-delayed-links-mgmt-fixed-link-trace ||
          $variant == upstream-prefix22-authorize-delayed-links-mgmt-wmm-trace ||
          $variant == upstream-prefix22-authorize-delayed-links-mgmt-mat-trace ||
          $variant == upstream-prefix22-authorize-delayed-links-host-flush-trace ||
          $variant == upstream-prefix22-authorize-delayed-links-data-txs-trace ||
          $variant == upstream-prefix22-authorize-delayed-links-mgmt-privilege-trace ||
          $variant == upstream-prefix22-authorize-delayed-links-mgmt-privilege-flush-trace ]]; then
        control_profile=--mgmt-tx
    fi
    if (( reconnect_datapath )); then control_profile=--reconnect-datapath; fi
    if [[ $wired_capture == ndp && $control_profile == --rx-cnm ]]; then
        control_profile=--rx-cnm-group
    fi
    wyse "sudo -n bash $client/client-control-trace.sh $tag $client_boot $control_profile $observe_seconds" > "$prefix.client-control-trace.txt" 2>&1 &
    client_control_pid=$!
    if [[ $wired_capture != none ]]; then
        # Header summaries only, no payload or promiscuous capture.
        # The NDP profile uses the host's existing Wireshark capture-group
        # access; decode only explicitly selected discovery metadata.
        if [[ $wired_capture == ndp ]]; then
            (
                dumpcap -i enp4s0f4u2u4 -p -s 128 \
                    -f 'icmp6 and ip6[40] >= 133 and ip6[40] <= 136' \
                    -i enp4s0f4u2u2u4 -p -s 128 \
                    -f 'icmp6 and ip6[40] >= 133 and ip6[40] <= 136' \
                    -a "duration:$observe_seconds" -w - 2>"$prefix.wired-ndp-status.txt" |
                    tshark -n -l -r - -T fields \
                        -e frame.time_epoch -e eth.src -e eth.dst \
                        -e ipv6.src -e ipv6.dst -e icmpv6.type \
                        -e frame.interface_name -e ipv6.hlim \
                        -e icmpv6.nd.ns.target_address -e icmpv6.nd.na.target_address \
                        -e icmpv6.opt.linkaddr \
                        >"$prefix.wired-ndp.txt" 2>"$prefix.wired-ndp-decode.txt"
            ) &
            capture_ready='^File: -$'
        else
            timeout -s INT "$observe_seconds" sudo -n /usr/bin/tcpdump -p -nn -l -tt -s 96 \
                -i enp4s0f4u2u4 'icmp and host 192.168.76.2 and not host 192.168.76.1' \
                > "$prefix.wired-icmp.txt" 2> "$prefix.wired-icmp-status.txt" &
            capture_ready='listening on enp4s0f4u2u4'
        fi
        wired_capture_pid=$!
    fi
    if (( ip6_observe )); then
        wyse "bash $client/client-ip6-observe.sh $tag $client_boot $observe_seconds" > "$prefix.client-ip6.txt" 2>&1 &
        ip6_pid=$!
    fi
    # Independent starts above may race for a busy host. No association
    # starts until each observer is live and has emitted its marker.
    pids=("$trace_pid" "$sample_pid" "$ap_trace_pid" "$client_control_pid")
    logs=("$prefix.client-trace.txt" "$prefix.ap-passive.txt"
          "$prefix.ap-control-trace.txt" "$prefix.client-control-trace.txt")
    markers=('^CRASH_STREAM_READY ' '^[0-9]+ [0-9.]+ running running running'
             '^AP_CONTROL_TRACE_READY ' '^CLIENT_CONTROL_TRACE_READY ')
    if [[ $wired_capture != none ]]; then
        pids+=("$wired_capture_pid")
        logs+=("$prefix.wired-$wired_capture-status.txt")
        markers+=("$capture_ready")
    fi
    if (( ip6_observe )); then
        pids+=("$ip6_pid")
        logs+=("$prefix.client-ip6.txt")
        markers+=('^CLIENT_IP6_OBSERVER_READY ')
    fi
    deadline=$((SECONDS + 45))
    while :; do
        ready=1
        for i in "${!pids[@]}"; do
            kill -0 "${pids[i]}" 2>/dev/null || fail "observer exited: ${logs[i]}"
            if [[ ! -s ${logs[i]} ]] || ! rg -q "${markers[i]}" "${logs[i]}"; then
                ready=0
            fi
        done
        (( ready )) && break
        (( SECONDS < deadline )) || fail 'observer readiness deadline'
        sleep .25
    done
    printf 'ALL_OBSERVERS_READY epoch=%s\n' "$(date +%s.%N)" > "$prefix.observers-ready.txt"
    mode=early-only
    if (( dual_hold )); then mode=early-dual; fi
    if (( dual_soak )); then mode=early-soak; fi
    if (( dual_load )); then mode=early-load; fi
    if (( dual_reconnect )); then mode=early-reconnect; fi
    rc=0
    if (( dual_load )); then
        # Wyse listens only on its temporary Wi-Fi address. Initiate TCP
        # from the existing Asus direct NIC so no firewall change is needed.
        wyse "timeout $client_seconds bash $client/client-sustained.sh $tag --$mode-$variant --bssid-$band" \
            > "$prefix.client-run.txt" 2>&1 &
        load_client_pid=$!
        target=''
        for direction in uplink downlink bidirectional; do
            deadline=$((SECONDS + 90))
            if [[ -n $target ]]; then deadline=$((SECONDS + 45)); fi
            ready=''
            while (( SECONDS < deadline )); do
                if [[ -f $prefix.client-run.txt ]]; then
                    ready=$(rg -m 1 "^LOAD_READY mode=$direction address=192[.]168[.]76[.][0-9]{1,3}$" "$prefix.client-run.txt" || :)
                fi
                [[ -n $ready ]] && break
                kill -0 "$load_client_pid" 2>/dev/null || break
                sleep .25
            done
            if [[ -z $ready ]]; then cases_failed=1; break; fi
            peer=${ready##*address=}
            if [[ -n $target && $peer != "$target" ]]; then cases_failed=1; break; fi
            target=$peer
            if ! ip -4 route get "$target" from 192.168.76.2 oif enp4s0f4u2u4 \
                > "$prefix.load-$direction-route.txt" ||
                ! rg -q 'dev enp4s0f4u2u4 ' "$prefix.load-$direction-route.txt"; then
                cases_failed=1
                break
            fi
            snapshot_load > "$prefix.load-$direction-ap-before.txt" || { cases_failed=1; break; }
            args=()
            case $direction in
                uplink) args=(-R) ;;
                bidirectional) args=(--bidir) ;;
            esac
            load_rc=0
            timeout --signal=TERM --kill-after=2s 30s iperf3 -4 -c "$target" \
                -B 192.168.76.2 --bind-dev enp4s0f4u2u4 -p 52231 -P 4 -t 15 -O 2 \
                --connect-timeout 4000 -J "${args[@]}" > "$prefix.load-$direction.json" \
                2>"$prefix.load-$direction-errors.txt" || load_rc=$?
            printf '%s\n' "$load_rc" > "$prefix.load-$direction-exit.txt"
            if (( load_rc )); then cases_failed=1; break; fi
            snapshot_load > "$prefix.load-$direction-ap-after.txt" || { cases_failed=1; break; }
        done
        wait "$load_client_pid" || rc=$?
        load_client_pid=''
    else
        wyse "timeout $client_seconds bash $client/client-sustained.sh $tag --$mode-$variant --bssid-$band" > "$prefix.client-run.txt" 2>&1 || rc=$?
    fi
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
    if (( ip6_observe )); then
        wait "$ip6_pid" || cases_failed=1
        ip6_pid=''
        rg -qx "CLIENT_IP6_OBSERVER_END samples=$((observe_seconds + 1))" "$prefix.client-ip6.txt" || cases_failed=1
    fi
    if [[ $wired_capture != none ]]; then
        capture_rc=0
        wait "$wired_capture_pid" || capture_rc=$?
        wired_capture_pid=''
        if [[ $wired_capture == ndp ]]; then
            if [[ $capture_rc != 0 ]] ||
               ! rg -q "Packets received/dropped on interface 'enp4s0f4u2u4': [0-9]+/0 \(pcap:[0-9]+/dumpcap:0/flushed:0/ps_ifdrop:0\)" "$prefix.wired-ndp-status.txt" ||
               ! rg -q "Packets received/dropped on interface 'enp4s0f4u2u2u4': [0-9]+/0 \(pcap:[0-9]+/dumpcap:0/flushed:0/ps_ifdrop:0\)" "$prefix.wired-ndp-status.txt"; then
                cases_failed=1
            fi
        elif [[ $capture_rc != 124 && $capture_rc != 0 ]] ||
             ! rg -qx '0 packets dropped by kernel' "$prefix.wired-icmp-status.txt"; then
            cases_failed=1
        fi
    fi
    wyse "tar -C $client_data -cf - $tag" > "$prefix.client.tar" 2>"$prefix.client-archive-error.txt" || :
    remote 'cat /proc/sys/kernel/random/boot_id; dmesg' > "$prefix.ap-after.txt" 2>&1 || :
    if (( ap_irq_spread )); then
        wait "$ap_irq_pid" || cases_failed=1
        ap_irq_pid=''
        rg -qx 'IRQ_PROFILE_END rc=0' "$prefix.ap-irq-profile.txt" || cases_failed=1
    fi
    if ! guard; then
        echo "AP_FAULT_AFTER_BAND_$band"
        exit 1
    fi
    snapshot_rx > "$prefix.rx-after.txt"
    snapshot_icmp > "$prefix.icmp-after.txt"
    uv run --no-project python -B "$delta_helper" "$prefix.rx-before.txt" "$prefix.rx-after.txt" > "$prefix.rx-delta.json" || cases_failed=1
    result_file=short-hold-result.txt
    expected=short_hold_all_replies=1
    if (( dual_hold )); then
        result_file=short-dual-hold-result.txt
        expected=short_dual_hold_pass=1
    fi
    if (( dual_reconnect )); then
        result_file=reconnect-result.txt
        expected=reconnect_pass=1
    fi
    if (( dual_load )); then
        result_file=dual-stack-load-result.txt
        expected=dual_stack_load_pass=1
        uv run --no-project python -B "$(dirname "$helper")/load-result.py" \
            "$prefix.client.tar" "$tag" "$prefix" > "$prefix.load-result.json" 2>"$prefix.load-result-errors.txt" ||
            cases_failed=1
    fi
    result=$(tar -xOf "$prefix.client.tar" "$tag/$result_file" 2>/dev/null || :)
    if [[ $rc != 0 || $result != "$expected" ]]; then
        cases_failed=1
    fi
    printf 'CASE_COMPLETE band=%s client_rc=%s hold=%s tag=%s\n' "$band" "$rc" "$result" "$tag"
done
echo PRIMARY_CLIENT_CASES_COMPLETE
exit "$cases_failed"
