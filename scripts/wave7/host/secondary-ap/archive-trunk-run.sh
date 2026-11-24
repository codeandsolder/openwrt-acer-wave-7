#!/usr/bin/env bash
# Seal a completed run while its exact observed boot is still live.
set -Eeuo pipefail
umask 077
base=/home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8
[[ $(id -un) == jan && $# == 1 ]] || exit 2
run=$(realpath -e "$1")
case "$run" in
  "$base"/trunk-health-dhcp-guard8/runs/*|"$base"/native-recovery-dhcp-guard8/runs/*|"$base"/serial-speed-dhcp-guard8/runs/source-reboot-*|"$base"/serial-speed-dhcp-guard8/runs/return-0498-*|"$base"/mib-refresh-dhcp-guard8/runs/*|"$base"/mib-diag-dhcp-guard8/runs/*|"$base"/stock-order-dhcp-guard8/runs/*|"$base"/force-order-dhcp-guard8/runs/*|"$base"/pcs0-force-only-dhcp-guard8/runs/*|"$base"/pcs0-stock-mode-dhcp-guard8/runs/*|"$base"/pcs0-handoff-dhcp-guard8/runs/*|"$base"/edma-feature-init-dhcp-guard8/runs/*|"$base"/edma-sg-inheritance-dhcp-guard8/runs/*|"$base"/edma-dsa-feature-check-dhcp-guard8/runs/*|"$base"/pcs0-stock-analog-dhcp-guard8/runs/*)
    iface=enp4s0f4u2u4; addr=192.168.76.2 ;;
  "$base"/stock-poll-fifo-dhcp-guard8/runs/*|"$base"/conditional-relink-dhcp-guard8/runs/*|"$base"/stock-mac-order-dhcp-guard8/runs/*|"$base"/nsscc-parent-order-dhcp-guard8/runs/*|"$base"/instant-fifo-dhcp-guard8/runs/*|"$base"/independent-fifo-dhcp-guard8/runs/*|"$base"/down-mode-dhcp-guard8/runs/*|"$base"/serial-speed-dhcp-guard8/runs/*)
    iface=enp4s0f4u2u2u4; addr=192.168.76.250 ;;
  *) exit 2 ;;
esac
lock="$base/.lab-control.lock"
[[ -f $lock && ! -L $lock && -O $lock ]]
exec 8<>"$lock"
flock -n 8 || { echo 'lab control held by another trial'; exit 2; }
status=$(cat "$run/status")
[[ $status == SOAK_PASS || $status == RESTORED || $status == RESTORED_DEGRADED ]] || { echo 'not a terminal qualified/restored trial'; exit 2; }
[[ ! -e $run/evidence.sha256 ]] || { echo 'already archived'; exit 2; }
planned_restore=0
if [[ ( $status == RESTORED || $status == RESTORED_DEGRADED ) && ${run##*/} == restore-0491-* ]]; then
  planned_restore=1
fi
source_state=latest-state.txt
if (( planned_restore )); then
  source_state=preflight.txt
fi
boot=$(sed -n 's/^boot=//p' "$run/$source_state")
[[ $boot =~ ^[a-f0-9-]{36}$ ]]
opts=(-i /home/jan/.ssh/wave7-root-rsa -o "BindInterface=$iface" -o "BindAddress=$addr" -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$base/known_hosts" -o ConnectTimeout=4)
remote() { ssh -nT "${opts[@]}" root@192.168.76.1 "$@"; }
script_dir=$(dirname "$(realpath "$0")")
for f in final-dmesg.txt final-hardware.txt restored-dmesg.txt restored-hardware.txt report.json; do
  [[ ! -e $run/$f ]] || { echo "already present: $f"; exit 2; }
done
tmp=$(mktemp -d "$run/.archive.XXXXXXXX")
trap 'rm -rf "$tmp"' EXIT
capture_boot=$boot
prefix=final
if [[ $status == RESTORED || $status == RESTORED_DEGRADED ]]; then
  [[ $addr == 192.168.76.2 ]] || { echo 'restored-run archival requires independent direct management'; exit 2; }
  capture_boot=$(sed -n 's/^boot=//p' "$run/restored-state.txt")
  [[ $capture_boot =~ ^[a-f0-9-]{36}$ && $capture_boot != "$boot" ]]
  prefix=restored
  if (( !planned_restore )); then
    cp "$run/pre-rollback.txt" "$tmp/"
  fi
  cp "$run/restored-state.txt" "$tmp/"
fi
remote "set -e; test \"\$(cat /proc/sys/kernel/random/boot_id)\" = '$capture_boot'; dmesg; test \"\$(cat /proc/sys/kernel/random/boot_id)\" = '$capture_boot'" > "$tmp/$prefix-dmesg.txt"
remote "set -e; test \"\$(cat /proc/sys/kernel/random/boot_id)\" = '$capture_boot'; cat /proc/sys/kernel/random/boot_id /proc/uptime /etc/openwrt_version; fw_printenv -n bootfail; ethtool -S switch; ethtool -S lan1; ethtool -S lan; iw dev ap-mld0 info; . /rom/lib/wave7/role-firstboot.sh; wave7_secondary_ap_local_ready && echo LOCAL_READY; test \"\$(cat /proc/sys/kernel/random/boot_id)\" = '$capture_boot'" > "$tmp/$prefix-hardware.txt"
cp "$run"/{status,observer.log,trunk-counters.tsv} "$tmp/"
cp "$run/$source_state" "$tmp/$source_state"
if [[ -f $run/trunk-xgmac.tsv ]]; then cp "$run/trunk-xgmac.tsv" "$tmp/"; fi
for f in "$run"/rollback-*-trunk-counters.tsv "$run"/rollback-*-xgmac.tsv; do
  if [[ -f $f ]]; then cp "$f" "$tmp/"; fi
done
uv run --no-project --offline --python /usr/bin/python3 python "$script_dir/report-trunk-run.py" "$tmp" > "$tmp/report.json"
for f in "$prefix-dmesg.txt" "$prefix-hardware.txt" report.json; do
  mv "$tmp/$f" "$run/$f"
done
# This run has a verified SOAK_PASS or approved RESTORED observation. Retire only
# its fallback collector before releasing the shared lab lock.
tag=${run##*/}
[[ $tag =~ ^[a-zA-Z0-9-]+$ ]] || exit 2
if [[ $run == "$base"/serial-speed-dhcp-guard8/runs/source-reboot-* ||
      $run == "$base"/serial-speed-dhcp-guard8/runs/return-0498-* ||
      $run == "$base"/mib-*-dhcp-guard8/runs/* ||
      $run == "$base"/stock-order-dhcp-guard8/runs/* ||
      $run == "$base"/force-order-dhcp-guard8/runs/* ||
      $run == "$base"/pcs0-force-only-dhcp-guard8/runs/* ||
      $run == "$base"/pcs0-stock-mode-dhcp-guard8/runs/* ||
      $run == "$base"/pcs0-handoff-dhcp-guard8/runs/* ||
      $run == "$base"/edma-feature-init-dhcp-guard8/runs/* ||
      $run == "$base"/edma-sg-inheritance-dhcp-guard8/runs/* ||
      $run == "$base"/edma-dsa-feature-check-dhcp-guard8/runs/* ||
      $run == "$base"/pcs0-stock-analog-dhcp-guard8/runs/* ]]; then
  XDG_RUNTIME_DIR=/run/user/$(id -u)
  export XDG_RUNTIME_DIR
  export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
  if systemctl --user is-active --quiet "wave7-fallback-watch-$tag.service"; then
    systemctl --user stop "wave7-fallback-watch-$tag.service"
  fi
  for suffix in fallback-watch.log pstore.txt ramoops-raw.bin; do
    f="/tmp/wave7-$tag-$suffix"
    if [[ -f $f && ! -L $f && -O $f ]]; then
      [[ ! -e $run/$suffix ]]
      mv -- "$f" "$run/$suffix"
    fi
  done
fi
(
  cd "$run"
  files=(status observer.log trunk-counters.tsv "$source_state" "$prefix-dmesg.txt" "$prefix-hardware.txt" report.json)
  if [[ -f outgoing-boot.sha256 ]]; then
    sha256sum -c outgoing-boot.sha256
  fi
  for f in preflight.txt sysupgrade.log reboot.log attestation-success.log outgoing-boot.txt outgoing-boot.sha256 fallback-watch.log pstore.txt ramoops-raw.bin pre-rollback.txt unhealthy-state.txt restored-state.txt restore.log attestation-latest.log trunk-xgmac.tsv; do
    if [[ -f $f && $f != "$source_state" ]]; then files+=("$f"); fi
  done
  for f in fault-pcs-*.json fault-pcs-*.log rollback-*-trunk-counters.tsv rollback-*-xgmac.tsv; do
    if [[ -f $f ]]; then files+=("$f"); fi
  done
  sha256sum "${files[@]}" > evidence.sha256
  sha256sum -c evidence.sha256
)
cat "$run/report.json"
