#!/usr/bin/env bash
# Run an isolated 1-stream comparison on the two permanent lab paths.
# No persistent router changes; use known ARM64 iperf runtime in /tmp.
set -Eeuo pipefail
umask 077
base=/home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8
runtime=/home/jan/firmware/wave7/trials/20261115-deferred-regression/iperf-runtime
[[ $(id -un) == jan && $# == 1 ]] || { echo 'usage: bench-trunk.sh RUN_DIR'; exit 2; }
run=$(realpath -e "$1")
case "$run" in
  "$base"/trunk-health-dhcp-guard8/runs/*) revision=r0+38346-895ed9016d-ap-dhcp-guard8 ;;
  "$base"/native-recovery-dhcp-guard8/runs/*) revision=r0+38346-0e69b8931c-ap-dhcp-guard8 ;;
  *) exit 2 ;;
esac
[[ -f $run/latest-state.txt ]] || exit 2
out=$run/throughput
[[ ! -e $out ]] || { echo 'refusing to overwrite prior benchmark'; exit 2; }
state=$run/latest-state.txt
boot=$(sed -n 's/^boot=//p' "$state")
[[ $boot =~ ^[a-f0-9-]{36}$ ]]
remote_dir=/tmp/wave7-trunk-bench-$boot
direct=enp4s0f4u2u4
switch=enp4s0f4u2u2u4
opts=(-i /home/jan/.ssh/wave7-root-rsa -o BindInterface="$direct" -o BindAddress=192.168.76.2 -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$base/known_hosts" -o ConnectTimeout=4)
remote() { ssh -nT "${opts[@]}" root@192.168.76.1 "$@"; }
ready() {
  remote "test \"\$(cat /proc/sys/kernel/random/boot_id)\" = '$boot' &&
    test \"\$(cat /etc/openwrt_version)\" = '$revision' &&
    test \"\$(fw_printenv -n bootfail)\" = 0 &&
    test -e /tmp/wave7-keep-boot &&
    test \"\$(cat /sys/class/net/lan/carrier)\" = 1 &&
    test \"\$(cat /sys/class/net/lan1/carrier)\" = 1 &&
    ! dmesg | grep -q 'NOC ERROR DETECTED'"
}
for dev in "$direct" "$switch"; do
  [[ $(cat /sys/class/net/"$dev"/carrier) == 1 ]]
done
[[ $(cat /sys/class/net/"$direct"/speed) == 2500 && $(cat /sys/class/net/"$switch"/speed) == 1000 ]]
ip route get 192.168.76.1 from 192.168.76.2 | rg -Fq "dev $direct "
ip route get 192.168.76.1 from 192.168.76.250 | rg -Fq "dev $switch "
sha256sum -c "$runtime/sha256sums"
ready
mkdir -m 700 "$out"
made=0
pid=''
cleanup() {
  local rc=$?
  trap - EXIT
  if [[ -n $pid ]]; then
    kill "$pid" 2>/dev/null || :
    wait "$pid" 2>/dev/null || :
  fi
  # Server is one-shot and bounded by timeout. Never remove a different
  # boot's files, or a runtime directory not created by this process.
  if (( made )); then
    remote "test \"\$(cat /proc/sys/kernel/random/boot_id)\" = '$boot' &&
      rm -f '$remote_dir/iperf3' '$remote_dir/libiperf.so.0' '$remote_dir/libatomic.so.1' &&
      rmdir '$remote_dir'" || rc=1
  fi
  exit "$rc"
}
trap cleanup EXIT
remote "test ! -e '$remote_dir' && mkdir -m 700 '$remote_dir'"
made=1
for f in iperf3 libiperf.so.0 libatomic.so.1; do
  scp -q -O "${opts[@]}" "$runtime/$f" "root@192.168.76.1:$remote_dir/"
  [[ $(sha256sum "$runtime/$f" | cut -d' ' -f1) == "$(remote "sha256sum '$remote_dir/$f'" | cut -d' ' -f1)" ]]
done
remote "LD_LIBRARY_PATH='$remote_dir' '$remote_dir/iperf3' --version" > "$out/version.txt"
snapshot() {
  remote 'cat /proc/sys/kernel/random/boot_id /proc/uptime; ethtool -S switch; ethtool -S lan; ethtool -S lan1; cat /proc/stat'
}
snapshot > "$out/before.txt"
printf 'case\tsender_mbps\treceiver_mbps\tretransmits\tasus_cpu_pct\trouter_cpu_pct\n' > "$out/results.tsv"
run_case() {
  local name=$1 addr=$2; shift 2
  ready
  remote '! netstat -lnt | grep -q ":52227 "'
  remote "timeout 25 env LD_LIBRARY_PATH='$remote_dir' '$remote_dir/iperf3' -s -1 -B 192.168.76.1 -p 52227 -J" > "$out/$name-server.json" 2>"$out/$name-server.err" &
  pid=$!
  for _ in {1..20}; do
    if remote 'netstat -lnt | grep -q ":52227 "'; then break; fi
    sleep .2
  done
  remote 'netstat -lnt | grep -q ":52227 "'
  timeout 20 iperf3 -4 -c 192.168.76.1 -B "$addr" -p 52227 --connect-timeout 4000 -t 8 -O 1 -J "$@" > "$out/$name.json"
  wait "$pid"
  pid=''
  jq -e '.error == null and .end.sum_received.bits_per_second > 0' "$out/$name.json" >/dev/null
  jq -r --arg name "$name" '[$name,.end.sum_sent.bits_per_second/1e6,.end.sum_received.bits_per_second/1e6,.end.sum_sent.retransmits,.end.cpu_utilization_percent.host_total,.end.cpu_utilization_percent.remote_total]|@tsv' "$out/$name.json" | tee -a "$out/results.tsv"
}
run_case switch-to-router 192.168.76.250
run_case router-to-switch 192.168.76.250 -R
run_case direct-to-router 192.168.76.2
run_case router-to-direct 192.168.76.2 -R
snapshot > "$out/after.txt"
ready
# Unchanged raw error counters and increasing CPU ingress are essential:
# throughput on the wrong host NIC must not pass a switch test.
counter() { awk -v key="$2:" '$1==key {print $2}' "$1"; }
for field in dot3StatsFCSErrors etherStatsFragments etherStatsDropEvents; do
  before=$(counter "$out/before.txt" "s00_p06_$field")
  after=$(counter "$out/after.txt" "s00_p06_$field")
  [[ $before =~ ^[0-9]+$ && $after == "$before" ]]
done
before=$(counter "$out/before.txt" s00_p06_ifInOctets)
after=$(counter "$out/after.txt" s00_p06_ifInOctets)
[[ $before =~ ^[0-9]+$ && $after =~ ^[0-9]+$ && $after -gt $before ]]
(cd "$out"; sha256sum *.json *.txt *.err *.tsv > SHA256SUMS; sha256sum -c SHA256SUMS)
echo TRUNK_BENCH_PASS
