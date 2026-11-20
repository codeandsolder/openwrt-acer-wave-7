#!/usr/bin/env bash
# Seal a completed run while its exact observed boot is still live.
set -Eeuo pipefail
umask 077
base=/home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8
[[ $(id -un) == jan && $# == 1 ]] || exit 2
run=$(realpath -e "$1")
case "$run" in
  "$base"/trunk-health-dhcp-guard8/runs/*|"$base"/native-recovery-dhcp-guard8/runs/*)
    iface=enp4s0f4u2u4; addr=192.168.76.2 ;;
  "$base"/stock-poll-fifo-dhcp-guard8/runs/*|"$base"/conditional-relink-dhcp-guard8/runs/*)
    iface=enp4s0f4u2u2u4; addr=192.168.76.250 ;;
  *) exit 2 ;;
esac
[[ $(cat "$run/status") == SOAK_PASS ]] || { echo 'not a completed soak'; exit 2; }
[[ ! -e $run/evidence.sha256 ]] || { echo 'already archived'; exit 2; }
boot=$(sed -n 's/^boot=//p' "$run/latest-state.txt")
[[ $boot =~ ^[a-f0-9-]{36}$ ]]
opts=(-i /home/jan/.ssh/wave7-root-rsa -o "BindInterface=$iface" -o "BindAddress=$addr" -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$base/known_hosts" -o ConnectTimeout=4)
remote() { ssh -nT "${opts[@]}" root@192.168.76.1 "$@"; }
script_dir=$(dirname "$(realpath "$0")")
for f in final-dmesg.txt final-hardware.txt report.json; do
  [[ ! -e $run/$f ]] || { echo "already present: $f"; exit 2; }
done
tmp=$(mktemp -d "$run/.archive.XXXXXXXX")
trap 'rm -rf "$tmp"' EXIT
remote "set -e; test \"\$(cat /proc/sys/kernel/random/boot_id)\" = '$boot'; dmesg; test \"\$(cat /proc/sys/kernel/random/boot_id)\" = '$boot'" > "$tmp/final-dmesg.txt"
remote "set -e; test \"\$(cat /proc/sys/kernel/random/boot_id)\" = '$boot'; cat /proc/sys/kernel/random/boot_id /proc/uptime /etc/openwrt_version; fw_printenv -n bootfail; ethtool -S switch; ethtool -S lan1; ethtool -S lan; iw dev ap-mld0 info; . /rom/lib/wave7/role-firstboot.sh; wave7_secondary_ap_local_ready && echo LOCAL_READY; test \"\$(cat /proc/sys/kernel/random/boot_id)\" = '$boot'" > "$tmp/final-hardware.txt"
cp "$run"/{status,observer.log,trunk-counters.tsv,latest-state.txt} "$tmp/"
uv run --no-project --offline --python /usr/bin/python3 python "$script_dir/report-trunk-run.py" "$tmp" > "$tmp/report.json"
for f in final-dmesg.txt final-hardware.txt report.json; do
  mv "$tmp/$f" "$run/$f"
done
(
  cd "$run"
  files=(status observer.log trunk-counters.tsv latest-state.txt final-dmesg.txt final-hardware.txt report.json)
  for f in preflight.txt sysupgrade.log attestation-success.log; do
    if [[ -f $f ]]; then files+=("$f"); fi
  done
  sha256sum "${files[@]}" > evidence.sha256
  sha256sum -c evidence.sha256
)
cat "$run/report.json"
