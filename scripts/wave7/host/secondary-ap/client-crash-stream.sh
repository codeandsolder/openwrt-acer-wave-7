#!/usr/bin/env bash
# Independent, bounded control-plane stream for a potentially fatal lab association.
# Run over the wired SSH session and save stdout on the observer, not on Wyse.
set -Eeuo pipefail
[[ $EUID == 0 && ( $# == 3 || $# == 4 ) &&
   $1 =~ ^0498-[0-9]{8}-[0-9]{6}$ &&
   $2 =~ ^[a-z0-9-]+$ &&
   $3 =~ ^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$ ]] || exit 2
tag=$1
variant=$2
boot=$3
seconds=${4:-240}
[[ $seconds =~ ^[0-9]{2,3}$ && $seconds -ge 30 && $seconds -le 300 ]] || exit 2
[[ $(cat /proc/sys/kernel/random/boot_id) == "$boot" ]]
guard=/home/jan/scripts/wave7/client-validation/client-module-stack.sh
[[ $(bash "$guard" "$variant" --trace-profile) == association-rxtx ]]
bash "$guard" "$variant" --check-candidate
root=/sys/kernel/tracing
inst="$root/instances/wave7-crash-$tag"
[[ ! -e $inst ]]
mkdir "$inst"
probe_group=wave7_lifecycle_${tag//-/_}
probes=()
cleanup() {
    local rc=$?
    trap - EXIT
    printf '0\n' > "$inst/tracing_on" || rc=1
    for event in "${probes[@]}"; do
        printf '0\n' > "$inst/events/$probe_group/$event/enable" || rc=1
    done
    rmdir "$inst" || rc=1
    for event in "${probes[@]}"; do
        printf '%s\n' "-:$probe_group/$event" >> "$root/dynamic_events" || rc=1
    done
    printf 'CRASH_STREAM_END rc=%s\n' "$rc"
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP
printf '0\n' > "$inst/tracing_on"
printf 'mono\n' > "$inst/trace_clock"
printf 'nop\n' > "$inst/current_tracer"
printf '1024\n' > "$inst/buffer_size_kb"
events=(mac80211/drv_change_vif_links mac80211/drv_change_sta_links
    mac80211/drv_remain_on_channel mac80211/drv_cancel_remain_on_channel
    mac80211/api_ready_on_channel mac80211/api_remain_on_channel_expired
    mac80211/api_beacon_loss mac80211/api_connection_loss)
for e in roc_wire mlo_roc_req mlo_roc_result roc_geometry roc_abort roc_band \
    roc_sync bss_basic bss_mld bss_result sta_mld_slot sta_result sta_eht_mld \
    key_result beacon_loss; do
    events+=("mt7925_lab/mt7925_lab_$e")
done
if [[ $variant == upstream-prefix22-authorize-primary-mld-trace ||
      $variant == upstream-prefix22-postscan-txroute-trace ||
      $variant == upstream-prefix22-postscan-txroute-fw20261016 ||
      $variant == upstream-prefix22-postscan-roc-reacquire-trace ||
      $variant == upstream-prefix22-postscan-link-park-trace ||
      $variant == upstream-prefix22-force-secondary-data-trace ||
      $variant == upstream-prefix22-authorize-single-link-trace ||
      $variant == upstream-prefix22-authorize-delayed-links-trace ]]; then
    events+=(mt7925_lab/mt7925_lab_sta_mld_update)
fi
if [[ $variant == upstream-prefix22-lifecycle-trace ||
      $variant == upstream-prefix22-primary-bss-band-trace ||
      $variant == upstream-prefix22-authorize-links-trace ||
      $variant == upstream-prefix22-authorize-bss-band-trace ||
      $variant == upstream-prefix22-authorize-primary-mld-trace ||
      $variant == upstream-prefix22-postscan-txroute-trace ||
      $variant == upstream-prefix22-postscan-txroute-fw20261016 ||
      $variant == upstream-prefix22-postscan-roc-reacquire-trace ||
      $variant == upstream-prefix22-postscan-link-park-trace ||
      $variant == upstream-prefix22-force-secondary-data-trace ||
      $variant == upstream-prefix22-authorize-single-link-trace ||
      $variant == upstream-prefix22-authorize-delayed-links-trace ]]; then
    # BTF field fetching avoids hard-coded structures/offsets. Register only
    # these two named probes and remove the exact definitions at cleanup.
    [[ ! -e $root/events/$probe_group && -e /sys/kernel/btf/mt76 &&
       -e /sys/kernel/btf/mt792x_lib ]]
    printf '%s\n' "f:$probe_group/wcid_cleanup mt76_wcid_cleanup idx=wcid->idx sta=wcid->sta" >> "$root/dynamic_events"
    probes+=(wcid_cleanup)
    printf '%s\n' "f:$probe_group/bss_remove mt792x_mac_link_bss_remove bss=mconf->mt76.idx link=mconf->link_id owner=mlink->wcid.idx sta=mlink->wcid.sta" >> "$root/dynamic_events"
    probes+=(bss_remove)
    for event in "${probes[@]}"; do
        events+=("$probe_group/$event")
        printf 'CRASH_PROBE_FORMAT %s\n' "$event"
        cat "$root/events/$probe_group/$event/format"
    done
fi
for e in "${events[@]}"; do
    [[ -f $inst/events/$e/enable ]]
    printf '1\n' > "$inst/events/$e/enable"
done
printf 'CRASH_STREAM_CLOCK '; cat "$inst/trace_clock"
printf 'CRASH_STREAM_EVENTS\n%s\n' "${events[@]}"
printf '1\n' > "$inst/tracing_on"
printf 'CRASH_STREAM_READY boot=%s time=%s\n' "$boot" "$(date +%s.%N)"
# A separate ring prevents consuming the canonical trial trace. This stream
# may be partial if the host locks; it is diagnostic, not acceptance evidence.
rc=0
timeout "${seconds}s" cat "$inst/trace_pipe" || rc=$?
[[ $rc == 124 ]]
printf 'CRASH_STREAM_STATS\n'
for stats in "$inst"/per_cpu/cpu*/stats; do
    printf '%s\n' "$stats"
    cat "$stats"
done
