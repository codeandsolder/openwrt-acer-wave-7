#!/usr/bin/env bash
set -u
out=/home/jan/firmware/wave7/trials/20261115-q6-phy-integration/q6-ssr/active-test
mkdir -p "$out"
key=/home/jan/.ssh/wave7-root-rsa
ssh_opts=(-n -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=3 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
echo "READY $(date -Is)" > "$out/observer-ready.txt"
for i in $(seq 1 75); do
  echo "sample=$i time=$(date -Is)" >> "$out/monitor.log"
  ssh "${ssh_opts[@]}" root@192.168.76.1 'printf "boot="; cat /proc/sys/kernel/random/boot_id; printf "rprocs="; for d in /sys/class/remoteproc/remoteproc0 /sys/class/remoteproc/remoteproc1 /sys/class/remoteproc/remoteproc2; do printf "%s," "$(cat "$d/state")"; done; echo; printf "sta="; iw dev ap-mld0 station dump | grep -c "^Station" || :; printf "links="; iw dev | grep -Ec "link ID[[:space:]]+[01]" || :; printf "txpower="; iw dev | grep txpower | tr "\n" " "; echo; printf "q6_crash_events="; dmesg | grep -c "handling crash #" || :; printf "q6_ssr_events="; dmesg | grep -c "root Q6 restarted after crash" || :; printf "ping_client="; ping -I br-lan -c 1 -W 1 192.168.76.145 >/dev/null && echo yes || echo no; printf "ping_peer="; ping -I br-lan -c 1 -W 1 192.168.76.2 >/dev/null && echo yes || echo no' >> "$out/monitor.log" 2>&1 || echo "router_unavailable" >> "$out/monitor.log"
  sleep 3
done
echo "DONE $(date -Is)" >> "$out/monitor.log"
