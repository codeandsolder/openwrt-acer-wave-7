#!/usr/bin/env bash
# Independent cross-kernel native AP qualification; exact candidate and rollback images.
set -Eeuo pipefail
umask 077
usage(){ echo "usage: $0 --verify-artifacts CANDIDATE_DIR ROLLBACK_DIR | --run-native CANDIDATE_DIR ROLLBACK_DIR PREDECESSOR_RUN | --watch CANDIDATE_DIR ROLLBACK_DIR RUN" >&2; exit 2; }
case "${1:-}" in
  --verify-artifacts) [[ $# == 3 ]] || usage ;;
  --run-native|--watch) [[ $# == 4 ]] || usage ;;
  *) usage ;;
esac
base=$(realpath -e "$2")
parent=$(realpath -e "$3")
[[ -d $base && -d $parent && $base != "$parent" ]] || usage
candidate_manifest="$base/native-manifest.json"
rollback_manifest="$parent/native-manifest.json"
guard8=/home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8
key=/home/jan/.ssh/wave7-root-rsa
iface=enp4s0f4u2u2u4
ip=192.168.76.250
direct=enp4s0f4u2u4
direct_ip=192.168.76.2
router=192.168.76.1
mac=70:5a:6f:5a:bb:14
attestor=$(dirname "$(realpath "$0")")/attest-management.sh
upstream=/home/jan/scripts/wave7/secondary-ap-guard8/lab-upstream.sh
digest(){ sha256sum "$1" | cut -d' ' -f1; }
fail(){ echo "RADIO_TRIAL_FAIL $*" >&2; exit 1; }
value(){ sed -n "s/^$2=//p" <<< "$1" | head -1; }
log(){ printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$out/observer.log"; }
finish(){ log "$1"; printf '%s\n' "$1" > "$out/status"; exit "${2:-0}"; }
validate_manifest(){
    local manifest=$1 dir=$2 name sha
    jq -e '
      def hash: type=="string" and test("^[a-f0-9]{64}$");
      def hashes: type=="object" and all(.[]; hash);
      (.image|type=="string" and test("^[a-zA-Z0-9_.-]+[.]bin$")) and
      (.image_sha256|hash) and (.fit_sha256|hash) and (.rootfs_sha256|hash) and
      (.revision|type=="string" and test("^r0[+][0-9]+-[a-f0-9]{10}-ap-dhcp-guard8$")) and
      (.kernel|type=="string" and test("^[0-9]+[.][0-9]+[.][0-9]+$")) and
      (.builder_commit|type=="string" and test("^[a-f0-9]{40}$")) and
      (.radio_release|type=="string" and test("^[a-zA-Z0-9_.-]+$")) and
      (.radio_sha256|hashes and length==46 and all(keys[]; test("^(IPQ5332|QCN6432)/hw1[.]0/[a-zA-Z0-9_.-]+$"))) and
      (.module_sha256|hashes and (keys==["ath12k.ko","ath12k_wifi7.ko","cfg80211.ko","mac80211.ko"])) and
      (.policy_sha256|hashes and (keys==["etc/config/dhcp","etc/config/dropbear","etc/config/firewall","etc/config/network","etc/config/wireless","etc/dropbear/authorized_keys","etc/init.d/wave7-firstboot-failsafe","etc/openwrt_version","etc/shadow","etc/wave7-role-profile","lib/preinit/05_wave7_firstboot_watchdog","lib/preinit/76_wave7_ap_overlay_reset","lib/wave7/overlay-reset.sh","lib/wave7/role-firstboot.sh"]))
    ' "$manifest" >/dev/null || fail 'manifest schema'
    name=$(jq -er .image "$manifest"); sha=$(jq -er .image_sha256 "$manifest")
    [[ -f $dir/$name && ! -L $dir/$name && $(digest "$dir/$name") == "$sha" ]] || fail 'image digest'
    [[ $(tar xOf "$dir/$name" sysupgrade-acer_wave7/CONTROL) == BOARD=acer_wave7 ]] || fail 'board'
    [[ $(tar xOf "$dir/$name" sysupgrade-acer_wave7/kernel | sha256sum | cut -d' ' -f1) == "$(jq -er .fit_sha256 "$manifest")" ]] || fail 'FIT digest'
    [[ $(tar xOf "$dir/$name" sysupgrade-acer_wave7/root | sha256sum | cut -d' ' -f1) == "$(jq -er .rootfs_sha256 "$manifest")" ]] || fail 'rootfs digest'
}
verify_artifacts(){
    validate_manifest "$candidate_manifest" "$base"
    validate_manifest "$rollback_manifest" "$parent"
    [[ $(jq -er .image_sha256 "$candidate_manifest") != $(jq -er .image_sha256 "$rollback_manifest") ]] || fail 'identical images'
    [[ $(jq -er .radio_release "$candidate_manifest") == $(jq -er .radio_release "$rollback_manifest") ]] || fail 'radio release changed'
    [[ $(jq -cS .radio_sha256 "$candidate_manifest") == $(jq -cS .radio_sha256 "$rollback_manifest") ]] || fail 'radio firmware changed in cross-kernel comparison'
}
verify_artifacts
native="$base/$(jq -er .image "$candidate_manifest")"
native_sha=$(jq -er .image_sha256 "$candidate_manifest")
rev=$(jq -er .revision "$candidate_manifest")
builder=$(jq -er .builder_commit "$candidate_manifest")
kernel=$(jq -er .kernel "$candidate_manifest")
rollback="$parent/$(jq -er .image "$rollback_manifest")"
rollback_sha=$(jq -er .image_sha256 "$rollback_manifest")
rollback_rev=$(jq -er .revision "$rollback_manifest")
rollback_kernel=$(jq -er .kernel "$rollback_manifest")
rollback_builder=$(jq -er .builder_commit "$rollback_manifest")
if [[ $1 == --verify-artifacts ]]; then echo NATIVE_IMAGE_ARTIFACTS_PASS; exit 0; fi
[[ $base == /home/jan/firmware/wave7/trials/* && $parent == /home/jan/firmware/wave7/trials/* ]] || fail 'not lab trial directories'
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
    local nic source result wanted wanted_kernel pair
    wanted=$rev; wanted_kernel=$kernel
    if [[ ${restoring:-0} == 1 ]]; then wanted=$rollback_rev; wanted_kernel=$rollback_kernel; fi
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
        [[ $result == "$(printf '%s\n%s\n%s' "$wanted_kernel" "$wanted" "$mac")" ]] || continue
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
verify_runtime(){
    local manifest=$1 prefix=${2:-} target_kernel path got expect group field root
    local -a paths
    target_kernel=$(jq -er .kernel "$manifest")
    for group in radio_sha256 module_sha256 policy_sha256; do
        mapfile -t paths < <(jq -r --arg group "$group" '.[$group]|keys[]' "$manifest")
        expect=$(jq -r --arg group "$group" '.[$group]|to_entries|sort_by(.key)[]|"\(.value)  \(.key)"' "$manifest")
        case "$group" in
          radio_sha256) field=lib/firmware/ath12k ;;
          module_sha256) field="lib/modules/$target_kernel" ;;
          policy_sha256) field='' ;;
        esac
        for root in /rom /; do
            path="${root%/}/$field"
            got=$(remote "cd '$path' && sha256sum ${paths[*]}") || return 1
            [[ $got == "$expect" ]] || return 1
        done
    done
    remote 'cat /proc/interrupts' > "$out/${prefix}irq-runtime.txt" || return 1
    rg -q 'wbm2host-tx-completions-ring4$' "$out/${prefix}irq-runtime.txt" || return 1
    remote 'cat /sys/kernel/debug/ath12k/ahb-c000000.wifi/srng_state' > "$out/${prefix}srng-initial.txt" || return 1
    rg -qx 'rx_release=5 rx_rbm=10 rx_buffer_rbm=10' "$out/${prefix}srng-initial.txt" || return 1
    rg -qx 'map tcl=3 wbm=3 rbm=8' "$out/${prefix}srng-initial.txt" || return 1
    rg -q '^WBM3 id=131 ' "$out/${prefix}srng-initial.txt" || return 1
    rg -q '^WBM_RX5 id=133 ' "$out/${prefix}srng-initial.txt" || return 1
    local release; release=$(jq -er .radio_release "$manifest")
    remote "lsmod | grep -E '^ath12k[[:space:]]'; lsmod | grep -E '^ath12k_wifi7[[:space:]]'; dmesg | grep -F '$release'" > "$out/${prefix}radio-runtime.txt" || return 1
}
ready(){
    local s=$1 wanted_rev=$2 wanted_kernel=$3 wanted_builder=$4
    for line in "rev=$wanted_rev" "merged_rev=$wanted_rev" "kernel=$wanted_kernel" "builder=$wanted_builder" bootfail=0 keep=1 token=1 q6=3 ap=2 noc=0 lan=1 lan_speed=2500 lan1=1 lan1_speed=1000 local_ready=1 ping=1 address=192.168.76.1/24; do
        grep -Fxq "$line" <<< "$s" || return 1
    done
    systemctl is-active --quiet wave7-lab-upstream-guard8.service || return 1
}
# Non-login SSH and remote executor sessions need not export the systemd
# user bus environment. Resolve the real login manager runtime directory;
# scope the canonical D-Bus address to these commands only.
resolve_user_manager(){
    user_runtime=$(loginctl show-user "$(id -u)" -p RuntimePath --value) ||
        fail 'cannot resolve user manager runtime directory'
    [[ $user_runtime == "/run/user/$(id -u)" && -O $user_runtime &&
       -S $user_runtime/bus && -O $user_runtime/bus ]] ||
        fail 'invalid user manager bus'
    user_systemctl show --property=Version --value >/dev/null ||
        fail 'cannot contact user manager'
}
user_systemctl(){
    DBUS_SESSION_BUS_ADDRESS="unix:path=$user_runtime/bus" systemctl --user "$@"
}
user_systemd_run(){
    DBUS_SESSION_BUS_ADDRESS="unix:path=$user_runtime/bus" systemd-run --user "$@"
}
common_preflight(){
    local observers
    verify_artifacts
    [[ $(id -un) == jan && -r $key ]] || fail 'Asus identity'
    physical_peer || fail 'lab physical peer'
    for nic in "$direct" "$iface"; do
        [[ $(cat "/sys/class/net/$nic/carrier") == 1 ]] || fail 'carrier'
    done
    "$attestor" --selftest
    "$upstream" --check
    systemctl is-active --quiet wave7-lab-upstream-guard8.service || fail 'lab upstream inactive'
    resolve_user_manager
    for service in wave7-q6-devcoredump-capture wave7-q6-noc-kmsg wave7-q6-noc-events; do
        user_systemctl is-active --quiet "$service.service" || fail "$service inactive"
    done
    observers=$(user_systemctl --no-pager --no-legend list-units --state=active,activating 'wave7-openwrt-watch-*' 'wave7-fallback-watch-*' 'wave7-secondary-ap-supervisor-*' 'wave7-integrated-supervisor-*' 'wave7-autonomous-observer-*' 'wave7-qdss-supervisor-*') || fail 'cannot enumerate user observers'
    [[ -z $observers ]] || fail 'another active observer'
    (cd /home/jan/firmware/wave7/captures/20261125-vendor-fallback && sha256sum -c SHA256SUMS)
}
case "${1:-}" in
--run-native)
    lock="$guard8/.lab-control.lock"
    [[ -f $lock && ! -L $lock && -O $lock ]] || fail 'invalid lab lock'
    exec 8<>"$lock"
    flock -n 8 || fail 'lab already reserved'
    common_preflight
    predecessor=$(realpath -e "$4")
    [[ $predecessor == "$parent"/runs/* && $(cat "$predecessor/status") == SOAK_PASS ]] || fail 'parent soak incomplete'
    known="$predecessor/known_hosts"
    source_boot=$(value "$(cat "$predecessor/last-state.txt")" boot)
    state=$(read_state)
    [[ $(value "$state" boot) == "$source_boot" ]] || fail 'predecessor boot changed'
    ready "$state" "$rollback_rev" "$rollback_kernel" "$rollback_builder" || fail 'predecessor unhealthy'
    [[ -z $(remote 'iw dev ap-mld0 station dump') ]] || fail 'client still attached'
    tag=native-$(date +%Y%m%d-%H%M%S)
    out="$base/runs/$tag"
    mkdir -p "$out"
    verify_runtime "$rollback_manifest" predecessor- || fail 'predecessor runtime identity'
    printf '%s\n' "$source_boot" > "$out/stock-boot"
    printf '%s\n' "$state" > "$out/predecessor-state.txt"
    remote 'cat /proc/sys/kernel/random/boot_id; dmesg; logread' > "$out/predecessor-capture.txt"
    dest=/tmp/wave7-native-candidate.bin
    upload "$native" "$dest"
    result=$(remote "sha256sum '$dest'; /sbin/sysupgrade -T -n '$dest'") || fail 'native image validation'
    [[ $result == "$native_sha  $dest"* ]] || fail 'native image hash'
    unit="wave7-secondary-ap-supervisor-$tag"
    fallback="wave7-fallback-watch-$tag"
    flash_started=0
    cleanup_native(){
        local rc=$?
        if (( rc != 0 && ! flash_started )); then
            user_systemctl stop "$unit.service" "$fallback.service" >/dev/null 2>&1 || :
            echo ABORTED_PRE_FLASH > "$out/status"
        fi
    }
    trap cleanup_native EXIT
    user_systemd_run --quiet --unit="$unit" --property=RuntimeMaxSec=1500 -- "$(realpath "$0")" --watch "$base" "$parent" "$out"
    user_systemd_run --quiet --unit="$fallback" --property=RuntimeMaxSec=1500 -- /home/jan/scripts/wave7/wave7-fallback-watch.sh "$tag"
    for _ in {1..15}; do
        [[ -r $out/status && $(cat "$out/status") == ARMED ]] && break
        sleep 1
    done
    [[ -r $out/status && $(cat "$out/status") == ARMED ]] || fail 'observer not armed'
    user_systemctl is-active --quiet "$unit.service" || fail 'observer inactive'
    user_systemctl is-active --quiet "$fallback.service" || fail 'fallback inactive'
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
    while :; do
        observer_state=$(user_systemctl show "$unit.service" -p ActiveState --value) ||
            fail 'lost user manager while observing flash'
        case "$observer_state" in
            active|activating|deactivating|reloading) sleep 5 ;;
            inactive|failed) break ;;
            *) fail "unexpected observer state: $observer_state" ;;
        esac
    done
    if [[ $(cat "$out/status") == SOAK_PASS || $(cat "$out/status") == ROLLED_BACK ]]; then
        user_systemctl stop "$fallback.service"
    fi
    cat "$out/status" "$out/observer.log"
    [[ $(cat "$out/status") == SOAK_PASS || $(cat "$out/status") == ROLLED_BACK ]]
    ;;
--watch)
    [[ $4 == "$base"/runs/native-* ]] || fail 'invalid run'
    out=$4
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
            [[ $gotrev == "$rollback_rev" && $(value "$state" kernel) == "$rollback_kernel" && $(value "$state" builder) == "$rollback_builder" ]] || { sleep 3; continue; }
            if (( ! verified )) && [[ $(value "$state" q6) == 3 && $(value "$state" ap) == 2 ]]; then
                if verify_runtime "$rollback_manifest" rollback-; then verified=1; log ROLLBACK_IDENTITY_VERIFIED; fi
            fi
            (( verified )) || { sleep 3; continue; }
            if [[ $(value "$state" keep) == 0 ]]; then
                "$attestor" --run "$router" "$rollback_rev" "$rollback_kernel" "$iface" "$ip" "$known" > "$out/rollback-attest.log" 2>&1 || :
            elif ready "$state" "$rollback_rev" "$rollback_kernel" "$rollback_builder"; then
                (( healthy_since )) || healthy_since=$now
                if (( now-healthy_since >= 300 )); then finish ROLLED_BACK; fi
            else
                healthy_since=0
            fi
            sleep 3; continue
        fi
        [[ $gotrev == "$rev" && $(value "$state" merged_rev) == "$rev" && $(value "$state" builder) == "$builder" && $(value "$state" kernel) == "$kernel" ]] || finish UNKNOWN_REVISION 2
        if (( ! verified )) && [[ $(value "$state" q6) == 3 && $(value "$state" ap) == 2 ]]; then
            if verify_runtime "$candidate_manifest"; then
                verified=1
                log RADIO_IDENTITY_VERIFIED
                remote 'cat /rom/etc/wave7-role-profile; dmesg; iw dev ap-mld0 info' > "$out/initial-radio.txt" 2>&1 || :
            fi
        fi
        if (( verified )) && [[ $(value "$state" keep) == 0 ]]; then
            "$attestor" --run "$router" "$rev" "$kernel" "$iface" "$ip" "$known" > "$out/attest.log" 2>&1 || :
        fi
        if [[ $(value "$state" keep) == 1 && $(value "$state" bootfail) == 0 ]]; then
            if (( ! accepted )); then accepted=1; log KEEP_BOOT; fi
            if (( verified )) && ready "$state" "$rev" "$kernel" "$builder"; then
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
                    restoring=1; healthy_since=0; verified=0
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
*) usage ;;
esac
