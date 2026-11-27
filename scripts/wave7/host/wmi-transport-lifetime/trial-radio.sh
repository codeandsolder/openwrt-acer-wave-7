#!/usr/bin/env bash
# Independent guarded stock->Guard8 radio experiment. Run on the isolated Asus lab.
set -Eeuo pipefail
umask 077
base=/home/jan/firmware/wave7/trials/20261127-ahb-tx-completion-irq
guard8=/home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8
native="$base/wave7-ahb-tx-completion-irq-dhcp-guard8-sysupgrade.bin"
native_sha=d519a6acb4ec1d88a7a2284528748b69187e4122d668d59c77488948f3165fde
rev=r0+38346-8b8a3f32c2-ap-dhcp-guard8
builder=8b8a3f32c2943bf2de3a523f97006793f2f79fcc
rollback=/home/jan/firmware/wave7/trials/20261125-netgear-primary-reo-lut/wave7-netgear-primary-reo-lut-dhcp-guard8-sysupgrade.bin
rollback_sha=ae9aa226c79d6263f9afaff4ec813ad34d1345966bba8fd81617073521498fb4
rollback_rev=r0+38346-65f3c6bcfc-ap-dhcp-guard8
key=/home/jan/.ssh/wave7-root-rsa
iface=enp4s0f4u2u2u4
ip=192.168.76.250
direct=enp4s0f4u2u4
direct_ip=192.168.76.2
router=192.168.76.1
mac=70:5a:6f:5a:bb:14
attestor=/home/jan/scripts/wave7/secondary-ap-guard8/attest-management.sh
upstream=/home/jan/scripts/wave7/secondary-ap-guard8/lab-upstream.sh
digest(){ sha256sum "$1" | cut -d' ' -f1; }
fail(){ echo "RADIO_TRIAL_FAIL $*" >&2; exit 1; }
value(){ sed -n "s/^$2=//p" <<< "$1" | head -1; }
log(){ printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$out/observer.log"; }
finish(){ log "$1"; printf '%s\n' "$1" > "$out/status"; exit "${2:-0}"; }
verify_artifacts(){
    [[ $(digest "$native") == "$native_sha" &&
       $(digest "$rollback") == "$rollback_sha" ]] || fail 'artifact digest'
    (cd "$base"; sha256sum -c SHA256SUMS)
    [[ $(jq -r .image_sha256 "$base/report.json") == "$native_sha" &&
       $(jq -r .revision "$base/report.json") == "$rev" &&
       $(jq -r .builder_commit "$base/report.json") == "$builder" ]] || fail 'report identity'
    [[ $(tar xOf "$native" sysupgrade-acer_wave7/CONTROL) == BOARD=acer_wave7 &&
       $(tar xOf "$rollback" sysupgrade-acer_wave7/CONTROL) == BOARD=acer_wave7 ]] || fail 'board'
}
physical_peer(){
    ping -I "$direct_ip" -c 1 -W 1 "$router" >/dev/null 2>&1 || return 1
    ping -I "$ip" -c 1 -W 1 "$router" >/dev/null 2>&1 || return 1
    for nic in "$direct" "$iface"; do
        ip neigh show "$router" dev "$nic" | grep -Fqi "lladdr $mac " || return 1
        [[ $(cat "/sys/class/net/$nic/carrier") == 1 ]] || return 1
    done
}
stock(){
    ssh -F /home/jan/.ssh/config -n -o BatchMode=yes -o ConnectTimeout=3 -o ConnectionAttempts=1 wave7 "$@"
}
# Bootstrap using the attestor's SSH KEX on a verified physical path.
# Both paths are still required for preflight and acceptance.
pin_native(){
    local nic source result wanted pair
    wanted=$rev
    [[ ${restoring:-0} != 1 ]] || wanted=$rollback_rev
    for pair in "enp4s0f4u2u2u4:192.168.76.250" "$direct:$direct_ip"; do
        nic=${pair%%:*}
        source=${pair#*:}
        [[ $(cat "/sys/class/net/$nic/carrier" 2>/dev/null) == 1 ]] || continue
        ping -I "$source" -c 1 -W 1 "$router" >/dev/null 2>&1 || continue
        ip neigh show "$router" dev "$nic" | grep -Fqi "lladdr $mac " || continue
        rm -f "$known.new"
        result=$(ssh -n -T -i "$key" -o "BindInterface=$nic" -o "BindAddress=$source" \
            -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=3 \
            -o ConnectionAttempts=1 -o HostKeyAlgorithms=ssh-ed25519 \
            -o GlobalKnownHostsFile=/dev/null -o StrictHostKeyChecking=accept-new \
            -o "UserKnownHostsFile=$known.new" "root@$router" \
            'uname -r; cat /rom/etc/openwrt_version; cat /sys/class/net/br-lan/address' \
            2>>"$out/pin.log") || continue
        [[ $result == "$(printf '6.18.60\n%s\n%s' "$wanted" "$mac")" ]] || continue
        [[ -s $known.new ]] || continue
        ssh-keygen -lf "$known.new" >> "$out/host-key-fingerprints.txt" || continue
        mv "$known.new" "$known"
        iface=$nic
        ip=$source
        log "NATIVE_PIN path=$iface source=$ip"
        return 0
    done
    rm -f "$known.new"
    return 1
}
remote(){
    ssh -n -T -i "$key" -o "BindInterface=$iface" -o "BindAddress=$ip"         -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4         -o ConnectionAttempts=1 -o ServerAliveInterval=4 -o ServerAliveCountMax=2 -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$known"         "root@$router" "$@"
}
upload(){
    scp -q -O -i "$key" -o "BindInterface=$iface" -o "BindAddress=$ip"         -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=5         -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$known"         "$1" "root@$router:$2"
}
read_state(){
    remote 'set -eu
        echo "boot=$(cat /proc/sys/kernel/random/boot_id)"
        echo "rev=$(cat /rom/etc/openwrt_version)"
        echo "merged_rev=$(cat /etc/openwrt_version)"
        echo "kernel=$(uname -r)"
        echo "bootfail=$(fw_printenv -n bootfail)"
        echo "keep=$(test -e /tmp/wave7-keep-boot && echo 1 || echo 0)"
        echo "token=$(test -e /tmp/wave7-ap-management-verified && echo 1 || echo 0)"
        echo "q6=$(n=0; for p in 0 1 2; do [ "$(cat /sys/class/remoteproc/remoteproc$p/state)" != running ] || n=$((n+1)); done; echo "$n")"
        echo "ap=$(iw dev ap-mld0 info 2>/dev/null | grep -Ec "link ID[[:space:]]+[01]" || :)"
        echo "noc=$(dmesg | grep -c "NOC ERROR DETECTED" || :)"
        echo "lan=$(cat /sys/class/net/lan/carrier)"
        echo "lan_speed=$(cat /sys/class/net/lan/speed)"
        echo "lan1=$(cat /sys/class/net/lan1/carrier)"
        echo "lan1_speed=$(cat /sys/class/net/lan1/speed)"
        echo "local_ready=$(. /rom/lib/wave7/role-firstboot.sh; wave7_secondary_ap_local_ready >/dev/null 2>&1 && echo 1 || echo 0)"
        echo "ping=$(ping -I br-lan -c 1 -W 1 192.168.76.2 >/dev/null 2>&1 && ping -I br-lan -c 1 -W 1 192.168.76.250 >/dev/null 2>&1 && echo 1 || echo 0)"
        echo "builder=$(sed -n "s/^builder_commit=//p" /rom/etc/wave7-role-profile)"
        echo "radio=$(sed -n "s/^trial_radio_release=//p" /rom/etc/wave7-role-profile)"
        echo "address=$(ip -4 -o addr show dev br-lan | awk "{print \$4}" | head -1)"
    '
}
verify_radio(){
    local path got expect
    mapfile -t paths < <(awk '{print $2}' "$base/radio.sha256")
    [[ ${#paths[@]} == 46 ]] || return 1
    for path in "${paths[@]}"; do
        [[ $path =~ ^(IPQ5332|QCN6432)/hw1\.0/[a-zA-Z0-9_.-]+$ ]] || return 1
    done
    for path in /rom/lib/firmware/ath12k /lib/firmware/ath12k; do
        got=$(remote "cd '$path' && sha256sum ${paths[*]}") || return 1
        expect=$(cat "$base/radio.sha256")
        [[ $got == "$expect" ]] || return 1
    done
    for path in /rom/lib/modules/6.18.60 /lib/modules/6.18.60; do
        got=$(remote "cd '$path' && sha256sum ath12k.ko ath12k_wifi7.ko") || return 1
        expect=$(jq -r '.module_sha256|to_entries[]|"\(.value)  \(.key)"' "$base/report.json")
        [[ $got == "$expect" ]] || return 1
    done
    remote 'cat /proc/interrupts' > "$out/irq-runtime.txt" || return 1
    rg -q "wbm2host-tx-completions-ring4$" "$out/irq-runtime.txt" || return 1
    remote 'lsmod | grep -E "^ath12k[[:space:]]"; lsmod | grep -E "^ath12k_wifi7[[:space:]]"; dmesg | grep -F "WBE.1.4-01734"' > "$out/radio-runtime.txt" || return 1
}
ready(){
    local s=$1
    for line in kernel=6.18.60 bootfail=0 keep=1 token=1 q6=3 ap=2 noc=0 lan=1 lan_speed=2500 lan1=1 lan1_speed=1000 local_ready=1 ping=1 address=192.168.76.1/24; do
        grep -Fxq "$line" <<< "$s" || return 1
    done
    systemctl is-active --quiet wave7-lab-upstream-guard8.service || return 1
}
common_preflight(){
    verify_artifacts
    [[ $(id -un) == jan && -r $key ]] || fail 'Asus identity'
    physical_peer || fail 'lab physical peer'
    for nic in "$direct" "$iface"; do
        [[ $(cat "/sys/class/net/$nic/carrier") == 1 ]] || fail 'carrier'
    done
    "$attestor" --selftest
    "$upstream" --check
    systemctl is-active --quiet wave7-lab-upstream-guard8.service || fail 'lab upstream inactive'
    for service in wave7-q6-devcoredump-capture wave7-q6-noc-kmsg wave7-q6-noc-events; do
        systemctl --user is-active --quiet "$service.service" || fail "$service inactive"
    done
    [[ -z $(systemctl --user --no-pager --no-legend list-units --state=active,activating 'wave7-openwrt-watch-*' 'wave7-fallback-watch-*' 'wave7-secondary-ap-supervisor-*' 'wave7-integrated-supervisor-*' 'wave7-autonomous-observer-*' 'wave7-qdss-supervisor-*') ]] || fail 'another active observer'
    (cd /home/jan/firmware/wave7/captures/20261125-vendor-fallback && sha256sum -c SHA256SUMS)
}
case "${1:-}" in
--check) common_preflight; echo RADIO_TRIAL_PREFLIGHT_PASS ;;
--run-native)
    [[ $# == 2 ]] || fail 'expected predecessor run'
    lock="$guard8/.lab-control.lock"
    [[ -f $lock && ! -L $lock && -O $lock ]] || fail 'invalid lab lock'
    exec 8<>"$lock"
    flock -n 8 || fail 'lab already reserved'
    common_preflight
    predecessor="$2"
    [[ $predecessor == /home/jan/firmware/wave7/trials/20261125-netgear-primary-reo-lut/runs/netgear-primary-reo-lut-native-* ]] || fail 'unexpected predecessor run'
    case "$(cat "$predecessor/status")" in
        SOAK_PASS) source_rev=$rollback_rev ;;
        *) fail 'predecessor has not completed guarded soak' ;;
    esac
    known="$predecessor/known_hosts"
    source_boot=$(value "$(cat "$predecessor/last-state.txt")" boot)
    state=$(read_state)
    [[ $(value "$state" boot) == "$source_boot" && $(value "$state" rev) == "$source_rev" && $(value "$state" merged_rev) == "$source_rev" ]] || fail 'predecessor identity changed'
    ready "$state" || fail 'predecessor unhealthy'
    [[ $(remote 'sha256sum /rom/lib/modules/6.18.60/ath12k.ko') == "477ea1d123a13791fd204958a9be4fd62f7d471f8f849810bb2faed473e5d015  /rom/lib/modules/6.18.60/ath12k.ko" ]] || fail 'predecessor module identity'
    tag=ahb-tx-completion-irq-native-$(date +%Y%m%d-%H%M%S)
    out="$base/runs/$tag"
    mkdir -p "$out"
    printf '%s\n' "$source_boot" > "$out/stock-boot"
    printf '%s\n' "$state" > "$out/predecessor-state.txt"
    remote 'cat /proc/sys/kernel/random/boot_id; dmesg; logread' > "$out/predecessor-capture.txt"
    dest=/tmp/wave7-ahb-irq-native.bin
    upload "$native" "$dest"
    result=$(remote "sha256sum '$dest'; /sbin/sysupgrade -T -n '$dest'") || fail 'native image validation'
    [[ $result == "$native_sha  $dest"* ]] || fail 'native image hash'
    unit="wave7-secondary-ap-supervisor-$tag"
    fallback="wave7-fallback-watch-$tag"
    flash_started=0
    cleanup_native(){
        local rc=$?
        if (( rc != 0 && ! flash_started )); then
            systemctl --user stop "$unit.service" "$fallback.service" >/dev/null 2>&1 || :
            echo ABORTED_PRE_FLASH > "$out/status"
        fi
    }
    trap cleanup_native EXIT
    systemd-run --user --quiet --unit="$unit" --property=RuntimeMaxSec=1500 -- "$(realpath "$0")" --watch "$out"
    systemd-run --user --quiet --unit="$fallback" --property=RuntimeMaxSec=1500 -- /home/jan/scripts/wave7/wave7-fallback-watch.sh "$tag"
    for _ in {1..15}; do
        [[ -r $out/status && $(cat "$out/status") == ARMED ]] && break
        sleep 1
    done
    [[ -r $out/status && $(cat "$out/status") == ARMED ]] || fail 'observer not armed'
    systemctl --user is-active --quiet "$unit.service" || fail 'observer inactive'
    systemctl --user is-active --quiet "$fallback.service" || fail 'fallback inactive'
    [[ $(remote 'cat /proc/sys/kernel/random/boot_id') == "$source_boot" ]] || fail 'source rebooted'
    flash_started=1
    echo FLASHING_NOW > "$out/flash.log"
    timeout 135 ssh -n -T -i "$key" -o "BindInterface=$iface" -o "BindAddress=$ip" \
        -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 \
        -o ConnectionAttempts=1 -o ServerAliveInterval=4 -o ServerAliveCountMax=2 \
        -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$known" \
        "root@$router" "/sbin/sysupgrade -n '$dest'" >> "$out/flash.log" 2>&1 || :
    grep -Fq 'Commencing upgrade. Closing all shell sessions.' "$out/flash.log" || { flash_started=0; fail 'native upgrade did not start'; }
    echo "RUN_DIR=$out"
    while systemctl --user is-active --quiet "$unit.service"; do sleep 5; done
    if [[ $(cat "$out/status") == SOAK_PASS || $(cat "$out/status") == ROLLED_BACK ]]; then
        systemctl --user stop "$fallback.service"
    fi
    cat "$out/status" "$out/observer.log"
    [[ $(cat "$out/status") == SOAK_PASS || $(cat "$out/status") == ROLLED_BACK ]]
    ;;
--watch)
    [[ $# == 2 && $2 == "$base"/runs/ahb-tx-completion-irq-native-* ]] || fail 'invalid run'
    out=$2
    known="$out/known_hosts"
    exec 9>"$out/.watch.lock"
    flock -n 9 || fail 'observer already running'
    echo ARMED > "$out/status"
    log ARMED
    deadline=$(( $(date +%s) + 1350 ))
    current_boot='' verified=0 healthy_since=0 first_seen=0 accepted=0 restoring=0 attempted=0
    while (( $(date +%s) < deadline )); do
        now=$(date +%s)
        if [[ ! -s $known ]] && ! pin_native; then
            if [[ $(stock 'uname -r' 2>/dev/null || :) == 5.4.213 ]] && [[ -s $out/flash.log ]] &&
               grep -q '^FLASHING_NOW$' "$out/flash.log" &&
               [[ $(stock 'cat /proc/sys/kernel/random/boot_id' 2>/dev/null || :) != "$(cat "$out/stock-boot")" ]]; then
                finish VENDOR_FALLBACK 2
            fi
            sleep 2; continue
        fi
        if ! state=$(read_state 2>/dev/null); then
            if [[ $(stock 'uname -r' 2>/dev/null || :) == 5.4.213 ]] && [[ -s $out/flash.log ]] &&
               grep -q '^FLASHING_NOW$' "$out/flash.log" &&
               [[ $(stock 'cat /proc/sys/kernel/random/boot_id' 2>/dev/null || :) != "$(cat "$out/stock-boot")" ]]; then
                finish VENDOR_FALLBACK 2
            fi
            # A new native boot can recreate its key. Only retry the physical
            # identity gate after a failed strict SSH, never bypass it.
            pin_native || :
            sleep 3; continue
        fi
        boot=$(value "$state" boot); gotrev=$(value "$state" rev)
        [[ $boot =~ ^[a-f0-9-]{36}$ ]] || finish INVALID_BOOT 2
        if [[ $boot != "$current_boot" ]]; then
            log "NEW_BOOT $boot revision=$gotrev"
            current_boot=$boot; verified=0; healthy_since=0; first_seen=$now
            printf '%s\n' "$state" > "$out/first-$boot.txt"
        fi
        printf '%s\n' "$state" > "$out/last-state.txt"
        if [[ $restoring == 1 ]]; then
            [[ $gotrev == "$rollback_rev" ]] || { sleep 3; continue; }
            if [[ $(value "$state" keep) == 0 ]]; then
                "$attestor" --run "$router" "$rollback_rev" "$iface" "$ip" "$known" > "$out/rollback-attest.log" 2>&1 || :
            elif ready "$state"; then
                (( healthy_since )) || healthy_since=$now
                if (( now-healthy_since >= 300 )); then finish ROLLED_BACK; fi
            else
                healthy_since=0
            fi
            sleep 3; continue
        fi
        [[ $gotrev == "$rev" && $(value "$state" merged_rev) == "$rev" && $(value "$state" builder) == "$builder" ]] || finish UNKNOWN_REVISION 2
        if (( ! verified )) && [[ $(value "$state" q6) == 3 && $(value "$state" ap) == 2 ]]; then
            if verify_radio; then
                verified=1
                log RADIO_IDENTITY_VERIFIED
                remote 'cat /rom/etc/wave7-role-profile; dmesg; iw dev ap-mld0 info' > "$out/initial-radio.txt" 2>&1 || :
            fi
        fi
        if (( verified )) && [[ $(value "$state" keep) == 0 ]]; then
            "$attestor" --run "$router" "$rev" "$iface" "$ip" "$known" > "$out/attest.log" 2>&1 || :
        fi
        if [[ $(value "$state" keep) == 1 && $(value "$state" bootfail) == 0 ]]; then
            if (( ! accepted )); then accepted=1; log KEEP_BOOT; fi
            if (( verified )) && ready "$state"; then
                if (( ! healthy_since )); then healthy_since=$now; log FIRST_HEALTHY; echo SOAKING > "$out/status"; fi
                if (( now-healthy_since >= 300 )); then
                    remote 'cat /proc/sys/kernel/random/boot_id; dmesg; iw dev ap-mld0 info' > "$out/soak-final.txt"
                    finish SOAK_PASS
                fi
            else
                healthy_since=0
                if [[ $(value "$state" noc) =~ ^[1-9][0-9]*$ ]] || (( now-first_seen > 165 )); then
                    (( ! attempted )) || finish ROLLBACK_FAILED 2
                    attempted=1
                    log ROLLBACK_REQUESTED
                    remote 'cat /proc/sys/kernel/random/boot_id; dmesg; logread' > "$out/pre-rollback.txt" 2>&1 || :
                    upload "$rollback" /tmp/wave7-radio-rollback.bin || finish ROLLBACK_COPY_FAILED 2
                    result=$(remote 'sha256sum /tmp/wave7-radio-rollback.bin; /sbin/sysupgrade -T -n /tmp/wave7-radio-rollback.bin') || finish ROLLBACK_PREFLIGHT_FAILED 2
                    [[ $result == "$rollback_sha  /tmp/wave7-radio-rollback.bin"* ]] || finish ROLLBACK_SHA_FAILED 2
                    restoring=1; healthy_since=0
                    log ROLLBACK_NATIVE_SYSUPGRADE
                    timeout 135 ssh -n -T -i "$key" -o "BindInterface=$iface" -o "BindAddress=$ip" \
                        -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 \
                        -o ConnectionAttempts=1 -o ServerAliveInterval=4 -o ServerAliveCountMax=2 \
                        -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$known" \
                        "root@$router" '/sbin/sysupgrade -n /tmp/wave7-radio-rollback.bin' > "$out/rollback.log" 2>&1 || :
                fi
            fi
        fi
        sleep 3
    done
    finish WATCH_TIMEOUT 2
    ;;
*) echo 'usage: trial-radio.sh --check|--run-native PREDECESSOR_RUN|--watch OUT' >&2; exit 2 ;;
esac
